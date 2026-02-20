"""Tests for backtest engine, portfolio tracker, and trade log."""

import numpy as np
import pandas as pd
import pytest

from momentum_pullback_system.config import Config
from momentum_pullback_system.backtest.trade_log import TradeRecord, TradeLog
from momentum_pullback_system.backtest.portfolio import Portfolio
from momentum_pullback_system.pipeline.risk_manager import (
    Position,
    TradeSetup,
    ExitSignal,
)


# -- TradeRecord ---------------------------------------------------------------

class TestTradeRecord:
    def test_pnl_calculation(self) -> None:
        trade = TradeRecord(
            ticker="AAPL", sector="Tech",
            entry_date=pd.Timestamp("2023-06-01"),
            exit_date=pd.Timestamp("2023-06-08"),
            entry_price=150.0, exit_price=159.0,
            shares=100, stop_loss=142.5,
            atr_at_entry=3.0, exit_reason="rsi_exit",
        )
        assert trade.pnl == (159.0 - 150.0) * 100  # $900
        assert trade.is_winner is True
        assert trade.holding_days == 5

    def test_losing_trade(self) -> None:
        trade = TradeRecord(
            ticker="XYZ", sector="Finance",
            entry_date=pd.Timestamp("2023-06-01"),
            exit_date=pd.Timestamp("2023-06-05"),
            entry_price=100.0, exit_price=92.5,
            shares=50, stop_loss=92.5,
            atr_at_entry=3.0, exit_reason="stop_loss",
        )
        assert trade.pnl == (92.5 - 100.0) * 50  # -$375
        assert trade.is_winner is False

    def test_pnl_with_slippage_and_commission(self) -> None:
        trade = TradeRecord(
            ticker="ABC", sector="Tech",
            entry_date=pd.Timestamp("2023-06-01"),
            exit_date=pd.Timestamp("2023-06-08"),
            entry_price=100.0, exit_price=110.0,
            shares=100, stop_loss=92.5,
            atr_at_entry=3.0, exit_reason="rsi_exit",
            slippage_entry=5.0, slippage_exit=5.0, commission=2.0,
        )
        gross = (110.0 - 100.0) * 100  # $1000
        assert trade.pnl == gross - 5.0 - 5.0 - 2.0  # $988


class TestTradeLog:
    def test_to_dataframe(self) -> None:
        log = TradeLog()
        log.add(TradeRecord(
            ticker="AAPL", sector="Tech",
            entry_date=pd.Timestamp("2023-06-01"),
            exit_date=pd.Timestamp("2023-06-08"),
            entry_price=150.0, exit_price=159.0,
            shares=100, stop_loss=142.5,
            atr_at_entry=3.0, exit_reason="rsi_exit",
        ))
        df = log.to_dataframe()
        assert len(df) == 1
        assert df.iloc[0]["Ticker"] == "AAPL"
        assert df.iloc[0]["Winner"] == True

    def test_empty_log(self) -> None:
        log = TradeLog()
        df = log.to_dataframe()
        assert df.empty


# -- Portfolio -----------------------------------------------------------------

class TestPortfolio:
    def test_execute_entry_deducts_cash(self) -> None:
        portfolio = Portfolio(100_000)
        setup = TradeSetup(
            ticker="AAPL", entry_price=150.0,
            stop_loss=142.5,
            shares=100, atr=3.0, risk_dollars=750.0,
        )
        result = portfolio.execute_entry(setup, pd.Timestamp("2023-06-01"), "Tech")
        assert result is True
        assert portfolio.cash < 100_000
        assert len(portfolio.positions) == 1
        assert portfolio.has_position("AAPL")

    def test_entry_rejected_insufficient_cash(self) -> None:
        portfolio = Portfolio(1_000)  # Not enough for 100 shares at $150
        setup = TradeSetup(
            ticker="AAPL", entry_price=150.0,
            stop_loss=142.5,
            shares=100, atr=3.0, risk_dollars=750.0,
        )
        result = portfolio.execute_entry(setup, pd.Timestamp("2023-06-01"), "Tech")
        assert result is False
        assert len(portfolio.positions) == 0

    def test_execute_exit_adds_cash_and_logs_trade(self) -> None:
        portfolio = Portfolio(100_000)
        setup = TradeSetup(
            ticker="AAPL", entry_price=150.0,
            stop_loss=142.5,
            shares=100, atr=3.0, risk_dollars=750.0,
        )
        portfolio.execute_entry(setup, pd.Timestamp("2023-06-01"), "Tech")
        cash_after_entry = portfolio.cash

        position = portfolio.positions[0]
        exit_signal = ExitSignal(ticker="AAPL", reason="rsi_exit", exit_price=159.0)
        portfolio.execute_exit(position, exit_signal, pd.Timestamp("2023-06-08"))

        assert portfolio.cash > cash_after_entry
        assert len(portfolio.positions) == 0
        assert not portfolio.has_position("AAPL")
        assert len(portfolio.trade_log.trades) == 1

    def test_snapshot_records_state(self) -> None:
        portfolio = Portfolio(100_000)
        ohlcv = pd.DataFrame(
            {"Open": [150], "High": [155], "Low": [148], "Close": [152], "Volume": [1e6]},
            index=[pd.Timestamp("2023-06-01")],
        )
        portfolio.take_snapshot(pd.Timestamp("2023-06-01"), {"AAPL": ohlcv}, True)
        assert len(portfolio.daily_snapshots) == 1
        assert portfolio.daily_snapshots[0].account_value == 100_000
        assert portfolio.daily_snapshots[0].regime_bullish is True

    def test_equity_curve(self) -> None:
        portfolio = Portfolio(100_000)
        for i in range(5):
            date = pd.Timestamp("2023-06-01") + pd.offsets.BDay(i)
            portfolio.take_snapshot(date, {}, True)
        ec = portfolio.get_equity_curve()
        assert len(ec) == 5
        assert "Account_Value" in ec.columns


# -- Engine integration (single-stock, synthetic data) -------------------------

class TestEngineIntegration:
    """Test the engine with synthetic data for a single stock."""

    def _build_synthetic_scenario(self) -> tuple:
        """Create a simple scenario: stock uptrends then has a sharp pullback.

        Returns all_ohlcv, spy_data, sector_map.
        """
        days = 300
        dates = pd.bdate_range("2020-01-01", periods=days)

        # SPY: steady uptrend (ensures bullish regime)
        spy_close = np.linspace(300, 450, days)
        spy = pd.DataFrame({
            "Open": spy_close - 1,
            "High": spy_close + 2,
            "Low": spy_close - 2,
            "Close": spy_close,
            "Volume": np.full(days, 50_000_000),
        }, index=dates)

        # TEST stock: uptrend with pullbacks
        stock_close = np.linspace(50, 120, days).copy()
        # Create a sharp 2-day pullback around day 260 to trigger RSI(2)
        stock_close[258] = stock_close[257] - 3.0
        stock_close[259] = stock_close[258] - 2.5

        stock = pd.DataFrame({
            "Open": stock_close - 0.3,
            "High": stock_close + 1.0,
            "Low": stock_close - 0.8,
            "Close": stock_close,
            "Volume": np.full(days, 2_000_000),
        }, index=dates)

        all_ohlcv = {"TEST": stock}
        sector_map = {"TEST": "Technology"}

        return all_ohlcv, spy, sector_map

    def test_engine_runs_without_error(self) -> None:
        all_ohlcv, spy, sector_map = self._build_synthetic_scenario()
        from momentum_pullback_system.backtest.engine import BacktestEngine

        engine = BacktestEngine(all_ohlcv, spy, sector_map)
        # Use dates within our synthetic data range
        start = spy.index[250].strftime("%Y-%m-%d")
        end = spy.index[-1].strftime("%Y-%m-%d")
        result = engine.run(start_date=start, end_date=end, show_progress=False)

        assert len(result.equity_curve) > 0
        assert result.equity_curve["Account_Value"].iloc[0] == pytest.approx(100_000, rel=0.01)

    def test_engine_equity_curve_has_all_days(self) -> None:
        all_ohlcv, spy, sector_map = self._build_synthetic_scenario()
        from momentum_pullback_system.backtest.engine import BacktestEngine

        engine = BacktestEngine(all_ohlcv, spy, sector_map)
        start = spy.index[250].strftime("%Y-%m-%d")
        end = spy.index[-1].strftime("%Y-%m-%d")
        result = engine.run(start_date=start, end_date=end, show_progress=False)

        expected_days = len(spy.loc[start:end])
        assert len(result.equity_curve) == expected_days
