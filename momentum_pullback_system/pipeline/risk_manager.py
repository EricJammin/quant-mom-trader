from __future__ import annotations

"""Stage 4: Risk Management (ATR-Based).

Handles position sizing, stop loss, and exit conditions for the RSI(2) mean
reversion strategy. Exits are driven by RSI recovery, stop loss, or time stop.
No profit target or trailing stop — the RSI exit handles profit-taking.
"""

from dataclasses import dataclass

import pandas as pd
from ta.volatility import AverageTrueRange

from momentum_pullback_system.config import Config


@dataclass
class TradeSetup:
    """Parameters for a new trade entry."""

    ticker: str
    entry_price: float
    stop_loss: float
    shares: int
    atr: float
    risk_dollars: float


@dataclass
class Position:
    """Tracks an open position."""

    ticker: str
    sector: str
    entry_price: float
    entry_date: pd.Timestamp
    shares: int
    stop_loss: float
    atr: float


def compute_atr(ohlcv: pd.DataFrame, date: pd.Timestamp, config: Config = Config) -> float | None:
    """Compute ATR for a stock on a given date.

    Parameters
    ----------
    ohlcv : pd.DataFrame
        OHLCV data indexed by date.
    date : pd.Timestamp
        The date to evaluate.
    config : Config
        Strategy configuration with ATR_PERIOD.

    Returns
    -------
    float | None
        ATR value, or None if insufficient data.
    """
    data = ohlcv.loc[:date]
    if len(data) < config.ATR_PERIOD + 1:
        return None
    atr_series = AverageTrueRange(
        data["High"], data["Low"], data["Close"], window=config.ATR_PERIOD
    ).average_true_range()
    val = atr_series.iloc[-1]
    return None if pd.isna(val) else float(val)


def calculate_trade_setup(
    ticker: str,
    entry_price: float,
    atr: float,
    account_value: float,
    config: Config = Config,
) -> TradeSetup | None:
    """Calculate stop and position size for a potential trade.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol.
    entry_price : float
        Expected entry price (next day's open).
    atr : float
        Current ATR-14 value.
    account_value : float
        Current total account value.
    config : Config
        Strategy configuration.

    Returns
    -------
    TradeSetup | None
        Trade parameters, or None if the trade should be skipped
        (stop distance exceeds MAX_STOP_PERCENT).
    """
    stop_loss = entry_price - (config.STOP_ATR_MULTIPLE * atr)

    stop_distance = entry_price - stop_loss
    stop_pct = (stop_distance / entry_price) * 100

    if stop_pct > config.MAX_STOP_PERCENT:
        return None

    risk_dollars = account_value * config.RISK_PER_TRADE
    if stop_distance <= 0:
        return None

    shares = int(risk_dollars / stop_distance)
    if shares <= 0:
        return None

    return TradeSetup(
        ticker=ticker,
        entry_price=entry_price,
        stop_loss=stop_loss,
        shares=shares,
        atr=atr,
        risk_dollars=risk_dollars,
    )


@dataclass
class ExitSignal:
    """Describes why a position should be closed."""

    ticker: str
    reason: str  # "stop_loss", "rsi_exit", "time_stop"
    exit_price: float


def check_exit_conditions(
    position: Position,
    today: pd.Series,
    current_date: pd.Timestamp,
    config: Config = Config,
    rsi_value: float | None = None,
) -> ExitSignal | None:
    """Check whether an open position should be exited.

    Parameters
    ----------
    position : Position
        The open position.
    today : pd.Series
        Today's OHLCV bar for the stock.
    current_date : pd.Timestamp
        Today's date.
    config : Config
        Strategy configuration.
    rsi_value : float | None
        Current RSI(2) value. If >= RSI_EXIT_THRESHOLD, triggers exit.

    Returns
    -------
    ExitSignal | None
        Exit signal if position should close, None otherwise.
    """
    low = today["Low"]

    # Stop loss takes priority
    if low <= position.stop_loss:
        return ExitSignal(
            ticker=position.ticker,
            reason="stop_loss",
            exit_price=position.stop_loss,
        )

    # RSI-based exit: RSI(2) has recovered above threshold
    if rsi_value is not None and rsi_value >= config.RSI_EXIT_THRESHOLD:
        return ExitSignal(
            ticker=position.ticker,
            reason="rsi_exit",
            exit_price=today["Close"],
        )

    # Time stop
    days_held = len(pd.bdate_range(position.entry_date, current_date)) - 1
    if days_held >= config.TIME_STOP_DAYS:
        return ExitSignal(
            ticker=position.ticker,
            reason="time_stop",
            exit_price=today["Close"],
        )

    return None


def can_open_position(
    open_positions: list[Position],
    sector: str,
    config: Config = Config,
) -> bool:
    """Check whether a new position can be opened given current exposure limits.

    Parameters
    ----------
    open_positions : list[Position]
        Currently open positions.
    sector : str
        GICS sector of the candidate stock.
    config : Config
        Strategy configuration.

    Returns
    -------
    bool
        True if a new position is allowed.
    """
    if len(open_positions) >= config.MAX_POSITIONS:
        return False

    sector_count = sum(1 for p in open_positions if p.sector == sector)
    if sector_count >= config.MAX_SECTOR_POSITIONS:
        return False

    return True
