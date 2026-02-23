from __future__ import annotations

"""Data fetcher with local caching for the live scanner.

Downloads OHLCV data from yfinance and caches as Parquet files.
On each run, only tickers whose cache is stale are re-downloaded.
If a download fails, the stale cache is used with a warning rather
than crashing the scan.
"""

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def load_ticker(
    ticker: str,
    cache_dir: Path,
    lookback_days: int = 365,
    force_refresh: bool = False,
) -> pd.DataFrame | None:
    """Load OHLCV data for a single ticker, downloading if stale.

    Parameters
    ----------
    ticker : str
        Ticker symbol.
    cache_dir : Path
        Directory for cached Parquet files.
    lookback_days : int
        Days of history to download when refreshing the cache.
    force_refresh : bool
        Re-download even if the cache is fresh.

    Returns
    -------
    pd.DataFrame | None
        OHLCV DataFrame indexed by date, or None if unavailable.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{ticker}.parquet"

    if not force_refresh and _is_cache_fresh(cache_path):
        try:
            return pd.read_parquet(cache_path)
        except Exception as e:
            logger.warning(f"Failed to read cache for {ticker}: {e}. Re-downloading.")

    df = _download(ticker, lookback_days)

    if df is not None and not df.empty:
        df.to_parquet(cache_path)
        logger.debug(f"Cached {ticker}: {len(df)} rows.")
        return df

    # Download failed — fall back to stale cache rather than returning None
    if cache_path.exists():
        logger.warning(f"Download failed for {ticker}; using stale cache.")
        try:
            return pd.read_parquet(cache_path)
        except Exception:
            pass

    logger.error(f"No data available for {ticker}.")
    return None


def load_all_tickers(
    tickers: list[str],
    cache_dir: Path,
    lookback_days: int = 365,
    force_refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV data for a list of tickers.

    Skips tickers that fail entirely (no download, no cache).
    Logs a summary of failures at the end.

    Parameters
    ----------
    tickers : list[str]
        Ticker symbols to load.
    cache_dir : Path
        Directory for cached Parquet files.
    lookback_days : int
        Days of history to download when refreshing.
    force_refresh : bool
        Re-download all tickers regardless of cache freshness.

    Returns
    -------
    dict[str, pd.DataFrame]
        Mapping of ticker → OHLCV DataFrame for successfully loaded tickers.
    """
    result: dict[str, pd.DataFrame] = {}
    failed: list[str] = []

    for ticker in tickers:
        df = load_ticker(ticker, cache_dir, lookback_days, force_refresh)
        if df is not None and not df.empty:
            result[ticker] = df
        else:
            failed.append(ticker)

    if failed:
        preview = ", ".join(failed[:10])
        suffix = f" ... and {len(failed) - 10} more" if len(failed) > 10 else ""
        logger.warning(f"Failed to load {len(failed)} ticker(s): {preview}{suffix}")

    return result


# ── Private helpers ────────────────────────────────────────────────────────────

def _is_cache_fresh(cache_path: Path) -> bool:
    """Return True if the cache contains data up through at least 3 days ago.

    3-day window accounts for weekends and market holidays so the cache
    is not re-downloaded unnecessarily on non-trading days.
    """
    if not cache_path.exists():
        return False
    try:
        # Read only the index to avoid loading the full file
        df = pd.read_parquet(cache_path, columns=["Close"])
        last_date = df.index[-1].date()
        cutoff = date.today() - timedelta(days=3)
        return last_date >= cutoff
    except Exception:
        return False


def _download(ticker: str, lookback_days: int) -> pd.DataFrame | None:
    """Download adjusted OHLCV data from yfinance."""
    start = (date.today() - timedelta(days=lookback_days)).isoformat()
    try:
        df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
        if df.empty:
            logger.warning(f"yfinance returned empty data for {ticker}.")
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel("Ticker")
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        return df[cols]
    except Exception as e:
        logger.error(f"yfinance download failed for {ticker}: {e}")
        return None
