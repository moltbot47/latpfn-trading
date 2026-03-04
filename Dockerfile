FROM python:3.11-slim

WORKDIR /app

# Only Flask needed — no PyTorch, no heavy deps
RUN pip install --no-cache-dir flask>=3.0

# Copy only the funding module + dashboard
COPY funding/ funding/
COPY scripts/funding_dashboard.py scripts/

# SQLite data directory (ephemeral on Railway free tier)
RUN mkdir -p /app/data

# Railway sets PORT env var
ENV PORT=5055
EXPOSE $PORT

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen(f'http://localhost:{__import__(\"os\").environ.get(\"PORT\",5055)}/health')" || exit 1

CMD python scripts/funding_dashboard.py --host 0.0.0.0 --port $PORT
