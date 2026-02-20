from __future__ import annotations

"""Stage 1: Universe Filter.

Ensures we only trade liquid, established stocks that are in uptrends.
All three conditions must be true for a stock to pass.
"""

import pandas as pd

from momentum_pullback_system.config import Config


def filter_stock(ohlcv: pd.DataFrame, date: pd.Timestamp, config: Config = Config) -> bool:
    """Check whether a single stock passes all universe filter criteria on a given date.

    Parameters
    ----------
    ohlcv : pd.DataFrame
        OHLCV data for one stock, indexed by date.
    date : pd.Timestamp
        The date to evaluate.
    config : Config
        Strategy configuration with MIN_PRICE, MIN_AVG_VOLUME, TREND_SMA_PERIOD.

    Returns
    -------
    bool
        True if the stock passes all filters on the given date.
    """
    data = ohlcv.loc[:date]
    if len(data) < config.TREND_SMA_PERIOD:
        return False

    close = data["Close"].iloc[-1]
    if close <= config.MIN_PRICE:
        return False

    avg_volume = data["Volume"].iloc[-20:].mean()
    if avg_volume < config.MIN_AVG_VOLUME:
        return False

    sma_200 = data["Close"].iloc[-config.TREND_SMA_PERIOD:].mean()
    if close <= sma_200:
        return False

    return True


def filter_universe(
    all_ohlcv: dict[str, pd.DataFrame],
    date: pd.Timestamp,
    config: Config = Config,
) -> list[str]:
    """Filter the full universe of stocks on a given date.

    Parameters
    ----------
    all_ohlcv : dict[str, pd.DataFrame]
        Mapping of ticker → OHLCV DataFrame.
    date : pd.Timestamp
        The date to evaluate.
    config : Config
        Strategy configuration.

    Returns
    -------
    list[str]
        Tickers that pass all universe filter criteria.
    """
    passing = []
    for ticker, ohlcv in all_ohlcv.items():
        if date not in ohlcv.index:
            continue
        if filter_stock(ohlcv, date, config):
            passing.append(ticker)
    return sorted(passing)
