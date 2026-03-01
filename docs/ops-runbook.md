# Operations Runbook

## Scheduled Tasks (Cron)

```crontab
# ── Every 5 minutes ──────────────────────────────────────────────
# Health check: verify dashboards are responding
*/5 * * * * cd /path/to/latpfn-trading && venv/bin/python scripts/health_monitor.py --json >> logs/health.log 2>&1

# ── Daily at 2 AM ET ─────────────────────────────────────────────
# Database backup with integrity verification (keep 14 days)
0 2 * * * cd /path/to/latpfn-trading && venv/bin/python scripts/backup.py --verify --retain 14 >> logs/backup.log 2>&1

# ── Weekly on Sunday at 3 AM ET ──────────────────────────────────
# Database maintenance: VACUUM + ANALYZE for query optimization
0 3 * * 0 cd /path/to/latpfn-trading && venv/bin/python scripts/db_maintenance.py >> logs/maintenance.log 2>&1
```

## Health Endpoints

| Service | URL | Expected |
|---------|-----|----------|
| Funding Dashboard | http://localhost:5055/health | `{"status": "ok"}` |
| Funding Dashboard (detail) | http://localhost:5055/health/detail | DB probe + memory |
| Funding Dashboard (metrics) | http://localhost:5055/metrics | Request stats |
| Trading Dashboard | http://localhost:5050/api/status | Heartbeat |

## Common Operations

### Check service health
```bash
make health
# or
python scripts/health_monitor.py --verbose
```

### Backup databases
```bash
make backup              # Backup all DBs with integrity verification
python scripts/backup.py --list  # List existing backups
python scripts/backup.py --db funding.db  # Backup specific DB
```

### Database maintenance
```bash
make db-maintain         # VACUUM + ANALYZE all databases
python scripts/db_maintenance.py --check-only  # Integrity check only
python scripts/db_maintenance.py --db funding.db  # Specific database
```

### View metrics
```bash
curl -s http://localhost:5055/metrics | python -m json.tool
```

## Incident Response

### Dashboard not responding
1. Check health: `python scripts/health_monitor.py --verbose`
2. Check logs: `tail -100 logs/trading_$(date +%Y-%m-%d).log`
3. Check database integrity: `python scripts/db_maintenance.py --check-only`
4. Restart: `python scripts/funding_dashboard.py`

### Database corruption
1. Stop services
2. Run integrity check: `python scripts/db_maintenance.py --check-only`
3. If corrupted, restore from backup: `cp data/backups/funding_backup_LATEST.db data/funding.db`
4. Restart services

### High error rate
1. Check metrics: `curl -s http://localhost:5055/metrics`
2. Check recent logs for stack traces
3. Check database health: `python scripts/db_maintenance.py --check-only`
