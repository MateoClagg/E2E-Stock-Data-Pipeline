# 🚀 GitHub Actions Workflows

This repository uses three main GitHub Actions workflows for CI/CD automation.

---

## 📋 Workflow Overview

| Workflow | Trigger | Purpose | Duration |
|----------|---------|---------|----------|
| **PR Build** | Pull requests to `main` | Fast validation (lint, build, test) | ~3-5 min |
| **Main Build** | Push to `main` | Comprehensive testing + S3 uploads | ~8-10 min |
| **Ingestion** | Nightly cron (Mon-Fri 11 PM UTC) | Fetch stock data → S3 | ~5-15 min |

---

## 🔄 PR Build Workflow (`pr-build.yml`)

**Goal:** Fast feedback for pull requests (≤5 minutes)

### Steps:
1. **Checkout code** (shallow clone for speed)
2. **Install dependencies** (cached pip)
3. **Quick lint check** (ruff, non-blocking)
4. **Build wheel** (wheel only, no sdist)
5. **Verify build** (twine check)
6. **Import smoke test** (verify `stock_pipeline` imports)
7. **Run unit tests** (timeout 60s, non-blocking)
8. **Upload artifact** (7-day retention)

### Key Optimizations:
- Single Python version (3.11) for speed
- Shallow git clone (`fetch-depth: 1`)
- Wheel-only build (no source distribution)
- Aggressive timeouts to catch hanging tests
- Continue-on-error for non-critical steps

---

## ✅ Main Build Workflow (`main-build.yml`)

**Goal:** Comprehensive validation before merging to main

### Steps:
1. **Matrix testing** (Python 3.10 + 3.11)
2. **Full lint check** (ruff with auto-fix)
3. **Build both artifacts** (wheel + sdist)
4. **Comprehensive tests** (full coverage)
5. **Upload coverage** (Codecov integration)
6. **AWS OIDC auth** (for S3 uploads)
7. **Upload wheel to S3** (for Databricks Unity Catalog)

### Key Features:
- **Full git history** (`fetch-depth: 0`) for setuptools_scm versioning
- **Python version matrix** (3.10, 3.11)
- **Coverage reporting** to Codecov
- **S3 wheel uploads** for Databricks consumption

### S3 Upload:
```
s3://{S3_WHEELS_BUCKET}/wheels/stock-pipeline/main/stock_pipeline-latest.whl
```

---

## 📊 Stock Data Ingestion Workflow (`ingest.yml`)

**Goal:** Automated nightly stock data ingestion

### Triggers:
- **Scheduled**: Monday-Friday at 11 PM UTC (after US market close)
- **Manual**: Workflow dispatch with custom parameters

### Manual Dispatch Parameters:
- `tickers_path`: Path to ticker file (local or s3://)
- `from_date` / `to_date`: Custom date range
- `backfill_days`: Quick backfill (e.g., 30 days)
- `force`: Overwrite existing S3 files

### Steps:
1. **Checkout code**
2. **Install dependencies** (aiohttp, polars, boto3, pandas-market-calendars)
3. **AWS OIDC authentication**
4. **Run ingestion script** with configured parameters
5. **Upload workflow summary**

### Environment Variables (Required):
- `FMP_API_KEY` (secret)
- `S3_BUCKET` (variable)
- `AWS_ROLE_ARN` (secret, for OIDC)
- `AWS_REGION` (secret)

### Optional Variables:
- `S3_RAW_PREFIX` (default: `raw`)
- `RATE_LIMIT_SECONDS` (default: `15.0`)
- `MAX_WORKERS` (default: `5`)

---

## 🔒 Security & Permissions

### OIDC Authentication
All workflows use **OpenID Connect (OIDC)** for AWS authentication:
- No long-lived AWS credentials stored in GitHub
- Time-limited tokens (12-hour validity)
- IAM role trust policy for GitHub Actions

### Required IAM Permissions:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${S3_BUCKET}/*",
        "arn:aws:s3:::${S3_BUCKET}"
      ]
    }
  ]
}
```

### GitHub Secrets Required:
- `FMP_API_KEY`
- `AWS_ROLE_ARN`
- `AWS_REGION`

### GitHub Variables Required:
- `S3_BUCKET`
- `S3_WHEELS_BUCKET` (for main-build.yml)

---

## 🛠️ Local Testing

### Test PR Build Locally:
```bash
# Install dependencies
pip install -r requirements.txt

# Lint
ruff check . --select E9,F63,F7,F82

# Build
python -m build --wheel

# Test
pip install dist/*.whl
python -c "import stock_pipeline; print(stock_pipeline.__version__)"
pytest tests/test_ingest_local.py -m "not integration"
```

### Test Ingestion Locally:
```bash
# Set environment variables
export FMP_API_KEY="your_key"
export S3_BUCKET="your_bucket"
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."

# Run ingestion
python stock_pipeline/scripts/ingest_local_to_s3.py
```

---

## 📈 Performance Targets

| Workflow | Target | Actual | Status |
|----------|--------|--------|--------|
| PR Build | ≤5 min | ~3-4 min | ✅ |
| Main Build | ≤10 min | ~8-9 min | ✅ |
| Ingestion (10 tickers) | ≤10 min | ~5-8 min | ✅ |
| Ingestion (100 tickers) | ≤30 min | ~20-25 min | ✅ |

---

## 🐛 Troubleshooting

### PR Build Failures
- **Import errors**: Check `pyproject.toml` packages list
- **Test timeouts**: Reduce test scope or increase timeout
- **Lint failures**: Run `ruff check . --fix` locally

### Main Build Failures
- **Coverage issues**: Update coverage thresholds in workflow
- **S3 upload fails**: Check AWS_ROLE_ARN trust policy

### Ingestion Failures
- **FMP API errors**: Check API key validity and rate limits
- **S3 permission errors**: Verify IAM role permissions
- **No data returned**: Check ticker symbols are valid

---

## 📚 Additional Resources

- [GitHub Actions Docs](https://docs.github.com/en/actions)
- [OIDC with AWS](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [Ingestion Quickstart](../ingestion_quickstart.md)
