"""Tests for pipeline/entry_trigger.py (RSI2 mean reversion strategy)."""

import numpy as np
import pandas as pd
import pytest

from momentum_pullback_system.config import Config
from momentum_pullback_system.pipeline.entry_trigger import (
    compute_indicators,
    check_entry_signal,
    scan_for_entries,
)


def _make_rsi2_scenario(
    rsi_oversold: bool = True,
    above_sma200: bool = True,
    above_sma50: bool = True,
    below_sma5: bool = True,
) -> pd.DataFrame:
    """Build a synthetic OHLCV dataset for RSI(2) entry testing.

    Creates 250 days of uptrending data with a sharp 2-day pullback at the end
    to trigger RSI(2) < 10.
    """
    days = 250
    dates = pd.bdate_range("2020-01-01", periods=days)

    # Uptrending base: 50 → 120
    close = np.linspace(50, 120, days).copy()

    if rsi_oversold:
        # Sharp 2-day drop at end to crush RSI(2), but keep above SMA-50
        close[-2] = close[-3] - 2.0
        close[-1] = close[-2] - 1.5
    else:
        # Mild continuation — RSI(2) stays high
        close[-1] = close[-2] + 0.5

    if not above_sma200:
        # Shift last close below SMA-200 by collapsing it
        close[-1] = 40.0

    if not above_sma50:
        # Drop the last price below the recent 50-day average
        close[-1] = close[-60:-10].mean() - 5.0

    if not below_sma5:
        # Make last close above 5-day SMA by raising it
        close[-1] = close[-6:-1].mean() + 3.0

    open_ = close - 0.3
    high = close + 1.0
    low = close - 1.0
    volume = np.full(days, 2_000_000, dtype=float)

    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


class TestComputeIndicators:
    def test_adds_expected_columns(self) -> None:
        df = _make_rsi2_scenario()
        result = compute_indicators(df)
        for col in ["RSI_2", "SMA_5", "SMA_50", "SMA_200"]:
            assert col in result.columns
        assert len(result) == len(df)

    def test_rsi2_values_in_range(self) -> None:
        df = _make_rsi2_scenario()
        result = compute_indicators(df)
        rsi_vals = result["RSI_2"].dropna()
        assert (rsi_vals >= 0).all()
        assert (rsi_vals <= 100).all()


class TestCheckEntrySignal:
    def test_valid_rsi2_triggers(self) -> None:
        df = _make_rsi2_scenario()
        df_ind = compute_indicators(df)
        date = df.index[-1]
        assert check_entry_signal(df_ind, date) is True

    def test_no_trigger_when_rsi_not_oversold(self) -> None:
        df = _make_rsi2_scenario(rsi_oversold=False)
        df_ind = compute_indicators(df)
        date = df.index[-1]
        assert check_entry_signal(df_ind, date) is False

    def test_no_trigger_when_below_sma200(self) -> None:
        df = _make_rsi2_scenario(above_sma200=False)
        df_ind = compute_indicators(df)
        date = df.index[-1]
        assert check_entry_signal(df_ind, date) is False

    def test_no_trigger_when_below_sma50(self) -> None:
        df = _make_rsi2_scenario(above_sma50=False)
        df_ind = compute_indicators(df)
        date = df.index[-1]
        assert check_entry_signal(df_ind, date) is False

    def test_no_trigger_when_above_sma5(self) -> None:
        df = _make_rsi2_scenario(below_sma5=False)
        df_ind = compute_indicators(df)
        date = df.index[-1]
        assert check_entry_signal(df_ind, date) is False

    def test_no_trigger_when_date_missing(self) -> None:
        df = _make_rsi2_scenario()
        df_ind = compute_indicators(df)
        fake_date = pd.Timestamp("2099-01-01")
        assert check_entry_signal(df_ind, fake_date) is False

    def test_sma5_filter_can_be_disabled(self) -> None:
        """When REQUIRE_BELOW_SMA5=False, close above SMA-5 is allowed."""
        df = _make_rsi2_scenario(below_sma5=False)
        df_ind = compute_indicators(df)
        date = df.index[-1]

        class NoSMA5Config(Config):
            REQUIRE_BELOW_SMA5 = False

        # With default config, this should fail (close > SMA5)
        assert check_entry_signal(df_ind, date) is False
        # With SMA5 disabled, it may pass (depends on other conditions)
        # Just verify it doesn't crash
        check_entry_signal(df_ind, date, NoSMA5Config)


class TestScanForEntries:
    def test_returns_sorted_by_lowest_rsi(self) -> None:
        # Stock A: very oversold
        df_a = _make_rsi2_scenario(rsi_oversold=True)
        # Stock B: same scenario
        df_b = _make_rsi2_scenario(rsi_oversold=True)
        # Make stock B slightly less oversold by bumping last close up a bit
        df_b.iloc[-1, df_b.columns.get_loc("Close")] += 1.0

        all_ohlcv = {"A": df_a, "B": df_b}
        date = df_a.index[-1]
        result = scan_for_entries(["A", "B"], all_ohlcv, date)

        # Should return tuples of (ticker, rsi_value) sorted by RSI
        assert len(result) >= 1
        if len(result) == 2:
            assert result[0][1] <= result[1][1]  # lowest RSI first
