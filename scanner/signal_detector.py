from __future__ import annotations

"""Signal detector for the live RSI(2) scanner.

Reuses existing pipeline modules from momentum_pullback_system.
Returns structured signal data ready for alert formatting.
"""

import logging
from dataclasses import dataclass, field

import pandas as pd

from momentum_pullback_system.pipeline.regime_filter import compute_regime
from momentum_pullback_system.pipeline.universe_filter import filter_universe
from momentum_pullback_system.pipeline.entry_trigger import compute_indicators, check_entry_signal
from momentum_pullback_system.pipeline.risk_manager import compute_atr

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """A single trade candidate signal."""

    ticker: str
    close: float
    rsi_2: float
    sma_200: float
    atr: float
    stop_loss: float
    pct_above_sma200: float
    is_supplemental: bool = False   # True for SPY and other supplemental tickers


@dataclass
class ScanResult:
    """Complete output from a single day's scan."""

    date: pd.Timestamp
    is_bullish: bool
    signals: list[Signal] = field(default_factory=list)
    tickers_scanned: int = 0
    tickers_passed_universe: int = 0


def run_scan(
    scan_date: pd.Timestamp,
    spy_data: pd.DataFrame,
    all_ohlcv: dict[str, pd.DataFrame],
    config,
) -> ScanResult:
    """Run the full signal detection pipeline for a single date.

    Parameters
    ----------
    scan_date : pd.Timestamp
        The date to scan (typically today's close).
    spy_data : pd.DataFrame
        SPY OHLCV data (used for regime calculation).
    all_ohlcv : dict[str, pd.DataFrame]
        All ticker OHLCV data, including supplemental tickers.
    config : LiveConfig
        Strategy configuration.

    Returns
    -------
    ScanResult
        Regime status, signals found, and scan metadata.
    """
    result = ScanResult(date=scan_date, is_bullish=False)

    # Stage 0: Regime check
    regime_series = compute_regime(spy_data, config)
    is_bullish = regime_series.get(scan_date, False)
    if pd.isna(is_bullish):
        is_bullish = False
    result.is_bullish = bool(is_bullish)

    if not result.is_bullish:
        return result

    # Stage 1: Universe filter — S&P 500 stocks only, not supplementals
    sp500_ohlcv = {
        t: df for t, df in all_ohlcv.items()
        if t not in config.SUPPLEMENTAL_TICKERS
    }
    filtered_tickers = filter_universe(sp500_ohlcv, scan_date, config)
    result.tickers_scanned = len(sp500_ohlcv)
    result.tickers_passed_universe = len(filtered_tickers)

    # Build scan list: filtered S&P 500 + supplemental tickers (e.g. SPY)
    scan_tickers: list[tuple[str, bool]] = (
        [(t, False) for t in filtered_tickers] +
        [(t, True) for t in config.SUPPLEMENTAL_TICKERS if t in all_ohlcv]
    )

    # Stage 2: Check RSI(2) entry signals
    for ticker, is_supplemental in scan_tickers:
        if ticker not in all_ohlcv or scan_date not in all_ohlcv[ticker].index:
            continue

        df_ind = compute_indicators(all_ohlcv[ticker], config)
        if not check_entry_signal(df_ind, scan_date, config, ticker=ticker):
            continue

        row = df_ind.loc[scan_date]
        atr = compute_atr(all_ohlcv[ticker], scan_date, config)
        if atr is None:
            logger.warning(f"Could not compute ATR for {ticker} on {scan_date.date()}. Skipping.")
            continue

        close = float(row["Close"])
        sma200 = float(row["SMA_200"])
        rsi = float(row["RSI_2"])
        stop = round(close - config.STOP_ATR_MULTIPLE * atr, 2)
        pct_above = (close / sma200 - 1) * 100

        result.signals.append(Signal(
            ticker=ticker,
            close=close,
            rsi_2=rsi,
            sma_200=sma200,
            atr=atr,
            stop_loss=stop,
            pct_above_sma200=pct_above,
            is_supplemental=is_supplemental,
        ))

    # Sort by RSI ascending — most oversold signal first
    result.signals.sort(key=lambda s: s.rsi_2)
    return result
