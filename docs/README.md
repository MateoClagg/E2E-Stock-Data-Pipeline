# 📚 Documentation Index

## 🎯 **Start Here**
- **[🚀 QUICK_START.md](../QUICK_START.md)** - Get up and running in 5 minutes

## 📁 **Documentation by Topic**

### 🚀 **CI/CD & Workflows** (`ci-cd/`)
- **[WORKFLOW_OPTIMIZATION_SUMMARY.md](ci-cd/WORKFLOW_OPTIMIZATION_SUMMARY.md)** - How the 3-tier CI/CD works
- **[DEPLOYMENT_SUMMARY.md](ci-cd/DEPLOYMENT_SUMMARY.md)** - Complete deployment architecture

### ⚙️ **Production Operations** (`operations/`)
- **[RELEASING.md](operations/RELEASING.md)** - How to create releases and setup AWS
- **[OPERATOR_RUNBOOK.md](operations/OPERATOR_RUNBOOK.md)** - Day-to-day operations, troubleshooting, rollbacks

### 🔒 **Security & Compliance** (`security/`)
- **[SECURITY.md](security/SECURITY.md)** - Security policies and vulnerability reporting
- **[ENTERPRISE_SECURITY_SUMMARY.md](security/ENTERPRISE_SECURITY_SUMMARY.md)** - Complete security features overview

### 📊 **Databricks Integration** (`../databricks/`)
- **[DATABRICKS_SETUP.md](../databricks/DATABRICKS_SETUP.md)** - Complete Databricks setup guide
- **[init-script.sh](../databricks/init-script.sh)** - Cluster initialization script

## 🎭 **By Persona**

### **Developers** (Daily Use)
1. [QUICK_START.md](../QUICK_START.md) - Basic usage
2. [ci-cd/WORKFLOW_OPTIMIZATION_SUMMARY.md](ci-cd/WORKFLOW_OPTIMIZATION_SUMMARY.md) - How PR builds work

### **DevOps/Platform Engineers** (Setup & Maintenance) 
1. [operations/RELEASING.md](operations/RELEASING.md) - AWS setup
2. [operations/OPERATOR_RUNBOOK.md](operations/OPERATOR_RUNBOOK.md) - Production operations
3. [ci-cd/DEPLOYMENT_SUMMARY.md](ci-cd/DEPLOYMENT_SUMMARY.md) - Architecture overview

### **Security Teams** (Compliance & Auditing)
1. [security/SECURITY.md](security/SECURITY.md) - Security policies
2. [security/ENTERPRISE_SECURITY_SUMMARY.md](security/ENTERPRISE_SECURITY_SUMMARY.md) - Security controls

### **Data Engineers** (Databricks Users)
1. [../databricks/DATABRICKS_SETUP.md](../databricks/DATABRICKS_SETUP.md) - Installation methods
2. [operations/OPERATOR_RUNBOOK.md](operations/OPERATOR_RUNBOOK.md) - Troubleshooting

## 🆘 **Common Scenarios**

| I want to... | Read this |
|-------------|-----------|
| **Test the new system** | [QUICK_START.md](../QUICK_START.md) |
| **Understand what changed** | [ci-cd/WORKFLOW_OPTIMIZATION_SUMMARY.md](ci-cd/WORKFLOW_OPTIMIZATION_SUMMARY.md) |
| **Set up production releases** | [operations/RELEASING.md](operations/RELEASING.md) |
| **Deploy to Databricks** | [../databricks/DATABRICKS_SETUP.md](../databricks/DATABRICKS_SETUP.md) |
| **Fix a production issue** | [operations/OPERATOR_RUNBOOK.md](operations/OPERATOR_RUNBOOK.md) |
| **Understand security** | [security/ENTERPRISE_SECURITY_SUMMARY.md](security/ENTERPRISE_SECURITY_SUMMARY.md) |

## 📝 **Quick Reference**

### **Package Names** (Important!)
- **Install**: `pip install stock-pipeline` (hyphen)
- **Import**: `import stock_pipeline, bronze, silver` (underscore)

### **Common Commands**
```bash
# Local development
pip install -e .
python -m build

# Create release  
git tag v1.2.3
git push origin v1.2.3

# Databricks install
%pip install stock-pipeline==1.2.3 --index-url <codeartifact-url>
```

### **Key Files**
- `pyproject.toml` - Package configuration
- `.github/workflows/` - CI/CD automation  
- `databricks/init-script.sh` - Auto-installation for clusters
- `docs/operations/` - Production playbooks