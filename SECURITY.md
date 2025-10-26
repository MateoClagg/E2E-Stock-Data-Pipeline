# Security Policy

## 🔒 Reporting Security Vulnerabilities

We take security seriously. If you discover a security vulnerability in this project, please report it responsibly.

### How to Report

**Please do NOT create a public GitHub issue for security vulnerabilities.**

Instead, report security issues by:

1. **GitHub Security Advisories** (preferred):
   - Go to the Security tab of this repository
   - Click "Report a vulnerability"
   - Fill out the form with details

2. **Email** (alternative):
   - Send details to: mateo.clagg@gmail.com
   - Use subject line: "[SECURITY] stock-pipeline vulnerability report"
   - Include as much detail as possible

### What to Include

Please provide:

- **Description** of the vulnerability
- **Steps to reproduce** the issue
- **Potential impact** and affected components
- **Suggested fix** (if you have one)
- **Your contact information** for follow-up

## 🛡️ Security Best Practices

### For Contributors

- **Never commit secrets** (API keys, passwords, certificates)
- **Use environment variables** for configuration
- **Validate all inputs** from external sources
- **Keep dependencies updated** and monitor for vulnerabilities
- **Follow principle of least privilege** in IAM policies

### For Users

- **Pin exact package versions** in production
- **Review SBOM files** attached to releases
- **Use secure credential management** (IAM roles, not access keys)
- **Monitor security advisories** for dependencies
- **Regularly update** to latest secure versions

## 🔍 Security Measures in Place

### Supply Chain Security

- **SBOM Generation**: Every release includes Software Bill of Materials
- **Dependency Scanning**: `pip-audit` runs on all builds
- **Signed Releases**: GitHub releases are cryptographically signed
- **Reproducible Builds**: Builds are deterministic and verifiable

### CI/CD Security

- **OIDC Authentication**: No long-term AWS credentials in CI
- **Minimal Permissions**: Workflows use least-privilege principle
- **Branch Protection**: Required reviews and status checks
- **Signed Commits**: Recommended for all contributions

### Infrastructure Security

- **CodeArtifact**: Private package repository with access control
- **IAM Policies**: Fine-grained permissions for AWS resources
- **Encryption**: All data encrypted in transit and at rest
- **Audit Logging**: All access logged via CloudTrail

## 🎯 Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | ✅ Active support |
| 0.x.x   | ❌ No longer supported |

## 📅 Security Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days  
- **Fix Development**: Depends on severity
  - Critical: 1-7 days
  - High: 7-14 days
  - Medium: 14-30 days
  - Low: Next planned release
- **Public Disclosure**: After fix is available

## 🚨 Vulnerability Categories

### Critical (Immediate action required)
- Remote code execution
- Authentication bypass
- Data exfiltration
- Credential exposure

### High (Fix within 7 days)
- Privilege escalation
- Unauthorized data access
- Service disruption
- Significant information disclosure

### Medium (Fix within 30 days)
- Denial of service
- Limited information disclosure
- Cross-site scripting (if applicable)

### Low (Next planned release)
- Information leakage
- Minor security misconfigurations

## 📚 Security Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Guide](https://python-security.readthedocs.io/)
- [AWS Security Best Practices](https://aws.amazon.com/architecture/security-identity-compliance/)
- [Databricks Security Guide](https://docs.databricks.com/security/index.html)

## 🏆 Security Hall of Fame

We recognize responsible security researchers who help improve our security:

<!-- Contributors who report security issues will be listed here with their permission -->

## 🔄 Security Updates

Subscribe to security updates:
- Watch this repository for security advisories
- Follow releases for security patches
- Monitor dependency security advisories

---

**Last Updated**: January 2025  
**Next Review**: July 2025