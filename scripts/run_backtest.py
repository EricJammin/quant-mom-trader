#!/usr/bin/env python3
from __future__ import annotations

"""Run the full backtest and generate a performance report.

Usage:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --start 2022-01-01 --end 2023-12-31
    python scripts/run_backtest.py --rsi-threshold 15
"""

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_pullback_system.config import Config
from momentum_pullback_system.data.historical import HistoricalFetcher
from momentum_pullback_system.data.universe import load_universe, get_sector_map
from momentum_pullback_system.backtest.engine import BacktestEngine
from momentum_pullback_system.backtest.metrics import compute_all_metrics
from momentum_pullback_system.reports.generator import generate_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RSI(2) Mean Reversion backtest")
    parser.add_argument("--start", default=Config.BACKTEST_START, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=Config.BACKTEST_END, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", default="reports/backtest_report.html", help="Report output path")
    parser.add_argument("--rsi-threshold", type=int, default=None, help="Override RSI_ENTRY_THRESHOLD")
    parser.add_argument("--universe", default="sp500", choices=["sp500", "combined"], help="Universe: sp500 or combined (SP500+SP400)")
    args = parser.parse_args()

    # Apply CLI overrides
    if args.rsi_threshold is not None:
        Config.RSI_ENTRY_THRESHOLD = args.rsi_threshold

    print("=" * 60)
    print("  RSI(2) Mean Reversion System — Full Backtest")
    print("=" * 60)
    print(f"  Period: {args.start} to {args.end}")
    print(f"  Initial Capital: ${Config.INITIAL_CAPITAL:,.0f}")
    print(f"  Max Positions: {Config.MAX_POSITIONS}")
    print(f"  RSI Entry Threshold: {Config.RSI_ENTRY_THRESHOLD}")
    print(f"  RSI Exit Threshold: {Config.RSI_EXIT_THRESHOLD}")
    print(f"  Stop ATR Multiple: {Config.STOP_ATR_MULTIPLE}")
    print(f"  Time Stop Days: {Config.TIME_STOP_DAYS}")
    print()

    # Load data
    print("Loading cached data...")
    cache_dir = PROJECT_ROOT / Config.CACHE_DIR
    fetcher = HistoricalFetcher(cache_dir)

    spy_data = fetcher.get_spy_data()
    tickers = fetcher.get_tickers()
    universe_file = "combined_universe.parquet" if args.universe == "combined" else "sp500_universe.parquet"
    universe = load_universe(cache_dir / universe_file)
    sector_map = get_sector_map(universe)

    print(f"  SPY: {len(spy_data)} trading days")
    print(f"  Universe: {len(tickers)} stocks")

    # Only load tickers that are in the selected universe
    universe_tickers = set(universe["Symbol"].tolist())
    print(f"\nLoading stock data for {len(universe_tickers)} universe members...")
    all_ohlcv = {}
    for ticker in universe_tickers:
        try:
            all_ohlcv[ticker] = fetcher.get_ohlcv(ticker)
        except FileNotFoundError:
            pass
    print(f"  Loaded {len(all_ohlcv)} stocks")

    # Run backtest
    print("\nRunning backtest...")
    t0 = time.time()
    engine = BacktestEngine(all_ohlcv, spy_data, sector_map)
    result = engine.run(start_date=args.start, end_date=args.end)
    elapsed = time.time() - t0
    print(f"  Completed in {elapsed:.1f}s")

    # Compute metrics
    metrics = compute_all_metrics(
        result.equity_curve, result.trade_log, Config.INITIAL_CAPITAL, spy_data
    )

    # Print summary
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)
    print(f"  Total Return:      {metrics['total_return_pct']:.2f}%")
    print(f"  Annualized Return: {metrics['annualized_return_pct']:.2f}%")
    print(f"  Sharpe Ratio:      {metrics['sharpe_ratio']:.2f}")
    print(f"  Sortino Ratio:     {metrics['sortino_ratio']:.2f}")
    print(f"  Profit Factor:     {metrics['profit_factor']:.2f}")
    print(f"  Max Drawdown:      {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Win Rate:          {metrics['win_rate_pct']:.0f}%")
    print(f"  Total Trades:      {metrics['num_trades']}")
    print(f"  Avg Holding Days:  {metrics['avg_holding_days']:.1f}")
    print(f"  Exposure Time:     {metrics['exposure_pct']:.1f}%")
    print(f"  Final Value:       ${metrics['final_value']:,.2f}")
    if metrics["spy_return_pct"] is not None:
        print(f"  SPY Return:        {metrics['spy_return_pct']:.2f}%")

    # Best single trade stats
    if not result.trade_log.empty and "PnL_Pct" in result.trade_log.columns:
        winners = result.trade_log[result.trade_log["PnL_Pct"] > 0]
        if not winners.empty:
            print(f"  Avg Win Trade:     {winners['PnL_Pct'].mean():.2f}%")
            print(f"  Max Single Win:    {winners['PnL_Pct'].max():.2f}%")
    print()

    # Acceptance criteria
    print("  ACCEPTANCE CRITERIA (In-Sample)")
    checks = [
        ("Sharpe >= 1.0", metrics["sharpe_ratio"] >= 1.0),
        ("Profit Factor >= 1.5", metrics["profit_factor"] >= 1.5),
        ("Max DD <= 15%", metrics["max_drawdown_pct"] >= -15.0),
        ("Trades >= 75", metrics["num_trades"] >= 75),
        ("Positive Expectancy", metrics["positive_expectancy"]),
    ]
    all_pass = True
    for label, passed in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"    {label}: {status}")
    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILED'}")

    # Generate report
    print(f"\nGenerating report...")
    output = generate_report(
        result.equity_curve,
        result.trade_log,
        result.regime_series,
        spy_data,
        Config.INITIAL_CAPITAL,
        output_path=args.output,
    )
    print(f"  Report saved to: {output}")
    print()


if __name__ == "__main__":
    main()
