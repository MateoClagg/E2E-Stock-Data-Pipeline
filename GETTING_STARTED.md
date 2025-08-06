# 🚀 Getting Started

**E2E Stock Data Pipeline** - Enterprise-grade financial data ingestion and processing pipeline built for Databricks.

## 📋 **Prerequisites**

- **Python 3.10+** with pip
- **FMP API key** from [Financial Modeling Prep](https://financialmodelingprep.com/)
- **AWS account** with S3 access
- **Databricks workspace** (optional for local development)

## ⚡ **Quick Start**

### **1. Install the Package**

```bash
# From PyPI (once published)
pip install stock-pipeline

# Development install
git clone <repository-url>
cd E2E-Stock-Data-Pipeline
pip install -e .
```

### **2. Environment Setup**

Create `.env` file in the project root:

```bash
# API Configuration
FMP_API_KEY=your_fmp_api_key_here

# AWS Configuration  
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_DEFAULT_REGION=us-east-2

# S3 Buckets
S3_BUCKET_BRONZE=your-bronze-bucket-name
```

### **3. Run Bronze Layer Ingestion**

```bash
# Ingest yesterday's data for specific tickers
python -m bronze.ingestion.fmp --tickers AAPL,MSFT,TSLA

# Backfill 5 years of historical data
python -m bronze.ingestion.fmp --tickers AAPL --backfill
```

### **4. Databricks Integration**

The package automatically uploads to S3 for Unity Catalog access:

```python
# In Databricks notebook
%pip install stock-pipeline==<version> --index-url <your-codeartifact-url>

# Or from Unity Catalog Volume
%pip install /Volumes/catalog/schema/volume/wheels/stock-pipeline/<version>/stock_pipeline-<version>-py3-none-any.whl
```

## 🏗️ **Architecture**

### **Medallion Data Architecture**
```
📊 FMP API → 🥉 Bronze (Raw S3) → 🥈 Silver (Cleaned) → 🥇 Gold (Analytics)
```

### **Package Structure**
```
stock-pipeline/
├── bronze/           # Raw data ingestion from FMP API
│   ├── ingestion/    # API clients and ingestion logic
│   └── utils.py      # Shared utilities and Spark configuration
├── silver/           # Data transformations and cleaning
│   ├── transformations/ # Business logic transformations
│   └── views/        # Unified analytical views
├── validation/       # Data quality and Great Expectations
└── tests/           # Comprehensive test suite
```

## 🔧 **Production Setup**

For full production deployment with CI/CD, AWS CodeArtifact, and Databricks automation, see:

- **[📊 Databricks Setup](databricks/DATABRICKS_SETUP.md)** - Unity Catalog and cluster configuration  
- **[📚 Documentation](docs/README.md)** - Complete documentation index

## 🧪 **Testing**

```bash
# Run unit tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=bronze --cov=silver --cov=validation

# Skip integration tests (require live API/S3)
pytest tests/ -m "not integration"
```

## 📖 **Usage Examples**

### **Bronze Layer - Raw Data Ingestion**
```python
from bronze.utils import AsyncFMPClient, FMPConfig

# Initialize client
config = FMPConfig(api_key="your_api_key")
client = AsyncFMPClient(config)

# Fetch data for multiple symbols
data = await client.fetch_all_data("AAPL", "2024-01-01", "2024-12-31")
# Returns: {"price": [...], "income": [...], "cashflow": [...], "balance": [...]}
```

### **Silver Layer - Transformations**
```python
from silver.transformations.clean_data import remove_duplicates
from silver.views.unified_views import create_price_fundamental_view

# Clean data
cleaned_df = remove_duplicates(raw_df)

# Create analytical views
unified_view = create_price_fundamental_view(spark)
```

## 🆘 **Common Issues**

**Environment Variables Not Loading?**
- Ensure `.env` file is in project root
- Check `.env` file syntax (no spaces around `=`)

**S3 Permission Errors?**
- Verify AWS credentials have S3 read/write access
- Check bucket name format (no `s3://` prefix in env vars)

**FMP API Rate Limits?**
- Built-in rate limiting (5 requests/second)
- Upgrade FMP plan for higher limits

## 🤝 **Contributing**

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 **License**

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📞 **Support**

- **Documentation**: [docs/](docs/README.md)
- **Issues**: [GitHub Issues](../../issues)
- **Discussions**: [GitHub Discussions](../../discussions)