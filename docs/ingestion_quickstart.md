# 🚀 Ingestion Quickstart

**Local async ingestion** for cost-optimized data pipeline: API calls run locally/GitHub Actions (not Databricks), writes to S3 for Auto Loader ingestion.

---

## 📊 Architecture

```
Local/GitHub Actions      S3 Raw Zone              Databricks
┌─────────────────┐       ┌──────────────┐         ┌─────────────────┐
│ FMP API         │       │ Parquet +    │         │ Auto Loader     │
│ (async fetch)   │──────▶│ NDJSON       │────────▶│ → Bronze (CDF)  │
│ polars/pyarrow  │       │ dt= parts    │         │ → Silver/Gold   │
└─────────────────┘       └──────────────┘         └─────────────────┘
```

**Cost savings:** ~70% by offloading API wait time from Databricks to GitHub Actions runners.

---

## 🗂️ S3 Layout

### Prices (OHLCV - Parquet)
```
s3://{S3_BUCKET}/raw/fmp/prices/
  dt=2024-10-24/
    prices-2024-10-24.parquet  ← All symbols combined (100+ rows)
  dt=2024-10-25/
    prices-2024-10-25.parquet
```

**Schema:**
- `symbol`, `as_of_date`, `open`, `high`, `low`, `close`, `volume`
- `fetched_at`, `source`, `endpoint`, `request_id`, `file_hash`

### Financial Statements (NDJSON)
```
s3://{S3_BUCKET}/raw/fmp/
  owner_earnings/
    dt=2024-10-24/
      symbol=AAPL/
        AAPL-owner-earnings-2024-10-24.ndjson
  statements/
    income/
      dt=2024-10-24/
        symbol=AAPL/
          AAPL-income-2024-10-24.ndjson
    balance_sheet/
      dt=2024-10-24/
        symbol=AAPL/
          AAPL-balance-2024-10-24.ndjson
    cash_flow/
      dt=2024-10-24/
        symbol=AAPL/
          AAPL-cashflow-2024-10-24.ndjson
```

**Schema:**
- `symbol`, `as_of_date`, `endpoint`, `payload` (raw JSON)
- `fetched_at`, `source`, `http_status`, `request_id`
- `fiscal_period_end`, `filing_date`, `hash`

### Treasury Rates (NDJSON)
```
s3://{S3_BUCKET}/raw/fmp/treasury_rates/
  dt=2024-10-24/
    treasury-rates-2024-10-24.ndjson
```

### Logs & Metrics
```
s3://{S3_BUCKET}/logs/ingest/
  date=2024-10-24/
    prices-run-1729807200.json
    owner-earnings-run-1729807300.json
    run-1729807400.json
```

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
export S3_RAW_PREFIX="raw/fmp"                # Default: raw/fmp
export RATE_LIMIT_SECONDS="0.2"               # FMP paid tier: 0.1-0.2s
export MAX_WORKERS="10"                       # Concurrent symbol processing
```

---

## 🏃 Running Locally

### 1. Install Dependencies
```bash
pip install aiohttp tenacity polars pyarrow boto3 python-dotenv
```

### 2. Price Data Ingestion

**Daily (default - yesterday's data):**
```bash
python stock_pipeline/scripts/ingest_fmp_prices.py
```

**Custom tickers:**
```bash
# Local file
python stock_pipeline/scripts/ingest_fmp_prices.py \
  --tickers-path my_tickers.csv

# S3 file
python stock_pipeline/scripts/ingest_fmp_prices.py \
  --tickers-path s3://my-bucket/tickers/watchlist.csv
```

**Backfill:**
```bash
# Last 30 days
python stock_pipeline/scripts/ingest_fmp_prices.py --backfill-days 30

# Custom date range
python stock_pipeline/scripts/ingest_fmp_prices.py \
  --from-date 2024-01-01 \
  --to-date 2024-10-24

# Force overwrite
python stock_pipeline/scripts/ingest_fmp_prices.py \
  --backfill-days 30 \
  --force
```

### 3. Statements & Metrics Ingestion

**All endpoints (default):**
```bash
python stock_pipeline/scripts/fmp_dump_raw.py --endpoints all
```

**Specific endpoints:**
```bash
# Only income statements
python stock_pipeline/scripts/fmp_dump_raw.py --endpoints income

# Multiple endpoints
python stock_pipeline/scripts/fmp_dump_raw.py \
  --endpoints income,balance_sheet,cash_flow

# Treasury rates only
python stock_pipeline/scripts/fmp_dump_raw.py --endpoints treasury_rates
```

**Custom date:**
```bash
# Specific snapshot date
python stock_pipeline/scripts/fmp_dump_raw.py \
  --date 2024-10-24 \
  --endpoints all

# Force overwrite
python stock_pipeline/scripts/fmp_dump_raw.py \
  --date 2024-10-24 \
  --endpoints all \
  --force
```

---

## 🤖 GitHub Actions

### Unified Workflow
Single workflow runs **both** price and statements ingestion sequentially.

**File:** `.github/workflows/ingest.yml`

**Schedule:** Monday-Friday at 11 PM UTC (after US market close)

**Jobs:**
1. `ingest-prices` - Fetch OHLCV price data → Parquet
2. `ingest-statements` - Fetch financial statements → NDJSON
3. `workflow-summary` - Generate combined summary

### Manual Dispatch

Trigger via GitHub UI:

1. Go to **Actions** → **FMP Data Ingestion**
2. Click **Run workflow**
3. Configure parameters:
   - **tickers_path**: `stock_pipeline/config/tickers.csv` (default)
   - **from_date / to_date**: Price date range
   - **backfill_days**: Quick price backfill (e.g., `30`)
   - **snapshot_date**: Statements snapshot date (`today` default)
   - **endpoints**: Which FMP endpoints (`all` default)
   - **force**: `true` to overwrite existing files

**GitHub Secrets Required:**
- `FMP_API_KEY`
- `AWS_ROLE_ARN` (for OIDC)
- `AWS_REGION`

**GitHub Variables Required:**
- `S3_BUCKET`
- `S3_RAW_PREFIX` (optional, default: `raw/fmp`)
- `RATE_LIMIT_SECONDS` (optional, default: `0.2`)
- `MAX_WORKERS` (optional, default: `10`)

---

## 🔒 Data Quality & Safety

### Price Data
- ✅ Locked schema (12 columns, prevents drift)
- ✅ Row-level de-dupe by `(symbol, as_of_date)`
- ✅ File-level hash for lineage
- ✅ Validated: non-null symbol/date, non-negative volume
- ✅ Combined files: All symbols per day in one Parquet

### Statements Data
- ✅ Raw JSON payload preserved (no flattening in Bronze)
- ✅ Metadata enrichment (timestamps, hashes, fiscal dates)
- ✅ NDJSON format for schema flexibility
- ✅ De-dupe by `(symbol, endpoint, fiscal_period_end, as_of_date, hash)`

### Idempotency
- Checks if S3 file exists before writing
- **Default behavior**: Skip if exists
- **With `--force`**: Overwrite
- File paths include date partitions for deterministic writes

---

## 📋 Metrics & Monitoring

### Price Metrics
```json
{
  "run_id": "2024-10-24T23:00:00Z",
  "data_type": "prices",
  "endpoint": "historical-price-full",
  "symbols_processed": 100,
  "files_written": 5,
  "rows_written": 500,
  "errors": 0,
  "duration_seconds": 45.2,
  "s3_prefix": "s3://bucket/raw/fmp/prices/"
}
```

### Statements Metrics
```json
{
  "run_id": "2024-10-24T23:00:00Z",
  "data_type": "owner_earnings",
  "symbols_processed": 100,
  "files_written": 100,
  "records_written": 500,
  "errors": 0,
  "duration_seconds": 120.5
}
```

**GitHub Actions Summary:**
```
## FMP Data Ingestion Summary

### Price Data
- Tickers: stock_pipeline/config/tickers.csv
- S3 Prefix: raw/fmp/prices/

### Statements Data
- Snapshot Date: today
- Endpoints: all
- S3 Prefix: raw/fmp/statements/

✅ Ingestion completed. Check S3 for output files and metrics.
```

---

## 🔗 Next Steps: Databricks Integration

### Price Data Auto Loader
```python
bucket = "s3://stock-pipeline-data-dev-mc"
raw_path = f"{bucket}/raw/fmp/prices/"
bronze_path = f"{bucket}/bronze/prices/"
ckpt_path = f"{bucket}/_checkpoints/bronze_prices/"

# Read with Auto Loader
df = (spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "parquet")
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaLocation", f"{ckpt_path}/schema")
    .load(raw_path))

# Write to Delta (append-only, partitioned by date)
(df.writeStream
    .format("delta")
    .option("checkpointLocation", f"{ckpt_path}/stream")
    .option("mergeSchema", "true")
    .partitionBy("as_of_date")
    .trigger(availableNow=True)
    .start(bronze_path))
```

### Statements Auto Loader
```python
raw_path = f"{bucket}/raw/fmp/statements/income/"
bronze_path = f"{bucket}/bronze/fmp_income/"
ckpt_path = f"{bucket}/_checkpoints/bronze_fmp_income/"

# Read NDJSON with Auto Loader
df = (spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaLocation", f"{ckpt_path}/schema")
    .load(raw_path))

# De-dupe and write
df_deduped = df.dropDuplicates(["symbol", "endpoint", "fiscal_period_end", "as_of_date", "hash"])

(df_deduped.writeStream
    .format("delta")
    .option("checkpointLocation", f"{ckpt_path}/stream")
    .option("mergeSchema", "true")
    .partitionBy("as_of_date", "symbol")
    .outputMode("append")
    .trigger(availableNow=True)
    .start(bronze_path))
```

---

## 🛠️ Troubleshooting

### No data returned from API
- Verify `FMP_API_KEY` is valid
- Check FMP account limits (paid tier recommended)
- Try a different ticker (e.g., `AAPL` always works)

### S3 permission errors
- Ensure IAM role/user has `s3:PutObject`, `s3:GetObject`, `s3:ListBucket`
- For GitHub Actions: verify `AWS_ROLE_ARN` OIDC trust policy

### Rate limit errors (429)
- Increase `RATE_LIMIT_SECONDS` (e.g., `1.0`)
- Reduce `MAX_WORKERS` (e.g., `5`)
- FMP paid tier allows 0.1-0.2s rate limiting

### Validation failures (prices)
- Check FMP response format
- Inspect logs for `⚠️ No valid data after validation`
- Verify date range doesn't include weekends/holidays

### Hash computation errors
- Fixed in latest version (uses `to_pandas().to_csv()` not `write_csv()`)
- Re-run with `--force` if seeing stale data

---

## 📚 Additional Resources

- [FMP API Docs](https://site.financialmodelingprep.com/developer/docs)
- [Polars DataFrame Guide](https://pola-rs.github.io/polars/py-polars/html/reference/dataframe/index.html)
- [Databricks Auto Loader](https://docs.databricks.com/ingestion/auto-loader/index.html)

---

**Questions?** Check the main [README](../README.md) or open an issue.
