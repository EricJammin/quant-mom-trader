from __future__ import annotations

"""Stage 2: Momentum Ranking.

Computes a composite relative strength score for each stock vs SPY,
ranks them, selects the top N as the watchlist, and enforces a sector cap.
"""

import pandas as pd

from momentum_pullback_system.config import Config


def compute_rs_composite(
    stock_close: pd.Series,
    spy_close: pd.Series,
    date: pd.Timestamp,
    config: Config = Config,
) -> float | None:
    """Compute the composite relative strength score for a stock on a given date.

    Parameters
    ----------
    stock_close : pd.Series
        Stock's adjusted close prices indexed by date.
    spy_close : pd.Series
        SPY's adjusted close prices indexed by date.
    date : pd.Timestamp
        The date to evaluate.
    config : Config
        Strategy configuration with RS lookback periods and weights.

    Returns
    -------
    float | None
        Composite RS score, or None if insufficient history.
    """
    stock_data = stock_close.loc[:date]
    spy_data = spy_close.loc[:date]

    if len(stock_data) < config.RS_LOOKBACK_LONG + 1:
        return None
    if len(spy_data) < config.RS_LOOKBACK_LONG + 1:
        return None

    stock_now = stock_data.iloc[-1]
    spy_now = spy_data.iloc[-1]

    rs_scores = []
    for lookback, weight in [
        (config.RS_LOOKBACK_MED, config.RS_WEIGHT_MED),
        (config.RS_LOOKBACK_LONG, config.RS_WEIGHT_LONG),
        (config.RS_LOOKBACK_SHORT, config.RS_WEIGHT_SHORT),
    ]:
        stock_past = stock_data.iloc[-(lookback + 1)]
        spy_past = spy_data.iloc[-(lookback + 1)]
        if stock_past == 0 or spy_past == 0:
            return None
        rs = (stock_now / stock_past) / (spy_now / spy_past)
        rs_scores.append(rs * weight)

    return sum(rs_scores)


def rank_stocks(
    tickers: list[str],
    all_ohlcv: dict[str, pd.DataFrame],
    spy_data: pd.DataFrame,
    date: pd.Timestamp,
    sector_map: dict[str, str],
    config: Config = Config,
) -> pd.DataFrame:
    """Rank stocks by composite RS and apply sector cap to build the watchlist.

    Parameters
    ----------
    tickers : list[str]
        Tickers that passed the universe filter.
    all_ohlcv : dict[str, pd.DataFrame]
        Mapping of ticker → OHLCV DataFrame.
    spy_data : pd.DataFrame
        SPY OHLCV data.
    date : pd.Timestamp
        The date to evaluate.
    sector_map : dict[str, str]
        Mapping of ticker → GICS sector.
    config : Config
        Strategy configuration.

    Returns
    -------
    pd.DataFrame
        Watchlist DataFrame with columns: Ticker, RS_Composite, Sector, Rank.
        Sorted by RS_Composite descending, capped at WATCHLIST_SIZE with
        sector cap enforced.
    """
    spy_close = spy_data["Close"]
    scores = []
    for ticker in tickers:
        if ticker not in all_ohlcv:
            continue
        rs = compute_rs_composite(all_ohlcv[ticker]["Close"], spy_close, date, config)
        if rs is not None:
            scores.append({
                "Ticker": ticker,
                "RS_Composite": rs,
                "Sector": sector_map.get(ticker, "Unknown"),
            })

    if not scores:
        return pd.DataFrame(columns=["Ticker", "RS_Composite", "Sector", "Rank"])

    df = pd.DataFrame(scores).sort_values("RS_Composite", ascending=False).reset_index(drop=True)

    # Apply sector cap
    watchlist = _apply_sector_cap(df, config.WATCHLIST_SIZE, config.SECTOR_CAP)
    watchlist = watchlist.reset_index(drop=True)
    watchlist["Rank"] = watchlist.index + 1
    return watchlist


def _apply_sector_cap(ranked: pd.DataFrame, watchlist_size: int, sector_cap: int) -> pd.DataFrame:
    """Select top stocks while enforcing a maximum per sector.

    Parameters
    ----------
    ranked : pd.DataFrame
        All scored stocks sorted by RS_Composite descending.
    watchlist_size : int
        Target number of stocks in the watchlist.
    sector_cap : int
        Maximum stocks from any single sector.

    Returns
    -------
    pd.DataFrame
        Filtered watchlist respecting the sector cap.
    """
    selected = []
    sector_counts: dict[str, int] = {}

    for _, row in ranked.iterrows():
        if len(selected) >= watchlist_size:
            break
        sector = row["Sector"]
        count = sector_counts.get(sector, 0)
        if count >= sector_cap:
            continue
        selected.append(row)
        sector_counts[sector] = count + 1

    return pd.DataFrame(selected)
