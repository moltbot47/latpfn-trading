FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY funding/ funding/
COPY scripts/funding_dashboard.py scripts/
COPY monitoring/logger.py monitoring/
COPY templates/ templates/

# Create data directory for SQLite databases
RUN mkdir -p /app/data

# Expose funding dashboard port
EXPOSE 5055

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5055/health')" || exit 1

# Run funding dashboard
CMD ["python", "scripts/funding_dashboard.py", "--host", "0.0.0.0", "--port", "5055"]
