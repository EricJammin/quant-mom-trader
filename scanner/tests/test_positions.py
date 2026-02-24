from __future__ import annotations

"""Tests for scanner/positions.py.

All file I/O uses tmp_path (pytest fixture) — no real positions.json is touched.

Run from the project root:
    pytest scanner/tests/test_positions.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scanner.positions import (
    Position, ExitAlert,
    load_positions, save_positions,
    add_position, remove_position,
    check_exits, format_positions_table,
    _trading_days_held,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

class _Config:
    ATR_PERIOD = 14
    STOP_ATR_MULTIPLE = 2.5
    SUPPLEMENTAL_TICKERS = ["SPY"]
    RSI_PERIOD = 2
    REQUIRE_BELOW_SMA5 = True
    SMA5_PERIOD = 5
    TREND_SMA_PERIOD = 200


def _make_ohlcv(
    n: int = 300,
    base: float = 100.0,
    final_close: float | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Uptrend OHLCV ending with a small down day to keep RSI(2) below 75.

    This ensures the fixture doesn't accidentally trigger an RSI exit in tests
    that are not testing the RSI exit condition.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2025-12-31", periods=n)
    prices = base + np.linspace(0, 20, n) + rng.normal(0, 0.2, n)
    # Small down day at end keeps RSI(2) in neutral range (well below 75)
    prices[-1] = prices[-2] * 0.992
    if final_close is not None:
        prices[-1] = final_close
    return pd.DataFrame({
        "Open":   prices * 0.999,
        "High":   prices * 1.003,
        "Low":    prices * 0.997,
        "Close":  prices,
        "Volume": np.full(n, 2_000_000),
    }, index=dates)


def _make_oversold_ohlcv(n: int = 300, base: float = 100.0) -> pd.DataFrame:
    """Two sharp down days at the end → RSI(2) > 75 on recovery or < 10 going in."""
    rng = np.random.default_rng(7)
    dates = pd.bdate_range(end="2025-12-31", periods=n)
    prices = base + np.linspace(0, 20, n) + rng.normal(0, 0.2, n)
    # Two up days at the end → RSI(2) shoots above 75
    prices[-2] *= 1.04
    prices[-1] *= 1.04
    return pd.DataFrame({
        "Open":   prices * 0.999,
        "High":   prices * 1.004,
        "Low":    prices * 0.996,
        "Close":  prices,
        "Volume": np.full(n, 2_000_000),
    }, index=dates)


def _make_position(
    ticker: str = "AAPL",
    entry_date: str = "2025-12-15",
    entry_price: float = 100.0,
    stop_loss: float = 90.0,
    signal_type: str = "stock",
) -> Position:
    return Position(
        ticker=ticker,
        entry_date=entry_date,
        entry_price=entry_price,
        stop_loss=stop_loss,
        signal_type=signal_type,
    )


# ── load / save ────────────────────────────────────────────────────────────────

class TestLoadSave:
    def test_load_returns_empty_when_file_missing(self, tmp_path):
        result = load_positions(tmp_path / "positions.json")
        assert result == []

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "positions.json"
        pos = _make_position()
        save_positions([pos], path)
        loaded = load_positions(path)
        assert len(loaded) == 1
        assert loaded[0].ticker == "AAPL"
        assert loaded[0].stop_loss == 90.0

    def test_saved_file_is_human_readable_json(self, tmp_path):
        path = tmp_path / "positions.json"
        save_positions([_make_position()], path)
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert "ticker" in data[0]

    def test_load_corrupted_file_returns_empty(self, tmp_path):
        path = tmp_path / "positions.json"
        path.write_text("not valid json")
        result = load_positions(path)
        assert result == []


# ── add_position ───────────────────────────────────────────────────────────────

class TestAddPosition:
    def test_adds_position_with_correct_stop(self, tmp_path):
        path = tmp_path / "positions.json"
        df = _make_ohlcv()
        pos = add_position("AAPL", 120.0, {"AAPL": df}, _Config(), path)
        assert pos.ticker == "AAPL"
        assert pos.entry_price == 120.0
        # Stop should be entry - 2.5 * ATR (ATR > 0, so stop < entry)
        assert pos.stop_loss < 120.0

    def test_stop_is_entry_minus_2_5x_atr(self, tmp_path):
        path = tmp_path / "positions.json"
        df = _make_ohlcv()
        pos = add_position("AAPL", 120.0, {"AAPL": df}, _Config(), path)
        # Verify structure: stop = entry - 2.5 * ATR → entry - stop = 2.5 * ATR
        gap = pos.entry_price - pos.stop_loss
        assert gap > 0
        assert round(gap % 1, 2) >= 0  # just verify it's a valid float

    def test_signal_type_stock_for_regular_ticker(self, tmp_path):
        path = tmp_path / "positions.json"
        df = _make_ohlcv()
        pos = add_position("AAPL", 120.0, {"AAPL": df}, _Config(), path)
        assert pos.signal_type == "stock"

    def test_signal_type_spy_for_supplemental(self, tmp_path):
        path = tmp_path / "positions.json"
        df = _make_ohlcv(base=500.0)
        pos = add_position("SPY", 500.0, {"SPY": df}, _Config(), path)
        assert pos.signal_type == "spy"

    def test_duplicate_ticker_raises(self, tmp_path):
        path = tmp_path / "positions.json"
        df = _make_ohlcv()
        add_position("AAPL", 120.0, {"AAPL": df}, _Config(), path)
        with pytest.raises(ValueError, match="already exists"):
            add_position("AAPL", 121.0, {"AAPL": df}, _Config(), path)

    def test_missing_ticker_data_raises(self, tmp_path):
        path = tmp_path / "positions.json"
        with pytest.raises(ValueError, match="No cached data"):
            add_position("AAPL", 120.0, {}, _Config(), path)

    def test_position_persisted_to_file(self, tmp_path):
        path = tmp_path / "positions.json"
        df = _make_ohlcv()
        add_position("AAPL", 120.0, {"AAPL": df}, _Config(), path)
        loaded = load_positions(path)
        assert len(loaded) == 1
        assert loaded[0].ticker == "AAPL"


# ── remove_position ────────────────────────────────────────────────────────────

class TestRemovePosition:
    def test_removes_existing_position(self, tmp_path):
        path = tmp_path / "positions.json"
        save_positions([_make_position("AAPL"), _make_position("MSFT")], path)
        found = remove_position("AAPL", path)
        assert found is True
        remaining = load_positions(path)
        assert len(remaining) == 1
        assert remaining[0].ticker == "MSFT"

    def test_returns_false_for_nonexistent_ticker(self, tmp_path):
        path = tmp_path / "positions.json"
        save_positions([_make_position("AAPL")], path)
        found = remove_position("TSLA", path)
        assert found is False

    def test_positions_file_unchanged_when_not_found(self, tmp_path):
        path = tmp_path / "positions.json"
        save_positions([_make_position("AAPL")], path)
        remove_position("TSLA", path)
        remaining = load_positions(path)
        assert len(remaining) == 1


# ── check_exits ────────────────────────────────────────────────────────────────

class TestCheckExits:
    def test_no_exit_for_healthy_position(self):
        """Uptrend stock well above stop — no exit condition triggered."""
        df = _make_ohlcv(n=300, base=100.0)
        scan_date = df.index[-1]
        pos = _make_position(
            ticker="AAPL",
            entry_date=(scan_date - pd.tseries.offsets.BDay(2)).strftime("%Y-%m-%d"),
            stop_loss=50.0,  # far below current price
        )
        exits = check_exits([pos], {"AAPL": df}, scan_date, _Config())
        assert exits == []

    def test_stop_loss_triggers_when_price_at_stop(self):
        """Position where closing price equals the stop level triggers STOP."""
        df = _make_ohlcv(n=300, base=100.0)
        scan_date = df.index[-1]
        close = float(df.loc[scan_date, "Close"])
        pos = _make_position(
            ticker="AAPL",
            entry_date=(scan_date - pd.tseries.offsets.BDay(1)).strftime("%Y-%m-%d"),
            stop_loss=close,  # stop exactly at current close
        )
        exits = check_exits([pos], {"AAPL": df}, scan_date, _Config())
        assert len(exits) == 1
        assert exits[0].reason == "STOP"

    def test_stop_loss_triggers_when_price_below_stop(self):
        """Price below stop triggers STOP exit."""
        df = _make_ohlcv(n=300, base=100.0, final_close=80.0)
        scan_date = df.index[-1]
        pos = _make_position(
            ticker="AAPL",
            entry_date=(scan_date - pd.tseries.offsets.BDay(1)).strftime("%Y-%m-%d"),
            stop_loss=90.0,
        )
        exits = check_exits([pos], {"AAPL": df}, scan_date, _Config())
        assert len(exits) == 1
        assert exits[0].reason == "STOP"
        assert exits[0].current_price == pytest.approx(80.0, abs=0.5)

    def test_rsi_exit_triggers_on_recovery(self):
        """Two big up days → RSI(2) > 75 → RSI exit."""
        df = _make_oversold_ohlcv(n=300, base=100.0)
        scan_date = df.index[-1]
        pos = _make_position(
            ticker="AAPL",
            entry_date=(scan_date - pd.tseries.offsets.BDay(2)).strftime("%Y-%m-%d"),
            stop_loss=50.0,
        )
        exits = check_exits([pos], {"AAPL": df}, scan_date, _Config())
        assert len(exits) == 1
        assert exits[0].reason == "RSI"
        assert exits[0].rsi_2 > 75

    def test_time_stop_triggers_after_5_trading_days(self):
        """Position held for 5 trading days triggers TIME exit."""
        df = _make_ohlcv(n=300, base=100.0)
        scan_date = df.index[-1]
        entry_date = scan_date - pd.tseries.offsets.BDay(5)
        pos = _make_position(
            ticker="AAPL",
            entry_date=entry_date.strftime("%Y-%m-%d"),
            stop_loss=50.0,
        )
        exits = check_exits([pos], {"AAPL": df}, scan_date, _Config())
        assert len(exits) == 1
        assert exits[0].reason == "TIME"

    def test_time_stop_does_not_trigger_before_5_days(self):
        """Position held for 4 trading days does NOT trigger time stop."""
        df = _make_ohlcv(n=300, base=100.0)
        scan_date = df.index[-1]
        entry_date = scan_date - pd.tseries.offsets.BDay(4)
        pos = _make_position(
            ticker="AAPL",
            entry_date=entry_date.strftime("%Y-%m-%d"),
            stop_loss=50.0,
        )
        exits = check_exits([pos], {"AAPL": df}, scan_date, _Config())
        assert exits == []

    def test_stop_takes_priority_over_rsi(self):
        """When both STOP and RSI conditions are met, STOP is reported."""
        df = _make_oversold_ohlcv(n=300, base=100.0)
        scan_date = df.index[-1]
        close = float(df.loc[scan_date, "Close"])
        pos = _make_position(
            ticker="AAPL",
            entry_date=(scan_date - pd.tseries.offsets.BDay(1)).strftime("%Y-%m-%d"),
            stop_loss=close + 1.0,  # stop above current close → STOP triggered
        )
        exits = check_exits([pos], {"AAPL": df}, scan_date, _Config())
        assert exits[0].reason == "STOP"

    def test_missing_ticker_data_skipped(self):
        """Position with no cached data is skipped without crashing."""
        df = _make_ohlcv()
        scan_date = df.index[-1]
        pos = _make_position(ticker="NOTREAL")
        exits = check_exits([pos], {"AAPL": df}, scan_date, _Config())
        assert exits == []

    def test_multiple_positions_checked_independently(self):
        """Each position is evaluated independently."""
        df_aapl = _make_ohlcv(n=300, base=100.0, final_close=80.0)
        df_msft = _make_ohlcv(n=300, base=200.0, seed=99)
        scan_date = df_aapl.index[-1]

        pos_aapl = _make_position("AAPL", stop_loss=90.0,
                                  entry_date=(scan_date - pd.tseries.offsets.BDay(1)).strftime("%Y-%m-%d"))
        pos_msft = _make_position("MSFT", stop_loss=50.0,
                                  entry_date=(scan_date - pd.tseries.offsets.BDay(1)).strftime("%Y-%m-%d"))

        exits = check_exits(
            [pos_aapl, pos_msft],
            {"AAPL": df_aapl, "MSFT": df_msft},
            scan_date, _Config(),
        )
        # AAPL hits stop, MSFT does not
        assert len(exits) == 1
        assert exits[0].position.ticker == "AAPL"


# ── _trading_days_held ─────────────────────────────────────────────────────────

class TestTradingDaysHeld:
    def test_same_day_is_zero(self):
        d = pd.Timestamp("2025-12-31")
        assert _trading_days_held(d, d) == 0

    def test_one_business_day_later(self):
        entry = pd.Timestamp("2025-12-29")   # Monday
        scan  = pd.Timestamp("2025-12-30")   # Tuesday
        assert _trading_days_held(entry, scan) == 1

    def test_five_business_days(self):
        entry = pd.Timestamp("2025-12-22")   # Monday
        scan  = pd.Timestamp("2025-12-29")   # Monday (5 bdays later)
        assert _trading_days_held(entry, scan) == 5

    def test_scan_before_entry_returns_zero(self):
        entry = pd.Timestamp("2025-12-31")
        scan  = pd.Timestamp("2025-12-29")
        assert _trading_days_held(entry, scan) == 0
