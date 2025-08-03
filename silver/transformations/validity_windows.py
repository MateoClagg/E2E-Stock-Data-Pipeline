import os
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, lit, to_date, lead, when, date_add
from pyspark.sql.types import DateType
from pyspark.sql.window import Window


def create_spark_session() -> SparkSession:
    # Create Spark session configured for Delta Lake
    return SparkSession.builder \
        .appName("Silver-Transformations") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .config("spark.hadoop.fs.s3a.access.key", os.getenv("AWS_ACCESS_KEY_ID")) \
        .config("spark.hadoop.fs.s3a.secret.key", os.getenv("AWS_SECRET_ACCESS_KEY")) \
        .config("spark.hadoop.fs.s3a.endpoint", "s3.amazonaws.com") \
        .getOrCreate()


def add_validity_windows(df: DataFrame, table_name: str) -> DataFrame:
    # Add effective_from and effective_to columns for time-series joins
    # This creates non-overlapping time windows for each annual reporting period
    
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


def transform_fundamental_table(spark: SparkSession, table_type: str) -> DataFrame:
    # Transform a fundamental table (income, cashflow, balance) with validity windows
    
    bronze_bucket = os.getenv('S3_BUCKET_BRONZE', 'stock-pipeline-bronze')
    
    # Read Bronze data
    df = spark.read.parquet(f"s3a://{bronze_bucket}/{table_type}_raw/")
    
    # Add validity windows for time-series joins
    df_silver = add_validity_windows(df, table_type)
    
    return df_silver