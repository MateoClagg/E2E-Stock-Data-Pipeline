# Release Process

This document outlines the complete process for releasing new versions of the stock-pipeline package to AWS CodeArtifact.

## Prerequisites

### AWS Infrastructure Setup

1. **AWS CodeArtifact Domain and Repository**
   ```bash
   # Create CodeArtifact domain
   aws codeartifact create-domain --domain <domain-name> --region <region>
   
   # Create repository
   aws codeartifact create-repository \
     --domain <domain-name> \
     --repository <repository-name> \
     --description "Stock pipeline Python packages" \
     --region <region>
   ```

2. **S3 Bucket for Wheel Storage (Optional)**
   ```bash
   aws s3 mb s3://<bucket-name> --region <region>
   ```

### IAM Role for GitHub Actions OIDC

1. **Create IAM Role with Trust Policy**:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": {
           "Federated": "arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com"
         },
         "Action": "sts:AssumeRoleWithWebIdentity",
         "Condition": {
           "StringEquals": {
             "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
             "token.actions.githubusercontent.com:sub": "repo:<owner>/<repo>:ref:refs/tags/v*"
           }
         }
       }
     ]
   }
   ```

2. **Attach Permissions Policy**:
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
           "arn:aws:codeartifact:<region>:<account-id>:domain/<domain>",
           "arn:aws:codeartifact:<region>:<account-id>:repository/<domain>/<repository>",
           "arn:aws:codeartifact:<region>:<account-id>:package/<domain>/<repository>/pypi/stock-pipeline"
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
       },
       {
         "Effect": "Allow",
         "Action": [
           "s3:PutObject",
           "s3:PutObjectAcl"
         ],
         "Resource": "arn:aws:s3:::<bucket-name>/wheels/*"
       }
     ]
   }
   ```

### GitHub Repository Configuration

1. **Repository Secrets** (Settings → Secrets and variables → Actions):
   ```
   AWS_ROLE_ARN: arn:aws:iam::<account-id>:role/<role-name>
   AWS_REGION: <region>
   CODEARTIFACT_DOMAIN: <domain-name>
   CODEARTIFACT_ACCOUNT_ID: <account-id>
   CODEARTIFACT_REPOSITORY: <repository-name>
   ```

2. **Repository Variables** (optional):
   ```
   S3_WHEELS_BUCKET: <bucket-name>  # Only if using S3 wheel storage
   ```

3. **Environment Protection** (Settings → Environments):
   - Create `production` environment
   - Add required reviewers (recommended)
   - Set deployment branch rule to tags only

## Release Steps

### 1. Prepare Release

1. **Ensure main branch is ready**:
   ```bash
   git checkout main
   git pull origin main
   ```

2. **Verify CI is passing**:
   - Check GitHub Actions build status
   - Ensure all tests pass

3. **Review changes since last release**:
   ```bash
   git log $(git describe --tags --abbrev=0)..HEAD --oneline
   ```

### 2. Create Release Tag

1. **Tag the release** (following semantic versioning):
   ```bash
   # For example: v1.2.3
   git tag v<major>.<minor>.<patch>
   git push origin v<major>.<minor>.<patch>
   ```

2. **Verify tag was created**:
   ```bash
   git tag -l | tail -5
   ```

### 3. Monitor Release Process

1. **Watch GitHub Actions**:
   - Go to Actions tab in GitHub repository
   - Monitor the "Release to CodeArtifact" workflow
   - Verify all steps complete successfully

2. **Check release artifacts**:
   - Verify package appears in CodeArtifact repository
   - Check GitHub Releases page for created release
   - Review installation instructions in workflow output

### 4. Verify Release

1. **Test installation from CodeArtifact**:
   ```bash
   # Configure AWS credentials locally
   aws codeartifact login --tool pip \
     --domain <domain> \
     --domain-owner <account-id> \
     --repository <repository> \
     --region <region>
   
   # Install and test
   pip install stock-pipeline==<version>
   python -c "import bronze, silver, ingestion; print('✓ Import successful')"
   ```

2. **Test in Databricks** (if applicable):
   ```python
   %pip install stock-pipeline==<version> --index-url https://<domain>-<account-id>.d.codeartifact.<region>.amazonaws.com/pypi/<repository>/simple/
   ```

## Troubleshooting

### Common Issues

1. **OIDC Authentication Failures**:
   - Verify IAM role trust policy allows the specific repository
   - Check that the role ARN is correct in GitHub secrets
   - Ensure the tag matches the condition in the trust policy

2. **CodeArtifact Permission Denied**:
   - Verify the IAM role has the required CodeArtifact permissions
   - Check that the domain, repository, and account ID are correct
   - Ensure the package name matches the IAM policy

3. **Build Failures**:
   - Check that all dependencies are properly specified in pyproject.toml
   - Verify Python version compatibility
   - Review setuptools_scm configuration for version generation

4. **S3 Upload Failures**:
   - Verify S3 bucket exists and is accessible
   - Check IAM permissions for S3 operations
   - Ensure the bucket variable is set if S3 uploads are enabled

### Version Rollback

If a release needs to be rolled back:

1. **Delete the problematic release from CodeArtifact**:
   ```bash
   aws codeartifact delete-package-versions \
     --domain <domain> \
     --repository <repository> \
     --format pypi \
     --package stock-pipeline \
     --versions <version>
   ```

2. **Delete the Git tag** (if necessary):
   ```bash
   git tag -d v<version>
   git push origin --delete v<version>
   ```

## Version Numbering Guidelines

- **Major version** (X.0.0): Breaking API changes
- **Minor version** (X.Y.0): New features, backward compatible
- **Patch version** (X.Y.Z): Bug fixes, backward compatible

### Development Versions

setuptools_scm automatically generates development versions:
- `1.2.3.dev4+g1234567` for commits after tag v1.2.2
- Ensures unique package versions for every commit
- Prevents pip caching issues during development

## Security Considerations

1. **Never commit credentials** to the repository
2. **Use OIDC instead of long-term AWS keys** when possible
3. **Limit IAM permissions** to minimum required scope
4. **Use GitHub environment protection** for production releases
5. **Regularly rotate any static credentials** if used
6. **Monitor CloudTrail logs** for unusual CodeArtifact activity

## Maintenance

### Regular Tasks

1. **Review and update dependencies** quarterly
2. **Monitor CodeArtifact storage costs** and cleanup old versions if needed
3. **Update GitHub Actions versions** in workflows
4. **Review IAM permissions** and apply principle of least privilege

### Annual Tasks

1. **Review and update Python version support**
2. **Audit security configurations**
3. **Review backup and disaster recovery procedures**