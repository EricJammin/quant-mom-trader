"""Tests for pipeline/risk_manager.py (RSI2 strategy — no profit target, no trailing stop)."""

import pandas as pd
import pytest

from momentum_pullback_system.config import Config
from momentum_pullback_system.pipeline.risk_manager import (
    calculate_trade_setup,
    check_exit_conditions,
    can_open_position,
    Position,
)


class TestCalculateTradeSetup:
    def test_basic_setup(self) -> None:
        setup = calculate_trade_setup("AAPL", entry_price=150.0, atr=3.0, account_value=100_000)
        assert setup is not None
        assert setup.stop_loss == 150.0 - (2.5 * 3.0)  # 142.5
        assert setup.shares == int(1000 / 7.5)  # 133 shares
        assert setup.risk_dollars == 1000.0

    def test_no_profit_target_field(self) -> None:
        setup = calculate_trade_setup("AAPL", entry_price=150.0, atr=3.0, account_value=100_000)
        assert setup is not None
        assert not hasattr(setup, "profit_target")

    def test_skips_when_stop_too_wide(self) -> None:
        # ATR=10 on a $100 stock → stop at $75 → 25% stop distance > 5% max
        setup = calculate_trade_setup("XYZ", entry_price=100.0, atr=10.0, account_value=100_000)
        assert setup is None

    def test_respects_max_stop_percent(self) -> None:
        # ATR=1.9 on a $100 stock → stop at $95.25 → 4.75% < 5% → should pass
        setup = calculate_trade_setup("ABC", entry_price=100.0, atr=1.9, account_value=100_000)
        assert setup is not None

        # ATR=2.1 on a $100 stock → stop at $94.75 → 5.25% > 5% → should skip
        setup = calculate_trade_setup("ABC", entry_price=100.0, atr=2.1, account_value=100_000)
        assert setup is None


class TestCheckExitConditions:
    def _make_position(self) -> Position:
        return Position(
            ticker="AAPL",
            sector="Technology",
            entry_price=100.0,
            entry_date=pd.Timestamp("2023-06-01"),
            shares=100,
            stop_loss=92.5,  # entry - 2.5*ATR (ATR=3)
            atr=3.0,
        )

    def test_stop_loss_exit(self) -> None:
        pos = self._make_position()
        today = pd.Series({"Open": 95.0, "High": 96.0, "Low": 91.0, "Close": 93.5, "Volume": 1e6})
        signal = check_exit_conditions(pos, today, pd.Timestamp("2023-06-05"))
        assert signal is not None
        assert signal.reason == "stop_loss"
        assert signal.exit_price == 92.5

    def test_rsi_exit(self) -> None:
        pos = self._make_position()
        today = pd.Series({"Open": 103.0, "High": 104.0, "Low": 102.0, "Close": 103.5, "Volume": 1e6})
        signal = check_exit_conditions(pos, today, pd.Timestamp("2023-06-05"), rsi_value=80.0)
        assert signal is not None
        assert signal.reason == "rsi_exit"
        assert signal.exit_price == 103.5  # exits at close

    def test_stop_takes_priority_over_rsi_exit(self) -> None:
        pos = self._make_position()
        # Low breaches stop, but RSI also above threshold
        today = pd.Series({"Open": 95.0, "High": 96.0, "Low": 90.0, "Close": 95.0, "Volume": 1e6})
        signal = check_exit_conditions(pos, today, pd.Timestamp("2023-06-05"), rsi_value=80.0)
        assert signal is not None
        assert signal.reason == "stop_loss"

    def test_time_stop_exit(self) -> None:
        pos = self._make_position()
        today = pd.Series({"Open": 101.0, "High": 102.0, "Low": 100.0, "Close": 101.0, "Volume": 1e6})
        # 5+ business days after June 1 (TIME_STOP_DAYS=5)
        signal = check_exit_conditions(pos, today, pd.Timestamp("2023-06-08"))
        assert signal is not None
        assert signal.reason == "time_stop"
        assert signal.exit_price == 101.0

    def test_no_exit_when_within_range_and_rsi_low(self) -> None:
        pos = self._make_position()
        today = pd.Series({"Open": 101.0, "High": 102.0, "Low": 99.0, "Close": 101.0, "Volume": 1e6})
        signal = check_exit_conditions(pos, today, pd.Timestamp("2023-06-05"), rsi_value=40.0)
        assert signal is None

    def test_no_exit_when_rsi_none(self) -> None:
        pos = self._make_position()
        today = pd.Series({"Open": 101.0, "High": 102.0, "Low": 99.0, "Close": 101.0, "Volume": 1e6})
        signal = check_exit_conditions(pos, today, pd.Timestamp("2023-06-05"), rsi_value=None)
        assert signal is None


class TestCanOpenPosition:
    def test_allows_when_under_limits(self) -> None:
        assert can_open_position([], "Technology") is True

    def test_blocks_at_max_positions(self) -> None:
        positions = [
            Position("A", "Tech", 100, pd.Timestamp("2023-01-01"), 10, 95, 3),
            Position("B", "Fin", 100, pd.Timestamp("2023-01-01"), 10, 95, 3),
            Position("C", "Energy", 100, pd.Timestamp("2023-01-01"), 10, 95, 3),
            Position("D", "Health", 100, pd.Timestamp("2023-01-01"), 10, 95, 3),
            Position("E", "Util", 100, pd.Timestamp("2023-01-01"), 10, 95, 3),
        ]
        assert can_open_position(positions, "Consumer") is False

    def test_blocks_at_sector_limit(self) -> None:
        positions = [
            Position("A", "Tech", 100, pd.Timestamp("2023-01-01"), 10, 95, 3),
            Position("B", "Tech", 100, pd.Timestamp("2023-01-01"), 10, 95, 3),
        ]
        assert can_open_position(positions, "Tech") is False
        assert can_open_position(positions, "Finance") is True
