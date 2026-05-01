# ─────────────────────────────────────────────────────────────
# Dockerfile — OHLCV Rolling-Mean Signal Pipeline
# ─────────────────────────────────────────────────────────────
FROM python:3.9-slim

# Set a non-root working directory
WORKDIR /app

# Install dependencies first (layer-cached unless requirements change)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY run.py      ./
COPY config.yaml ./
COPY data.csv    ./

# Pre-create output directory so logs/metrics are written there
RUN mkdir -p output

# Default command using the exact required argument structure
CMD ["python", "run.py", "--input", "data.csv", "--config", "config.yaml", "--output", "metrics.json", "--log-file", "run.log"]
