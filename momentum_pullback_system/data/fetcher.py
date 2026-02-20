"""Abstract base class for data fetching.

Pipeline modules depend on this interface, not on concrete implementations.
This allows swapping between historical (cached Parquet) and live (API) sources
without changing any strategy logic.
"""

from abc import ABC, abstractmethod

import pandas as pd


class DataFetcher(ABC):
    """Abstract interface for fetching OHLCV market data."""

    @abstractmethod
    def get_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Fetch OHLCV data for a single ticker.

        Parameters
        ----------
        ticker : str
            Stock ticker symbol (e.g., "AAPL").

        Returns
        -------
        pd.DataFrame
            DataFrame indexed by date with columns:
            Open, High, Low, Close, Volume.
            Prices are adjusted for splits and dividends.
        """

    @abstractmethod
    def get_spy_data(self) -> pd.DataFrame:
        """Fetch OHLCV data for the SPY benchmark.

        Returns
        -------
        pd.DataFrame
            Same format as get_ohlcv().
        """

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return list of available ticker symbols.

        Returns
        -------
        list[str]
            Tickers for which data is available.
        """
