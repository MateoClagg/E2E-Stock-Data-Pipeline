# 🔧 Databricks Setup Guide

Configure Databricks to ingest data from the S3 raw zone into Bronze/Silver/Gold layers.

---

## 🏗️ Architecture

```
S3 Raw Zone              Databricks
┌──────────────┐         ┌─────────────────────────┐
│ Parquet      │────────▶│ Auto Loader             │
│ Day-level    │         │ → Bronze (Delta + CDF)  │
│ partitions   │         │ → Silver (MERGE)        │
└──────────────┘         │ → Gold (Features)       │
                         └─────────────────────────┘
```

**Cost-optimized approach**: Local ingestion writes to S3, Databricks only processes transformations.

---

## 📋 Prerequisites

1. **S3 Bucket** with raw data from local ingestion
2. **Databricks workspace** (Unity Catalog enabled recommended)
3. **AWS IAM permissions** for S3 access
4. **External Location** configured in Unity Catalog (or instance profile for legacy)

---

## 🔐 Step 1: Configure S3 Access

### Option A: Unity Catalog External Location (Recommended)

```sql
-- Create external location for raw data
CREATE EXTERNAL LOCATION IF NOT EXISTS stock_raw_data
URL 's3://your-bucket/raw/'
WITH (STORAGE CREDENTIAL stock_s3_credential);

-- Grant access
GRANT READ FILES ON EXTERNAL LOCATION stock_raw_data TO `data_engineers`;
```

### Option B: Instance Profile (Legacy)

Attach IAM role to Databricks cluster with S3 permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket/raw/*",
        "arn:aws:s3:::your-bucket"
      ]
    }
  ]
}
```

---

## 📊 Step 2: Create Bronze Layer (Auto Loader)

### Create Bronze Delta Table

```sql
CREATE CATALOG IF NOT EXISTS stock_pipeline;
CREATE SCHEMA IF NOT EXISTS stock_pipeline.bronze;

-- Bronze prices table with Change Data Feed
CREATE TABLE IF NOT EXISTS stock_pipeline.bronze.prices (
  symbol STRING NOT NULL,
  date DATE NOT NULL,
  open DOUBLE,
  high DOUBLE,
  low DOUBLE,
  close DOUBLE,
  adjClose DOUBLE,
  volume BIGINT,
  ingest_ts TIMESTAMP NOT NULL,
  -- Auto Loader metadata
  _rescued_data STRING
)
USING DELTA
PARTITIONED BY (symbol)
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact' = 'true'
);
```

### Set up Auto Loader Stream

```python
# Databricks notebook

from pyspark.sql.functions import col, to_date

# Configure Auto Loader
raw_data_path = "s3://your-bucket/raw/prices/"
checkpoint_path = "s3://your-bucket/checkpoints/prices_bronze/"

# Read stream from S3
raw_stream = (
    spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "parquet")
    .option("cloudFiles.schemaLocation", "s3://your-bucket/schemas/prices/")
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
    .load(raw_data_path)
)

# Write to Bronze Delta table
query = (
    raw_stream.writeStream
    .format("delta")
    .outputMode("append")
    .option("checkpointLocation", checkpoint_path)
    .option("mergeSchema", "true")
    .trigger(availableNow=True)  # Or use processingTime="5 minutes"
    .toTable("stock_pipeline.bronze.prices")
)

# Monitor progress
query.awaitTermination()
```

---

## 🥈 Step 3: Create Silver Layer (Cleaned Data)

### Create Silver Table

```sql
CREATE SCHEMA IF NOT EXISTS stock_pipeline.silver;

CREATE TABLE IF NOT EXISTS stock_pipeline.silver.prices (
  symbol STRING NOT NULL,
  trade_date DATE NOT NULL,
  open DOUBLE,
  high DOUBLE,
  low DOUBLE,
  close DOUBLE,
  adj_close DOUBLE,
  volume BIGINT,
  ingest_ts TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
PARTITIONED BY (symbol)
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true'
);
```

### Deduplication & Quality Checks

```sql
MERGE INTO stock_pipeline.silver.prices AS target
USING (
  SELECT
    symbol,
    CAST(date AS DATE) AS trade_date,
    open,
    high,
    low,
    close,
    adjClose AS adj_close,
    volume,
    ingest_ts,
    CURRENT_TIMESTAMP() AS updated_at,
    ROW_NUMBER() OVER (
      PARTITION BY symbol, date
      ORDER BY ingest_ts DESC
    ) AS row_num
  FROM stock_pipeline.bronze.prices
  WHERE
    symbol IS NOT NULL
    AND date IS NOT NULL
    AND volume >= 0  -- Data quality check
) AS source
ON target.symbol = source.symbol AND target.trade_date = source.trade_date
WHEN MATCHED AND source.row_num = 1 THEN
  UPDATE SET *
WHEN NOT MATCHED AND source.row_num = 1 THEN
  INSERT *;
```

---

## 🥇 Step 4: Create Gold Layer (Features)

### Create Gold Feature Table

```sql
CREATE SCHEMA IF NOT EXISTS stock_pipeline.gold;

CREATE OR REPLACE VIEW stock_pipeline.gold.price_features AS
SELECT
  symbol,
  trade_date,
  close,

  -- Moving averages
  AVG(close) OVER (
    PARTITION BY symbol
    ORDER BY trade_date
    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
  ) AS ma_20,

  AVG(close) OVER (
    PARTITION BY symbol
    ORDER BY trade_date
    ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
  ) AS ma_50,

  -- Volatility
  STDDEV(close) OVER (
    PARTITION BY symbol
    ORDER BY trade_date
    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
  ) AS volatility_20d,

  -- Daily returns
  (close - LAG(close, 1) OVER (PARTITION BY symbol ORDER BY trade_date))
    / LAG(close, 1) OVER (PARTITION BY symbol ORDER BY trade_date) AS daily_return

FROM stock_pipeline.silver.prices
ORDER BY symbol, trade_date DESC;
```

---

## ⚙️ Step 5: Automation (Delta Live Tables)

For production, use Delta Live Tables for automatic orchestration:

```python
# DLT Pipeline

import dlt
from pyspark.sql.functions import col, to_date, current_timestamp

@dlt.table(
  name="bronze_prices",
  comment="Raw price data from S3",
  table_properties={"delta.enableChangeDataFeed": "true"}
)
def bronze_prices():
    return (
        spark.readStream
        .format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.schemaLocation", "/mnt/schemas/prices/")
        .load("s3://your-bucket/raw/prices/")
    )

@dlt.table(
  name="silver_prices",
  comment="Cleaned and deduplicated prices"
)
@dlt.expect_or_drop("valid_volume", "volume >= 0")
@dlt.expect_or_drop("valid_symbol", "symbol IS NOT NULL")
def silver_prices():
    return (
        dlt.read_stream("bronze_prices")
        .select(
            col("symbol"),
            to_date(col("date")).alias("trade_date"),
            col("open"),
            col("high"),
            col("low"),
            col("close"),
            col("adjClose").alias("adj_close"),
            col("volume"),
            col("ingest_ts"),
            current_timestamp().alias("updated_at")
        )
        .dropDuplicates(["symbol", "date"])
    )
```

---

## 🔍 Monitoring & Troubleshooting

### Check Auto Loader Status

```sql
-- View recent ingestions
SELECT
  symbol,
  COUNT(*) as records,
  MAX(ingest_ts) as latest_ingest
FROM stock_pipeline.bronze.prices
WHERE DATE(ingest_ts) = CURRENT_DATE()
GROUP BY symbol
ORDER BY symbol;
```

### Verify Data Quality

```sql
-- Check for duplicates in Silver
SELECT symbol, trade_date, COUNT(*) as count
FROM stock_pipeline.silver.prices
GROUP BY symbol, trade_date
HAVING COUNT(*) > 1;

-- Check for missing dates
SELECT
  symbol,
  MIN(trade_date) as first_date,
  MAX(trade_date) as last_date,
  COUNT(DISTINCT trade_date) as trading_days
FROM stock_pipeline.silver.prices
GROUP BY symbol;
```

### Monitor Stream Health

```python
# Check Auto Loader checkpoint
display(
    spark.sql("""
        DESCRIBE HISTORY stock_pipeline.bronze.prices
        LIMIT 10
    """)
)
```

---

## 📅 Scheduling

### Option 1: Databricks Jobs

Create a job to run the MERGE operations daily:

```python
# Job configuration
{
  "name": "Stock Pipeline - Bronze to Silver",
  "schedule": {
    "quartz_cron_expression": "0 0 1 * * ?",  # Daily at 1 AM UTC
    "timezone_id": "America/New_York"
  },
  "tasks": [
    {
      "task_key": "merge_to_silver",
      "notebook_task": {
        "notebook_path": "/pipelines/bronze_to_silver",
        "source": "WORKSPACE"
      },
      "new_cluster": {
        "spark_version": "13.3.x-scala2.12",
        "node_type_id": "i3.xlarge",
        "num_workers": 2
      }
    }
  ]
}
```

### Option 2: Delta Live Tables Pipeline

Set DLT pipeline to run on trigger or schedule:
- **Triggered**: Runs when new data appears in S3
- **Scheduled**: Runs at specific times (e.g., daily at 2 AM)

---

## 💰 Cost Optimization

1. **Use Auto Loader triggers**: `trigger(availableNow=True)` instead of continuous
2. **Partition pruning**: Partition by `symbol` for efficient queries
3. **Auto-optimize**: Enable `autoOptimize` for automatic compaction
4. **Spot instances**: Use spot instances for batch processing
5. **Serverless compute**: Use Databricks serverless for SQL queries

**Estimated costs**: <$10/month for 10-100 tickers (with optimization)

---

## 🆘 Troubleshooting

**Auto Loader not picking up files**
- Check S3 permissions
- Verify `cloudFiles.schemaLocation` path
- Check checkpoint location is writable

**Schema evolution errors**
- Enable `cloudFiles.schemaEvolutionMode = "addNewColumns"`
- Use `_rescued_data` column for schema mismatches

**MERGE performance issues**
- Add Z-ordering: `OPTIMIZE table ZORDER BY (symbol, trade_date)`
- Increase cluster size for large datasets
- Use `delta.autoOptimize.optimizeWrite = true`

---

## 📚 Additional Resources

- [Databricks Auto Loader](https://docs.databricks.com/ingestion/auto-loader/index.html)
- [Delta Live Tables](https://docs.databricks.com/workflows/delta-live-tables/index.html)
- [Unity Catalog](https://docs.databricks.com/data-governance/unity-catalog/index.html)
