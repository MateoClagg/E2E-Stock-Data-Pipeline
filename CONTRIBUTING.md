# 🤝 Contributing Guidelines

Thank you for contributing to the E2E Stock Data Pipeline! This guide covers the technical details for development and testing.

> 💡 **New to the project?** Start with [GETTING_STARTED.md](GETTING_STARTED.md) for installation and basic usage.

## 🔧 **Development Setup**

**Option A: Conda (Recommended)**
```bash
# Create conda environment
conda env create -f environment.yml
conda activate stock-pipeline
```

**Option B: Pip**
```bash
# Install dependencies
pip install -r requirements.txt
# Or install as editable package
pip install -e .

# Install dev dependencies
pip install pytest pytest-asyncio pytest-cov ruff
```

## 📝 **Code Standards**

### **Style & Formatting**
- **Ruff** for linting and formatting: `ruff check . && ruff format .`
- **Type hints** required for all functions: `def func(param: str) -> bool:`
- **Docstrings** for public APIs using Google style

### **Commit Messages**
Use [Conventional Commits](https://www.conventionalcommits.org/):
```
feat(ingest): add support for additional FMP endpoints
fix(validation): resolve polars schema validation edge case
docs: update ingestion quickstart guide
test: add integration tests for S3 uploads
```

## 🧪 **Testing Strategy**

### **Test Types**
```bash
# Unit tests (fast, no external deps)
pytest tests/test_ingest_local.py -m "not integration"

# Integration tests (require FMP API key + AWS)
pytest tests/test_ingest_local.py --runlive

# Full test suite with coverage
pytest tests/ --cov=stock_pipeline --cov=validation --cov-report=html
```

### **Test Requirements**
- **Unit tests** for all new functions
- **Integration tests** for API interactions
- **Mock external dependencies** in unit tests
- **Test both success and error cases**

### **Example Test Pattern**
```python
@pytest.mark.asyncio
async def test_fetch_stock_data_success():
    # Arrange
    client = AsyncFMPClient(test_config)
    
    # Act
    with patch.object(client, '_make_request') as mock:
        mock.return_value = [{"symbol": "AAPL", "close": 150.0}]
        result = await client.fetch_all_data("AAPL", "2024-01-01", "2024-01-31")
    
    # Assert
    assert result["price"][0]["close"] == 150.0
```

## 🏗️ **Architecture Guidelines**

### **Adding New Data Sources**
1. **Ingestion**: Update `stock_pipeline/scripts/ingest_local_to_s3.py`
2. **S3 Layout**: Define partitioning strategy in `build_s3_key_for_day()`
3. **Validation**: Add Great Expectations rules in `validation/expectations_*.json`
4. **Databricks**: Update Auto Loader config to ingest new data types
5. **Transformations**: Bronze/Silver/Gold transformations live in Databricks (not this repo)

### **Performance Considerations**
- Use **async/await** for I/O operations (aiohttp)
- Implement **rate limiting** for external APIs (tenacity + custom RateLimiter)
- **Partition data** by symbol/year/month/day in S3
- Use **Polars** for local data transformations (faster than pandas)
- Validate data before writing to S3 (fail fast)

### **Error Handling**
```python
try:
    result = await api_call()
except APIRateLimitError:
    # Implement exponential backoff
    await asyncio.sleep(retry_delay)
except APIError as e:
    logger.error(f"API call failed: {e}")
    raise ProcessingError(f"Failed to fetch data: {e}")
```

## 🔒 **Security Requirements**

- **Never commit secrets**: Use environment variables
- **Validate inputs**: Prevent injection attacks  
- **Use least privilege**: Minimal AWS permissions
- **Audit dependencies**: Run `pip-audit` before releases

## 🚀 **CI/CD Integration**

### **Automated Checks**
- **PR builds**: Fast validation (≤5 min)
- **Main builds**: Full test suite + PySpark validation
- **Release builds**: Security auditing + CodeArtifact publishing

### **Local Validation**
```bash
# Run the same checks as CI
ruff check . && ruff format .
pytest tests/ -v
pytest tests/test_silver_* -v  # PySpark tests
```

## 📊 **Data Pipeline Best Practices**

### **Local Ingestion (Raw Zone)**
- **Async fetching**: Use aiohttp for concurrent API calls
- **Rate limiting**: Respect FMP API limits (12-15s between batches)
- **Idempotency**: Skip existing day files unless `--force`
- **Validation**: Filter invalid data before writing to S3
- **Partitioning**: Day-level partitions for efficient Auto Loader ingestion
- **Metrics**: Emit run metrics to S3 logs for monitoring

### **Data Quality (Validation Layer)**
- Use **Great Expectations** for schema validation
- Define **column expectations** (non-null, min/max, data types)
- **Version control** expectation suites in `validation/`
- Apply validations **before** writing to S3 (fail fast)

### **Databricks Integration**
- **Bronze layer**: Auto Loader streams from S3 raw zone
- **Silver layer**: MERGE operations for deduplication
- **Gold layer**: Feature engineering and aggregations
- All Spark transformations live in Databricks (not this repo)

## 🐛 **Debugging Tips**

### **Local Development**
```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Test API without rate limits
client = AsyncFMPClient(config, rate_limiter=None)

# Inspect Spark execution plans
df.explain(True)
```

### **Databricks Issues**
- Check **cluster logs** for PySpark errors
- Verify **Unity Catalog permissions**
- Test with **smaller datasets** first
- Use `%pip list` to verify package versions

## 🔄 **Release Process**

Maintainers handle releases via git tags:
```bash
git tag v1.2.3
git push origin v1.2.3
# This triggers automated release pipeline
```

## 📚 **Documentation**

- **Code**: Docstrings with examples
- **Architecture**: Update diagrams in `/docs`  
- **APIs**: Keep `/docs` reference current
- **Breaking changes**: Update migration guides

---

**Questions?** Open a [GitHub Discussion](../../discussions) or check our [documentation](docs/README.md).