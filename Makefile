.PHONY: help install test lint coverage backup db-maintain docker clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies into venv
	pip install torch --index-url https://download.pytorch.org/whl/cpu
	pip install -r requirements.txt
	pip install ruff pre-commit
	pre-commit install

test: ## Run all tests
	python -m pytest tests/ -v --tb=short -x

lint: ## Run ruff linter on project files
	ruff check tests/ funding/ scripts/funding_dashboard.py scripts/backup.py scripts/health_monitor.py scripts/db_maintenance.py monitoring/logger.py

lint-fix: ## Auto-fix lint issues
	ruff check --fix tests/ funding/ scripts/funding_dashboard.py scripts/backup.py scripts/health_monitor.py scripts/db_maintenance.py monitoring/logger.py

coverage: ## Run tests with coverage report
	python -m pytest tests/test_funding_models.py tests/test_funding_database.py tests/test_funding_strategy.py tests/test_funding_api.py tests/test_monitoring.py \
		--cov=funding.database --cov=funding.models --cov=funding.product_catalog --cov=funding.strategy_engine \
		--cov-report=term-missing --cov-fail-under=70 --tb=short

backup: ## Backup all SQLite databases
	python scripts/backup.py --verify

backup-list: ## List existing backups
	python scripts/backup.py --list

db-maintain: ## Run database maintenance (VACUUM, ANALYZE, integrity check)
	python scripts/db_maintenance.py

health: ## Check service health
	python scripts/health_monitor.py --verbose

docker: ## Build and run funding dashboard in Docker
	docker compose up --build -d

docker-stop: ## Stop Docker containers
	docker compose down

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov
