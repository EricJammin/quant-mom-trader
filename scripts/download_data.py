#!/usr/bin/env python3
from __future__ import annotations

"""Download and cache historical OHLCV data for all S&P 500 constituents + SPY.

Usage:
    python scripts/download_data.py
"""

import sys
from pathlib import Path

import pandas as pd
import yfinance as yf
from tqdm import tqdm

# Add project root to path so we can import our modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_pullback_system.config import Config
from momentum_pullback_system.data.universe import fetch_sp500_universe


def download_ticker(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """Download adjusted OHLCV data for a single ticker.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol.
    start : str
        Start date (YYYY-MM-DD).
    end : str
        End date (YYYY-MM-DD).

    Returns
    -------
    pd.DataFrame | None
        OHLCV DataFrame, or None if download failed.
    """
    try:
        df = yf.download(
            ticker,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            return None
        # yfinance sometimes returns MultiIndex columns for single tickers
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel("Ticker")
        # Keep only standard OHLCV columns
        expected = ["Open", "High", "Low", "Close", "Volume"]
        df = df[[c for c in expected if c in df.columns]]
        return df
    except Exception as e:
        print(f"  Error downloading {ticker}: {e}")
        return None


def main() -> None:
    """Download all data and save as Parquet files."""
    cache_dir = PROJECT_ROOT / Config.CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Fetch S&P 500 universe
    print("Fetching S&P 500 constituent list...")
    universe = fetch_sp500_universe()
    universe_path = cache_dir / "sp500_universe.parquet"
    universe.to_parquet(universe_path, index=False)
    print(f"  Saved {len(universe)} constituents to {universe_path}")

    tickers = universe["Symbol"].tolist()

    # Step 2: Download SPY
    print("\nDownloading SPY benchmark data...")
    spy_df = download_ticker("SPY", Config.DATA_START, None)
    if spy_df is not None and not spy_df.empty:
        spy_path = cache_dir / "SPY.parquet"
        spy_df.to_parquet(spy_path)
        print(f"  SPY: {len(spy_df)} trading days saved")
    else:
        print("  FAILED to download SPY — aborting.")
        sys.exit(1)

    # Step 3: Download all constituents
    print(f"\nDownloading {len(tickers)} S&P 500 constituents...")
    success = 0
    failed = []

    for ticker in tqdm(tickers, desc="Downloading"):
        path = cache_dir / f"{ticker}.parquet"
        # Skip if already cached
        if path.exists():
            success += 1
            continue
        df = download_ticker(ticker, Config.DATA_START, None)
        if df is not None and not df.empty:
            df.to_parquet(path)
            success += 1
        else:
            failed.append(ticker)

    # Summary
    print(f"\nDownload complete:")
    print(f"  Success: {success}/{len(tickers)}")
    print(f"  Failed:  {len(failed)}/{len(tickers)}")

    if failed:
        failed_path = cache_dir / "failed_tickers.txt"
        failed_path.write_text("\n".join(failed))
        print(f"  Failed tickers saved to {failed_path}")
        print(f"  Failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
