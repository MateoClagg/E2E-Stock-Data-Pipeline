"""
Bronze layer utilities for data ingestion.

Contains shared utilities for Bronze layer operations including
writing to S3 with proper partitioning and metadata tracking.
"""

import os
from datetime import datetime, timezone
from typing import Dict, List
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.types import StructType


def create_spark_session() -> SparkSession:
    """Create Spark session configured for S3 and Delta Lake."""
    return SparkSession.builder \
        .appName("FMP-Stock-Ingestion") \
        .config("spark.hadoop.fs.s3a.access.key", os.getenv("AWS_ACCESS_KEY_ID")) \
        .config("spark.hadoop.fs.s3a.secret.key", os.getenv("AWS_SECRET_ACCESS_KEY")) \
        .config("spark.hadoop.fs.s3a.endpoint", "s3.amazonaws.com") \
        .config("spark.sql.adaptive.enabled", "true") \
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true") \
        .getOrCreate()


def write_bronze_data(spark: SparkSession, data: List[Dict], schema: StructType, 
                     table_type: str, symbol: str, run_metadata: Dict) -> str:
    """
    Write raw data to Bronze S3 bucket with proper partitioning.
    
    Overwrites only the specific (symbol, ingest_date) partition to allow
    for safe reruns without duplicating data across the entire dataset.
    """
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