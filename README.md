# OHLCV Rolling-Mean Signal Pipeline

A Python pipeline that ingests BTC/USD 1-minute OHLCV data, computes a rolling mean on the close price, generates a binary trading signal, and writes structured metrics + detailed logs.

---

## Project Structure

```
assignment_prime_trade/
├── data.csv               ← 10,000-row OHLCV dataset (BTC/USD 1-min bars)
├── config.yaml            ← Top-level tuneable parameters (seed, window, version)
├── run.py                 ← Pipeline entrypoint
├── requirements.txt       ← Python dependencies
├── Dockerfile             ← Container definition (python:3.9-slim)
├── docker-compose.yml     ← Local compose setup
├── metrics.json           ← Structured metrics output (JSON)
└── run.log                ← Detailed timestamped execution log
```

---

## Config (`config.yaml`)

```yaml
seed: 42
window: 5
version: "v1"

data:
  filepath: data.csv
  date_column: timestamp

signal:
  column: close
```

---

## Signal Logic

```
signal = 1  (BUY)   if  close >  rolling_mean(close, window)
signal = 0  (SELL)  if  close <= rolling_mean(close, window)
signal = NaN        during the first (window - 1) warm-up rows
```

---

## Running Locally

### Prerequisites
- Python 3.9 or newer

### Install & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the pipeline
python run.py --input data.csv --config config.yaml --output metrics.json --log-file run.log
```

---

## Running in Docker

### Standard Evaluation Command

The Docker image builds the required files natively and will output the JSON schema directly to stdout before exiting.

```bash
# 1. Build the image exactly as required
docker build -t mlops-task .

# 2. Run the container
docker run --rm mlops-task
```

---

## Output Formats

### `metrics.json` — Success Case
```json
{
  "version": "v1",
  "rows_processed": 10000,
  "metric": "signal_rate",
  "value": 0.4991,
  "latency_ms": 35,
  "seed": 42,
  "status": "success"
}
```

### `metrics.json` — Error Case
```json
{
  "version": "v1",
  "status": "error",
  "error_message": "Config file not found: doesnotexist.yaml"
}
```

### `run.log` — Example Summary
```
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | =================================================================
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline |   OHLCV Rolling-Mean Signal Pipeline
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | =================================================================
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | Job started
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | Config loaded from : config.yaml
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | Pipeline version   : v1
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | Random seed        : 42
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | Loaded 10,000 rows | retained columns: ['close']
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | Computing 5-period rolling mean on 'close' -> 'rolling_mean_5'
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | Generating binary signal 'signal_5' (1 = close > rolling_mean_5, 0 = close <= rolling_mean_5)
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | Metrics summary: {"version": "v1", ...}
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | =================================================================
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline |   Job end | Status: Pipeline completed successfully [OK]
2026-05-01T00:00:00 | INFO     | ohlcv_pipeline | =================================================================
```

---

