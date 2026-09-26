# ABL dashboard image — demo mode, self-contained (docs/DEPLOY.zh.md).
# Build:  docker build -t abl .          (≈8 min: the demo ledger is generated at build time)
# Run:    docker run -p 8501:8501 -e ABL_DASHBOARD_PASSWORD=secret abl
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app ABL_DEMO=1 ABL_LANG=zh ABL_LLM=stub

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Generate the demo ledger once, at build time, so the container starts with data in it.
RUN python scripts/build_demo.py

# Render/Railway/Fly inject $PORT; default 8501 for `docker run`.
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8501\")}/_stcore/health')"
CMD ["sh", "-c", "streamlit run dashboard/app.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
