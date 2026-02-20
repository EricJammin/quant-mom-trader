from __future__ import annotations

"""S&P 500 constituent list and GICS sector data."""

from io import StringIO
from pathlib import Path

import pandas as pd
import requests


UNIVERSE_CACHE = Path("data/cache/sp500_universe.parquet")

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKIPEDIA_SP400_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"


def fetch_sp500_universe() -> pd.DataFrame:
    """Scrape the current S&P 500 constituent list from Wikipedia.

    Returns
    -------
    pd.DataFrame
        Columns: Symbol, Security, GICS Sector, GICS Sub-Industry.
    """
    resp = requests.get(
        WIKIPEDIA_URL,
        headers={"User-Agent": "MomentumPullbackSystem/1.0"},
        timeout=30,
    )
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]
    # Normalize column names
    df = df.rename(columns={
        "Symbol": "Symbol",
        "Security": "Security",
        "GICS Sector": "GICS Sector",
        "GICS Sub-Industry": "GICS Sub-Industry",
    })
    # Clean ticker symbols (some have dots, e.g., BRK.B → BRK-B for yfinance)
    df["Symbol"] = df["Symbol"].str.replace(".", "-", regex=False)
    cols = ["Symbol", "Security", "GICS Sector", "GICS Sub-Industry"]
    return df[cols].reset_index(drop=True)


def fetch_sp400_universe() -> pd.DataFrame:
    """Scrape the current S&P 400 MidCap constituent list from Wikipedia.

    Returns
    -------
    pd.DataFrame
        Columns: Symbol, Security, GICS Sector, GICS Sub-Industry.
    """
    resp = requests.get(
        WIKIPEDIA_SP400_URL,
        headers={"User-Agent": "MomentumPullbackSystem/1.0"},
        timeout=30,
    )
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]
    # S&P 400 Wikipedia table may have different column names
    col_map = {}
    for col in df.columns:
        col_lower = str(col).lower()
        if "symbol" in col_lower or "ticker" in col_lower:
            col_map[col] = "Symbol"
        elif "company" in col_lower or "security" in col_lower:
            col_map[col] = "Security"
        elif "sector" in col_lower and "sub" not in col_lower:
            col_map[col] = "GICS Sector"
        elif "sub" in col_lower and "industry" in col_lower:
            col_map[col] = "GICS Sub-Industry"
    df = df.rename(columns=col_map)
    df["Symbol"] = df["Symbol"].str.replace(".", "-", regex=False)
    cols = [c for c in ["Symbol", "Security", "GICS Sector", "GICS Sub-Industry"] if c in df.columns]
    return df[cols].reset_index(drop=True)


def load_universe(cache_path: str | Path = UNIVERSE_CACHE) -> pd.DataFrame:
    """Load the S&P 500 universe from cache, or fetch and cache it.

    Parameters
    ----------
    cache_path : str | Path
        Path to the cached Parquet file.

    Returns
    -------
    pd.DataFrame
        S&P 500 constituents with sector data.
    """
    cache_path = Path(cache_path)
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    df = fetch_sp500_universe()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path, index=False)
    return df


def get_sector_map(universe: pd.DataFrame) -> dict[str, str]:
    """Build a ticker → GICS sector mapping.

    Parameters
    ----------
    universe : pd.DataFrame
        Universe DataFrame with Symbol and GICS Sector columns.

    Returns
    -------
    dict[str, str]
        Mapping of ticker symbol to GICS sector name.
    """
    return dict(zip(universe["Symbol"], universe["GICS Sector"]))
