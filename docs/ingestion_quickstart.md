# 🚀 Ingestion Quickstart

**Local async ingestion** for cost-optimized data pipeline: API calls run locally/GitHub Actions (not Databricks), writes day-partitioned Parquet to S3.

---

## 📊 Architecture

```
Local/GitHub Actions      S3 Raw Zone              Databricks
┌─────────────────┐       ┌──────────────┐         ┌─────────────────┐
│ FMP API         │       │ Day-level    │         │ Auto Loader     │
│ (async fetch)   │──────▶│ Parquet      │────────▶│ → Bronze (CDF)  │
│ polars/pyarrow  │       │ partitions   │         │ → Silver/Gold   │
└─────────────────┘       └──────────────┘         └─────────────────┘
```

**Cost savings:** ~70% by offloading API wait time from Databricks to GitHub Actions runners.

---

## 🗂️ S3 Layout

### Prices (Daily OHLCV)

**Backfill mode** (yearly Parquet files):
```
s3://{S3_BUCKET}/raw/prices/
  symbol=AAPL/
    year=2020/
      AAPL-2020.parquet  ← All trading days for 2020
    year=2021/
      AAPL-2021.parquet
```

**Daily mode** (incremental ingestion):
```
s3://{S3_BUCKET}/raw/prices/
  symbol=AAPL/
    year=2024/
      month=09/
        AAPL-2024-09-15.parquet  ← Single file per day
        AAPL-2024-09-16.parquet
```

### Fundamentals (Future)
```
s3://{S3_BUCKET}/raw/fundamentals/
  type=income/
    symbol=AAPL/
      year=2024/
        docdate=2024-09-30/
          AAPL-2024-09-30.parquet
```

### Logs & Metrics
```
s3://{S3_BUCKET}/logs/ingest/
  date=2024-09-30/
    run-1727740800.json  ← Metrics for each run
```

**Partitioning strategy:**
- **Backfill mode (`--backfill`)**: Writes one Parquet file per symbol/year (optimized for historical data)
- **Daily mode (default)**: Writes one Parquet file per symbol/day (optimized for incremental ingestion)
- Each file contains `ingest_ts` column for lineage tracking
- Idempotent: skips existing files unless `--force`

---

## ⚙️ Environment Variables

Required:
```bash
export FMP_API_KEY="your_fmp_api_key"         # From financialmodelingprep.com
export S3_BUCKET="your-bucket-name"           # Main S3 bucket
export AWS_ACCESS_KEY_ID="..."                # Or use OIDC in GitHub Actions
export AWS_SECRET_ACCESS_KEY="..."
export AWS_DEFAULT_REGION="us-east-1"
```

Optional:
```bash
export S3_RAW_PREFIX="raw"                    # Default: raw
export RATE_LIMIT_SECONDS="15.0"              # FMP free tier: ~12-15s
export MAX_WORKERS="5"                        # Concurrent symbol processing
```

---

## 🏃 Running Locally

### 1. Install Dependencies
```bash
pip install aiohttp tenacity polars pyarrow boto3 python-dotenv pandas pandas-market-calendars
```

### 2. Daily Ingestion (Default)
```bash
# Fetch yesterday's data for tickers in stock_pipeline/config/tickers.csv
python stock_pipeline/scripts/ingest_local_to_s3.py
```

### 3. Custom Tickers
```bash
# Local file
python stock_pipeline/scripts/ingest_local_to_s3.py \
  --tickers-path my_tickers.csv

# S3 file
python stock_pipeline/scripts/ingest_local_to_s3.py \
  --tickers-path s3://my-bucket/tickers/watchlist.csv
```

### 4. Backfill

**Historical backfill (yearly partitions):**
```bash
# 5 years of historical data (~1825 days)
python stock_pipeline/scripts/ingest_local_to_s3.py \
  --backfill \
  --backfill-days 1825

# Custom date range with yearly partitions
python stock_pipeline/scripts/ingest_local_to_s3.py \
  --backfill \
  --from-date 2020-01-01 \
  --to-date 2024-12-31

# Force overwrite existing files
python stock_pipeline/scripts/ingest_local_to_s3.py \
  --backfill \
  --backfill-days 1825 \
  --force
```

**Recent backfill (daily partitions):**
```bash
# Last 30 days (daily files for recent data)
python stock_pipeline/scripts/ingest_local_to_s3.py \
  --backfill-days 30
```

**Performance:**
- Backfill mode: 5 years of data for 10 tickers in ~12 seconds (writes ~50 yearly files)
- Daily mode: Same data takes ~9000 seconds (writes ~12,500 daily files)

---

## 🤖 GitHub Actions

### Nightly Ingestion (Automatic)
Runs Monday-Friday at 11 PM UTC (after US market close).

Configured in `.github/workflows/ingest.yml`:
```yaml
schedule:
  - cron: '0 23 * * 1-5'  # Mon-Fri 11 PM UTC
```

### Manual Dispatch
Trigger via GitHub UI:

1. Go to **Actions** → **Stock Data Ingestion**
2. Click **Run workflow**
3. Configure parameters:
   - **tickers_path**: `stock_pipeline/config/tickers.csv` (default) or `s3://...`
   - **from_date / to_date**: Custom date range
   - **backfill_days**: Quick backfill (e.g., `30`)
   - **force**: `true` to overwrite existing files

**GitHub Secrets Required:**
- `FMP_API_KEY`
- `AWS_ROLE_ARN` (for OIDC)
- `AWS_REGION`

**GitHub Variables Required:**
- `S3_BUCKET`
- `S3_RAW_PREFIX` (optional, default: `raw`)
- `RATE_LIMIT_SECONDS` (optional, default: `15.0`)
- `MAX_WORKERS` (optional, default: `5`)

---

## 🔒 Idempotency & Safety

### File-Level Idempotency
Before writing, checks if the target S3 file exists:
- **Backfill mode**: Checks `s3://.../symbol=X/year=Y/X-Y.parquet`
- **Daily mode**: Checks `s3://.../symbol=X/year=Y/month=M/X-Y-M-D.parquet`

Behavior:
- **Exists + no `--force`**: Skip silently (no terminal output)
- **Exists + `--force`**: Overwrite
- **Does not exist**: Write

**Backfills and daily increments coexist safely** — yearly and daily files are stored in different S3 paths.

### Data Validation (Polars)
Before writing, each day's DataFrame is validated:
- ✅ Non-null `symbol`, `date`
- ✅ Non-negative `volume`
- ✅ Sorted by `date` descending

Invalid rows are filtered out with warnings.

---

## 📋 Metrics & Monitoring

After each run, `metrics.json` is written to:
```
s3://{S3_BUCKET}/logs/ingest/date={YYYY-MM-DD}/run-{unix_ts}.json
```

**Contents:**
```json
{
  "run_id": "2024-09-30T23:00:00+00:00",
  "date_range": {"from": "2024-09-29", "to": "2024-09-29"},
  "symbols_processed": 10,
  "files_written": 10,
  "rows_written": 10,
  "errors": 0,
  "duration_seconds": 45.2,
  "results": [
    {
      "symbol": "AAPL",
      "files_written": 1,
      "rows_written": 1,
      "errors": []
    }
  ]
}
```

**GitHub Actions logs** also display a summary:
```
✅ Ingestion Complete
============================================================
📊 Symbols: 10
📁 Files written: 10
📝 Rows written: 10
❌ Errors: 0
⏱️  Duration: 45.2s
📋 Metrics: s3://my-bucket/logs/ingest/date=2024-09-30/run-1727740800.json
============================================================
```

---

## 🔗 Next Steps: Databricks Integration

Once raw data is in S3, configure Databricks **Auto Loader** to ingest into Bronze layer:

### 1. Auto Loader to Bronze (Streaming)
```sql
-- Create Bronze table with Change Data Feed (CDF)
CREATE TABLE IF NOT EXISTS bronze.prices (
  symbol STRING,
  date DATE,
  open DOUBLE,
  high DOUBLE,
  low DOUBLE,
  close DOUBLE,
  adjClose DOUBLE,
  volume BIGINT,
  ingest_ts TIMESTAMP
)
USING DELTA
TBLPROPERTIES (delta.enableChangeDataFeed = true)
PARTITIONED BY (symbol, date);

-- Auto Loader stream from S3 raw zone
CREATE OR REFRESH STREAMING LIVE TABLE bronze_prices_stream
AS SELECT * FROM cloud_files(
  's3://{{S3_BUCKET}}/raw/prices/',
  'parquet',
  map('cloudFiles.schemaLocation', 's3://{{S3_BUCKET}}/schemas/prices/')
);
```

### 2. Bronze → Silver (Deduplication + Quality)
```sql
MERGE INTO silver.prices AS target
USING (
  SELECT DISTINCT
    symbol,
    date,
    open, high, low, close, adjClose, volume,
    ingest_ts,
    ROW_NUMBER() OVER (PARTITION BY symbol, date ORDER BY ingest_ts DESC) AS rn
  FROM bronze.prices
) AS source
ON target.symbol = source.symbol AND target.date = source.date
WHEN MATCHED AND source.rn = 1 THEN UPDATE SET *
WHEN NOT MATCHED AND source.rn = 1 THEN INSERT *;
```

### 3. Silver → Gold (Features)
```sql
-- Price-based features for ML
CREATE OR REPLACE VIEW gold.price_features AS
SELECT
  symbol,
  date,
  close,
  -- Moving averages
  AVG(close) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma_20,
  AVG(close) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS ma_50,
  -- Volatility
  STDDEV(close) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS volatility_20d
FROM silver.prices;
```

---

## 🛠️ Troubleshooting

### No data returned from API
- Verify `FMP_API_KEY` is valid
- Check FMP account limits (free tier: 250 calls/day)
- Try a different ticker (e.g., `AAPL` always works)

### S3 permission errors
- Ensure IAM role/user has `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` on `S3_BUCKET`
- For GitHub Actions: verify `AWS_ROLE_ARN` has correct trust policy for OIDC

### Rate limit errors (429)
- Increase `RATE_LIMIT_SECONDS` (e.g., `20.0` for extra buffer)
- Reduce `MAX_WORKERS` (fewer concurrent symbols)

### Validation failures
- Check FMP response format (API may return errors as `{"Error Message": "..."}`)
- Inspect logs for `⚠️ No valid data after validation`

---

## 📚 Additional Resources

- [FMP API Docs](https://site.financialmodelingprep.com/developer/docs)
- [Polars DataFrame Guide](https://pola-rs.github.io/polars/py-polars/html/reference/dataframe/index.html)
- [Databricks Auto Loader](https://docs.databricks.com/ingestion/auto-loader/index.html)
- [pandas-market-calendars](https://github.com/rsheftel/pandas_market_calendars)

---

**Questions?** Check the main [README](../README.md) or open an issue.
