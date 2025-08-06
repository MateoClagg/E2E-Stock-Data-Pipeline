# Databricks Installation Guide

This guide covers three methods for installing and using the `stock-pipeline` package in Databricks.

## 🎯 Installation Methods

### Method 1: CodeArtifact with Cluster Init Script (Recommended for Production)

**Advantages:**
- ✅ Automatic token refresh (12-hour validity)
- ✅ Cluster-wide installation
- ✅ Handles authentication complexity
- ✅ Works across cluster restarts

**Setup Steps:**

1. **Upload Init Script to DBFS:**
   ```bash
   # From your local machine or Databricks CLI
   databricks fs cp databricks/init-script.sh dbfs:/init-scripts/stock-pipeline-install.sh
   ```

2. **Configure Cluster Environment Variables:**
   
   In your cluster configuration (`Advanced Options` → `Environment Variables`):
   ```bash
   CODEARTIFACT_DOMAIN=<your-domain>
   CODEARTIFACT_ACCOUNT_ID=<your-account-id>
   CODEARTIFACT_REPOSITORY=<your-repository>
   AWS_REGION=<your-region>
   STOCK_PIPELINE_VERSION=1.2.3  # Optional: pin specific version
   ```

3. **Add Init Script to Cluster:**
   
   In cluster configuration (`Advanced Options` → `Init Scripts`):
   ```
   DBFS Path: dbfs:/init-scripts/stock-pipeline-install.sh
   ```

4. **Restart Cluster** and verify installation:
   ```python
   import stock_pipeline
   print(f"✅ Installed version: {stock_pipeline.__version__}")
   ```

**IAM Requirements:**
Your Databricks cluster's instance profile needs:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "codeartifact:GetAuthorizationToken",
                "codeartifact:GetRepositoryEndpoint",
                "codeartifact:ReadFromRepository"
            ],
            "Resource": [
                "arn:aws:codeartifact:<region>:<account-id>:domain/<domain>",
                "arn:aws:codeartifact:<region>:<account-id>:repository/<domain>/<repository>"
            ]
        },
        {
            "Effect": "Allow",
            "Action": "sts:GetServiceBearerToken",
            "Resource": "*",
            "Condition": {
                "StringEquals": {
                    "sts:AWSServiceName": "codeartifact.amazonaws.com"
                }
            }
        }
    ]
}
```

---

### Method 2: Unity Catalog Volumes (Fallback/Air-gapped)

**Advantages:**
- ✅ No token expiration issues
- ✅ Works in air-gapped environments
- ✅ Immutable versioned storage
- ✅ Fine-grained access control via Unity Catalog

**Setup Steps:**

1. **Create External Location and Volume:**
   ```sql
   -- Create external location pointing to S3 bucket
   CREATE EXTERNAL LOCATION stock_pipeline_wheels
   URL 's3://<your-bucket>/wheels/'
   WITH (CREDENTIAL `<your-storage-credential>`);
   
   -- Create volume
   CREATE VOLUME <catalog>.<schema>.stock_pipeline_wheels
   USING EXTERNAL LOCATION stock_pipeline_wheels;
   ```

2. **Grant Access:**
   ```sql
   GRANT READ VOLUME ON VOLUME <catalog>.<schema>.stock_pipeline_wheels 
   TO `<your-workspace-users>`;
   ```

3. **Install from Volume:**
   ```python
   # Install specific version
   %pip install /Volumes/<catalog>/<schema>/stock_pipeline_wheels/stock-pipeline/1.2.3/stock_pipeline-1.2.3-py3-none-any.whl
   
   # Or use variables for dynamic versioning
   version = "1.2.3"
   %pip install f"/Volumes/<catalog>/<schema>/stock_pipeline_wheels/stock-pipeline/{version}/stock_pipeline-{version}-py3-none-any.whl"
   ```

**File Layout in S3/Volumes:**
```
s3://your-bucket/wheels/
├── stock-pipeline/
│   ├── 1.0.0/
│   │   └── stock_pipeline-1.0.0-py3-none-any.whl
│   ├── 1.1.0/
│   │   └── stock_pipeline-1.1.0-py3-none-any.whl
│   └── 1.2.3/
│       └── stock_pipeline-1.2.3-py3-none-any.whl
```

---

### Method 3: Databricks Repos (Development Only)

**Advantages:**
- ✅ Live code editing and testing
- ✅ Git integration
- ✅ No packaging overhead

**⚠️ Use Case:** Development and testing only, never production

**Setup Steps:**

1. **Clone Repository:**
   - Go to `Repos` in Databricks workspace
   - Click `Add Repo` and clone your repository

2. **Install in Editable Mode:**
   ```python
   # Navigate to repo root and install
   %pip install -e .
   
   # Restart Python to reload changes
   dbutils.library.restartPython()
   ```

3. **Development Workflow:**
   ```python
   # After making code changes
   dbutils.library.restartPython()
   import bronze, silver  # Will load fresh code
   ```

---

## 🔧 Package Usage Examples

### Basic Import and Usage
```python
# Core modules
import bronze, silver, ingestion, validation
import stock_pipeline

print(f"Package version: {stock_pipeline.__version__}")

# Specific functionality
from bronze.ingestion.fmp_bronze import fetch_stock_data
from silver.transformations.clean_data import remove_duplicates
from silver.views.unified_views import create_stock_summary
```

### PySpark Integration
```python
# The package is designed to work seamlessly with PySpark
from pyspark.sql import SparkSession
from silver.transformations import clean_data

# Your existing Spark session in Databricks
df = spark.table("bronze.stock_prices")
cleaned_df = clean_data.remove_duplicates(df)
```

### Version Management
```python
# Check installed version
import stock_pipeline
current_version = stock_pipeline.__version__
print(f"Current version: {current_version}")

# Version comparison for conditional logic
from packaging import version
if version.parse(current_version) >= version.parse("1.2.0"):
    # Use new features
    pass
```

---

## 🚨 Troubleshooting

### Common Issues

**1. CodeArtifact Token Expired**
```
ERROR: Could not find a version that satisfies the requirement stock-pipeline
```
**Solution:** Restart cluster (init script will fetch fresh token)

**2. Import Errors After Installation**
```python
# Restart Python kernel to refresh imports
dbutils.library.restartPython()
```

**3. Version Cache Issues**
```python
# Clear pip cache and reinstall
%pip cache purge
%pip install --no-cache-dir stock-pipeline==1.2.3 --index-url <your-index-url>
```

**4. Permission Denied on CodeArtifact**
- Verify cluster's instance profile has required CodeArtifact permissions
- Check that domain, repository, and account ID are correct
- Ensure AWS region matches your CodeArtifact setup

**5. Unity Catalog Volume Access**
```sql
-- Check volume permissions
SHOW GRANTS ON VOLUME <catalog>.<schema>.stock_pipeline_wheels;

-- Grant access if needed
GRANT READ VOLUME ON VOLUME <catalog>.<schema>.stock_pipeline_wheels TO `<user>`;
```

### Debugging Commands

```python
# Check installed packages
%pip list | grep stock-pipeline

# Verify import paths
import sys
print([p for p in sys.path if 'stock' in p.lower()])

# Test basic functionality
try:
    import bronze, silver, ingestion
    print("✅ All modules imported successfully")
except ImportError as e:
    print(f"❌ Import failed: {e}")

# Check PySpark integration
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
test_df = spark.createDataFrame([("TEST", 100.0)], ["symbol", "price"])
print(f"✅ PySpark test: {test_df.count()} rows")
```

---

## 📋 Production Upgrade Checklist

When upgrading to a new version:

1. **Test in Development First:**
   ```python
   # In dev cluster/notebook
   %pip install stock-pipeline==X.Y.Z --index-url <index-url>
   # Run your tests
   ```

2. **Update Environment Variable:**
   ```bash
   STOCK_PIPELINE_VERSION=X.Y.Z  # In cluster config
   ```

3. **Rolling Cluster Restart:**
   - Restart clusters one by one
   - Verify package installation
   - Run smoke tests

4. **Rollback Plan:**
   ```bash
   # Set previous version if needed
   STOCK_PIPELINE_VERSION=X.Y.Z-1
   ```

## 🔒 Security Best Practices

1. **Pin Exact Versions in Production:**
   ```bash
   STOCK_PIPELINE_VERSION=1.2.3  # Not just "1.2" or "latest"
   ```

2. **Use Least-Privilege IAM:**
   - Only grant required CodeArtifact permissions
   - Restrict to specific repositories/domains

3. **Monitor Package Usage:**
   ```python
   # Log package version in production jobs
   import stock_pipeline
   import logging
   logging.info(f"Using stock-pipeline version: {stock_pipeline.__version__}")
   ```

4. **Regular Security Audits:**
   - Review SBOM files attached to GitHub releases
   - Monitor security advisories for dependencies