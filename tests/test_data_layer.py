"""Tests for the data layer modules."""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from momentum_pullback_system.data.historical import HistoricalFetcher
from momentum_pullback_system.data.universe import get_sector_map


def _make_ohlcv(days: int = 50) -> pd.DataFrame:
    """Create synthetic OHLCV data for testing."""
    dates = pd.bdate_range("2023-01-01", periods=days)
    rng = np.random.default_rng(42)
    close = 100 + rng.standard_normal(days).cumsum()
    return pd.DataFrame(
        {
            "Open": close - rng.uniform(0, 1, days),
            "High": close + rng.uniform(0, 2, days),
            "Low": close - rng.uniform(0, 2, days),
            "Close": close,
            "Volume": rng.integers(500_000, 5_000_000, days),
        },
        index=dates,
    )


class TestHistoricalFetcher:
    def test_missing_cache_dir_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="Cache directory not found"):
            HistoricalFetcher("/nonexistent/path")

    def test_get_ohlcv_roundtrip(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df.to_parquet(tmp_path / "AAPL.parquet")
        fetcher = HistoricalFetcher(tmp_path)
        result = fetcher.get_ohlcv("AAPL")
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert len(result) == len(df)
        assert result.index.name == "Date"

    def test_get_spy_data(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df.to_parquet(tmp_path / "SPY.parquet")
        fetcher = HistoricalFetcher(tmp_path)
        result = fetcher.get_spy_data()
        assert len(result) == len(df)

    def test_missing_ticker_raises(self, tmp_path: Path) -> None:
        # Need at least one file so the dir exists
        _make_ohlcv().to_parquet(tmp_path / "SPY.parquet")
        fetcher = HistoricalFetcher(tmp_path)
        with pytest.raises(FileNotFoundError, match="No cached data for XYZ"):
            fetcher.get_ohlcv("XYZ")

    def test_get_tickers_excludes_spy(self, tmp_path: Path) -> None:
        for t in ["AAPL", "MSFT", "SPY"]:
            _make_ohlcv().to_parquet(tmp_path / f"{t}.parquet")
        fetcher = HistoricalFetcher(tmp_path)
        tickers = fetcher.get_tickers()
        assert "SPY" not in tickers
        assert tickers == ["AAPL", "MSFT"]


class TestSectorMap:
    def test_get_sector_map(self) -> None:
        universe = pd.DataFrame({
            "Symbol": ["AAPL", "JPM", "XOM"],
            "GICS Sector": ["Technology", "Financials", "Energy"],
        })
        sector_map = get_sector_map(universe)
        assert sector_map["AAPL"] == "Technology"
        assert sector_map["JPM"] == "Financials"
        assert len(sector_map) == 3
