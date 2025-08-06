import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
import aiohttp
from pydantic import BaseModel
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.types import StructType
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def create_spark_session() -> SparkSession:
    import platform
    import tempfile
    
    # Windows-specific setup to avoid winutils.exe issues
    if platform.system() == "Windows":
        # Set HADOOP_HOME to temp directory if not set
        if not os.getenv('HADOOP_HOME'):
            temp_hadoop = os.path.join(tempfile.gettempdir(), "hadoop")
            os.makedirs(temp_hadoop, exist_ok=True)
            os.environ['HADOOP_HOME'] = temp_hadoop
    
    builder = SparkSession.builder \
        .appName("FMP-Stock-Ingestion") \
        .config("spark.driver.memory", "2g") \
        .config("spark.driver.maxResultSize", "1g") \
        .config("spark.jars.packages", "org.apache.hadoop:hadoop-aws:3.3.4") \
        .config("spark.hadoop.fs.s3a.access.key", os.getenv("AWS_ACCESS_KEY_ID")) \
        .config("spark.hadoop.fs.s3a.secret.key", os.getenv("AWS_SECRET_ACCESS_KEY")) \
        .config("spark.hadoop.fs.s3a.endpoint", "s3.amazonaws.com") \
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
        .config("spark.hadoop.fs.s3a.aws.credentials.provider", "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider") \
        .config("spark.sql.adaptive.enabled", "true") \
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true") \
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
    
    # Additional Windows-specific configurations 
    if platform.system() == "Windows":
        builder = builder \
            .config("spark.hadoop.fs.file.impl", "org.apache.hadoop.fs.LocalFileSystem") \
            .config("spark.sql.warehouse.dir", "file:///C:/temp/spark-warehouse") \
            .config("spark.hadoop.io.compression.codecs", "org.apache.hadoop.io.compress.GzipCodec,org.apache.hadoop.io.compress.DefaultCodec")
    
    return builder.getOrCreate()


def write_bronze_data(spark: SparkSession, data: List[Dict], schema: StructType, 
                     table_type: str, symbol: str, run_metadata: Dict) -> str:
    if not data:
        print(f"⚠️  No {table_type} data for {symbol}, skipping")
        return ""
    
    # Add our tracking metadata to each record so we know when/how it was ingested
    enriched_data = []
    for record in data:
        record.update(run_metadata)
        # All fundamental data is annual period since we don't have quarterly access
        if table_type != "price":
            record["report_type"] = "ANNUAL"
        enriched_data.append(record)
    
    # Create DataFrame with strict schema enforcement to catch data issues early
    df = spark.createDataFrame(enriched_data, schema)
    
    # Write to S3 with symbol and date partitioning for efficient queries
    bucket = os.getenv('S3_BUCKET_BRONZE')
    s3_path = f"s3a://{bucket}/{table_type}_raw/"
    
    df.write \
        .mode("overwrite") \
        .partitionBy("symbol", "ingest_date") \
        .parquet(s3_path)
    
    print(f"✅ Wrote {df.count()} {table_type} records for {symbol} to {s3_path}")
    return s3_path


# FMP API Client Classes
class RateLimiter:
    def __init__(self, max_requests: int = 5, time_window: float = 1.0):
        self.max_requests = max_requests
        self.time_window = time_window
        self.tokens = max_requests
        self.last_refill = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        async with self._lock:
            current_time = time.time()
            elapsed = current_time - self.last_refill
            
            # Refill our token bucket based on time passed
            self.tokens = min(
                self.max_requests,
                self.tokens + elapsed * (self.max_requests / self.time_window)
            )
            self.last_refill = current_time
            
            if self.tokens < 1:
                # Need to wait before we can make another request
                sleep_time = (1 - self.tokens) * (self.time_window / self.max_requests)
                await asyncio.sleep(sleep_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class FMPConfig(BaseModel):
    api_key: str
    base_url: str = "https://financialmodelingprep.com/api/v3"


class AsyncFMPClient:
    def __init__(self, config: FMPConfig, rate_limiter: Optional[RateLimiter] = None):
        self.config = config
        self.rate_limiter = rate_limiter or RateLimiter(max_requests=5, time_window=1.0)
        self.run_id = str(uuid.uuid4())
        self.ingested_at = datetime.now(timezone.utc)
    
    async def _make_request(self, session: aiohttp.ClientSession, endpoint: str, params: Optional[Dict] = None) -> List[Dict]:
        if params is None:
            params = {}
        
        params["apikey"] = self.config.api_key
        
        # Wait for permission to make the request
        await self.rate_limiter.acquire()
        
        try:
            async with session.get(f"{self.config.base_url}/{endpoint}", params=params) as response:
                response.raise_for_status()
                data = await response.json()
                
                # Handle both list and dict responses
                if isinstance(data, dict) and "historical" in data:
                    return data["historical"]
                elif isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return [data]
                else:
                    return []
                    
        except Exception as e:
            print(f"❌ API request failed for {endpoint}: {e}")
            return []
    
    async def fetch_all_data(self, symbol: str, from_date: str, to_date: str) -> Dict[str, List[Dict]]:
        async with aiohttp.ClientSession() as session:
            # Fire off all four requests concurrently
            tasks = {
                "price": self._make_request(session, f"historical-price-full/{symbol}", 
                                           {"from": from_date, "to": to_date}),
                "income": self._make_request(session, f"income-statement/{symbol}", 
                                           {"period": "annual", "limit": 5}),
                "cashflow": self._make_request(session, f"cash-flow-statement/{symbol}", 
                                             {"period": "annual", "limit": 5}),
                "balance": self._make_request(session, f"balance-sheet-statement/{symbol}", 
                                            {"period": "annual", "limit": 5})
            }
            
            # Wait for all requests to complete
            results = {}
            for data_type, task in tasks.items():
                results[data_type] = await task
                print(f"✅ {symbol} {data_type}: {len(results[data_type])} records")
            
            return results