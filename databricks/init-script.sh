#!/bin/bash
# Databricks Cluster Init Script for stock-pipeline package installation
# Place this script in DBFS and reference it in cluster configuration

set -euo pipefail

echo "🚀 Installing stock-pipeline package via CodeArtifact..."

# Configuration (set these as environment variables in cluster config)
CODEARTIFACT_DOMAIN="${CODEARTIFACT_DOMAIN:-}"
CODEARTIFACT_ACCOUNT_ID="${CODEARTIFACT_ACCOUNT_ID:-}"
CODEARTIFACT_REPOSITORY="${CODEARTIFACT_REPOSITORY:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"
PACKAGE_VERSION="${STOCK_PIPELINE_VERSION:-}"  # Optional: pin specific version

# Validation
if [[ -z "$CODEARTIFACT_DOMAIN" || -z "$CODEARTIFACT_ACCOUNT_ID" || -z "$CODEARTIFACT_REPOSITORY" ]]; then
    echo "❌ ERROR: Missing required environment variables:"
    echo "  CODEARTIFACT_DOMAIN, CODEARTIFACT_ACCOUNT_ID, CODEARTIFACT_REPOSITORY"
    echo "  Set these in your cluster's environment variables or Spark config."
    exit 1
fi

# Check if AWS CLI is available (should be in Databricks runtime)
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. This script requires Databricks Runtime with AWS CLI."
    exit 1
fi

# Function to get CodeArtifact token (expires in 12 hours)
get_codeartifact_token() {
    echo "🔑 Fetching fresh CodeArtifact authentication token..."
    
    # Get the repository endpoint and token
    REPO_ENDPOINT=$(aws codeartifact get-repository-endpoint \
        --domain "$CODEARTIFACT_DOMAIN" \
        --domain-owner "$CODEARTIFACT_ACCOUNT_ID" \
        --repository "$CODEARTIFACT_REPOSITORY" \
        --format pypi \
        --region "$AWS_REGION" \
        --query repositoryEndpoint \
        --output text)
    
    AUTH_TOKEN=$(aws codeartifact get-authorization-token \
        --domain "$CODEARTIFACT_DOMAIN" \
        --domain-owner "$CODEARTIFACT_ACCOUNT_ID" \
        --region "$AWS_REGION" \
        --query authorizationToken \
        --output text)
    
    if [[ -z "$REPO_ENDPOINT" || -z "$AUTH_TOKEN" ]]; then
        echo "❌ Failed to get CodeArtifact authentication. Check IAM permissions."
        exit 1
    fi
    
    # Construct the authenticated index URL
    INDEX_URL="https://aws:${AUTH_TOKEN}@${REPO_ENDPOINT#https://}simple/"
    echo "✓ CodeArtifact authentication successful"
}

# Function to install package with dependency confusion protection
install_package() {
    echo "📦 Installing stock-pipeline package with security protections..."
    
    # CRITICAL: Validate package name to prevent dependency confusion
    EXPECTED_PACKAGE="stock-pipeline"
    if [[ "$EXPECTED_PACKAGE" != "stock-pipeline" ]]; then
        echo "❌ SECURITY ERROR: Package name validation failed"
        exit 1
    fi
    
    # Determine version specification
    if [[ -n "$PACKAGE_VERSION" ]]; then
        VERSION_SPEC="stock-pipeline==$PACKAGE_VERSION"
        echo "📌 Installing pinned version: $PACKAGE_VERSION"
    else
        VERSION_SPEC="stock-pipeline"
        echo "📌 Installing latest version"
    fi
    
    # SECURITY: Install ONLY from CodeArtifact - NO PUBLIC FALLBACK
    # This prevents dependency confusion attacks from PyPI
    echo "🔒 Installing from private CodeArtifact only (no PyPI fallback)"
    /databricks/python/bin/pip install "$VERSION_SPEC" \
        --index-url "$INDEX_URL" \
        --trusted-host "${REPO_ENDPOINT#https://}" \
        --no-deps \
        --no-cache-dir \
        --upgrade \
        --only-binary=:all: \
        --disable-pip-version-check
    
    # Install dependencies separately from CodeArtifact if needed
    echo "📦 Installing dependencies from CodeArtifact..."
    /databricks/python/bin/pip install \
        requests==2.31.0 \
        python-dotenv==1.0.0 \
        aiohttp==3.8.6 \
        great-expectations==0.18.8 \
        pydantic==2.7.1 \
        --index-url "$INDEX_URL" \
        --trusted-host "${REPO_ENDPOINT#https://}" \
        --no-cache-dir \
        --disable-pip-version-check
    
    # CRITICAL: Verify we got the package from CodeArtifact, not elsewhere
    INSTALLED_VERSION=$(/databricks/python/bin/python -c "import stock_pipeline; print(stock_pipeline.__version__)" 2>/dev/null || echo "unknown")
    PACKAGE_LOCATION=$(/databricks/python/bin/pip show stock-pipeline | grep "Location:" | head -1)
    
    if [[ "$INSTALLED_VERSION" != "unknown" ]]; then
        echo "✅ Successfully installed stock-pipeline version: $INSTALLED_VERSION"
        echo "📍 Package location: $PACKAGE_LOCATION"
        
        # Security validation: ensure module name matches expected
        MODULE_CHECK=$(/databricks/python/bin/python -c "
import sys
try:
    import stock_pipeline
    # Verify this is our expected package structure  
    import bronze, silver, ingestion
    print('SECURITY_CHECK_PASSED')
except ImportError as e:
    print('SECURITY_CHECK_FAILED: ' + str(e))
    sys.exit(1)
" 2>/dev/null || echo "SECURITY_CHECK_FAILED")
        
        if [[ "$MODULE_CHECK" == "SECURITY_CHECK_PASSED" ]]; then
            echo "✅ Security validation: Package structure verified"
        else
            echo "❌ SECURITY ALERT: Package structure validation failed!"
            echo "    This could indicate a dependency confusion attack."
            echo "    Installed package does not match expected module structure."
            exit 1
        fi
    else
        echo "❌ Package installation failed or version could not be determined"
        exit 1
    fi
    
    # Token expiry warning
    echo ""
    echo "⏰ IMPORTANT: CodeArtifact tokens expire every 12 hours"
    echo "   If package installation fails later, restart this cluster"
    echo "   to refresh the authentication token automatically"
}

# Function to test package functionality
test_package() {
    echo "🧪 Testing package functionality..."
    
    /databricks/python/bin/python -c "
try:
    import bronze, silver, ingestion, validation
    import stock_pipeline
    print('✓ All modules imported successfully')
    print(f'✓ Package version: {stock_pipeline.__version__}')
    
    # Test basic Spark integration
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    test_df = spark.createDataFrame([('AAPL', 100.0)], ['symbol', 'price'])
    print(f'✓ Spark integration test passed: {test_df.count()} rows')
    
except Exception as e:
    print(f'❌ Package test failed: {e}')
    exit(1)
"
    
    echo "✅ Package testing completed successfully"
}

# Main execution
main() {
    echo "🔧 stock-pipeline init script starting..."
    echo "📍 Domain: $CODEARTIFACT_DOMAIN"
    echo "📍 Repository: $CODEARTIFACT_REPOSITORY"
    echo "📍 Region: $AWS_REGION"
    
    get_codeartifact_token
    install_package
    test_package
    
    echo "🎉 stock-pipeline init script completed successfully!"
    echo "💡 Package is ready to use in notebooks with: import bronze, silver, ingestion"
}

# Run main function
main "$@"