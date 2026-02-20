from __future__ import annotations

"""Concrete DataFetcher that loads cached Parquet files from disk."""

from pathlib import Path

import pandas as pd

from momentum_pullback_system.data.fetcher import DataFetcher


class HistoricalFetcher(DataFetcher):
    """Loads OHLCV data from locally cached Parquet files.

    Parameters
    ----------
    cache_dir : str | Path
        Directory containing ticker Parquet files and spy.parquet.
    """

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        if not self.cache_dir.exists():
            raise FileNotFoundError(
                f"Cache directory not found: {self.cache_dir}. "
                "Run scripts/download_data.py first."
            )

    def get_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Load OHLCV data for a ticker from its cached Parquet file.

        Parameters
        ----------
        ticker : str
            Stock ticker symbol.

        Returns
        -------
        pd.DataFrame
            OHLCV DataFrame indexed by date.

        Raises
        ------
        FileNotFoundError
            If no cached file exists for the ticker.
        """
        path = self.cache_dir / f"{ticker}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"No cached data for {ticker} at {path}")
        df = pd.read_parquet(path)
        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"
        return df

    def get_spy_data(self) -> pd.DataFrame:
        """Load SPY benchmark data from cache.

        Returns
        -------
        pd.DataFrame
            SPY OHLCV DataFrame indexed by date.
        """
        return self.get_ohlcv("SPY")

    def get_tickers(self) -> list[str]:
        """Return all tickers available in the cache directory.

        Returns
        -------
        list[str]
            Sorted list of ticker symbols (excludes SPY).
        """
        tickers = [
            p.stem for p in self.cache_dir.glob("*.parquet")
            if p.stem != "SPY"
        ]
        return sorted(tickers)
