"""Stage 0: Market Regime Gate.

Prevents trading during broad market downtrends. When the regime is bearish,
no new trades are opened (existing positions are managed normally).
"""

import pandas as pd

from momentum_pullback_system.config import Config


def compute_regime(spy_data: pd.DataFrame, config: Config = Config) -> pd.Series:
    """Classify each trading day as bullish or bearish based on SPY moving averages.

    Parameters
    ----------
    spy_data : pd.DataFrame
        SPY OHLCV data indexed by date. Must have a 'Close' column.
    config : Config
        Strategy configuration with REGIME_SMA_LONG and REGIME_SMA_SHORT.

    Returns
    -------
    pd.Series
        Boolean series indexed by date. True = BULLISH, False = BEARISH.
        Bullish when SPY close > SMA-200 AND SMA-50 > SMA-200.
    """
    close = spy_data["Close"]
    sma_long = close.rolling(window=config.REGIME_SMA_LONG).mean()
    sma_short = close.rolling(window=config.REGIME_SMA_SHORT).mean()

    bullish = (close > sma_long) & (sma_short > sma_long)
    bullish.name = "regime_bullish"
    return bullish
