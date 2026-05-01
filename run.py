import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def setup_logging(log_path, log_level="INFO"):
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("ohlcv_pipeline")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()  # avoid duplicate handlers on re-runs

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # File handler — full detailed log
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Stream handler — same format to stdout
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


def load_config(config_path):
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    # Basic validation
    required_keys = [
        ("data", "filepath"),
        ("data", "date_column"),
        ("signal", "column"),
        ("output", "metrics_path"),
        ("output", "log_path"),
    ]
    for section, key in required_keys:
        if section not in cfg or key not in cfg[section]:
            raise KeyError(f"Missing config key: {section}.{key}")

    # Top-level checks
    if "window" not in cfg:
        raise KeyError("Missing config key: window")
    if "seed" not in cfg:
        cfg["seed"] = 42
    if "version" not in cfg:
        cfg["version"] = "v1"

    return cfg


def load_data(filepath, date_column, logger):
    logger.info(f"Loading OHLCV data from: {filepath!r}")

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")

    import io
    
    # Read all lines and strip leading/trailing quotes and whitespace
    with path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
        
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1]
        cleaned_lines.append(line)
        
    buffer = io.StringIO("\n".join(cleaned_lines))
    
    try:
        df = pd.read_csv(buffer, parse_dates=[date_column])
    except Exception as e:
        raise ValueError(f"Invalid CSV format in file {filepath}: {e}")

    df.columns = [c.strip().strip('"') for c in df.columns]

    # Ensure timestamp column is datetime
    if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
        df[date_column] = pd.to_datetime(df[date_column])

    df.set_index(date_column, inplace=True)
    df.sort_index(inplace=True)

    # Validate non-empty
    if df.empty:
        raise ValueError(f"The input data from {filepath} is empty or could not be parsed.")

    # Validate that 'close' exists
    if "close" not in df.columns:
        raise ValueError(f"Required column 'close' is missing from data. Columns found: {list(df.columns)}")

    # Use only 'close' for calculations (drop other OHLCV columns to save memory)
    df = df[["close"]].copy()

    # Cast 'close' column to float
    df["close"] = pd.to_numeric(df["close"], errors="coerce")

    logger.info(f"Loaded {len(df):,} rows | retained columns: {list(df.columns)}")
    logger.info(f"Date range: {df.index.min()} -> {df.index.max()}")
    logger.debug(f"Memory usage: {df.memory_usage(deep=True).sum() / 1024:.1f} KB")

    nan_counts = df.isna().sum()
    if nan_counts.any():
        logger.warning(f"NaN values detected after load:\n{nan_counts[nan_counts > 0].to_dict()}")
    else:
        logger.info("No NaN values in raw data")

    return df


def compute_rolling_mean(df, column, window, logger):
    if column not in df.columns:
        raise ValueError(f"Column '{column}' not found. Available: {list(df.columns)}")

    rolling_col = f"rolling_mean_{window}"
    logger.info(f"Computing {window}-period rolling mean on '{column}' -> '{rolling_col}'")

    df[rolling_col] = df[column].rolling(window=window, min_periods=window).mean()

    n_nan = int(df[rolling_col].isna().sum())
    n_valid = len(df) - n_nan
    logger.info(f"Rolling mean computed | warm-up NaNs: {n_nan} | valid: {n_valid:,}")
    logger.debug(f"Rolling mean stats — min: {df[rolling_col].min():.4f}, "
                 f"max: {df[rolling_col].max():.4f}, "
                 f"mean: {df[rolling_col].mean():.4f}")

    return df


def generate_signal(df, column, window, logger):
    rolling_col = f"rolling_mean_{window}"
    signal_col = f"signal_{window}"

    logger.info(f"Generating binary signal '{signal_col}' "
                f"(1 = close > {rolling_col}, 0 = close <= {rolling_col})")

    warm_up_mask = df[rolling_col].isna()
    df[signal_col] = np.where(
        warm_up_mask,
        np.nan,
        (df[column] > df[rolling_col]).astype(float),
    )

    valid_signals = df[signal_col].dropna()
    n_buy  = int((valid_signals == 1).sum())
    n_sell = int((valid_signals == 0).sum())
    n_total = len(valid_signals)

    logger.info(f"Signal distribution | BUY(1): {n_buy:,} ({n_buy/n_total:.2%}) | "
                f"SELL(0): {n_sell:,} ({n_sell/n_total:.2%}) | total: {n_total:,}")

    # Log signal flip count (number of direction changes)
    transitions = int(valid_signals.diff().abs().fillna(0).sum())
    logger.info(f"Signal transitions (direction changes): {transitions:,}")

    # Log first few signal values for a sanity check
    sample = df[[column, rolling_col, signal_col]].dropna().head(5)
    logger.debug(f"First 5 valid signal rows:\n{sample.to_string()}")

    return df


    return df


def main():
    parser = argparse.ArgumentParser(description="OHLCV Rolling-Mean Signal Pipeline")
    parser.add_argument("--input", type=str, default="data.csv", help="Path to input data.csv")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--output", type=str, default="metrics.json", help="Path to output metrics.json")
    parser.add_argument("--log-file", type=str, default="run.log", help="Path to output run.log")
    args = parser.parse_args()

    # Provide default fallback variables for the exception block
    start_time = time.perf_counter()
    version = "v1"
    seed = 42

    try:
        # Bootstrap logger before config is read (logs to stderr only)
        logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
        bootstrap = logging.getLogger("bootstrap")
        bootstrap.info(f"Using config: {args.config}")

        # ── Load configuration ─────────────────────────────────────
        cfg = load_config(args.config)
        version = cfg["version"]
        seed = cfg["seed"]
        
        # ── Override YAML paths with CLI arguments ─────────────────
        if "data" not in cfg: cfg["data"] = {}
        if "output" not in cfg: cfg["output"] = {}
        
        cfg["data"]["filepath"] = args.input
        cfg["output"]["metrics_path"] = args.output
        cfg["output"]["log_path"] = args.log_file

        # ── Set up full logging ────────────────────────────────────
        logger = setup_logging(cfg["output"]["log_path"], cfg["output"].get("log_level", "INFO"))

        sep = "=" * 65
        logger.info(sep)
        logger.info("  OHLCV Rolling-Mean Signal Pipeline")
        logger.info(sep)
        logger.info("Job started")
        logger.info(f"Config loaded from : {args.config}")
        logger.info(f"Pipeline version   : {version}")
        logger.info(f"Random seed        : {seed}")
        logger.info(f"Input data file    : {cfg['data']['filepath']}")
        logger.info(f"Signal column      : {cfg['signal']['column']}")
        logger.info(f"Rolling window     : {cfg['window']} periods")
        logger.info(f"Metrics output     : {cfg['output']['metrics_path']}")
        logger.info(f"Log output         : {cfg['output']['log_path']}")
        logger.info(sep)

        # Apply the random seed globally just in case any downstream code needs it
        np.random.seed(seed)

        # ── Pipeline steps ─────────────────────────────────────────
        df = load_data(
            cfg["data"]["filepath"],
            cfg["data"]["date_column"],
            logger,
        )
        rows_processed = len(df)

        df = compute_rolling_mean(
            df,
            cfg["signal"]["column"],
            cfg["window"],
            logger,
        )

        df = generate_signal(
            df,
            cfg["signal"]["column"],
            cfg["window"],
            logger,
        )

        # ── Exact Metrics Output Requirement ───────────────────────
        signal_col = f"signal_{cfg['window']}"
        signal_series = df[signal_col].dropna()
        signal_rate = round(float((signal_series == 1).mean()), 4)

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        output_data = {
            "version": version,
            "rows_processed": rows_processed,
            "metric": "signal_rate",
            "value": signal_rate,
            "latency_ms": latency_ms,
            "seed": seed,
            "status": "success"
        }

        logger.info(f"Metrics summary: {json.dumps(output_data)}")

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)

        # Print final metrics JSON to stdout exactly as requested
        print(json.dumps(output_data, indent=2))

        logger.info(sep)
        logger.info("  Job end | Status: Pipeline completed successfully [OK]")
        logger.info(sep)
        sys.exit(0)

    except Exception as e:
        if 'logger' in locals():
            logger.error(f"Job end | Status: Pipeline failed with exception: {e}", exc_info=True)
        else:
            bootstrap.error(f"Job end | Status: Pipeline failed with exception: {e}", exc_info=True)
        # Write exact error schema
        error_data = {
            "version": version,
            "status": "error",
            "error_message": str(e)
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(error_data, f, indent=2)
            
        # Print final metrics JSON to stdout even on error
        print(json.dumps(error_data, indent=2))
        
        sys.exit(1)


if __name__ == "__main__":
    main()
