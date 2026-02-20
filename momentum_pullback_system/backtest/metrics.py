from __future__ import annotations

"""Performance metrics for backtest results.

Computes all statistics required by the spec (Section 5, Phase D):
Sharpe, Sortino, profit factor, max drawdown, win rate, exposure, etc.
"""

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.045  # ~4.5% annual


def compute_all_metrics(
    equity_curve: pd.DataFrame,
    trade_log: pd.DataFrame,
    initial_capital: float,
    spy_data: pd.DataFrame | None = None,
) -> dict:
    """Compute the full set of backtest performance metrics.

    Parameters
    ----------
    equity_curve : pd.DataFrame
        Daily portfolio snapshots with Account_Value column.
    trade_log : pd.DataFrame
        Completed trades from TradeLog.to_dataframe().
    initial_capital : float
        Starting account value.
    spy_data : pd.DataFrame | None
        SPY OHLCV for benchmark comparison (buy-and-hold return).

    Returns
    -------
    dict
        All metrics as a flat dictionary.
    """
    account = equity_curve["Account_Value"]
    daily_returns = account.pct_change().dropna()

    final_value = account.iloc[-1]
    total_days = len(equity_curve)
    years = total_days / TRADING_DAYS_PER_YEAR

    # Returns
    total_return_pct = (final_value / initial_capital - 1) * 100
    annualized_return_pct = ((final_value / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0

    # Sharpe ratio (annualized)
    daily_rf = (1 + RISK_FREE_RATE) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess_returns = daily_returns - daily_rf
    sharpe = (excess_returns.mean() / excess_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)) if excess_returns.std() > 0 else 0

    # Sortino ratio (only downside deviation)
    downside = excess_returns[excess_returns < 0]
    downside_std = np.sqrt((downside ** 2).mean()) if len(downside) > 0 else 0
    sortino = (excess_returns.mean() / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR)) if downside_std > 0 else 0

    # Drawdown
    rolling_max = account.cummax()
    drawdown = (account - rolling_max) / rolling_max
    max_drawdown_pct = drawdown.min() * 100

    # Trade statistics
    num_trades = len(trade_log)
    if num_trades > 0:
        winners = trade_log[trade_log["PnL"] > 0]
        losers = trade_log[trade_log["PnL"] <= 0]
        win_rate_pct = len(winners) / num_trades * 100
        avg_win_pct = winners["PnL_Pct"].mean() if len(winners) > 0 else 0
        avg_loss_pct = losers["PnL_Pct"].mean() if len(losers) > 0 else 0
        avg_win_dollars = winners["PnL"].mean() if len(winners) > 0 else 0
        avg_loss_dollars = losers["PnL"].mean() if len(losers) > 0 else 0

        gross_gains = winners["PnL"].sum() if len(winners) > 0 else 0
        gross_losses = abs(losers["PnL"].sum()) if len(losers) > 0 else 0
        profit_factor = gross_gains / gross_losses if gross_losses > 0 else float("inf")

        avg_holding_days = trade_log["Holding_Days"].mean()

        # Positive expectancy check
        loss_rate = 1 - win_rate_pct / 100
        positive_expectancy = (win_rate_pct / 100 * avg_win_dollars) > (loss_rate * abs(avg_loss_dollars))
    else:
        win_rate_pct = 0
        avg_win_pct = 0
        avg_loss_pct = 0
        avg_win_dollars = 0
        avg_loss_dollars = 0
        profit_factor = 0
        avg_holding_days = 0
        positive_expectancy = False
        gross_gains = 0
        gross_losses = 0

    # Exposure time
    exposure_days = (equity_curve["Num_Positions"] > 0).sum()
    exposure_pct = exposure_days / total_days * 100 if total_days > 0 else 0

    # Exit reason breakdown
    exit_reasons = {}
    if num_trades > 0:
        exit_reasons = trade_log["Exit_Reason"].value_counts().to_dict()

    # SPY benchmark
    spy_return_pct = None
    if spy_data is not None:
        spy_slice = spy_data.loc[equity_curve.index[0]:equity_curve.index[-1]]
        if len(spy_slice) > 0:
            spy_return_pct = (spy_slice["Close"].iloc[-1] / spy_slice["Close"].iloc[0] - 1) * 100

    return {
        "total_return_pct": total_return_pct,
        "annualized_return_pct": annualized_return_pct,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate_pct": win_rate_pct,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "avg_win_dollars": avg_win_dollars,
        "avg_loss_dollars": avg_loss_dollars,
        "gross_gains": gross_gains,
        "gross_losses": gross_losses,
        "num_trades": num_trades,
        "avg_holding_days": avg_holding_days,
        "exposure_pct": exposure_pct,
        "positive_expectancy": positive_expectancy,
        "exit_reasons": exit_reasons,
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_days": total_days,
        "max_drawdown_date": drawdown.idxmin() if len(drawdown) > 0 else None,
        "spy_return_pct": spy_return_pct,
    }


def compute_monthly_returns(equity_curve: pd.DataFrame) -> pd.DataFrame:
    """Compute monthly returns for the heatmap.

    Parameters
    ----------
    equity_curve : pd.DataFrame
        Daily portfolio snapshots.

    Returns
    -------
    pd.DataFrame
        Pivot table with years as rows, months as columns, values as return %.
    """
    account = equity_curve["Account_Value"].copy()
    monthly = account.resample("ME").last()
    monthly_returns = monthly.pct_change() * 100

    df = pd.DataFrame({
        "Year": monthly_returns.index.year,
        "Month": monthly_returns.index.month,
        "Return": monthly_returns.values,
    }).dropna()

    pivot = df.pivot_table(values="Return", index="Year", columns="Month")
    pivot.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return pivot


def compute_drawdown_series(equity_curve: pd.DataFrame) -> pd.Series:
    """Compute the rolling drawdown percentage over time.

    Parameters
    ----------
    equity_curve : pd.DataFrame
        Daily portfolio snapshots.

    Returns
    -------
    pd.Series
        Drawdown as negative percentages, indexed by date.
    """
    account = equity_curve["Account_Value"]
    rolling_max = account.cummax()
    drawdown = (account - rolling_max) / rolling_max * 100
    drawdown.name = "Drawdown_Pct"
    return drawdown
