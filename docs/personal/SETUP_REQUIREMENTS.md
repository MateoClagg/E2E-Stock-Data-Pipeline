# 🔧 Complete Setup Requirements

## 🚨 **What Works Right Now (No Setup)**
- ✅ **PR builds** on feature branches (5-minute builds)
- ✅ **Main builds** with comprehensive testing
- ✅ **Package building** and artifact downloads
- ✅ **Local development** (`pip install -e .`)

## 🚨 **What Needs Setup for Full Production**

### 1. **AWS Account & Services**

#### **AWS CodeArtifact** (Private Package Repository)
```bash
# Required AWS CLI commands to run:
aws codeartifact create-domain --domain stock-pipeline-domain --region us-east-2

aws codeartifact create-repository \
  --domain stock-pipeline-domain \
  --repository stock-pipeline-repo \
  --description "Stock pipeline Python packages" \
  --region us-east-2
```

#### **IAM Role for GitHub Actions** (OIDC - Recommended)
Create role: `github-actions-stock-pipeline-role`

**Trust Policy:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::YOUR_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:MateoClagg/E2E-Stock-Data-Pipeline:ref:refs/tags/v*"
        }
      }
    }
  ]
}
```

**Permissions Policy:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "codeartifact:GetAuthorizationToken",
        "codeartifact:GetRepositoryEndpoint",
        "codeartifact:ReadFromRepository",
        "codeartifact:PublishPackageVersion"
      ],
      "Resource": [
        "arn:aws:codeartifact:us-east-2:YOUR_ACCOUNT_ID:domain/stock-pipeline-domain",
        "arn:aws:codeartifact:us-east-2:YOUR_ACCOUNT_ID:repository/stock-pipeline-domain/stock-pipeline-repo"
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

#### **S3 Bucket** (Optional - for Unity Catalog)
```bash
aws s3 mb s3://stock-pipeline-wheels --region us-east-2
```

---

### 2. **GitHub Repository Settings**

#### **GitHub Secrets** (Settings → Secrets and variables → Actions)

**Required for Releases:**
```
AWS_ROLE_ARN: arn:aws:iam::YOUR_ACCOUNT_ID:role/github-actions-stock-pipeline-role
AWS_REGION: us-east-2
CODEARTIFACT_DOMAIN: stock-pipeline-domain
CODEARTIFACT_ACCOUNT_ID: YOUR_ACCOUNT_ID
CODEARTIFACT_REPOSITORY: stock-pipeline-repo
```

**Optional:**
```
SLACK_WEBHOOK_URL: https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
```

#### **GitHub Variables** (Optional)
```
S3_WHEELS_BUCKET: your-stock-pipeline-wheels
```

#### **GitHub Environment** (Settings → Environments)
- Create environment: `production`
- Add protection rules (require reviews for releases)
- Restrict to tags only: `v*`

#### **Branch Protection** (Settings → Branches)
- Protect `main` branch
- Require status checks: ✅ `Fast Build & Test`, ✅ `Comprehensive Build & Test`
- Require pull request reviews
- Require up-to-date branches

---

### 3. **Databricks Integration**

#### **Cluster Configuration**
Add these **Environment Variables** to your cluster config:
```bash
CODEARTIFACT_DOMAIN=stock-pipeline-domain
CODEARTIFACT_ACCOUNT_ID=YOUR_ACCOUNT_ID
CODEARTIFACT_REPOSITORY=stock-pipeline-repo
AWS_REGION=us-east-1
STOCK_PIPELINE_VERSION=1.0.0  # Pin specific version in production
```

#### **Init Script Setup**
1. Upload `databricks/init-script.sh` to DBFS:
```bash
databricks fs cp databricks/init-script.sh dbfs:/init-scripts/stock-pipeline-install.sh
```

2. Add to cluster config (Advanced Options → Init Scripts):
```
DBFS Path: dbfs:/init-scripts/stock-pipeline-install.sh
```

#### **IAM Instance Profile** (for Databricks clusters)
Your cluster needs IAM permissions to access CodeArtifact:
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
      "Resource": "*"
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

### 4. **Local Development (.env file)**

**Create `.env` file** (already in `.gitignore`):
```bash
# API Keys
FMP_API_KEY=your_fmp_api_key_here

# AWS (if testing locally)
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION=us-east-1

# CodeArtifact (if testing releases locally)
CODEARTIFACT_DOMAIN=stock-pipeline-domain
CODEARTIFACT_ACCOUNT_ID=YOUR_ACCOUNT_ID
CODEARTIFACT_REPOSITORY=stock-pipeline-repo
```

---

## 📋 **Setup Checklist**

### **Phase 1: Basic CI (Works Immediately)**
- [ ] ✅ Push to feature branch → Fast PR builds work
- [ ] ✅ Merge to main → Comprehensive builds work
- [ ] ✅ Download artifacts from GitHub Actions
- [ ] ✅ Test local development: `pip install -e .`

### **Phase 2: AWS Setup (For Releases)**
- [ ] Create AWS CodeArtifact domain and repository
- [ ] Create IAM role with OIDC trust policy
- [ ] Add required permissions to the role
- [ ] Test AWS CLI access to CodeArtifact

### **Phase 3: GitHub Configuration (For Releases)**
- [ ] Add GitHub Secrets (AWS_ROLE_ARN, etc.)
- [ ] Create `production` environment
- [ ] Set up branch protection rules
- [ ] Test release: `git tag v0.1.0 && git push origin v0.1.0`

### **Phase 4: Databricks Integration (When Ready)**
- [ ] Configure cluster environment variables
- [ ] Upload and configure init script
- [ ] Set up cluster IAM instance profile
- [ ] Test package installation in Databricks

### **Phase 5: Optional Enhancements**
- [ ] Set up Slack notifications
- [ ] Configure S3 bucket for Unity Catalog
- [ ] Set up Unity Catalog External Location/Volume
- [ ] Configure lifecycle policies for old versions

---

## 🎯 **Quick Test Commands**

### **Test Basic Setup (No AWS needed)**
```bash
# 1. Local build
python -m build
pip install dist/*.whl
python -c "import bronze, silver; print('✅ Works locally')"

# 2. Push and check GitHub Actions
git push origin feature/test-ci
# Check Actions tab for green builds
```

### **Test Release Setup (After AWS configuration)**
```bash
# 1. Configure AWS CLI
aws configure

# 2. Test CodeArtifact access
aws codeartifact list-packages --domain stock-pipeline-domain --repository stock-pipeline-repo

# 3. Create test release
git tag v0.1.0-test
git push origin v0.1.0-test
# Check GitHub Actions for successful release
```

### **Test Databricks Setup**
```python
# In Databricks notebook after cluster restart
%pip list | grep stock-pipeline
import bronze, silver
print("✅ Databricks integration works")
```

---

## 💡 **Recommendations**

### **Start Simple**
1. **Week 1**: Use just the GitHub Actions builds (no AWS setup)
2. **Week 2**: Set up AWS CodeArtifact for releases when needed
3. **Week 3**: Configure Databricks when you need deployment

### **Production Ready**
- Always pin exact versions in production: `STOCK_PIPELINE_VERSION=1.2.3`
- Use separate AWS accounts for dev/staging/prod
- Monitor CodeArtifact usage and costs
- Set up lifecycle policies for old package versions

### **Security**
- Use OIDC instead of static AWS keys
- Regularly rotate any static credentials
- Monitor CloudTrail for unusual CodeArtifact activity
- Keep GitHub repository private until ready for open source

**Need help with any specific setup step? Let me know!**