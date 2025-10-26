# 🚀 Getting Started

**Local stock data ingestion pipeline** - Fetches FMP market data locally (cost-optimized) and writes to S3 for Databricks processing.

---

## 📋 Prerequisites

- **Python 3.10+** with pip
- **FMP API key** from [Financial Modeling Prep](https://financialmodelingprep.com/)
- **AWS account** with S3 access
- **Databricks workspace** (for Bronze/Silver/Gold transformations)

---

## ⚡ Quick Start

### 1. Clone and Install

**Option A: Conda (Recommended for local development)**
```bash
git clone <repository-url>
cd E2E-Stock-Data-Pipeline

# Create conda environment
conda env create -f environment.yml
conda activate stock-pipeline
```

**Option B: Pip**
```bash
git clone <repository-url>
cd E2E-Stock-Data-Pipeline

# Install dependencies
pip install -r requirements.txt
# Or install as editable package
pip install -e .
```

### 2. Configure Environment

Create `.env` file in project root:

```bash
# FMP API
FMP_API_KEY=your_fmp_api_key_here

# AWS S3
S3_BUCKET=your-bucket-name
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_DEFAULT_REGION=us-east-1

# Optional: Rate limiting
RATE_LIMIT_SECONDS=0.2   # Paid tier (300/min). Free tier: use 15.0 (250/day)
MAX_WORKERS=10
```

### 3. Run Local Ingestion

**Price Data (OHLCV - Daily):**
```bash
# Fetch yesterday's data (default)
python stock_pipeline/scripts/ingest_fmp_prices.py

# Backfill last 30 days
python stock_pipeline/scripts/ingest_fmp_prices.py --backfill-days 30

# Custom date range
python stock_pipeline/scripts/ingest_fmp_prices.py \
  --from-date 2024-01-01 \
  --to-date 2024-10-24
```

**Financial Statements & Metrics:**
```bash
# Fetch all endpoints (income, balance sheet, cash flow, owner earnings, treasury rates)
python stock_pipeline/scripts/fmp_dump_raw.py --endpoints all

# Specific endpoints only
python stock_pipeline/scripts/fmp_dump_raw.py --endpoints income,balance_sheet

# Treasury rates only
python stock_pipeline/scripts/fmp_dump_raw.py --endpoints treasury_rates
```

### 4. Verify S3 Output

```bash
# Price data (Parquet - all symbols combined per day)
aws s3 ls s3://your-bucket/raw/fmp/prices/ --recursive
# Expected: raw/fmp/prices/dt=2024-10-24/prices-2024-10-24.parquet

# Financial statements (NDJSON - per symbol)
aws s3 ls s3://your-bucket/raw/fmp/statements/income/ --recursive
# Expected: raw/fmp/statements/income/dt=2024-10-24/symbol=AAPL/AAPL-income-2024-10-24.ndjson

# Treasury rates (NDJSON - market-wide)
aws s3 ls s3://your-bucket/raw/fmp/treasury_rates/ --recursive
# Expected: raw/fmp/treasury_rates/dt=2024-10-24/treasury-rates-2024-10-24.ndjson
```

---

## 🏗️ Architecture

```
Local/GitHub Actions      S3 Raw Zone              Databricks
┌─────────────────┐       ┌──────────────┐         ┌─────────────────┐
│ FMP API         │       │ Parquet +    │         │ Auto Loader     │
│ (async fetch)   │──────▶│ NDJSON       │────────▶│ → Bronze (CDF)  │
│ polars/pyarrow  │       │ dt= parts    │         │ → Silver/Gold   │
└─────────────────┘       └──────────────┘         └─────────────────┘
```

**Key principle:** API wait time runs locally (free), Databricks only for data transformations (cost-optimized).

**Data formats:**
- **Prices**: Parquet (all symbols combined per day, locked schema)
- **Statements**: NDJSON (raw JSON payloads, flexible schema)

---

## 📊 What Gets Ingested

### Price Data (Daily OHLCV)
- Symbol, Date, Open, High, Low, Close, Volume
- Metadata: fetched_at, source, endpoint, request_id, file_hash
- Partitioned by: `dt=YYYY-MM-DD`
- Format: Parquet (all symbols combined per day)
- S3 Path: `raw/fmp/prices/dt=2024-10-24/prices-2024-10-24.parquet`

### Financial Statements (Annual)
- **Income Statement**: Revenue, expenses, net income (5 years)
- **Balance Sheet**: Assets, liabilities, equity (5 years)
- **Cash Flow**: Operating, investing, financing activities (5 years)
- **Owner Earnings**: Buffett-style owner earnings calculation (5 years)
- Partitioned by: `dt=YYYY-MM-DD/symbol=X`
- Format: NDJSON (preserves raw JSON payloads)
- S3 Path: `raw/fmp/statements/{type}/dt=2024-10-24/symbol=AAPL/AAPL-{type}-2024-10-24.ndjson`

### Treasury Rates (Daily)
- Full yield curve (1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 30Y)
- Partitioned by: `dt=YYYY-MM-DD`
- Format: NDJSON
- S3 Path: `raw/fmp/treasury_rates/dt=2024-10-24/treasury-rates-2024-10-24.ndjson`

---

## 🤖 GitHub Actions (Automated)

The unified ingestion workflow runs automatically Monday-Friday at 11 PM UTC (after US market close).

**Jobs (sequential execution):**
1. **ingest-prices** - Fetch price data → Parquet
2. **ingest-statements** - Fetch financial statements → NDJSON
3. **workflow-summary** - Generate combined summary

**Manual trigger:**
1. Go to **Actions** → **FMP Data Ingestion**
2. Click **Run workflow**
3. Configure parameters:
   - **Price settings**: tickers path, date range, backfill days
   - **Statements settings**: snapshot date, endpoints (all/specific)
   - **force**: Overwrite existing files

See [docs/ingestion_quickstart.md](docs/ingestion_quickstart.md) for full details.

---

## 🧪 Testing

```bash
# Run unit tests
pytest tests/test_ingest_local.py -v

# Test S3 key generation
pytest tests/test_ingest_local.py::TestS3KeyBuilder -v

# Test Polars validation
pytest tests/test_ingest_local.py::TestPolarsTransformations -v
```

---

## 🔧 Databricks Integration

Once raw data lands in S3, configure Databricks Auto Loader:

**Price Data (Parquet):**
```python
# Read with Auto Loader
df = (spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "parquet")
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaLocation", f"{checkpoint_path}/schema")
    .load("s3://your-bucket/raw/fmp/prices/"))

# Write to Bronze Delta (append-only, CDF enabled)
(df.writeStream
    .format("delta")
    .option("checkpointLocation", f"{checkpoint_path}/stream")
    .partitionBy("as_of_date")
    .trigger(availableNow=True)
    .start("s3://your-bucket/bronze/prices/"))
```

**Financial Statements (NDJSON):**
```python
# Read NDJSON with Auto Loader
df = (spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "json")  # NDJSON = JSON lines
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaLocation", f"{checkpoint_path}/schema")
    .load("s3://your-bucket/raw/fmp/statements/income/"))

# De-dupe and write to Bronze
(df.dropDuplicates(["symbol", "endpoint", "fiscal_period_end", "as_of_date", "hash"])
    .writeStream
    .format("delta")
    .option("checkpointLocation", f"{checkpoint_path}/stream")
    .partitionBy("as_of_date", "symbol")
    .trigger(availableNow=True)
    .start("s3://your-bucket/bronze/fmp_income/"))
```

See [databricks/DATABRICKS_SETUP.md](databricks/DATABRICKS_SETUP.md) for complete setup.

---

## 🆘 Common Issues

**FMP API rate limit errors (429)?**
- **Free tier**: 250 calls/day - set `RATE_LIMIT_SECONDS=15.0` or higher
- **Paid tier**: 300 calls/minute - set `RATE_LIMIT_SECONDS=0.2` (default)
- Reduce `MAX_WORKERS` to process fewer symbols concurrently if needed

**S3 permission errors?**
- Verify IAM role has `s3:PutObject`, `s3:GetObject`, `s3:ListBucket`
- For GitHub Actions: check `AWS_ROLE_ARN` trust policy for OIDC

**No data returned from API?**
- Verify `FMP_API_KEY` is valid
- Try a different ticker (e.g., `AAPL` always works)
- Check FMP account status/limits

**Trading days vs calendar days?**
- Script uses `pandas-market-calendars` for NYSE calendar
- Weekends/holidays are automatically excluded

---

## 📚 Next Steps

1. **[Ingestion Guide](docs/ingestion_quickstart.md)** - Complete local ingestion documentation
2. **[Databricks Setup](databricks/DATABRICKS_SETUP.md)** - Unity Catalog and medallion architecture
3. **[GitHub Workflows](.github/workflows/ingest.yml)** - Automated ingestion config

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.
