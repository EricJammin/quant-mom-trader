"""Tests for pipeline/regime_filter.py."""

import numpy as np
import pandas as pd
import pytest

from momentum_pullback_system.pipeline.regime_filter import compute_regime


def _make_spy_data(prices: list[float]) -> pd.DataFrame:
    """Create SPY DataFrame from a list of close prices."""
    dates = pd.bdate_range("2020-01-01", periods=len(prices))
    return pd.DataFrame({"Close": prices}, index=dates)


class TestComputeRegime:
    def test_bullish_when_above_sma(self) -> None:
        # Steadily rising prices → bullish once enough data
        prices = list(np.linspace(100, 200, 250))
        spy = _make_spy_data(prices)
        regime = compute_regime(spy)
        # After SMA-200 is available, should be bullish (trending up)
        assert regime.iloc[-1] is np.True_

    def test_bearish_when_below_sma(self) -> None:
        # Rise then sharp decline
        prices = list(np.linspace(100, 200, 220)) + list(np.linspace(200, 120, 50))
        spy = _make_spy_data(prices)
        regime = compute_regime(spy)
        # Price dropped well below SMA-200 → bearish
        assert regime.iloc[-1] is np.False_

    def test_false_before_enough_data(self) -> None:
        prices = list(range(100, 250))  # Only 150 points
        spy = _make_spy_data(prices)
        regime = compute_regime(spy)
        # SMA-200 needs 200 points → NaN SMAs → boolean ops yield False
        assert regime.iloc[0] is np.False_

    def test_returns_series_with_correct_index(self) -> None:
        prices = list(np.linspace(100, 200, 250))
        spy = _make_spy_data(prices)
        regime = compute_regime(spy)
        assert isinstance(regime, pd.Series)
        assert regime.name == "regime_bullish"
        assert len(regime) == len(spy)
        assert regime.index.equals(spy.index)
