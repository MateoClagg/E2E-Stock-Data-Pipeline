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
RATE_LIMIT_SECONDS=15.0  # Free tier FMP
MAX_WORKERS=5
```

### 3. Run Local Ingestion

```bash
# Fetch yesterday's data (default)
python stock_pipeline/scripts/ingest_local_to_s3.py

# Backfill last 30 days
python stock_pipeline/scripts/ingest_local_to_s3.py --backfill-days 30

# Custom date range
python stock_pipeline/scripts/ingest_local_to_s3.py \
  --from-date 2024-01-01 \
  --to-date 2024-09-30
```

### 4. Verify S3 Output

```bash
aws s3 ls s3://your-bucket/raw/prices/ --recursive

# Expected structure:
# raw/prices/symbol=AAPL/year=2024/month=09/day=30/AAPL-2024-09-30.parquet
```

---

## 🏗️ Architecture

```
Local/GitHub Actions      S3 Raw Zone              Databricks
┌─────────────────┐       ┌──────────────┐         ┌─────────────────┐
│ FMP API         │       │ Day-level    │         │ Auto Loader     │
│ (async fetch)   │──────▶│ Parquet      │────────▶│ → Bronze (CDF)  │
│ polars/pyarrow  │       │ partitions   │         │ → Silver/Gold   │
└─────────────────┘       └──────────────┘         └─────────────────┘
```

**Key principle:** API wait time runs locally (free), Databricks only for data transformations (cost-optimized).

---

## 📊 What Gets Ingested

### Price Data (Daily OHLCV)
- Date, Open, High, Low, Close, Adj Close, Volume
- Partitioned by: `symbol/year/month/day`
- One Parquet file per symbol per day

### Fundamentals (Future)
- Income statements, balance sheets, cash flow (annual)
- Partitioned by: `type/symbol/year/docdate`

---

## 🤖 GitHub Actions (Automated)

The pipeline runs automatically Monday-Friday at 11 PM UTC (after US market close).

**Manual trigger:**
1. Go to **Actions** → **Stock Data Ingestion**
2. Click **Run workflow**
3. Configure: tickers, dates, backfill days, force overwrite

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

```sql
-- Auto-load from S3 → Bronze Delta table
CREATE OR REFRESH STREAMING LIVE TABLE bronze_prices
AS SELECT * FROM cloud_files(
  's3://your-bucket/raw/prices/',
  'parquet',
  map('cloudFiles.schemaLocation', 's3://your-bucket/schemas/prices/')
);

-- Bronze → Silver (deduplication, quality checks)
MERGE INTO silver.prices ...

-- Silver → Gold (features, aggregations)
CREATE VIEW gold.price_features AS ...
```

See [databricks/DATABRICKS_SETUP.md](databricks/DATABRICKS_SETUP.md) for complete setup.

---

## 🆘 Common Issues

**FMP API rate limit errors (429)?**
- Increase `RATE_LIMIT_SECONDS` to `20.0` or higher
- Reduce `MAX_WORKERS` to process fewer symbols concurrently
- Free tier: 250 calls/day

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
