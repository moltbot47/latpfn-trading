# Contributing

## Quick Start

```bash
# Clone and setup
git clone https://github.com/moltbot47/latpfn-trading.git
cd latpfn-trading
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
make install

# Copy env template and fill in your credentials
cp .env.template .env

# Run tests
make test

# Run linter
make lint
```

## Development Workflow

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make changes and add tests
3. Run `make lint` and `make test` before committing
4. Pre-commit hooks will auto-fix lint issues on commit
5. Push and open a PR — CI must pass (lint + test + docker build)

## Project Structure

```
├── funding/           # Business funding tracker (models, DB, strategy)
├── signals/           # Trading signal generation
├── risk/              # Risk management and compliance
├── execution/         # Order execution (TradersPost, Hyperliquid)
├── monitoring/        # Logging, health checks, TUI dashboard
├── scripts/           # CLI tools (dashboards, backup, health monitor)
├── tests/             # Test suite (228+ tests)
├── config/            # YAML configuration
└── data/              # SQLite databases (gitignored)
```

## Testing

```bash
make test              # Run all 228 tests
make coverage          # Run with coverage report (70% min threshold)
make lint              # Ruff linter
```

Tests are organized by domain:
- `test_core.py` — Trading system core (signals, risk, execution)
- `test_funding_*.py` — Funding tracker (models, DB, strategy, API)
- `test_funding_e2e.py` — End-to-end workflow tests
- `test_backup.py` — Backup utility
- `test_monitoring.py` — Logger, JSON formatter, error aggregator
- `test_health_monitor.py` — Health check script

## CI/CD

GitHub Actions runs 3 parallel jobs on every push/PR:
- **lint**: Ruff linter (fast fail)
- **test**: Full pytest suite + coverage
- **docker**: Docker image build verification

Branch protection requires all 3 to pass before merging to main.
