# 🔧 Troubleshooting Guide

Common issues and solutions for the stock data ingestion pipeline.

---

## 🚨 Common Issues

### 1. FMP API Issues

#### **Error: `401 Unauthorized` or `Invalid API Key`**
**Cause:** FMP_API_KEY is invalid or expired

**Solution:**
```bash
# Verify your API key
echo $FMP_API_KEY

# Test API key directly
curl "https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=$FMP_API_KEY"

# Update .env file
vim .env  # Add FMP_API_KEY=your_actual_key
```

#### **Error: `429 Too Many Requests`**
**Cause:** Exceeded FMP API rate limits

**Solution:**
```bash
# Increase rate limit delay
export RATE_LIMIT_SECONDS=20.0  # Default is 15.0

# Reduce concurrent workers
export MAX_WORKERS=3  # Default is 5

# Free tier limits: 250 calls/day
```

#### **Warning: No data returned for symbol**
**Cause:** Invalid ticker symbol or delisted stock

**Solution:**
```bash
# Test the symbol directly
python -c "
import asyncio
from stock_pipeline.scripts.ingest_local_to_s3 import FMPClient, Config, RateLimiter

async def test():
    config = Config()
    Config.validate()
    rate_limiter = RateLimiter(15.0)
    async with FMPClient(config.FMP_API_KEY, rate_limiter) as client:
        data = await client.fetch_prices('AAPL', '2024-09-01', '2024-09-30')
        print(f'Got {len(data)} records')

asyncio.run(test())
"
```

---

### 2. AWS S3 Issues

#### **Error: `Access Denied` or `NoSuchBucket`**
**Cause:** Insufficient IAM permissions or wrong bucket name

**Solution:**
```bash
# Verify bucket exists
aws s3 ls s3://$S3_BUCKET/

# Check IAM permissions
aws sts get-caller-identity

# Required permissions:
# - s3:PutObject
# - s3:GetObject
# - s3:ListBucket
```

#### **Error: `An error occurred (ExpiredToken)`**
**Cause:** AWS credentials expired (GitHub Actions OIDC tokens)

**Solution:**
- OIDC tokens are valid for 12 hours
- Workflow will automatically refresh on next run
- For local development, refresh AWS credentials

#### **Files not appearing in S3**
**Cause:** Check for silent failures in ingestion script

**Solution:**
```bash
# Check metrics.json for errors
aws s3 ls s3://$S3_BUCKET/logs/ingest/date=$(date +%Y-%m-%d)/ --recursive

# Download and inspect metrics
aws s3 cp s3://$S3_BUCKET/logs/ingest/date=2024-09-30/run-*.json - | jq '.errors'
```

---

### 3. Local Development Issues

#### **Error: `ModuleNotFoundError: No module named 'stock_pipeline'`**
**Cause:** Package not installed

**Solution:**
```bash
# Install in editable mode
pip install -e .

# Or use conda
conda env create -f environment.yml
conda activate stock-pipeline
```

#### **Error: `ImportError: cannot import name 'Config'`**
**Cause:** Circular imports or missing __init__.py

**Solution:**
```bash
# Check package structure
find stock_pipeline -name "__init__.py"

# Reinstall package
pip uninstall stock-pipeline
pip install -e .
```

#### **Tests fail with `AssertionError`**
**Cause:** Dependencies not installed or outdated

**Solution:**
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run specific test
pytest tests/test_ingest_local.py::TestS3KeyBuilder -v

# Check test dependencies
pip list | grep -E "pytest|polars|aiohttp"
```

---

### 4. Data Quality Issues

#### **Warning: `No valid data after validation`**
**Cause:** All records filtered out due to validation failures

**Solution:**
```python
# Check validation logic in prices_to_polars()
# Common issues:
# - Null symbols or dates
# - Negative volumes
# - Invalid date formats

# Debug validation
import polars as pl
from stock_pipeline.scripts.ingest_local_to_s3 import prices_to_polars
from datetime import datetime, timezone

test_data = [{"symbol": "AAPL", "date": "2024-09-30", "volume": 1000}]
df = prices_to_polars("AAPL", test_data, datetime.now(timezone.utc))
print(df)
```

#### **Error: `Polars schema mismatch`**
**Cause:** FMP API response structure changed

**Solution:**
- Check FMP API documentation
- Update `prices_to_polars()` function
- Add new columns to validation expectations

---

### 5. GitHub Actions Issues

#### **Workflow: `FMP_API_KEY not set`**
**Cause:** GitHub secret not configured

**Solution:**
1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Add secret: `FMP_API_KEY`
3. Re-run workflow

#### **Workflow: `AWS authentication failed`**
**Cause:** OIDC role trust policy misconfigured

**Solution:**
```json
// IAM Role Trust Policy should include:
{
  "Effect": "Allow",
  "Principal": {
    "Federated": "arn:aws:iam::{ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
  },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
    },
    "StringLike": {
      "token.actions.githubusercontent.com:sub": "repo:{ORG}/{REPO}:*"
    }
  }
}
```

---

## 🔍 Debugging Commands

### Check Ingestion Logs
```bash
# View recent S3 metrics
aws s3 ls s3://$S3_BUCKET/logs/ingest/ --recursive --human-readable | tail -20

# Download latest metrics
aws s3 cp s3://$S3_BUCKET/logs/ingest/date=$(date +%Y-%m-%d)/ . --recursive

# Parse errors from metrics
cat run-*.json | jq '.results[] | select(.errors | length > 0)'
```

### Verify S3 Data
```bash
# Count files written today
aws s3 ls s3://$S3_BUCKET/raw/prices/ --recursive | grep $(date +%Y-%m-%d) | wc -l

# Check specific symbol
aws s3 ls s3://$S3_BUCKET/raw/prices/symbol=AAPL/ --recursive

# Download and inspect Parquet
aws s3 cp s3://$S3_BUCKET/raw/prices/symbol=AAPL/year=2024/month=09/day=30/AAPL-2024-09-30.parquet .
python -c "import polars as pl; print(pl.read_parquet('AAPL-2024-09-30.parquet'))"
```

### Test Trading Calendar
```python
from stock_pipeline.scripts.utils.dates import get_trading_days, is_trading_day

# Check if today is a trading day
import datetime
today = datetime.date.today().strftime("%Y-%m-%d")
print(f"Is {today} a trading day? {is_trading_day(today)}")

# Get last 5 trading days
from stock_pipeline.scripts.utils.dates import get_last_n_trading_days
from_date, to_date = get_last_n_trading_days(5)
print(f"Last 5 trading days: {from_date} to {to_date}")
```

---

## 📞 Getting Help

1. **Check logs**: `s3://{bucket}/logs/ingest/`
2. **Review metrics**: Look for `errors` array in metrics.json
3. **Enable debug logging**: Set `LOG_LEVEL=DEBUG` in .env
4. **Run locally**: Test with a single ticker first
5. **Check GitHub Issues**: Search for similar problems

---

## 🆘 Emergency Procedures

### Stop Runaway Ingestion
```bash
# Kill local process
pkill -f ingest_local_to_s3.py

# Cancel GitHub Actions workflow
gh run cancel <run-id>
```

### Rollback Bad Data
```bash
# Delete specific day's data
aws s3 rm s3://$S3_BUCKET/raw/prices/ \
  --recursive \
  --exclude "*" \
  --include "*/day=30/*"

# Re-run with --force
python stock_pipeline/scripts/ingest_local_to_s3.py \
  --from-date 2024-09-30 \
  --to-date 2024-09-30 \
  --force
```

### Check API Quota
```bash
# FMP free tier: 250 calls/day
# Each symbol = 1 call
# Monitor usage via FMP dashboard

# Estimate remaining quota
TICKERS_TODAY=$(aws s3 ls s3://$S3_BUCKET/logs/ingest/date=$(date +%Y-%m-%d)/ | wc -l)
echo "Estimated calls today: $TICKERS_TODAY"
echo "Remaining (free tier): $((250 - TICKERS_TODAY))"
```
