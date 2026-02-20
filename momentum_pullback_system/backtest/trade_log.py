"""Trade log for recording every completed trade with full metadata."""

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class TradeRecord:
    """A completed trade with all relevant details."""

    ticker: str
    sector: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: int
    stop_loss: float
    atr_at_entry: float
    exit_reason: str  # "stop_loss", "rsi_exit", "time_stop"
    slippage_entry: float = 0.0
    slippage_exit: float = 0.0
    commission: float = 0.0

    @property
    def pnl(self) -> float:
        """Net profit/loss after slippage and commissions."""
        gross = (self.exit_price - self.entry_price) * self.shares
        return gross - self.slippage_entry - self.slippage_exit - self.commission

    @property
    def pnl_pct(self) -> float:
        """Return as a percentage of the entry cost."""
        cost = self.entry_price * self.shares
        if cost == 0:
            return 0.0
        return (self.pnl / cost) * 100

    @property
    def holding_days(self) -> int:
        """Number of trading days the position was held."""
        return len(pd.bdate_range(self.entry_date, self.exit_date)) - 1

    @property
    def is_winner(self) -> bool:
        """Whether the trade was profitable."""
        return self.pnl > 0


class TradeLog:
    """Collects and summarizes all completed trades."""

    def __init__(self) -> None:
        self.trades: list[TradeRecord] = []

    def add(self, trade: TradeRecord) -> None:
        """Record a completed trade."""
        self.trades.append(trade)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert all trades to a DataFrame for analysis.

        Returns
        -------
        pd.DataFrame
            One row per trade with all fields plus computed P&L.
        """
        if not self.trades:
            return pd.DataFrame()
        records = []
        for t in self.trades:
            records.append({
                "Ticker": t.ticker,
                "Sector": t.sector,
                "Entry_Date": t.entry_date,
                "Exit_Date": t.exit_date,
                "Entry_Price": t.entry_price,
                "Exit_Price": t.exit_price,
                "Shares": t.shares,
                "Stop_Loss": t.stop_loss,
                "ATR": t.atr_at_entry,
                "Exit_Reason": t.exit_reason,
                "PnL": t.pnl,
                "PnL_Pct": t.pnl_pct,
                "Holding_Days": t.holding_days,
                "Winner": t.is_winner,
            })
        return pd.DataFrame(records)
