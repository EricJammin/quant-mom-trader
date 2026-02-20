from __future__ import annotations

"""Backtest engine: orchestrates the daily pipeline over historical data.

Simulates each trading day from start to end date, running all pipeline
stages and managing entries/exits through the portfolio tracker.
"""

import logging
from dataclasses import dataclass

import pandas as pd
from tqdm import tqdm

from momentum_pullback_system.config import Config
from momentum_pullback_system.backtest.portfolio import Portfolio
from momentum_pullback_system.pipeline.regime_filter import compute_regime
from momentum_pullback_system.pipeline.universe_filter import filter_universe
from momentum_pullback_system.pipeline.momentum_rank import rank_stocks
from momentum_pullback_system.pipeline.entry_trigger import compute_indicators, check_entry_signal
from momentum_pullback_system.pipeline.risk_manager import (
    compute_atr,
    calculate_trade_setup,
    check_exit_conditions,
    can_open_position,
    ExitSignal,
)

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Container for all backtest outputs."""

    portfolio: Portfolio
    equity_curve: pd.DataFrame
    trade_log: pd.DataFrame
    regime_series: pd.Series


class BacktestEngine:
    """Day-by-day backtest simulator.

    Parameters
    ----------
    all_ohlcv : dict[str, pd.DataFrame]
        Mapping of ticker -> OHLCV DataFrame for all stocks.
    spy_data : pd.DataFrame
        SPY OHLCV data.
    sector_map : dict[str, str]
        Mapping of ticker -> GICS sector.
    config : Config
        Strategy configuration.
    """

    def __init__(
        self,
        all_ohlcv: dict[str, pd.DataFrame],
        spy_data: pd.DataFrame,
        sector_map: dict[str, str],
        config: Config = Config,
    ) -> None:
        self.all_ohlcv = all_ohlcv
        self.spy_data = spy_data
        self.sector_map = sector_map
        self.config = config

        # Pre-compute indicators for all stocks to avoid redundant calculation
        self._indicators_cache: dict[str, pd.DataFrame] = {}

        # Track which tickers had a recent entry to avoid re-entering same pullback
        self._recent_entries: dict[str, pd.Timestamp] = {}

        # Pending entries: signals detected today, executed at next day's open
        self._pending_entries: list[dict] = []

    def run(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        show_progress: bool = True,
    ) -> BacktestResult:
        """Run the full backtest simulation.

        Parameters
        ----------
        start_date : str | None
            Start date (YYYY-MM-DD). Defaults to config.BACKTEST_START.
        end_date : str | None
            End date (YYYY-MM-DD). Defaults to config.BACKTEST_END.
        show_progress : bool
            Whether to show a tqdm progress bar.

        Returns
        -------
        BacktestResult
            Complete backtest results including equity curve and trade log.
        """
        start = pd.Timestamp(start_date or self.config.BACKTEST_START)
        end = pd.Timestamp(end_date or self.config.BACKTEST_END)

        # Get trading days from SPY index
        trading_days = self.spy_data.loc[start:end].index
        if len(trading_days) == 0:
            raise ValueError(f"No trading days found between {start} and {end}")

        # Pre-compute regime for the entire period
        regime = compute_regime(self.spy_data, self.config)

        portfolio = Portfolio(self.config.INITIAL_CAPITAL, self.config)

        iterator = tqdm(trading_days, desc="Backtesting", disable=not show_progress)

        for date in iterator:
            self._process_day(date, regime, portfolio)

        # Build results
        equity_curve = portfolio.get_equity_curve()
        trade_df = portfolio.trade_log.to_dataframe()

        return BacktestResult(
            portfolio=portfolio,
            equity_curve=equity_curve,
            trade_log=trade_df,
            regime_series=regime.loc[start:end],
        )

    def _process_day(
        self,
        date: pd.Timestamp,
        regime: pd.Series,
        portfolio: Portfolio,
    ) -> None:
        """Process a single trading day through the full pipeline.

        Parameters
        ----------
        date : pd.Timestamp
            Current trading day.
        regime : pd.Series
            Pre-computed regime series.
        portfolio : Portfolio
            The portfolio tracker.
        """
        # Step 1: Execute pending entries from yesterday's signals
        self._execute_pending_entries(date, portfolio)

        # Step 2: Manage existing positions (check exits)
        self._manage_positions(date, portfolio)

        # Step 3: Check regime
        is_bullish = regime.get(date, False)
        if pd.isna(is_bullish):
            is_bullish = False

        # Step 4: Scan for new signals (only if bullish)
        if is_bullish:
            self._scan_for_new_entries(date, portfolio)

        # Step 5: Take end-of-day snapshot
        portfolio.take_snapshot(date, self.all_ohlcv, bool(is_bullish))

    def _execute_pending_entries(self, date: pd.Timestamp, portfolio: Portfolio) -> None:
        """Execute entries that were signaled on the previous day.

        Entry at today's open price (with slippage).

        Parameters
        ----------
        date : pd.Timestamp
            Today's date.
        portfolio : Portfolio
            The portfolio tracker.
        """
        entries_to_execute = self._pending_entries.copy()
        self._pending_entries.clear()

        for entry in entries_to_execute:
            ticker = entry["ticker"]
            sector = entry["sector"]
            atr = entry["atr"]

            # Skip if we already have a position in this ticker
            if portfolio.has_position(ticker):
                continue

            # Skip if position limits would be violated
            if not can_open_position(portfolio.positions, sector, self.config):
                continue

            # Get today's open price for entry
            if ticker not in self.all_ohlcv or date not in self.all_ohlcv[ticker].index:
                continue

            open_price = self.all_ohlcv[ticker].loc[date, "Open"]

            # Calculate trade setup with actual entry price
            setup = calculate_trade_setup(
                ticker, open_price, atr, portfolio.account_value, self.config
            )
            if setup is None:
                continue

            portfolio.execute_entry(setup, date, sector)
            self._recent_entries[ticker] = date
            logger.debug(
                f"ENTRY {ticker} @ {open_price:.2f} | "
                f"Stop: {setup.stop_loss:.2f} | "
                f"Shares: {setup.shares}"
            )

    def _manage_positions(self, date: pd.Timestamp, portfolio: Portfolio) -> None:
        """Check exits for all open positions using RSI(2) and stop loss.

        Parameters
        ----------
        date : pd.Timestamp
            Today's date.
        portfolio : Portfolio
            The portfolio tracker.
        """
        # Work on a copy since exits modify the list
        positions_to_check = list(portfolio.positions)

        for position in positions_to_check:
            ticker = position.ticker
            if ticker not in self.all_ohlcv or date not in self.all_ohlcv[ticker].index:
                continue

            today_bar = self.all_ohlcv[ticker].loc[date]

            # Look up current RSI(2) from cached indicators
            rsi_value = None
            if ticker in self._indicators_cache:
                df_ind = self._indicators_cache[ticker]
                if date in df_ind.index and not pd.isna(df_ind.loc[date, "RSI_2"]):
                    rsi_value = float(df_ind.loc[date, "RSI_2"])

            # Check exit conditions
            exit_signal = check_exit_conditions(
                position, today_bar, date, self.config, rsi_value=rsi_value,
            )
            if exit_signal is not None:
                portfolio.execute_exit(position, exit_signal, date)
                logger.debug(
                    f"EXIT {ticker} @ {exit_signal.exit_price:.2f} | "
                    f"Reason: {exit_signal.reason}"
                )

    def _scan_for_new_entries(self, date: pd.Timestamp, portfolio: Portfolio) -> None:
        """Run stages 1-3 to find new entry signals.

        Signals are queued as pending entries to be executed at next day's open.

        Parameters
        ----------
        date : pd.Timestamp
            Today's date.
        portfolio : Portfolio
            The portfolio tracker.
        """
        # Stage 1: Universe filter
        filtered = filter_universe(self.all_ohlcv, date, self.config)

        # Exclude sectors
        if self.config.EXCLUDED_SECTORS:
            filtered = [
                t for t in filtered
                if self.sector_map.get(t, "Unknown") not in self.config.EXCLUDED_SECTORS
            ]

        # Stage 2: Momentum ranking
        watchlist = rank_stocks(
            filtered, self.all_ohlcv, self.spy_data, date,
            self.sector_map, self.config,
        )
        if watchlist.empty:
            return

        watchlist_tickers = watchlist["Ticker"].tolist()

        # Append supplemental tickers that bypass momentum ranking (e.g. SPY)
        supplemental = [
            t for t in self.config.SUPPLEMENTAL_TICKERS
            if t not in watchlist_tickers and t in self.all_ohlcv
        ]
        scan_tickers = watchlist_tickers + supplemental

        # Stage 3: Entry trigger scan — rank candidates by lowest RSI(2)
        for ticker in scan_tickers:
            # Skip if already have a position
            if portfolio.has_position(ticker):
                continue

            # Skip if position limits would be violated
            sector = self.sector_map.get(ticker, "Unknown")
            if not can_open_position(portfolio.positions, sector, self.config):
                continue

            # Skip if we recently entered this ticker (avoid re-entering same pullback)
            if ticker in self._recent_entries:
                last_entry = self._recent_entries[ticker]
                days_since = len(pd.bdate_range(last_entry, date)) - 1
                if days_since < self.config.REENTRY_COOLDOWN_DAYS:
                    continue

            # Compute indicators (cache to avoid recomputation)
            if ticker not in self._indicators_cache:
                if ticker in self.all_ohlcv:
                    self._indicators_cache[ticker] = compute_indicators(
                        self.all_ohlcv[ticker], self.config
                    )

            if ticker not in self._indicators_cache:
                continue

            df_ind = self._indicators_cache[ticker]
            if check_entry_signal(df_ind, date, self.config, ticker=ticker):
                # Get ATR for position sizing
                atr = compute_atr(self.all_ohlcv[ticker], date, self.config)
                if atr is None:
                    continue

                signal_close = self.all_ohlcv[ticker].loc[date, "Close"]
                self._pending_entries.append({
                    "ticker": ticker,
                    "sector": sector,
                    "atr": atr,
                    "signal_close": signal_close,
                })
                logger.debug(f"SIGNAL {ticker} on {date.date()} | ATR: {atr:.2f}")

                # Check if we've queued enough entries
                pending_plus_open = len(portfolio.positions) + len(self._pending_entries)
                if pending_plus_open >= self.config.MAX_POSITIONS:
                    break
