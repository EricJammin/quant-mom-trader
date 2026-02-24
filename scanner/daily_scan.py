#!/usr/bin/env python3
from __future__ import annotations

"""MPS Daily RSI(2) Scanner — run once after market close.

Usage:
    python -m scanner.daily_scan                    # Live scan for today
    python -m scanner.daily_scan --dry-run          # Print to console + Telegram [DRY RUN]
    python -m scanner.daily_scan --date 2024-06-14  # Scan a historical date (dry-run implied)
    python -m scanner.daily_scan --refresh          # Force re-download all ticker data
    python -m scanner.daily_scan --test-alerts      # Send test message to verify credentials
"""

import argparse
import logging
import sys

import pandas as pd
from dotenv import load_dotenv

# Load .env file if present (for local development)
load_dotenv()

from scanner.config_live import LiveConfig
from scanner.sp500_tickers import get_tickers
from scanner.data_fetcher import load_all_tickers
from scanner.signal_detector import run_scan
from scanner.alert_sender import send_alerts, send_error_alert, send_test_alerts, format_dry_run_output

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="MPS RSI(2) Daily Scanner")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print alert to console and send Telegram tagged [DRY RUN]. Email is skipped.",
    )
    parser.add_argument(
        "--date", default=None, metavar="YYYY-MM-DD",
        help="Scan a specific historical date (note: cache covers last 365 days).",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Force re-download all ticker data even if cache is fresh.",
    )
    parser.add_argument(
        "--test-alerts", action="store_true",
        help="Send a test message through all configured channels to verify credentials.",
    )
    args = parser.parse_args()

    config = LiveConfig()

    # ── Test-alerts: verify delivery without running a scan ────────────────────
    if args.test_alerts:
        logger.info("Sending test alerts...")
        send_test_alerts(config)
        return

    # Historical date scans are always dry-run — avoid sending alerts for old data
    dry_run = args.dry_run or (args.date is not None)

    try:
        _run_scan(args, config, dry_run)
    except Exception as e:
        logger.exception(f"Unhandled scanner error: {e}")
        send_error_alert(str(e), config)
        sys.exit(1)


def _run_scan(args, config, dry_run: bool) -> None:
    """Core scan logic, separated so exceptions can be caught and alerted in main()."""

    # ── Determine scan date ────────────────────────────────────────────────────
    if args.date:
        scan_date = pd.Timestamp(args.date)
        logger.info(f"Historical scan for {scan_date.date()} (dry-run)")
    else:
        scan_date = pd.Timestamp.today().normalize()
        logger.info(f"Live scan for {scan_date.date()} | dry-run={dry_run}")

    # ── Load ticker list ───────────────────────────────────────────────────────
    tickers = get_tickers(config.CACHE_DIR / "sp500_tickers.csv")
    if not tickers:
        raise RuntimeError("Failed to load S&P 500 ticker list.")

    all_tickers = tickers + [
        t for t in config.SUPPLEMENTAL_TICKERS if t not in tickers
    ]
    logger.info(
        f"Universe: {len(tickers)} S&P 500 tickers + "
        f"{len(config.SUPPLEMENTAL_TICKERS)} supplemental"
    )

    # ── Load / refresh data ────────────────────────────────────────────────────
    logger.info("Loading ticker data...")
    all_ohlcv = load_all_tickers(
        all_tickers,
        cache_dir=config.CACHE_DIR,
        lookback_days=config.CACHE_LOOKBACK_DAYS,
        force_refresh=args.refresh,
    )
    logger.info(f"Loaded {len(all_ohlcv)} tickers.")

    spy_data = all_ohlcv.get("SPY")
    if spy_data is None:
        raise RuntimeError("SPY data unavailable.")

    # ── Validate scan date ─────────────────────────────────────────────────────
    if scan_date not in spy_data.index:
        latest = spy_data.index[-1]
        if args.date:
            raise RuntimeError(
                f"Requested date {args.date} not found in SPY data "
                f"(cache covers up to {latest.date()}). "
                f"Dates older than ~{config.CACHE_LOOKBACK_DAYS} days are not cached."
            )
        else:
            logger.warning(
                f"Today ({scan_date.date()}) not yet in data. "
                f"Using latest available: {latest.date()}."
            )
            scan_date = latest

    # ── Run scan ───────────────────────────────────────────────────────────────
    logger.info("Running signal scan...")
    result = run_scan(scan_date, spy_data, all_ohlcv, config)

    logger.info(
        f"Regime: {'BULLISH' if result.is_bullish else 'BEARISH'} | "
        f"Universe passed: {result.tickers_passed_universe} | "
        f"Signals: {len(result.signals)}"
    )

    # ── Output ─────────────────────────────────────────────────────────────────
    if dry_run:
        print(format_dry_run_output(result, config))

    send_alerts(result, config, dry_run=dry_run)


if __name__ == "__main__":
    main()
