# 🚀 Operator Runbook: Stock Pipeline Package

This runbook provides operational procedures for managing the `stock-pipeline` package in production environments.

## 📋 Quick Reference

| Task | Command/Location |
|------|------------------|
| **Check package version** | `python -c "import stock_pipeline; print(stock_pipeline.__version__)"` |
| **View latest release** | https://github.com/MateoClagg/E2E-Stock-Data-Pipeline/releases |
| **Monitor CI/CD** | https://github.com/MateoClagg/E2E-Stock-Data-Pipeline/actions |
| **CodeArtifact Console** | https://console.aws.amazon.com/codeartifact/ |
| **SBOM/Security** | Check release attachments for `sbom.json` and `audit-report.json` |
| **Emergency rollback** | Set `STOCK_PIPELINE_VERSION=1.2.2` → restart clusters |

## 🏷️ **CRITICAL: Package Name Mapping**

**Distribution Name vs Module Name:**
- **PyPI/CodeArtifact package name**: `stock-pipeline` (with hyphen)
- **Python import name**: `stock_pipeline` (with underscore)
- **Main modules**: `bronze`, `silver`, `ingestion`, `validation`

```bash
# Install the distribution package
pip install stock-pipeline==1.2.3

# Import the Python modules  
python -c "import stock_pipeline, bronze, silver"
```

**⚠️ Security Note**: This naming difference is intentional and helps prevent dependency confusion attacks.

---

## 🔄 Release Management

### Creating a New Release

1. **Pre-release Checklist:**
   ```bash
   # Ensure main branch is ready
   git checkout main
   git pull origin main
   
   # Verify CI is passing
   # Check GitHub Actions status
   
   # Review changes since last release
   git log $(git describe --tags --abbrev=0)..HEAD --oneline
   ```

2. **Create Release Tag:**
   ```bash
   # Create and push signed tag
   git tag -a v1.2.3 -m "Release v1.2.3: Add new data validation features"
   git push origin v1.2.3
   ```

3. **Monitor Release Process:**
   - Watch GitHub Actions "Release to CodeArtifact" workflow
   - Verify successful CodeArtifact publication
   - Check GitHub Release creation
   - Review SBOM and security audit results

### Version Strategy

| Version Type | Example | When to Use |
|--------------|---------|-------------|
| **Patch** | 1.2.1 → 1.2.2 | Bug fixes, security patches |
| **Minor** | 1.2.0 → 1.3.0 | New features, backward compatible |
| **Major** | 1.x.x → 2.0.0 | Breaking changes, major rewrites |

---

## 🏭 Production Deployment

### Standard Production Upgrade

1. **Pre-deployment Testing:**
   ```python
   # Test in development cluster first
   %pip install stock-pipeline==X.Y.Z --index-url <codeartifact-url>
   
   # Run smoke tests
   import stock_pipeline
   print(f"Version: {stock_pipeline.__version__}")
   
   # Test core functionality
   from bronze.ingestion import fmp_bronze
   from silver.transformations import clean_data
   ```

2. **Production Deployment (Rolling):**
   ```bash
   # Update cluster environment variable
   STOCK_PIPELINE_VERSION=X.Y.Z
   
   # Restart clusters one by one:
   # 1. Non-critical/dev clusters first
   # 2. Staging clusters  
   # 3. Production clusters (during maintenance window)
   ```

3. **Post-deployment Verification:**
   ```python
   # In each restarted cluster
   import stock_pipeline
   print(f"✅ Version: {stock_pipeline.__version__}")
   
   # Run basic functionality test
   from pyspark.sql import SparkSession
   spark = SparkSession.builder.getOrCreate()
   test_df = spark.createDataFrame([("AAPL", 100.0)], ["symbol", "price"])
   print(f"✅ Spark integration: {test_df.count()} rows")
   ```

### 🚨 Emergency Rollback Procedure

**When to Execute Emergency Rollback:**
- Production pipeline failures after new release
- Data corruption or processing errors  
- Security vulnerability discovered in current version
- Performance degradation affecting SLAs

#### **Phase 1: Immediate Response (< 5 minutes)**

1. **Identify Last Known Good Version:**
   ```bash
   # Check recent releases
   git tag -l | grep "^v" | sort -V | tail -5
   
   # Or check GitHub releases
   curl -s https://api.github.com/repos/MateoClagg/E2E-Stock-Data-Pipeline/releases | jq -r '.[0:3][].tag_name'
   ```

2. **Execute Emergency Rollback:**
   ```bash
   # Set rollback version in ALL affected cluster environment variables
   STOCK_PIPELINE_VERSION=1.2.2  # Replace with last known good version
   
   # Priority order for cluster restarts:
   # 1. Critical production clusters (immediate)
   # 2. Secondary production clusters (within 30 mins)  
   # 3. Staging/dev clusters (within 2 hours)
   ```

#### **Phase 2: Verification (< 15 minutes)**

3. **Verify Rollback Success:**
   ```python
   # Run this in EVERY rolled-back cluster
   import stock_pipeline
   
   # Critical version check
   current_version = stock_pipeline.__version__
   expected_version = "1.2.2"  # Your rollback target
   
   assert current_version == expected_version, f"Rollback failed: {current_version} != {expected_version}"
   print(f"✅ Rollback successful: {current_version}")
   
   # Basic functionality test
   import bronze, silver, ingestion
   print("✅ All modules imported successfully")
   
   # Quick Spark test
   from pyspark.sql import SparkSession
   spark = SparkSession.builder.getOrCreate()
   test_df = spark.createDataFrame([("ROLLBACK_TEST", 100.0)], ["symbol", "price"])
   assert test_df.count() == 1, "Spark integration failed"
   print("✅ PySpark integration verified")
   ```

4. **Validate Data Pipeline:**
   ```python
   # Run minimal data pipeline test
   # Replace with your actual pipeline validation
   try:
       from silver.transformations.clean_data import remove_duplicates
       print("✅ Core transformation functions accessible")
   except ImportError as e:
       print(f"❌ CRITICAL: Function import failed: {e}")
   ```

#### **Phase 3: Communication & Documentation (< 30 minutes)**

5. **Notify Stakeholders:**
   ```bash
   # Send Slack/Teams notification
   echo "🚨 PRODUCTION ROLLBACK EXECUTED
   
   Package: stock-pipeline
   Rolled back from: v$OLD_VERSION 
   Rolled back to: v$ROLLBACK_VERSION
   Reason: $ROLLBACK_REASON
   
   Status: ✅ Rollback complete, production stable
   Next steps: Root cause analysis and fix planning
   
   Affected clusters: [list cluster IDs]
   ETA for fix: TBD after RCA
   
   Incident lead: @$INCIDENT_LEAD"
   ```

6. **Document the Incident:**
   ```markdown
   # Production Rollback Incident - $(date)
   
   ## Timeline
   - **Issue detected**: $(date) 
   - **Rollback decision**: $(date)
   - **Rollback completed**: $(date)
   - **Production restored**: $(date)
   
   ## Root Cause
   - [To be completed after investigation]
   
   ## Affected Systems
   - Clusters: [list]
   - Data pipelines: [list]
   - Impact duration: X minutes
   
   ## Resolution
   - Rolled back from v$OLD_VERSION to v$ROLLBACK_VERSION
   - All production systems verified stable
   
   ## Action Items
   - [ ] Root cause analysis
   - [ ] Fix development
   - [ ] Enhanced testing procedures  
   - [ ] Rollback process improvements
   ```

#### **Phase 4: Recovery Planning**

7. **Block Problematic Version:**
   ```bash
   # Prevent accidental reinstall of bad version
   # Update cluster configs to pin good version
   STOCK_PIPELINE_VERSION=1.2.2  # Keep pinned until fix ready
   ```

8. **Plan Forward Fix:**
   - Investigate root cause in development environment
   - Implement fix and comprehensive testing
   - Plan careful re-deployment strategy
   - Consider gradual rollout (canary deployment)

#### **Rollback Verification Checklist**

- [ ] ✅ All critical clusters restarted with correct version
- [ ] ✅ Package version verified on each cluster
- [ ] ✅ Basic functionality tests pass
- [ ] ✅ PySpark integration confirmed
- [ ] ✅ Data pipeline core functions accessible
- [ ] ✅ No error logs from package imports
- [ ] ✅ Stakeholders notified
- [ ] ✅ Incident documented  
- [ ] ✅ Problematic version blocked from future installs
- [ ] ✅ Recovery plan created

#### **Common Rollback Scenarios**

**Scenario: Import Errors**
```python
# Before rollback - failing
>>> import bronze
ModuleNotFoundError: No module named 'bronze.new_module'

# After rollback - working
>>> import bronze
>>> print("✅ Module imports restored")
```

**Scenario: Data Processing Errors**
```python
# Before rollback - failing
>>> from silver.transformations import clean_data
>>> clean_data.remove_duplicates(df)
AttributeError: 'DataFrame' object has no attribute 'new_method'

# After rollback - working  
>>> cleaned = clean_data.remove_duplicates(df)
>>> print(f"✅ Processing restored: {cleaned.count()} rows")
```

**Scenario: Performance Regression**
```python
# Monitor key metrics after rollback
import time
start = time.time()
# Run typical workload
processing_time = time.time() - start
print(f"Processing time: {processing_time:.2f}s")
# Should return to baseline performance
```

---

## 🚨 Troubleshooting Guide

### Issue: Package Installation Fails

**Symptoms:**
```
ERROR: Could not find a version that satisfies the requirement stock-pipeline
```

**Diagnosis Steps:**
1. **Check CodeArtifact Authentication:**
   ```bash
   # Verify AWS credentials
   aws sts get-caller-identity
   
   # Test CodeArtifact access
   aws codeartifact list-packages --domain <domain> --repository <repo>
   ```

2. **Verify Package Exists:**
   ```bash
   # List available versions
   aws codeartifact list-package-versions \
     --domain <domain> \
     --repository <repo> \
     --format pypi \
     --package stock-pipeline
   ```

**Solutions:**
- **Token Expired**: Restart Databricks cluster (init script fetches fresh token)
- **Wrong Repository**: Verify domain/repository names in cluster config
- **Permissions**: Check cluster's IAM role has CodeArtifact access
- **Network**: Verify cluster can reach CodeArtifact endpoints

### Issue: Import Errors After Installation

**Symptoms:**
```python
>>> import bronze
ModuleNotFoundError: No module named 'bronze'
```

**Solutions:**
```python
# Restart Python kernel
dbutils.library.restartPython()

# Clear import cache
import sys
if 'bronze' in sys.modules:
    del sys.modules['bronze']
    
# Force pip cache clear and reinstall
%pip cache purge
%pip install --no-cache-dir stock-pipeline==X.Y.Z --index-url <url>
```

### Issue: Version Mismatch

**Symptoms:**
```python
# Expected v1.3.0 but got v1.2.0
```

**Diagnosis:**
```python
# Check pip list
%pip list | grep stock-pipeline

# Check installation path
import stock_pipeline
print(stock_pipeline.__file__)

# Check for multiple installations
import sys
print([p for p in sys.path if 'stock' in p.lower()])
```

**Solutions:**
```bash
# Pin exact version in cluster environment
STOCK_PIPELINE_VERSION=1.3.0

# Restart cluster to trigger init script
```

### Issue: CodeArtifact Token Expiration

**Symptoms:**
- Package installs fail after ~12 hours
- 403 Forbidden errors from CodeArtifact

**Solutions:**
1. **Automatic (Recommended)**: Cluster restart triggers init script
2. **Manual**: Re-run authentication commands:
   ```bash
   aws codeartifact login --tool pip \
     --domain <domain> \
     --repository <repo>
   ```

### Issue: PySpark Compatibility Problems

**Symptoms:**
```
pyspark.sql.utils.AnalysisException: [UNRESOLVED_COLUMN]
```

**Diagnosis:**
```python
# Check PySpark version compatibility
from pyspark import __version__ as spark_version
print(f"PySpark version: {spark_version}")

# Expected: 3.5.x (Databricks Runtime 14.3 LTS)
```

**Solutions:**
- Verify package was built against compatible PySpark version
- Check function signatures in transformation modules
- Review release notes for breaking changes

### 🛡️ Issue: Dependency Confusion Attacks

**What is Dependency Confusion:**
An attack where malicious packages with similar names are uploaded to public repositories (PyPI) to trick systems into installing them instead of your private packages.

**Our Protection Mechanisms:**

1. **Package Name Strategy:**
   - Distribution name: `stock-pipeline` (hyphen)
   - Import name: `stock_pipeline` (underscore)  
   - This naming difference makes attacks harder

2. **Private-Only Installation:**
   ```bash
   # ✅ SECURE - Our init script uses --index-url ONLY
   pip install stock-pipeline --index-url https://codeartifact.../simple/
   
   # ❌ VULNERABLE - Never use --extra-index-url with public PyPI
   pip install stock-pipeline --extra-index-url https://pypi.org/simple/
   ```

3. **Module Validation:**
   ```python
   # Our init script validates expected module structure
   import stock_pipeline
   import bronze, silver, ingestion  # Must all import successfully
   ```

**Detection Signs:**
```python
# Check if package came from unexpected source
import pip
installed_packages = [d for d in pip.get_installed_distributions() if d.project_name == 'stock-pipeline']
for pkg in installed_packages:
    print(f"Package location: {pkg.location}")
    # Should be in databricks/python/lib, not site-packages from PyPI
```

**Response Protocol:**
1. **Immediate isolation:** Stop all cluster operations
2. **Forensic analysis:** Check pip logs and package locations
3. **Clean reinstall:** Wipe Python environment, reinstall from known-good source
4. **Incident reporting:** Document for security team review

**Prevention Checklist:**
- ✅ Always use `--index-url` (not `--extra-index-url`) 
- ✅ Pin exact versions in production
- ✅ Validate module imports after installation
- ✅ Monitor unusual package behavior or performance
- ✅ Use different distribution vs import names
- ✅ Regular security audits of installed packages

---

## 📊 Monitoring and Alerts

### Key Metrics to Monitor

1. **Package Installation Success Rate:**
   - Monitor cluster startup times
   - Track init script failures
   - Alert on repeated installation failures

2. **CodeArtifact Usage:**
   ```bash
   # Monitor package downloads
   aws codeartifact get-package-version-asset \
     --domain <domain> \
     --repository <repo> \
     --format pypi \
     --package stock-pipeline \
     --package-version X.Y.Z
   ```

3. **Security Vulnerabilities:**
   - Review SBOM files with each release
   - Monitor pip-audit reports
   - Subscribe to security advisories

### Recommended Alerts

1. **Release Pipeline Failures:**
   - GitHub Actions workflow failures
   - CodeArtifact publication errors

2. **Package Installation Issues:**
   - Multiple clusters failing to install package
   - Increased cluster startup times

3. **Security Alerts:**
   - New vulnerabilities in dependencies
   - Failed security audits

---

## 🔒 Security Operations

### Regular Security Tasks

**Weekly:**
- Review new dependency updates via Dependabot
- Check for new security advisories

**Monthly:**
- Audit CodeArtifact access logs
- Review IAM permissions for principle of least privilege
- Update cluster configurations if needed

**Quarterly:**
- Full security audit of CI/CD pipeline
- Review and rotate any static credentials
- Update security documentation

### Incident Response

**Security Vulnerability Discovered:**

1. **Immediate Assessment:**
   ```bash
   # Check if vulnerability affects production
   pip-audit --desc --format json
   ```

2. **Containment:**
   - Temporarily pin to last known good version
   - Block vulnerable version in CodeArtifact if possible

3. **Remediation:**
   - Update dependencies and release patch
   - Follow standard release process with expedited testing

4. **Communication:**
   - Notify stakeholders of security patch
   - Update security advisories

---

## 📞 Emergency Contacts

### Escalation Path

1. **Package Issues**: @MateoClagg (GitHub)
2. **AWS/Infrastructure**: Cloud team
3. **Databricks Issues**: Platform team
4. **Security Incidents**: Security team

### Key Information for Support

When reporting issues, include:
- Package version attempting to install
- Databricks runtime version
- Complete error messages
- Cluster configuration (environment variables)
- Timeline of issue (when it started)

---

## 🧪 Testing Procedures

### Pre-production Testing Checklist

```python
# 1. Version verification
import stock_pipeline
print(f"Version: {stock_pipeline.__version__}")

# 2. Module imports
import bronze, silver, ingestion, validation
print("✅ All modules imported")

# 3. Core functionality
from bronze.ingestion.fmp_bronze import fetch_stock_data
from silver.transformations.clean_data import remove_duplicates
print("✅ Key functions accessible")

# 4. PySpark integration
from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()
test_df = spark.createDataFrame([("TEST", 100.0)], ["symbol", "price"])
result = remove_duplicates(test_df) if hasattr(remove_duplicates, '__call__') else test_df
print(f"✅ PySpark test: {result.count()} rows")

# 5. Data validation
if 'validation' in sys.modules:
    print("✅ Validation module available")
```

### Performance Baseline Testing

```python
import time
import stock_pipeline

# Measure import time
start = time.time()
import bronze, silver, ingestion
import_time = time.time() - start
print(f"Import time: {import_time:.2f}s")

# Expected: < 2 seconds for cold import
assert import_time < 2.0, f"Import too slow: {import_time:.2f}s"
```

---

## 📈 Capacity Planning

### CodeArtifact Storage

- **Current usage**: ~50MB per version
- **Retention**: Keep last 10 versions of each major release
- **Cleanup**: Remove pre-release versions older than 90 days

### Databricks Cluster Impacts

- **Startup time increase**: +30-60 seconds with init script
- **Memory usage**: +100MB per cluster for package
- **Network**: Minimal bandwidth for package downloads

---

**Last Updated**: January 2025  
**Next Review**: April 2025  
**Document Owner**: @MateoClagg