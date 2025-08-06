# 🤝 Contributing Guidelines

Thank you for contributing to the E2E Stock Data Pipeline! This guide covers the technical details for development and testing.

> 💡 **New to the project?** Start with [GETTING_STARTED.md](GETTING_STARTED.md) for installation and basic usage.

## 🔧 **Development Setup**

```bash
# After cloning, install development dependencies
pip install -e .
pip install pytest pytest-cov ruff

# Set up pre-commit hooks (optional)
pip install pre-commit
pre-commit install
```

## 📝 **Code Standards**

### **Style & Formatting**
- **Ruff** for linting and formatting: `ruff check . && ruff format .`
- **Type hints** required for all functions: `def func(param: str) -> bool:`
- **Docstrings** for public APIs using Google style

### **Commit Messages**
Use [Conventional Commits](https://www.conventionalcommits.org/):
```
feat(bronze): add support for crypto data ingestion
fix(silver): resolve duplicate removal edge case  
docs: update API examples
test: add integration tests for S3 uploads
```

## 🧪 **Testing Strategy**

### **Test Types**
```bash
# Unit tests (fast, no external deps)
pytest tests/ -m "not integration"

# Integration tests (require API keys)
pytest tests/ -m integration  

# Full test suite with coverage
pytest tests/ --cov=bronze --cov=silver --cov=validation
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
1. **Bronze layer**: Create client in `bronze/ingestion/`
2. **Schemas**: Define in `bronze/ingestion/schemas.py`
3. **Silver layer**: Add transformations in `silver/transformations/`
4. **Views**: Update `silver/views/unified_views.py`
5. **Validation**: Add rules in `validation/expectations_*.json`

### **Performance Considerations**
- Use **async/await** for I/O operations
- Implement **rate limiting** for external APIs
- **Partition data** by symbol and date in S3
- Use **PySpark** for large transformations
- Configure **memory settings** appropriately

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

### **Bronze Layer (Raw Ingestion)**
- Store **all raw data** without transformation
- Use **strict schemas** for validation
- Include **lineage metadata** (run_id, ingested_at)
- **Partition by symbol and date** for query performance

### **Silver Layer (Cleaned Data)**
- Apply **data quality rules**
- Create **validity windows** for time-series joins
- Use **Delta Lake** for ACID transactions
- **Deduplicate** and handle missing values

### **Validation Layer**
- Use **Great Expectations** for data quality
- Define **statistical expectations** (min/max/distribution)
- **Alert on anomalies** in production
- **Version control** expectation suites

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