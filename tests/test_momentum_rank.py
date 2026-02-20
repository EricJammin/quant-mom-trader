"""Tests for pipeline/momentum_rank.py."""

import numpy as np
import pandas as pd
import pytest

from momentum_pullback_system.config import Config
from momentum_pullback_system.pipeline.momentum_rank import (
    compute_rs_composite,
    rank_stocks,
    _apply_sector_cap,
)


def _make_close_series(days: int = 200, base: float = 100.0, growth: float = 0.5) -> pd.Series:
    """Create a synthetic close price series."""
    dates = pd.bdate_range("2020-01-01", periods=days)
    prices = base + np.linspace(0, growth * days, days)
    return pd.Series(prices, index=dates, name="Close")


class TestComputeRsComposite:
    def test_outperformer_scores_above_one(self) -> None:
        # Stock grows faster than SPY
        stock = _make_close_series(days=200, base=100, growth=1.0)
        spy = _make_close_series(days=200, base=100, growth=0.2)
        date = stock.index[-1]
        rs = compute_rs_composite(stock, spy, date)
        assert rs is not None
        assert rs > 1.0

    def test_underperformer_scores_below_one(self) -> None:
        stock = _make_close_series(days=200, base=100, growth=0.1)
        spy = _make_close_series(days=200, base=100, growth=1.0)
        date = stock.index[-1]
        rs = compute_rs_composite(stock, spy, date)
        assert rs is not None
        assert rs < 1.0

    def test_returns_none_with_insufficient_data(self) -> None:
        stock = _make_close_series(days=50, base=100, growth=0.5)
        spy = _make_close_series(days=50, base=100, growth=0.2)
        date = stock.index[-1]
        rs = compute_rs_composite(stock, spy, date)
        assert rs is None


class TestApplySectorCap:
    def test_respects_sector_cap(self) -> None:
        rows = []
        for i in range(15):
            rows.append({"Ticker": f"TECH{i}", "RS_Composite": 2.0 - i * 0.01, "Sector": "Tech"})
        for i in range(5):
            rows.append({"Ticker": f"FIN{i}", "RS_Composite": 1.5 - i * 0.01, "Sector": "Finance"})
        ranked = pd.DataFrame(rows)

        result = _apply_sector_cap(ranked, watchlist_size=10, sector_cap=3)
        tech_count = (result["Sector"] == "Tech").sum()
        assert tech_count <= 3
        assert len(result) <= 10

    def test_fills_from_other_sectors(self) -> None:
        rows = []
        for i in range(10):
            rows.append({"Ticker": f"T{i}", "RS_Composite": 2.0 - i * 0.01, "Sector": "Tech"})
        for i in range(10):
            rows.append({"Ticker": f"F{i}", "RS_Composite": 1.5 - i * 0.01, "Sector": "Finance"})
        ranked = pd.DataFrame(rows)

        result = _apply_sector_cap(ranked, watchlist_size=8, sector_cap=5)
        assert len(result) == 8


class TestRankStocks:
    def test_returns_ranked_watchlist(self) -> None:
        spy_close = _make_close_series(days=200, base=100, growth=0.3)
        spy_data = pd.DataFrame({"Close": spy_close})

        all_ohlcv = {}
        tickers = []
        for i, name in enumerate(["FAST", "MED", "SLOW"]):
            close = _make_close_series(days=200, base=100, growth=1.0 - i * 0.3)
            all_ohlcv[name] = pd.DataFrame({
                "Open": close, "High": close, "Low": close,
                "Close": close, "Volume": [1_000_000] * len(close),
            })
            tickers.append(name)

        sector_map = {"FAST": "Tech", "MED": "Finance", "SLOW": "Energy"}
        date = spy_close.index[-1]

        result = rank_stocks(tickers, all_ohlcv, spy_data, date, sector_map)
        assert len(result) > 0
        assert result.iloc[0]["Ticker"] == "FAST"
        assert list(result.columns) == ["Ticker", "RS_Composite", "Sector", "Rank"]
        assert result["Rank"].iloc[0] == 1
