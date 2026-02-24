from __future__ import annotations

"""S&P 500 ticker list.

Fetches the current constituent list from the iShares IVV ETF holdings CSV
(primary) with Wikipedia as a fallback. The cache is refreshed automatically
when it is more than 7 days old, keeping the list current with quarterly index
rebalances without hitting the network on every scan run.
"""

import io
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_IVV_URL = (
    "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf"
    "/1467271812596.ajax?fileType=csv&fileName=IVV_holdings&dataType=fund"
)
_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_DEFAULT_CACHE = Path("scanner/cache/sp500_tickers.csv")
_REFRESH_AFTER_DAYS = 7
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; mps-scanner/1.0)"}

# IVV strips dots from some tickers (e.g. BRK.B → BRKB) rather than using hyphens.
# Map these to the yfinance-compatible hyphenated form.
_IVV_SYMBOL_MAP: dict[str, str] = {
    "BRKB": "BRK-B",
    "BFB": "BF-B",
}


def get_tickers(cache_path: Path = _DEFAULT_CACHE) -> list[str]:
    """Return the current S&P 500 ticker list.

    Loads from a local cache if it is fresh (< 7 days old).
    Fetches from IVV holdings (with Wikipedia fallback) and updates the cache otherwise.

    Parameters
    ----------
    cache_path : Path
        Path to the local CSV cache file.

    Returns
    -------
    list[str]
        Ticker symbols, e.g. ['AAPL', 'MSFT', ...].
        Returns an empty list if all sources fail and no cache exists.
    """
    if _cache_is_fresh(cache_path):
        try:
            df = pd.read_csv(cache_path)
            tickers = df["Symbol"].tolist()
            logger.debug(f"Loaded {len(tickers)} tickers from cache ({cache_path}).")
            return tickers
        except Exception as e:
            logger.warning(f"Could not read ticker cache: {e}. Fetching fresh.")

    return refresh_tickers(cache_path)


def refresh_tickers(cache_path: Path = _DEFAULT_CACHE) -> list[str]:
    """Fetch the S&P 500 list from IVV holdings (fallback: Wikipedia) and update cache.

    Parameters
    ----------
    cache_path : Path
        Path to write the updated cache file.

    Returns
    -------
    list[str]
        Ticker symbols, or empty list if all sources failed.
    """
    tickers = _fetch_ivv() or _fetch_wikipedia()
    if not tickers:
        logger.error("All ticker sources failed. Check network connectivity.")
        return []

    df = pd.DataFrame({"Symbol": tickers})
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path, index=False)
    logger.info(f"Fetched {len(tickers)} tickers. Cache updated: {cache_path}")
    return tickers


# ── Source: iShares IVV ────────────────────────────────────────────────────────

def _fetch_ivv() -> list[str]:
    """Fetch tickers from the iShares IVV ETF holdings CSV.

    Returns list of ticker symbols, or empty list on failure.
    """
    logger.info("Fetching S&P 500 tickers from iShares IVV...")
    try:
        resp = requests.get(_IVV_URL, headers=_HEADERS, timeout=20)
        resp.raise_for_status()

        # The IVV CSV has metadata rows at the top before the actual holdings table.
        # Find the header row by locating "Ticker" in the raw text.
        lines = resp.text.splitlines()
        header_idx = next(
            (i for i, line in enumerate(lines) if line.startswith("Ticker")), None
        )
        if header_idx is None:
            logger.warning("IVV CSV format unexpected — could not find 'Ticker' header.")
            return []

        csv_body = "\n".join(lines[header_idx:])
        df = pd.read_csv(io.StringIO(csv_body))

        # Keep only equity rows (exclude cash, futures, etc.)
        df = df[df["Asset Class"] == "Equity"].copy()
        tickers = df["Ticker"].dropna().str.strip().tolist()

        # IVV uses dots in some tickers (e.g. BRK.B); yfinance uses hyphens
        tickers = [t.replace(".", "-") for t in tickers if t and t != "-"]

        # Apply known IVV quirks (e.g. BRKB → BRK-B, BFB → BF-B)
        tickers = [_IVV_SYMBOL_MAP.get(t, t) for t in tickers]

        logger.info(f"IVV: fetched {len(tickers)} equity tickers.")
        return tickers
    except Exception as e:
        logger.warning(f"IVV fetch failed: {e}. Falling back to Wikipedia.")
        return []


# ── Source: Wikipedia (fallback) ───────────────────────────────────────────────

def _fetch_wikipedia() -> list[str]:
    """Fetch tickers from the Wikipedia S&P 500 constituent list.

    Returns list of ticker symbols, or empty list on failure.
    """
    logger.info("Fetching S&P 500 tickers from Wikipedia (fallback)...")
    try:
        resp = requests.get(_WIKIPEDIA_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        df = tables[0][["Symbol"]].copy()
        df["Symbol"] = df["Symbol"].str.replace(".", "-", regex=False)
        tickers = df["Symbol"].tolist()
        logger.info(f"Wikipedia: fetched {len(tickers)} tickers.")
        return tickers
    except Exception as e:
        logger.error(f"Wikipedia fetch failed: {e}")
        return []


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_is_fresh(cache_path: Path) -> bool:
    """Return True if the cache file exists and is less than 7 days old."""
    if not cache_path.exists():
        return False
    mtime = date.fromtimestamp(cache_path.stat().st_mtime)
    return (date.today() - mtime) < timedelta(days=_REFRESH_AFTER_DAYS)
