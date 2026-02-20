# Momentum Pullback System

Systematic long-only swing trading strategy for S&P 500 stocks. Buys top momentum stocks on RSI(2) mean reversion pullbacks with ATR-based risk management.

## Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Download Data

Historical data must be downloaded before running backtests. Data is cached locally as Parquet files in `data/cache/`.

```bash
python scripts/download_data.py
```

This downloads daily OHLCV data for all S&P 500 constituents and SPY from Yahoo Finance. The initial download takes several minutes.

## Run Backtest

```bash
python scripts/run_backtest.py
```

Options:
- `--start YYYY-MM-DD` — Backtest start date (default: 2021-01-01)
- `--end YYYY-MM-DD` — Backtest end date (default: 2025-12-31)
- `--rsi-threshold N` — Override RSI entry threshold
- `--universe sp500|combined` — Stock universe (default: sp500)

Results are printed to the console and an HTML report is saved to `reports/backtest_report.html`.

## Run Tests

```bash
pytest tests/
```

## Strategy Summary

1. **Regime Filter** — Only trade when SPY is above SMA-200 and SMA-50 > SMA-200
2. **Universe Filter** — Liquid stocks above $10, volume > 500k, price > SMA-200
3. **Momentum Ranking** — Composite relative strength vs SPY (1m/3m/6m), top 25 watchlist
4. **Entry** — RSI(2) drops below threshold while stock is in uptrend (close > SMA-200, close < SMA-5). Default threshold: 10; configurable per-ticker via `RSI_ENTRY_OVERRIDES` in config.
5. **Exit** — RSI(2) recovers above 75, ATR-based stop loss, or 5-day time stop

All parameters are configured in `momentum_pullback_system/config.py`.
