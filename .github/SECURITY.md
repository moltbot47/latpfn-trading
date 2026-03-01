# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public GitHub issue
2. Email the maintainer directly or use GitHub's private vulnerability reporting
3. Include steps to reproduce and potential impact

## Security Practices

- All secrets stored in `.env` (excluded from version control)
- SQLite databases use parameterized queries (no raw string interpolation)
- Flask endpoints validate and sanitize all input
- Column allowlists prevent SQL injection in dynamic queries
- CSRF protection on state-changing endpoints
- Upload size limits enforced (20 MB max)
- Health endpoints expose no sensitive data
