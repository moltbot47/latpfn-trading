# Changelog

## [1.1.0] - 2026-03-01

### Added
- **CI/CD Pipeline**: GitHub Actions with 3 parallel jobs (lint, test, docker build)
- **236 automated tests**: unit, integration, E2E, backup, monitoring, load
- **Monitoring infrastructure**: /health, /health/detail, /metrics endpoints
- **Security hardening**: rate limiting (120 req/min), security headers, request IDs
- **Database backup utility**: SQLite online backup with integrity verification
- **Database maintenance utility**: VACUUM, ANALYZE, integrity checks
- **Health monitor script**: cron-ready service health checker
- **Error aggregator**: time-windowed error deduplication for alerting
- **Dockerfile + docker-compose.yml**: containerized funding dashboard
- **Operations runbook**: cron schedules, incident response procedures
- **Developer tooling**: Makefile, pre-commit hooks, pyproject.toml
- **Repository governance**: SECURITY.md, CODEOWNERS, CONTRIBUTING.md, PR template
- **Dependabot**: automated dependency updates for pip and GitHub Actions
- **Branch protection**: require lint + test + docker checks before merge
- **Log rotation**: RotatingFileHandler (10 MB max, 5 backups)
- **Structured JSON logging**: machine-parseable log output option

### Changed
- Request logging now includes request IDs for log correlation
- Coverage threshold enforced at 70% on core modules (currently 90%)
- Ruff linter integrated into CI and pre-commit hooks

## [1.0.0] - 2026-02-28

### Added
- **Business funding tracker**: credit profiles, applications, strategy engine
- **Referral system**: client management, commission tracking, product catalog
- **Partner onboarding tracker**: affiliate program status management
- **Funding dashboard**: Flask web UI on port 5055 with AG Grid
- **Credit report PDF parser**: automated extraction from Experian/TransUnion/Equifax
- **Strategy engine**: readiness scoring, recommendations, round planning
- **Product catalog**: 90+ lending products with eligibility criteria

## [0.9.0] - 2026-02-24

### Added
- EMA trend filter in gate mode (hard reject counter-trend signals)
- Trading pause capability
- Updated Apex accounts (fresh $50k evals)

### Fixed
- Counter-trend loss prevention (accounts 16+17 blown from soft mode)

## [0.8.0] - 2026-02-19

### Added
- Broker-confirmed live statistics tracking
- Estimated hold time in trade alerts
- TradersPost webhook integration updates
