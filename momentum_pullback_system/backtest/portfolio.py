from __future__ import annotations

"""Portfolio tracker for backtesting.

Manages cash, open positions, daily equity snapshots, and handles
trade execution with slippage and commissions.
"""

from dataclasses import dataclass, field

import pandas as pd

from momentum_pullback_system.config import Config
from momentum_pullback_system.backtest.trade_log import TradeLog, TradeRecord
from momentum_pullback_system.pipeline.risk_manager import (
    Position,
    TradeSetup,
    ExitSignal,
)


@dataclass
class DailySnapshot:
    """Portfolio state at end of day."""

    date: pd.Timestamp
    cash: float
    positions_value: float
    account_value: float
    num_positions: int
    regime_bullish: bool


class Portfolio:
    """Tracks portfolio state throughout a backtest simulation.

    Parameters
    ----------
    initial_capital : float
        Starting cash balance.
    config : Config
        Strategy configuration for slippage and commissions.
    """

    def __init__(self, initial_capital: float, config: Config = Config) -> None:
        self.cash = initial_capital
        self.initial_capital = initial_capital
        self.config = config
        self.positions: list[Position] = []
        self.trade_log = TradeLog()
        self.daily_snapshots: list[DailySnapshot] = []
        self._open_tickers: set[str] = set()

    @property
    def account_value(self) -> float:
        """Current total account value (cash + positions at last known price)."""
        return self.cash + self._positions_market_value

    @property
    def _positions_market_value(self) -> float:
        """Sum of all open positions valued at their entry price.

        Note: updated to mark-to-market during daily snapshot.
        """
        return sum(p.entry_price * p.shares for p in self.positions)

    def has_position(self, ticker: str) -> bool:
        """Check if a position is already open for a ticker."""
        return ticker in self._open_tickers

    def execute_entry(self, setup: TradeSetup, date: pd.Timestamp, sector: str) -> bool:
        """Open a new position based on a trade setup.

        Applies slippage to the entry price and deducts the cost from cash.

        Parameters
        ----------
        setup : TradeSetup
            The calculated trade parameters.
        date : pd.Timestamp
            The entry date.
        sector : str
            GICS sector for the stock.

        Returns
        -------
        bool
            True if the entry was executed, False if insufficient cash.
        """
        # Apply slippage: assume we pay slightly more than the open
        slippage_per_share = setup.entry_price * (self.config.SLIPPAGE_PCT / 100)
        actual_entry = setup.entry_price + slippage_per_share

        shares = setup.shares
        total_cost = actual_entry * shares + self.config.COMMISSION_PER_TRADE

        # If position exceeds available cash, reduce shares to fit
        if total_cost > self.cash:
            shares = int((self.cash - self.config.COMMISSION_PER_TRADE) / actual_entry)
            if shares <= 0:
                return False
            total_cost = actual_entry * shares + self.config.COMMISSION_PER_TRADE

        self.cash -= total_cost

        position = Position(
            ticker=setup.ticker,
            sector=sector,
            entry_price=actual_entry,
            entry_date=date,
            shares=shares,
            stop_loss=setup.stop_loss,
            atr=setup.atr,
        )
        self.positions.append(position)
        self._open_tickers.add(setup.ticker)
        return True

    def execute_exit(self, position: Position, exit_signal: ExitSignal, date: pd.Timestamp) -> None:
        """Close a position and record the trade.

        Parameters
        ----------
        position : Position
            The position to close.
        exit_signal : ExitSignal
            Contains exit reason and price.
        date : pd.Timestamp
            The exit date.
        """
        # Apply slippage: assume we receive slightly less than the exit price
        slippage_per_share = exit_signal.exit_price * (self.config.SLIPPAGE_PCT / 100)
        actual_exit = exit_signal.exit_price - slippage_per_share

        proceeds = actual_exit * position.shares - self.config.COMMISSION_PER_TRADE
        self.cash += proceeds

        slippage_entry = position.entry_price * (self.config.SLIPPAGE_PCT / 100) * position.shares
        slippage_exit = slippage_per_share * position.shares

        trade = TradeRecord(
            ticker=position.ticker,
            sector=position.sector,
            entry_date=position.entry_date,
            exit_date=date,
            entry_price=position.entry_price,
            exit_price=actual_exit,
            shares=position.shares,
            stop_loss=position.stop_loss,
            atr_at_entry=position.atr,
            exit_reason=exit_signal.reason,
            slippage_entry=slippage_entry,
            slippage_exit=slippage_exit,
            commission=self.config.COMMISSION_PER_TRADE * 2,  # entry + exit
        )
        self.trade_log.add(trade)

        self.positions.remove(position)
        self._open_tickers.discard(position.ticker)

    def take_snapshot(
        self,
        date: pd.Timestamp,
        all_ohlcv: dict[str, pd.DataFrame],
        regime_bullish: bool,
    ) -> None:
        """Record end-of-day portfolio state using mark-to-market prices.

        Parameters
        ----------
        date : pd.Timestamp
            Current date.
        all_ohlcv : dict[str, pd.DataFrame]
            All OHLCV data for mark-to-market pricing.
        regime_bullish : bool
            Current market regime state.
        """
        positions_value = 0.0
        for pos in self.positions:
            if pos.ticker in all_ohlcv and date in all_ohlcv[pos.ticker].index:
                close = all_ohlcv[pos.ticker].loc[date, "Close"]
                positions_value += close * pos.shares
            else:
                positions_value += pos.entry_price * pos.shares

        snapshot = DailySnapshot(
            date=date,
            cash=self.cash,
            positions_value=positions_value,
            account_value=self.cash + positions_value,
            num_positions=len(self.positions),
            regime_bullish=regime_bullish,
        )
        self.daily_snapshots.append(snapshot)

    def get_equity_curve(self) -> pd.DataFrame:
        """Convert daily snapshots to a DataFrame.

        Returns
        -------
        pd.DataFrame
            Indexed by date with columns: Cash, Positions_Value, Account_Value,
            Num_Positions, Regime_Bullish.
        """
        if not self.daily_snapshots:
            return pd.DataFrame()
        records = []
        for s in self.daily_snapshots:
            records.append({
                "Date": s.date,
                "Cash": s.cash,
                "Positions_Value": s.positions_value,
                "Account_Value": s.account_value,
                "Num_Positions": s.num_positions,
                "Regime_Bullish": s.regime_bullish,
            })
        df = pd.DataFrame(records).set_index("Date")
        return df
