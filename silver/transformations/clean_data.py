import os
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, to_date
from pyspark.sql.types import DoubleType, LongType
from silver.transformations.validity_windows import create_spark_session, transform_fundamental_table


def transform_price_data(spark: SparkSession) -> DataFrame:
    # Transform price data - clean up data types and rename date column
    
    bronze_bucket = os.getenv('S3_BUCKET_BRONZE', 'stock-pipeline-bronze')
    
    # Read Bronze price data and apply Silver transformations
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
    
    return price_df


def create_all_silver_tables(spark: SparkSession) -> None:
    # Create all Silver Delta tables with proper data types and validity windows
    # Each fundamental table gets effective_from/effective_to dates so we can
    # match daily prices to the correct annual fundamental data in time-series analysis
    
    print("🔄 Creating Silver tables...")
    
    # Transform price data (straightforward data type cleanup)
    price_df = transform_price_data(spark)
    
    # Write price table as Delta for consistency
    price_df.write \
        .format("delta") \
        .mode("overwrite") \
        .saveAsTable("silver.fact_price")
    
    print(f"✅ Created silver.fact_price with {price_df.count()} records")
    
    # Transform each fundamental table with validity windows
    for table_type in ["income", "cashflow", "balance"]:
        df_silver = transform_fundamental_table(spark, table_type)
        
        # Write as Delta table for ACID transactions and time travel
        df_silver.write \
            .format("delta") \
            .mode("overwrite") \
            .saveAsTable(f"silver.fact_{table_type}")
        
        print(f"✅ Created silver.fact_{table_type} with {df_silver.count()} records")


def main():
    # Main Silver transformation pipeline
    # Reads Bronze data and creates clean Silver tables
    
    print("🎯 Starting Silver layer transformations...")
    
    spark = create_spark_session()
    
    try:
        create_all_silver_tables(spark)
        print("\n✅ All Silver tables created successfully!")
        print("🔄 Next step: Create unified views for analytics")
        
    finally:
        # Clean up Spark resources
        spark.stop()


if __name__ == "__main__":
    main()