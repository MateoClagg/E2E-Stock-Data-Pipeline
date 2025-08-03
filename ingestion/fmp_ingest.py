#!/usr/bin/env python3

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, lit, to_date, lead, when, date_add
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, 
    LongType, DateType, TimestampType
)
from pyspark.sql.window import Window

# Import handling for both package and script execution
try:
    from .utils import AsyncFMPClient, FMPConfig
except ImportError:
    from utils import AsyncFMPClient, FMPConfig


def create_spark_session() -> SparkSession:
    # Create Spark session configured for S3 and Delta Lake
    return SparkSession.builder \
        .appName("FMP-Stock-Ingestion") \
        .config("spark.hadoop.fs.s3a.access.key", os.getenv("AWS_ACCESS_KEY_ID")) \
        .config("spark.hadoop.fs.s3a.secret.key", os.getenv("AWS_SECRET_ACCESS_KEY")) \
        .config("spark.hadoop.fs.s3a.endpoint", "s3.amazonaws.com") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .getOrCreate()


def get_bronze_schemas() -> Dict[str, StructType]:
    # Define strict schemas for all Bronze tables - prevents data type issues
    
    # Price data schema - daily OHLCV with volume
    price_schema = StructType([
        StructField("symbol", StringType(), False),
        StructField("date", StringType(), False),  # Will convert to DateType in Silver
        StructField("open", DoubleType(), True),
        StructField("high", DoubleType(), True),
        StructField("low", DoubleType(), True),
        StructField("close", DoubleType(), True),
        StructField("adjClose", DoubleType(), True),
        StructField("volume", LongType(), True),
        # Metadata columns for lineage tracking
        StructField("ingested_at", TimestampType(), False),
        StructField("run_id", StringType(), False),
    ])
    
    # Income statement has the core P&L metrics we care about
    income_schema = StructType([
        StructField("symbol", StringType(), False),
        StructField("date", StringType(), False),  # Fiscal period end date
        StructField("revenue", LongType(), True),
        StructField("grossProfit", LongType(), True),
        StructField("operatingIncome", LongType(), True),
        StructField("netIncome", LongType(), True),
        StructField("eps", DoubleType(), True),
        StructField("report_type", StringType(), False),  # Always "ANNUAL"
        StructField("ingested_at", TimestampType(), False),
        StructField("run_id", StringType(), False),
    ])
    
    # Cash flow focuses on FCF and operating cash flow
    cashflow_schema = StructType([
        StructField("symbol", StringType(), False),
        StructField("date", StringType(), False),
        StructField("operatingCashFlow", LongType(), True),
        StructField("capitalExpenditure", LongType(), True),
        StructField("freeCashFlow", LongType(), True),
        StructField("report_type", StringType(), False),
        StructField("ingested_at", TimestampType(), False),
        StructField("run_id", StringType(), False),
    ])
    
    # Balance sheet has debt, cash, equity for financial health analysis
    balance_schema = StructType([
        StructField("symbol", StringType(), False),
        StructField("date", StringType(), False),
        StructField("totalDebt", LongType(), True),
        StructField("cashAndCashEquivalents", LongType(), True),
        StructField("totalEquity", LongType(), True),
        StructField("commonStockSharesOutstanding", LongType(), True),
        StructField("report_type", StringType(), False),
        StructField("ingested_at", TimestampType(), False),
        StructField("run_id", StringType(), False),
    ])
    
    return {
        "price": price_schema,
        "income": income_schema,
        "cashflow": cashflow_schema,
        "balance": balance_schema
    }


def write_bronze_data(spark: SparkSession, data: List[Dict], schema: StructType, 
                     table_type: str, symbol: str, run_metadata: Dict) -> str:
    # Write raw data to Bronze S3 bucket with proper partitioning
    # Overwrites only the specific (symbol, ingest_date) partition to allow
    # for safe reruns without duplicating data across the entire dataset
    
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
    s3_path = f"s3a://{os.getenv('S3_BUCKET_BRONZE', 'stock-pipeline-bronze')}/{table_type}_raw/"
    
    df.write \
        .mode("overwrite") \
        .partitionBy("symbol", "ingest_date") \
        .parquet(s3_path)
    
    print(f"✅ Wrote {df.count()} {table_type} records for {symbol} to {s3_path}")
    return s3_path


def create_silver_tables(spark: SparkSession) -> None:
    # Create Silver Delta tables with proper data types and validity windows
    # Each fundamental table gets effective_from/effective_to dates so we can
    # match daily prices to the correct annual fundamental data in time-series analysis
    
    # Read Bronze data and apply Silver transformations
    bronze_bucket = os.getenv('S3_BUCKET_BRONZE', 'stock-pipeline-bronze')
    
    # Price data is straightforward - just clean up data types and rename date column
    price_df = spark.read.parquet(f"s3a://{bronze_bucket}/price_raw/") \
        .withColumn("trade_date", to_date(col("date"), "yyyy-MM-dd")) \
        .select(
            col("symbol"),
            col("trade_date"),
            col("open").cast(DoubleType()),
            col("high").cast(DoubleType()),
            col("low").cast(DoubleType()),
            col("close").cast(DoubleType()),
            col("adjClose").cast(DoubleType()),
            col("volume").cast(LongType()),
            col("ingested_at"),
            col("run_id")
        )
    
    # For fundamentals, we need to create validity windows so daily prices can join to correct annual data
    def add_validity_windows(df: DataFrame, table_name: str) -> DataFrame:
        # Add effective_from and effective_to columns for time-series joins
        
        # Convert fiscal period end date and add one day for when data becomes effective
        # This assumes companies report their annual results the day after fiscal year end
        df = df.withColumn("period_end", to_date(col("date"), "yyyy-MM-dd")) \
               .withColumn("effective_from", date_add(col("period_end"), 1))
        
        # Use window function to get next period_end for effective_to boundary
        # This creates non-overlapping time windows for each annual reporting period
        window = Window.partitionBy("symbol").orderBy("period_end")
        df = df.withColumn("next_period_end", lead("period_end").over(window)) \
               .withColumn("effective_to", 
                          when(col("next_period_end").isNull(), lit("2999-12-31").cast(DateType()))
                          .otherwise(col("next_period_end")))
        
        return df.drop("date", "next_period_end")
    
    # Transform each fundamental table with validity windows
    for table_type in ["income", "cashflow", "balance"]:
        df = spark.read.parquet(f"s3a://{bronze_bucket}/{table_type}_raw/")
        df_silver = add_validity_windows(df, table_type)
        
        # Write as Delta table for ACID transactions and time travel
        df_silver.write \
            .format("delta") \
            .mode("overwrite") \
            .saveAsTable(f"silver.fact_{table_type}")
        
        print(f"✅ Created silver.fact_{table_type} with {df_silver.count()} records")
    
    # Write price table as Delta for consistency
    price_df.write \
        .format("delta") \
        .mode("overwrite") \
        .saveAsTable("silver.fact_price")
    
    print(f"✅ Created silver.fact_price with {price_df.count()} records")


def create_unified_view(spark: SparkSession) -> None:
    # Create unified view that LEFT JOINs price data with all fundamental tables
    # This gives us a complete picture - daily prices enriched with the most
    # recent fundamental data that was available at that point in time
    # Uses LEFT JOINs so we always get price data even if fundamentals are missing
    
    view_sql = """
    CREATE OR REPLACE VIEW silver.vw_price_fundamental AS
    SELECT 
        p.symbol,
        p.trade_date,
        p.open, p.high, p.low, p.close, p.adjClose, p.volume,
        
        -- Income statement metrics (revenue, profitability)
        i.revenue, i.grossProfit, i.operatingIncome, i.netIncome, i.eps,
        i.period_end as income_period_end,
        
        -- Cash flow metrics (operating cash, capex, free cash flow)
        c.operatingCashFlow, c.capitalExpenditure, c.freeCashFlow,
        c.period_end as cashflow_period_end,
        
        -- Balance sheet metrics (debt, cash, equity, shares outstanding)
        b.totalDebt, b.cashAndCashEquivalents, b.totalEquity, 
        b.commonStockSharesOutstanding,
        b.period_end as balance_period_end,
        
        p.ingested_at, p.run_id
        
    FROM silver.fact_price p
    
    -- LEFT JOIN ensures we get all price data even if fundamentals are missing
    LEFT JOIN silver.fact_income i 
        ON p.symbol = i.symbol 
        AND p.trade_date BETWEEN i.effective_from AND i.effective_to
        
    LEFT JOIN silver.fact_cashflow c
        ON p.symbol = c.symbol
        AND p.trade_date BETWEEN c.effective_from AND c.effective_to
        
    LEFT JOIN silver.fact_balance b  
        ON p.symbol = b.symbol
        AND p.trade_date BETWEEN b.effective_from AND b.effective_to
    """
    
    spark.sql(view_sql)
    print("✅ Created silver.vw_price_fundamental unified view")


async def ingest_ticker(client: AsyncFMPClient, spark: SparkSession, symbol: str, 
                       from_date: str, to_date: str, schemas: Dict[str, StructType]) -> Dict:
    # Ingest all data types for one ticker and write to Bronze
    # Fetches price, income, cashflow, and balance sheet data concurrently
    # then writes each to its respective Bronze S3 bucket
    # Returns summary stats for logging and monitoring
    
    print(f"🔄 Processing {symbol}...")
    
    # Fetch all four data types concurrently to minimize total API call time
    data = await client.fetch_all_data(symbol, from_date, to_date)
    
    # Prepare metadata that gets added to every record for data lineage
    ingest_date = datetime.now(timezone.utc).date()
    run_metadata = {
        "symbol": symbol,
        "ingested_at": client.ingested_at,
        "run_id": client.run_id,
        "ingest_date": ingest_date
    }
    
    # Write each data type to its Bronze bucket with proper schema validation
    paths_written = []
    record_counts = {}
    
    for table_type in ["price", "income", "cashflow", "balance"]:
        table_data = data.get(table_type, [])
        if table_data:
            # Add symbol to each record since it's not always in the API response
            for record in table_data:
                record["symbol"] = symbol
            
            path = write_bronze_data(spark, table_data, schemas[table_type], 
                                   table_type, symbol, run_metadata)
            if path:
                paths_written.append(path)
            record_counts[table_type] = len(table_data)
        else:
            record_counts[table_type] = 0
    
    return {
        "symbol": symbol,
        "record_counts": record_counts,
        "paths_written": paths_written
    }


async def main():
    # Main ingestion pipeline - handles CLI args and orchestrates the full process
    # Supports both backfill mode (5 years of history) and daily mode (yesterday only)
    # Processes multiple tickers concurrently while respecting API rate limits
    
    parser = argparse.ArgumentParser(description="FMP Stock Data Ingestion Pipeline")
    parser.add_argument("--tickers", required=True, help="Comma-separated ticker symbols (e.g. AAPL,NVDA,TSLA)")
    parser.add_argument("--backfill", action="store_true", help="Fetch 5-year history instead of just yesterday")
    
    args = parser.parse_args()
    
    # Parse ticker list and normalize to uppercase
    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    print(f"🎯 Starting ingestion for {len(tickers)} tickers: {', '.join(tickers)}")
    
    # Calculate date range based on mode
    if args.backfill:
        # Backfill mode: get 5 years of history
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
        print(f"📅 Backfill mode: {from_date} to {to_date}")
    else:
        # Daily mode: just get yesterday's data (today's data might not be complete)
        yesterday = datetime.now() - timedelta(days=1)
        from_date = to_date = yesterday.strftime("%Y-%m-%d")
        print(f"📅 Daily mode: {from_date}")
    
    # Initialize components
    config = FMPConfig(api_key=os.getenv("FMP_API_KEY"))
    client = AsyncFMPClient(config)
    spark = create_spark_session()
    schemas = get_bronze_schemas()
    
    # Process all tickers concurrently - rate limiting handles the API limits automatically
    tasks = [ingest_ticker(client, spark, ticker, from_date, to_date, schemas) 
             for ticker in tickers]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Create Silver tables and unified view after all Bronze data is written
    print("\n🔄 Creating Silver tables...")
    create_silver_tables(spark)
    create_unified_view(spark)
    
    # Generate summary report for monitoring and debugging
    summary = {
        "run_id": client.run_id,
        "ingested_at": client.ingested_at.isoformat(),
        "date_range": {"from": from_date, "to": to_date},
        "results": [r for r in results if not isinstance(r, Exception)],
        "errors": [str(r) for r in results if isinstance(r, Exception)]
    }
    
    # Write summary to logs directory for future reference
    os.makedirs("logs", exist_ok=True)
    with open(f"logs/ingestion_{client.run_id}.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    
    print(f"\n✅ Ingestion complete! Summary: logs/ingestion_{client.run_id}.json")
    
    # Clean up Spark resources
    spark.stop()


if __name__ == "__main__":
    asyncio.run(main())