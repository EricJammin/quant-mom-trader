from __future__ import annotations

"""Position tracking for the live scanner.

Open positions are stored in scanner/positions.json — plain JSON, human-readable
and manually editable. The file is gitignored (local only).

Each daily scan checks all open positions for three exit conditions:
  - RSI(2) > 75     (mean-reversion target hit)
  - Price ≤ stop    (stop loss breach)
  - 5 trading days  (time stop)

Use the CLI commands in daily_scan.py to add/remove positions:
  python3 -m scanner.daily_scan --add-position TSLA 401.50
  python3 -m scanner.daily_scan --remove-position TSLA
  python3 -m scanner.daily_scan --list-positions
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from momentum_pullback_system.pipeline.entry_trigger import compute_indicators
from momentum_pullback_system.pipeline.risk_manager import compute_atr

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("scanner/positions.json")
_RSI_EXIT_THRESHOLD = 75
_TIME_STOP_DAYS = 5


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class Position:
    """An open trade position."""
    ticker: str
    entry_date: str       # YYYY-MM-DD (signal day)
    entry_price: float
    stop_loss: float
    signal_type: str      # "stock" or "spy"


@dataclass
class ExitAlert:
    """An exit condition that triggered for an open position."""
    position: Position
    reason: str           # "RSI", "STOP", or "TIME"
    current_price: float
    rsi_2: float
    days_held: int


# ── File I/O ───────────────────────────────────────────────────────────────────

def load_positions(path: Path = _DEFAULT_PATH) -> list[Position]:
    """Load open positions from JSON. Returns empty list if file doesn't exist.

    Parameters
    ----------
    path : Path
        Path to positions.json.

    Returns
    -------
    list[Position]
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [Position(**p) for p in data]
    except Exception as e:
        logger.error(f"Failed to load positions from {path}: {e}")
        return []


def save_positions(positions: list[Position], path: Path = _DEFAULT_PATH) -> None:
    """Save positions to JSON.

    Parameters
    ----------
    positions : list[Position]
    path : Path
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(p) for p in positions], indent=2))


# ── Position management ────────────────────────────────────────────────────────

def add_position(
    ticker: str,
    entry_price: float,
    all_ohlcv: dict[str, pd.DataFrame],
    config,
    path: Path = _DEFAULT_PATH,
) -> Position:
    """Add a new position. Stop loss is computed from cached ATR on the signal day.

    Parameters
    ----------
    ticker : str
        Ticker symbol (e.g. 'TSLA').
    entry_price : float
        Actual fill price.
    all_ohlcv : dict[str, pd.DataFrame]
        Loaded OHLCV data. Must include the ticker.
    config : LiveConfig
    path : Path

    Returns
    -------
    Position
        The newly created and saved position.

    Raises
    ------
    ValueError
        If the position already exists, or the ticker has no cached data.
    """
    positions = load_positions(path)

    if any(p.ticker == ticker for p in positions):
        raise ValueError(
            f"Position for {ticker} already exists. Remove it first with --remove-position."
        )

    if ticker not in all_ohlcv:
        raise ValueError(
            f"No cached data for {ticker}. Run with --refresh or download data first."
        )

    df = all_ohlcv[ticker]
    signal_date = df.index[-1]
    atr = compute_atr(df, signal_date, config)

    if atr is None:
        raise ValueError(
            f"Could not compute ATR for {ticker}. "
            f"Need at least {config.ATR_PERIOD} days of data in cache."
        )

    stop_loss = round(entry_price - config.STOP_ATR_MULTIPLE * atr, 2)
    signal_type = "spy" if ticker in config.SUPPLEMENTAL_TICKERS else "stock"

    pos = Position(
        ticker=ticker,
        entry_date=signal_date.strftime("%Y-%m-%d"),
        entry_price=entry_price,
        stop_loss=stop_loss,
        signal_type=signal_type,
    )
    positions.append(pos)
    save_positions(positions, path)
    logger.info(
        f"Position added: {ticker} @ ${entry_price:.2f} | "
        f"stop: ${stop_loss:.2f} | entry date: {pos.entry_date}"
    )
    return pos


def remove_position(ticker: str, path: Path = _DEFAULT_PATH) -> bool:
    """Remove a position by ticker.

    Parameters
    ----------
    ticker : str
    path : Path

    Returns
    -------
    bool
        True if the position was found and removed, False if not found.
    """
    positions = load_positions(path)
    updated = [p for p in positions if p.ticker != ticker]
    if len(updated) == len(positions):
        logger.warning(f"No open position found for {ticker}.")
        return False
    save_positions(updated, path)
    logger.info(f"Position removed: {ticker}")
    return True


# ── Exit checking ──────────────────────────────────────────────────────────────

def check_exits(
    positions: list[Position],
    all_ohlcv: dict[str, pd.DataFrame],
    scan_date: pd.Timestamp,
    config,
) -> list[ExitAlert]:
    """Check all open positions for exit conditions.

    Exit priority per position: STOP > RSI > TIME. At most one alert per position.
    Exit checking runs regardless of market regime — existing positions must always
    be monitored even when the regime turns bearish.

    Parameters
    ----------
    positions : list[Position]
    all_ohlcv : dict[str, pd.DataFrame]
    scan_date : pd.Timestamp
    config : LiveConfig

    Returns
    -------
    list[ExitAlert]
        Positions that should be exited. Empty if no exits triggered.
    """
    exits = []

    for pos in positions:
        ticker = pos.ticker

        if ticker not in all_ohlcv:
            logger.warning(f"No data for position {ticker} — skipping exit check.")
            continue

        df = all_ohlcv[ticker]
        if scan_date not in df.index:
            logger.warning(f"{scan_date.date()} not in {ticker} data — skipping exit check.")
            continue

        df_ind = compute_indicators(df, config)
        row = df_ind.loc[scan_date]
        current_price = float(row["Close"])
        rsi = float(row["RSI_2"])

        entry_date = pd.Timestamp(pos.entry_date)
        days_held = _trading_days_held(entry_date, scan_date)
        time_stop_date = entry_date + pd.tseries.offsets.BDay(_TIME_STOP_DAYS)

        reason: str | None = None
        if current_price <= pos.stop_loss:
            reason = "STOP"
        elif rsi > _RSI_EXIT_THRESHOLD:
            reason = "RSI"
        elif scan_date >= time_stop_date:
            reason = "TIME"

        if reason:
            exits.append(ExitAlert(
                position=pos,
                reason=reason,
                current_price=current_price,
                rsi_2=rsi,
                days_held=days_held,
            ))

    return exits


# ── Display ────────────────────────────────────────────────────────────────────

def format_positions_table(
    positions: list[Position],
    all_ohlcv: dict[str, pd.DataFrame],
    scan_date: pd.Timestamp,
) -> str:
    """Return a console-friendly positions table with current price and P&L.

    Parameters
    ----------
    positions : list[Position]
    all_ohlcv : dict[str, pd.DataFrame]
    scan_date : pd.Timestamp

    Returns
    -------
    str
    """
    if not positions:
        return "No open positions."

    lines = [
        f"\n{'Ticker':<8} {'Entry':>8} {'Current':>9} {'P&L%':>7} "
        f"{'Stop':>8} {'Days':>5} {'Type'}",
        "-" * 58,
    ]

    for pos in positions:
        entry_date = pd.Timestamp(pos.entry_date)
        days_held = _trading_days_held(entry_date, scan_date)

        current_price = _latest_price(pos.ticker, all_ohlcv, scan_date)
        if current_price is not None:
            pnl_pct = (current_price - pos.entry_price) / pos.entry_price * 100
            current_str = f"${current_price:.2f}"
            pnl_str = f"{pnl_pct:+.1f}%"
        else:
            current_str = "N/A"
            pnl_str = "N/A"

        lines.append(
            f"{pos.ticker:<8} ${pos.entry_price:>7.2f} {current_str:>9} {pnl_str:>7} "
            f"${pos.stop_loss:>7.2f} {days_held:>5} {pos.signal_type}"
        )

    return "\n".join(lines) + "\n"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _trading_days_held(entry_date: pd.Timestamp, scan_date: pd.Timestamp) -> int:
    """Return the number of trading days elapsed since entry (entry day not counted)."""
    if scan_date < entry_date:
        return 0
    return len(pd.bdate_range(entry_date, scan_date)) - 1


def _latest_price(
    ticker: str,
    all_ohlcv: dict[str, pd.DataFrame],
    scan_date: pd.Timestamp,
) -> float | None:
    """Return the closing price for a ticker on scan_date, or the most recent available."""
    if ticker not in all_ohlcv or all_ohlcv[ticker].empty:
        return None
    df = all_ohlcv[ticker]
    if scan_date in df.index:
        return float(df.loc[scan_date, "Close"])
    return float(df.iloc[-1]["Close"])
