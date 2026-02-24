#!/usr/bin/env python3
from __future__ import annotations

"""MPS Daily RSI(2) Scanner — run once after market close.

Usage:
    python3 -m scanner.daily_scan                          # Live scan for today
    python3 -m scanner.daily_scan --dry-run               # Print to console + Telegram [DRY RUN]
    python3 -m scanner.daily_scan --date 2024-06-14       # Scan a historical date (dry-run)
    python3 -m scanner.daily_scan --refresh               # Force re-download all ticker data
    python3 -m scanner.daily_scan --test-alerts           # Verify credentials

Position tracking:
    python3 -m scanner.daily_scan --add-position TSLA 401.50
    python3 -m scanner.daily_scan --remove-position TSLA
    python3 -m scanner.daily_scan --list-positions
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
from scanner.positions import (
    load_positions, add_position, remove_position,
    check_exits, format_positions_table,
)

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
    parser.add_argument(
        "--add-position", nargs=2, metavar=("TICKER", "ENTRY_PRICE"),
        help="Log a new position. Example: --add-position TSLA 401.50",
    )
    parser.add_argument(
        "--remove-position", metavar="TICKER",
        help="Remove an open position. Example: --remove-position TSLA",
    )
    parser.add_argument(
        "--list-positions", action="store_true",
        help="Show all open positions with current price and P&L.",
    )
    args = parser.parse_args()

    config = LiveConfig()

    # ── Test-alerts: verify delivery without running a scan ────────────────────
    if args.test_alerts:
        logger.info("Sending test alerts...")
        send_test_alerts(config)
        return

    # ── Position management commands (load minimal data, then exit) ────────────
    if args.add_position:
        ticker, price_str = args.add_position
        ticker = ticker.upper()
        try:
            entry_price = float(price_str)
        except ValueError:
            logger.error(f"Invalid entry price: {price_str!r}. Must be a number.")
            sys.exit(1)

        data = load_all_tickers([ticker], config.CACHE_DIR, config.CACHE_LOOKBACK_DAYS)
        try:
            pos = add_position(ticker, entry_price, data, config)
            print(
                f"Position added: {pos.ticker} @ ${pos.entry_price:.2f} | "
                f"stop: ${pos.stop_loss:.2f} | entry date: {pos.entry_date}"
            )
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)
        return

    if args.remove_position:
        ticker = args.remove_position.upper()
        found = remove_position(ticker)
        if not found:
            sys.exit(1)
        print(f"Position removed: {ticker}")
        return

    if args.list_positions:
        positions = load_positions()
        scan_date = pd.Timestamp.today().normalize()
        tickers = [p.ticker for p in positions]
        data = load_all_tickers(tickers, config.CACHE_DIR, config.CACHE_LOOKBACK_DAYS) if tickers else {}
        print(format_positions_table(positions, data, scan_date))
        return

    # ── Regular scan ───────────────────────────────────────────────────────────
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

    # ── Check open positions for exits ─────────────────────────────────────────
    positions = load_positions()
    exit_alerts = []
    if positions:
        # Ensure any position tickers not in the S&P 500 universe are loaded
        missing = [p.ticker for p in positions if p.ticker not in all_ohlcv]
        if missing:
            extra = load_all_tickers(missing, config.CACHE_DIR, config.CACHE_LOOKBACK_DAYS)
            all_ohlcv.update(extra)

        exit_alerts = check_exits(positions, all_ohlcv, scan_date, config)
        if exit_alerts:
            logger.info(f"Exit alerts: {len(exit_alerts)} position(s) to close")

    # ── Run entry signal scan ──────────────────────────────────────────────────
    logger.info("Running signal scan...")
    result = run_scan(scan_date, spy_data, all_ohlcv, config)

    logger.info(
        f"Regime: {'BULLISH' if result.is_bullish else 'BEARISH'} | "
        f"Universe passed: {result.tickers_passed_universe} | "
        f"Signals: {len(result.signals)}"
    )

    # ── Output ─────────────────────────────────────────────────────────────────
    if dry_run:
        print(format_dry_run_output(result, config, exit_alerts))

    send_alerts(result, config, dry_run=dry_run, exit_alerts=exit_alerts)


if __name__ == "__main__":
    main()
