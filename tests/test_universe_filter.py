"""Tests for pipeline/universe_filter.py."""

import numpy as np
import pandas as pd
import pytest

from momentum_pullback_system.config import Config
from momentum_pullback_system.pipeline.universe_filter import filter_stock, filter_universe


def _make_ohlcv(
    days: int = 250,
    base_price: float = 100.0,
    trend: float = 0.1,
    volume: int = 2_000_000,
) -> pd.DataFrame:
    """Create synthetic OHLCV data with controllable price and volume."""
    dates = pd.bdate_range("2020-01-01", periods=days)
    close = base_price + np.linspace(0, trend * days, days)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": [volume] * days,
        },
        index=dates,
    )


class TestFilterStock:
    def test_passes_all_criteria(self) -> None:
        ohlcv = _make_ohlcv(days=250, base_price=50.0, trend=0.1, volume=2_000_000)
        date = ohlcv.index[-1]
        assert filter_stock(ohlcv, date) is True

    def test_fails_price_too_low(self) -> None:
        # MIN_PRICE is now 10.0; use base_price=5.0 to fail
        ohlcv = _make_ohlcv(days=250, base_price=5.0, trend=0.0, volume=2_000_000)
        date = ohlcv.index[-1]
        assert filter_stock(ohlcv, date) is False

    def test_fails_volume_too_low(self) -> None:
        # MIN_AVG_VOLUME is now 500_000; use 200_000 to fail
        ohlcv = _make_ohlcv(days=250, base_price=50.0, trend=0.1, volume=200_000)
        date = ohlcv.index[-1]
        assert filter_stock(ohlcv, date) is False

    def test_fails_below_sma200(self) -> None:
        # Declining price → close will be below SMA-200
        ohlcv = _make_ohlcv(days=250, base_price=100.0, trend=-0.2, volume=2_000_000)
        date = ohlcv.index[-1]
        assert filter_stock(ohlcv, date) is False

    def test_fails_below_sma50(self) -> None:
        # Stock with recent decline: uptrend for 200 days then decline for 50
        days = 250
        dates = pd.bdate_range("2020-01-01", periods=days)
        close = np.zeros(days)
        close[:200] = np.linspace(50, 120, 200)
        close[200:] = np.linspace(120, 85, 50)
        ohlcv = pd.DataFrame(
            {
                "Open": close - 0.5,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": [2_000_000] * days,
            },
            index=dates,
        )
        date = ohlcv.index[-1]
        assert filter_stock(ohlcv, date) is False

    def test_fails_insufficient_history(self) -> None:
        ohlcv = _make_ohlcv(days=100, base_price=50.0, trend=0.1, volume=2_000_000)
        date = ohlcv.index[-1]
        assert filter_stock(ohlcv, date) is False


class TestFilterUniverse:
    def test_filters_multiple_stocks(self) -> None:
        good = _make_ohlcv(days=250, base_price=50.0, trend=0.1, volume=2_000_000)
        bad_price = _make_ohlcv(days=250, base_price=5.0, trend=0.0, volume=2_000_000)
        bad_vol = _make_ohlcv(days=250, base_price=50.0, trend=0.1, volume=200_000)
        date = good.index[-1]

        all_ohlcv = {"GOOD": good, "LOWPRICE": bad_price, "LOWVOL": bad_vol}
        result = filter_universe(all_ohlcv, date)
        assert result == ["GOOD"]
