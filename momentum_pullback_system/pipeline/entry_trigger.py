from __future__ import annotations

"""Stage 3: RSI(2) Mean Reversion Entry Trigger.

Detects mean reversion entries when RSI(2) drops to extreme oversold levels
while the stock remains in a long-term uptrend:
- RSI(2) < RSI_ENTRY_THRESHOLD (default 10)
- Close > SMA-200 (uptrend confirmation)
- Optionally: close < SMA-5 (short-term pullback confirmation)
"""

import pandas as pd
from ta.momentum import RSIIndicator

from momentum_pullback_system.config import Config


def compute_indicators(ohlcv: pd.DataFrame, config: Config = Config) -> pd.DataFrame:
    """Add technical indicators needed for RSI(2) entry detection.

    Parameters
    ----------
    ohlcv : pd.DataFrame
        OHLCV data for one stock, indexed by date.
    config : Config
        Strategy configuration.

    Returns
    -------
    pd.DataFrame
        Copy of input with added columns: RSI_2, SMA_5, SMA_200.
    """
    df = ohlcv.copy()
    df["RSI_2"] = RSIIndicator(df["Close"], window=config.RSI_PERIOD).rsi()
    df["SMA_5"] = df["Close"].rolling(window=config.SMA5_PERIOD).mean()
    df["SMA_200"] = df["Close"].rolling(window=config.TREND_SMA_PERIOD).mean()
    return df


def check_entry_signal(df: pd.DataFrame, date: pd.Timestamp, config: Config = Config) -> bool:
    """Check whether a stock triggers an RSI(2) entry signal on a given date.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with indicators (output of compute_indicators).
    date : pd.Timestamp
        The date to check.
    config : Config
        Strategy configuration.

    Returns
    -------
    bool
        True if all RSI(2) entry conditions are met on the given date.
    """
    if date not in df.index:
        return False

    row = df.loc[date]

    # Check for NaN indicators
    if pd.isna(row["RSI_2"]) or pd.isna(row["SMA_200"]):
        return False

    # Primary trigger: RSI(2) below entry threshold
    if row["RSI_2"] >= config.RSI_ENTRY_THRESHOLD:
        return False

    # Uptrend confirmation: close above SMA-200
    if row["Close"] <= row["SMA_200"]:
        return False

    # Optional: close below SMA-5 (short-term pullback)
    if config.REQUIRE_BELOW_SMA5:
        if pd.isna(row["SMA_5"]):
            return False
        if row["Close"] >= row["SMA_5"]:
            return False

    return True


def scan_for_entries(
    watchlist_tickers: list[str],
    all_ohlcv: dict[str, pd.DataFrame],
    date: pd.Timestamp,
    config: Config = Config,
    indicators_cache: dict[str, pd.DataFrame] | None = None,
) -> list[tuple[str, float]]:
    """Scan the watchlist for stocks triggering an RSI(2) signal on a given date.

    Parameters
    ----------
    watchlist_tickers : list[str]
        Tickers in the current watchlist (from momentum ranking).
    all_ohlcv : dict[str, pd.DataFrame]
        Mapping of ticker -> OHLCV DataFrame.
    date : pd.Timestamp
        The date to check.
    config : Config
        Strategy configuration.
    indicators_cache : dict[str, pd.DataFrame] | None
        Optional cache of pre-computed indicators. Updated in place if provided.

    Returns
    -------
    list[tuple[str, float]]
        Triggered tickers with their RSI(2) values, sorted by lowest RSI first.
    """
    triggered: list[tuple[str, float]] = []
    for ticker in watchlist_tickers:
        if ticker not in all_ohlcv:
            continue

        # Use cache if available
        if indicators_cache is not None and ticker in indicators_cache:
            df = indicators_cache[ticker]
        else:
            df = compute_indicators(all_ohlcv[ticker], config)
            if indicators_cache is not None:
                indicators_cache[ticker] = df

        if check_entry_signal(df, date, config):
            rsi_val = df.loc[date, "RSI_2"]
            triggered.append((ticker, float(rsi_val)))

    # Sort by lowest RSI(2) first (most oversold)
    triggered.sort(key=lambda x: x[1])
    return triggered
