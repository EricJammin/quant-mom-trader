from __future__ import annotations

"""Tests for the live scanner signal detector.

Run from the project root:
    pytest scanner/tests/test_signal_detector.py
"""

import numpy as np
import pandas as pd
import pytest

from scanner.config_live import LiveConfig
from scanner.signal_detector import Signal, ScanResult, run_scan


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_uptrend(n: int = 300, base: float = 100.0, seed: int = 42) -> pd.DataFrame:
    """Steady uptrend with controlled noise — stock stays above SMA-200."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2025-12-31", periods=n)
    prices = base + np.linspace(0, 30, n) + rng.normal(0, 0.3, n)
    return pd.DataFrame({
        "Open": prices * 0.999,
        "High": prices * 1.004,
        "Low":  prices * 0.996,
        "Close": prices,
        "Volume": np.full(n, 2_000_000),
    }, index=dates)


def _make_spy_bullish(n: int = 300) -> pd.DataFrame:
    """SPY data that passes both regime conditions."""
    return _make_uptrend(n, base=450.0, seed=1)


def _make_spy_bearish(n: int = 300) -> pd.DataFrame:
    """SPY data in a clear downtrend — below SMA-200."""
    dates = pd.bdate_range(end="2025-12-31", periods=n)
    prices = 600.0 - np.linspace(0, 300, n)          # steep decline
    return pd.DataFrame({
        "Open": prices, "High": prices * 1.002,
        "Low": prices * 0.998, "Close": prices,
        "Volume": np.full(n, 80_000_000),
    }, index=dates)


def _make_oversold_stock(n: int = 300, base: float = 100.0) -> pd.DataFrame:
    """Uptrending stock with two sharp down days at the end to force RSI(2) < 10."""
    rng = np.random.default_rng(7)
    dates = pd.bdate_range(end="2025-12-31", periods=n)
    prices = base + np.linspace(0, 30, n) + rng.normal(0, 0.3, n)
    # Two hard down days at the end → RSI(2) near zero
    prices[-2] *= 0.965
    prices[-1] *= 0.965
    return pd.DataFrame({
        "Open": prices * 1.001,
        "High": prices * 1.003,
        "Low":  prices * 0.997,
        "Close": prices,
        "Volume": np.full(n, 3_000_000),
    }, index=dates)


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestRegime:
    def test_bearish_regime_returns_no_signals(self):
        """When SPY is in a downtrend, run_scan should not produce any signals."""
        config = LiveConfig()
        spy = _make_spy_bearish()
        scan_date = spy.index[-1]

        result = run_scan(scan_date, spy, {"SPY": spy}, config)

        assert result.is_bullish is False
        assert result.signals == []

    def test_bullish_regime_is_detected(self):
        """When SPY is in a clear uptrend, the regime should be bullish."""
        config = LiveConfig()
        spy = _make_spy_bullish()
        scan_date = spy.index[-1]

        result = run_scan(scan_date, spy, {"SPY": spy}, config)

        assert result.is_bullish is True


class TestSignalDetection:
    def test_steady_uptrend_does_not_signal(self):
        """A stock in a smooth uptrend will not have RSI(2) < 10 — no signal."""
        config = LiveConfig()
        spy = _make_spy_bullish()
        stock = _make_uptrend()
        scan_date = spy.index[-1]

        result = run_scan(scan_date, spy, {"SPY": spy, "TEST": stock}, config)

        assert result.is_bullish is True
        stock_signals = [s for s in result.signals if s.ticker == "TEST"]
        assert stock_signals == []

    def test_oversold_stock_triggers_signal(self):
        """A stock that drops sharply at the end should trigger an RSI(2) signal."""
        config = LiveConfig()
        spy = _make_spy_bullish()
        stock = _make_oversold_stock()
        scan_date = spy.index[-1]

        result = run_scan(scan_date, spy, {"SPY": spy, "OVER": stock}, config)

        assert result.is_bullish is True
        signals = [s for s in result.signals if s.ticker == "OVER"]
        assert len(signals) == 1
        assert signals[0].rsi_2 < 10

    def test_signals_sorted_by_rsi_ascending(self):
        """Signals must be sorted by RSI(2) ascending (most oversold first)."""
        signals = [
            Signal("A", 50.0, rsi_2=8.5, sma_200=45.0, atr=1.0, stop_loss=47.5, pct_above_sma200=11.0),
            Signal("B", 60.0, rsi_2=3.2, sma_200=55.0, atr=1.2, stop_loss=57.0, pct_above_sma200=9.0),
            Signal("C", 70.0, rsi_2=6.1, sma_200=65.0, atr=1.5, stop_loss=66.3, pct_above_sma200=7.5),
        ]
        signals.sort(key=lambda s: s.rsi_2)

        assert signals[0].ticker == "B"   # RSI 3.2 — most oversold
        assert signals[1].ticker == "C"   # RSI 6.1
        assert signals[2].ticker == "A"   # RSI 8.5

    def test_tickers_scanned_count(self):
        """tickers_scanned should reflect the number of non-supplemental tickers passed in."""
        config = LiveConfig()
        spy = _make_spy_bullish()
        stocks = {f"TICK{i}": _make_uptrend(base=50.0 + i * 5, seed=i) for i in range(5)}
        scan_date = spy.index[-1]

        result = run_scan(scan_date, spy, {"SPY": spy, **stocks}, config)

        assert result.tickers_scanned == 5


class TestConfiguration:
    def test_spy_rsi_threshold_is_15(self):
        """SPY entry threshold should be 15, not the default 10."""
        config = LiveConfig()
        assert config.RSI_ENTRY_OVERRIDES.get("SPY") == 15

    def test_default_rsi_threshold_is_10(self):
        """Default RSI entry threshold for S&P 500 stocks should be 10."""
        config = LiveConfig()
        assert config.RSI_ENTRY_THRESHOLD == 10

    def test_stop_loss_formula(self):
        """Stop loss = close - (STOP_ATR_MULTIPLE × ATR)."""
        config = LiveConfig()
        close, atr = 100.0, 2.0
        expected_stop = close - config.STOP_ATR_MULTIPLE * atr    # 100 - 2.5*2 = 95.0
        signal = Signal(
            ticker="TEST", close=close, rsi_2=5.0, sma_200=90.0,
            atr=atr, stop_loss=round(close - config.STOP_ATR_MULTIPLE * atr, 2),
            pct_above_sma200=11.1,
        )
        assert abs(signal.stop_loss - expected_stop) < 0.01

    def test_spy_is_supplemental(self):
        """SPY should be in SUPPLEMENTAL_TICKERS and bypass universe ranking."""
        config = LiveConfig()
        assert "SPY" in config.SUPPLEMENTAL_TICKERS
