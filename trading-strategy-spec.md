# Trading Strategy Specification: Momentum Pullback System

## Document Purpose

This is the complete blueprint for building a systematic swing trading strategy. It covers the strategy logic, architecture, backtesting workflow, acceptance criteria, and future live-alerting system. This document should be used as the primary reference when building the codebase.

---

## 1. Strategy Overview

**Name:** Momentum Pullback System (MPS)
**Type:** Systematic long-only swing trading
**Holding Period:** 2–10 trading days
**Frequency:** 1–3 trades per day maximum, 5 open positions maximum at any time
**Universe:** S&P 500 constituents
**Benchmark:** SPY (S&P 500 ETF)

### Core Thesis

Buy stocks that are outperforming the market (momentum) when they temporarily pull back to a key support level (mean reversion entry). Exit using ATR-based risk management that respects each stock's individual volatility.

### Priority

Consistency and capital preservation over maximum returns. The system should produce a smooth equity curve with controlled drawdowns, not a volatile one with occasional large wins.

---

## 2. Strategy Logic: The Pipeline

The strategy operates as a sequential pipeline with 5 stages. Each stage narrows the candidate pool.

### Stage 0: Market Regime Gate

**Purpose:** Prevent trading during broad market downtrends where long-only momentum strategies historically underperform.

**Rules:**
- Compute the 200-day Simple Moving Average (SMA-200) of SPY's closing price.
- Compute the 50-day Simple Moving Average (SMA-50) of SPY's closing price.
- **IF** SPY close > SMA-200 **AND** SMA-50 > SMA-200 → Market is BULLISH → proceed to Stage 1.
- **IF** either condition is false → Market is BEARISH → **no new trades are opened**. Existing trades are managed normally (stops and targets still apply) but no new entries.

**Rationale:** This single filter would have kept the system out of most of 2022's decline. It's a blunt instrument but highly effective for long-only strategies.

**Implementation Notes:**
- Recalculate daily at market close (or before market open using prior day's close).
- Log the regime state each day for backtest analysis.

### Stage 1: Universe Filter

**Purpose:** Ensure we only trade liquid, established stocks in uptrends.

**Rules — ALL must be true:**
- **Price filter:** Closing price > $15.00
- **Volume filter:** 20-day SMA of daily volume > 1,000,000 shares
- **Trend filter:** Closing price > 200-day SMA

**Implementation Notes:**
- Recalculate daily.
- Use adjusted close prices (accounts for splits and dividends).
- The input universe is the current S&P 500 constituent list. See "Known Limitations" section regarding survivorship bias.

### Stage 2: Momentum Ranking

**Purpose:** Identify the stocks outperforming the broader market by the widest margin.

**Formula — Composite Relative Strength Score:**

```
RS_3m = (Stock_Price_Now / Stock_Price_63d_ago) / (SPY_Price_Now / SPY_Price_63d_ago)
RS_6m = (Stock_Price_Now / Stock_Price_126d_ago) / (SPY_Price_Now / SPY_Price_126d_ago)
RS_1m = (Stock_Price_Now / Stock_Price_21d_ago) / (SPY_Price_Now / SPY_Price_21d_ago)

RS_Composite = (0.50 * RS_3m) + (0.30 * RS_6m) + (0.20 * RS_1m)
```

**Selection:**
- Rank all stocks passing Stage 1 by RS_Composite, descending.
- Select the top 25 stocks as the daily "Watchlist."
- **Sector cap:** No more than 8 stocks (roughly 30%) from any single GICS sector. If a sector exceeds 8, drop the lowest-ranked stocks from that sector and backfill with the next-highest-ranked stocks from other sectors.

**Implementation Notes:**
- Use 63 trading days for 3-month, 126 for 6-month, 21 for 1-month.
- If a stock doesn't have enough history for the 126-day lookback, exclude it from ranking.
- Recalculate daily but the watchlist can also be updated weekly (parameter to test in backtesting).
- Store the full ranked list and the sector distribution for analysis.

### Stage 3: Entry Trigger

**Purpose:** Time the entry — don't chase stocks at their peak; wait for a pullback to support.

**Primary Trigger — EMA-20 Pullback:**
- The stock's daily low touches or crosses below the 20-period Exponential Moving Average (EMA-20), AND
- The stock's daily close is AT or ABOVE the EMA-20 (i.e., it touched the EMA and bounced back — not a breakdown).

**Confirmation Filters — ALL must be true:**
1. **Volume declining on pullback:** The 3-day average volume at the time of the pullback is LESS than the 20-day average volume. This indicates the pullback is on light selling (healthy consolidation), not heavy distribution.
2. **RSI in the "goldilocks" zone:** The 14-period RSI is between 40 and 60 (inclusive). This means the stock is neither overbought nor oversold — it's resting.
3. **Not gapping:** The entry day's open is within 2% of the previous day's close. This avoids entering on large gap-ups where the actual fill price would be much worse than the signal price.

**Entry Price:**
- **Backtest assumption:** Enter at the NEXT DAY's open after the trigger fires. (We detect the signal at close, then enter the following morning.) This is realistic — you can't trade at the close of the signal day because you need the close to confirm the trigger.
- **Live mode:** The alert fires after market close. You place a limit order at or near the prior close for the next morning.

**Implementation Notes:**
- Only ONE entry per stock per pullback. If a stock triggers, don't re-enter the same pullback if the first trade is still open or was just stopped out.
- If multiple stocks trigger on the same day, prioritize by RS_Composite rank (highest first).
- Maximum 3 open positions at any time. If 3 positions are already open, no new entries until one closes.

### Stage 4: Risk Management (ATR-Based)

**Purpose:** Size positions and set exits based on each stock's actual volatility, not arbitrary fixed percentages.

**ATR Calculation:**
- Use the 14-period Average True Range (ATR-14) at the time of entry.

**Stop Loss:**
- Initial stop = Entry Price - (2.0 × ATR-14)
- This gives the stock room to breathe within its normal volatility range.
- **Hard stop:** If the stop distance would be greater than 5% of the entry price, SKIP the trade. The stock is too volatile for our risk tolerance.

**Profit Target:**
- Target = Entry Price + (3.0 × ATR-14)
- This creates a 1.5:1 reward-to-risk ratio at minimum.

**Trailing Stop (activated after partial profit):**
- Once the stock reaches Entry Price + (1.5 × ATR-14), move the stop to breakeven (entry price).
- After that, trail the stop at Entry Price + (current high since entry - 2.0 × ATR-14). In other words, the stop follows the highest price reached, always staying 2× ATR below the peak.

**Position Sizing:**
- Risk per trade = 1% of total account value.
- Shares = (Account Value × 0.01) / (Entry Price - Stop Loss Price)
- This means if you're stopped out, you lose exactly 1% of your account — regardless of the stock's price or volatility.

**Maximum Exposure:**
- Maximum 3 simultaneous positions.
- Maximum 3% of account at risk at any time (3 positions × 1% each).
- No more than 2 positions in the same GICS sector.

**Exit Conditions (checked daily at close):**
1. Stop loss hit (price closed below stop) → EXIT at next day's open.
2. Profit target hit (price closed above target) → EXIT at next day's open.
3. Time stop: If the trade has been open for 10 trading days and hasn't hit the target, EXIT at next day's open. (Avoids tying up capital in stalled trades.)

**Implementation Notes:**
- In backtesting, check if the day's LOW breached the stop (not just the close). If the low is below the stop, assume exit at the stop price (not the low — this is conservative).
- Similarly, if the day's HIGH exceeds the target, assume exit at the target price.
- If both stop and target are breached in the same bar, assume the STOP was hit (conservative assumption).

---

## 3. Project Architecture

The project must be modular so the same core pipeline works for both backtesting and live alerting.

```
momentum_pullback_system/
│
├── config.py                  # All tunable parameters (see Section 4)
│
├── data/
│   ├── __init__.py
│   ├── fetcher.py             # Abstract base class: get_ohlcv(), get_spy_data()
│   ├── historical.py          # Concrete: loads from local Parquet/CSV files
│   ├── live.py                # Concrete: pulls from yfinance or other API (Phase 2)
│   └── universe.py            # Gets S&P 500 constituent list + GICS sectors
│
├── pipeline/
│   ├── __init__.py
│   ├── regime_filter.py       # Stage 0: Market regime gate
│   ├── universe_filter.py     # Stage 1: Price/volume/trend filter
│   ├── momentum_rank.py       # Stage 2: RS composite score + sector cap
│   ├── entry_trigger.py       # Stage 3: EMA pullback + confirmations
│   └── risk_manager.py        # Stage 4: ATR stops, sizing, trailing stops
│
├── backtest/
│   ├── __init__.py
│   ├── engine.py              # Orchestrates the daily pipeline over historical data
│   ├── portfolio.py           # Tracks positions, cash, account value over time
│   ├── trade_log.py           # Records every trade with full metadata
│   ├── metrics.py             # Computes Sharpe, drawdown, profit factor, etc.
│   ├── monte_carlo.py         # Shuffles trade sequence for distribution analysis
│   └── parameter_sweep.py     # Runs backtests across parameter grid
│
├── live/                      # Phase 2 — built after backtesting validates strategy
│   ├── __init__.py
│   ├── scanner.py             # Runs pipeline daily, outputs trade candidates
│   └── alerter.py             # Sends SMS/email/push with entry, stop, target
│
├── reports/
│   ├── __init__.py
│   └── generator.py           # Produces HTML/PDF backtest report with charts
│
├── scripts/
│   ├── download_data.py       # One-time script to download and cache historical data
│   ├── run_backtest.py        # CLI entry point for backtesting
│   ├── run_parameter_sweep.py # CLI entry point for parameter sensitivity
│   └── run_scanner.py         # CLI entry point for live scanning (Phase 2)
│
├── tests/
│   ├── test_regime_filter.py
│   ├── test_universe_filter.py
│   ├── test_momentum_rank.py
│   ├── test_entry_trigger.py
│   ├── test_risk_manager.py
│   └── test_backtest_engine.py
│
├── requirements.txt
└── README.md
```

### Key Design Principle

The `pipeline/` modules accept DataFrames (or similar) and return filtered results. They do NOT know or care whether the data came from a historical file or a live API. The `data/` layer handles that abstraction. This means switching from backtest to live mode requires zero changes to the strategy logic.

---

## 4. Configuration (config.py)

All tunable parameters live in a single file. This is critical for parameter sweeps and reproducibility.

```python
# config.py

class Config:
    # === Stage 0: Market Regime ===
    REGIME_SMA_LONG = 200          # Long-term trend (days)
    REGIME_SMA_SHORT = 50          # Short-term trend (days)
    REGIME_INDEX = "SPY"           # Benchmark index

    # === Stage 1: Universe Filter ===
    MIN_PRICE = 15.0               # Minimum stock price ($)
    MIN_AVG_VOLUME = 1_000_000     # Minimum 20-day average volume
    TREND_SMA_PERIOD = 200         # Stock must be above this SMA

    # === Stage 2: Momentum Ranking ===
    RS_LOOKBACK_SHORT = 21         # 1-month lookback (trading days)
    RS_LOOKBACK_MED = 63           # 3-month lookback
    RS_LOOKBACK_LONG = 126         # 6-month lookback
    RS_WEIGHT_SHORT = 0.20         # Weight for 1-month RS
    RS_WEIGHT_MED = 0.50           # Weight for 3-month RS
    RS_WEIGHT_LONG = 0.30          # Weight for 6-month RS
    WATCHLIST_SIZE = 25            # Number of top stocks to track
    SECTOR_CAP = 8                 # Max stocks from one sector
    RANK_UPDATE_FREQUENCY = "daily"  # "daily" or "weekly"

    # === Stage 3: Entry Trigger ===
    EMA_PERIOD = 20                # Pullback target EMA
    RSI_PERIOD = 14                # RSI calculation period
    RSI_LOWER = 40                 # RSI must be above this
    RSI_UPPER = 60                 # RSI must be below this
    VOLUME_PULLBACK_WINDOW = 3     # Days to average for pullback volume
    VOLUME_BASELINE_WINDOW = 20    # Days to average for baseline volume
    MAX_GAP_PERCENT = 2.0          # Max overnight gap to accept entry (%)

    # === Stage 4: Risk Management ===
    ATR_PERIOD = 14                # ATR lookback
    STOP_ATR_MULTIPLE = 2.0        # Stop loss = entry - (this × ATR)
    TARGET_ATR_MULTIPLE = 3.0      # Profit target = entry + (this × ATR)
    TRAILING_ACTIVATION_ATR = 1.5  # Move stop to breakeven after this × ATR gain
    TRAILING_ATR_MULTIPLE = 2.0    # Trail stop at peak - (this × ATR)
    MAX_STOP_PERCENT = 5.0         # Skip trade if stop > this % of entry price
    RISK_PER_TRADE = 0.01          # Risk 1% of account per trade
    MAX_POSITIONS = 3              # Maximum simultaneous open positions
    MAX_SECTOR_POSITIONS = 2       # Max positions in one sector
    TIME_STOP_DAYS = 10            # Close trade if open this many days without hitting target

    # === Backtesting ===
    INITIAL_CAPITAL = 100_000      # Starting account value ($)
    SLIPPAGE_PCT = 0.05            # Assumed slippage per trade (%)
    COMMISSION_PER_TRADE = 0.00    # Commission per trade ($) — adjust if needed
    BACKTEST_START = "2021-01-01"  # In-sample start date
    BACKTEST_END = "2025-06-30"    # In-sample end date
    OOS_START = "2025-07-01"       # Out-of-sample start date
    OOS_END = "2025-12-31"         # Out-of-sample end date
```

---

## 5. Backtesting Workflow

### Phase A: Data Preparation

**Script:** `scripts/download_data.py`

1. Fetch the S&P 500 constituent list (with GICS sectors) from Wikipedia or a similar source.
2. Download daily OHLCV data for all constituents from `2020-01-01` to present using `yfinance`.
3. Download SPY daily OHLCV data for the same period.
4. Save as Parquet files in a `data/cache/` directory.
5. Log any tickers that failed to download (delisted, renamed, etc.).

**Important:** We need data starting from 2020-01-01 even though backtesting starts 2021-01-01 because we need ~200 days of lookback for the SMA-200 and RS calculations.

### Phase B: Visual Sanity Check

Before running the full backtest:
1. Pick 5 well-known stocks (e.g., AAPL, MSFT, NVDA, JPM, UNH).
2. Run the entry trigger logic on each.
3. Generate a chart showing: price, EMA-20, SMA-200, and buy/sell signal markers.
4. Manually verify: Do the entries look reasonable? Are we buying pullbacks or catching falling knives?

### Phase C: Full Historical Backtest

**Script:** `scripts/run_backtest.py`

The backtest engine simulates each trading day from `BACKTEST_START` to `BACKTEST_END`:

```
For each trading day:
    1. Check Stage 0 (regime). If bearish, skip to managing existing positions.
    2. Run Stage 1 (universe filter) on all stocks.
    3. Run Stage 2 (momentum rank) on filtered stocks.
    4. Run Stage 3 (entry trigger) on watchlist stocks.
    5. For any new triggers (up to MAX_POSITIONS limit):
       a. Calculate Stage 4 (ATR stop, target, position size).
       b. If stop < MAX_STOP_PERCENT, simulate entry at next day's open.
    6. For all open positions:
       a. Check if stop, target, or trailing stop was hit during today's bar.
       b. Check time stop.
       c. Update trailing stop if applicable.
       d. Record any exits.
    7. Log daily portfolio value, cash, and open positions.
```

### Phase D: Performance Report

**Module:** `reports/generator.py`

Generate a report containing:

1. **Equity Curve:** Portfolio value over time, overlaid with SPY buy-and-hold.
2. **Drawdown Chart:** Rolling max drawdown over time.
3. **Summary Statistics Table:**
   - Total Return (%) and Annualized Return (%)
   - Sharpe Ratio (annualized, using risk-free rate of ~4.5%)
   - Sortino Ratio
   - Profit Factor (gross gains / gross losses)
   - Max Drawdown (%)
   - Win Rate (%)
   - Average Win (%) and Average Loss (%)
   - Average Win / Average Loss ratio
   - Total number of trades
   - Average holding period (days)
   - Exposure time (% of days with at least one open position)
4. **Monthly Returns Heatmap:** Shows P&L by month/year.
5. **Trade Distribution:** Histogram of individual trade returns.
6. **Regime Analysis:** Performance separated by bullish vs. bearish regime periods.

### Phase E: Stress Testing

Run the backtest specifically on these periods and report metrics separately:
- **2022 Bear Market** (Jan 2022 – Oct 2022): The regime filter should keep us mostly in cash.
- **2020 COVID Crash** (Feb 2020 – Apr 2020): Test the speed of the regime gate.
- **2023 Rally** (Jan 2023 – Dec 2023): The strategy should participate in most of this.
- **2024-2025 Mixed Markets:** Recent behavior.

### Phase F: Parameter Sensitivity Analysis

**Script:** `scripts/run_parameter_sweep.py`

Vary these parameters in a grid search:

| Parameter | Values to Test |
|-----------|---------------|
| EMA_PERIOD | 15, 18, 20, 22, 25 |
| RS_LOOKBACK_MED | 42, 63, 84, 105 |
| STOP_ATR_MULTIPLE | 1.5, 2.0, 2.5, 3.0 |
| TARGET_ATR_MULTIPLE | 2.0, 2.5, 3.0, 4.0 |
| TIME_STOP_DAYS | 7, 10, 15, 20 |

That's 5 × 4 × 4 × 4 × 4 = 1,280 combinations. For each, record Sharpe, Max Drawdown, Profit Factor, and number of trades. Present results as heatmaps (2D parameter pairs) to identify robust "plateaus" where many nearby parameter values all produce acceptable results.

**Critical:** If only a narrow range of parameters works (e.g., only EMA=20 but not 19 or 21), the strategy is overfit. We want broad regions of viability.

### Phase G: Out-of-Sample Test

After finalizing parameters based on Phases C–F:
1. Run the strategy on `OOS_START` to `OOS_END` (the held-out 6-month window).
2. Compare metrics to in-sample performance.
3. Accept if: Sharpe > 0.7, Profit Factor > 1.2, Max Drawdown < 20%. (Expect ~30-40% degradation from in-sample.)

### Phase H: Monte Carlo Simulation

**Module:** `backtest/monte_carlo.py`

1. Take the full list of completed trades from the in-sample backtest.
2. Shuffle the trade sequence randomly.
3. Simulate the equity curve with the shuffled order.
4. Repeat 10,000 times.
5. Report:
   - Median final account value
   - 5th percentile (bad luck scenario)
   - 95th percentile (good luck scenario)
   - Distribution of max drawdowns across simulations
   - Probability of a >20% drawdown at any point

---

## 6. Minimum Acceptance Criteria

Define these BEFORE running any backtest. Do not change them after seeing results.

### In-Sample (Must pass ALL):
- Sharpe Ratio ≥ 1.0
- Profit Factor ≥ 1.5
- Max Drawdown ≤ 15%
- Total trades ≥ 75 (statistical significance)
- Win Rate × Avg Win > Loss Rate × Avg Loss (positive expectancy)
- Equity curve is generally upward-sloping (not dependent on 1–2 trades)

### Out-of-Sample (Must pass ALL):
- Sharpe Ratio ≥ 0.7
- Profit Factor ≥ 1.2
- Max Drawdown ≤ 20%

### Monte Carlo (Must pass ALL):
- 5th percentile final value > starting capital (even bad luck doesn't lose money)
- Probability of >25% drawdown < 10%

---

## 7. Troubleshooting / Tweak Protocol

If backtesting fails the acceptance criteria, apply these adjustments in order:

### Problem: Win rate < 35%
**Diagnosis:** Entry trigger is too loose — generating too many false signals.
**Fixes (try in order):**
1. Add a requirement that the RSI must be rising (RSI today > RSI yesterday) at the time of entry.
2. Require a "confirmation candle" — wait for the day AFTER the EMA touch to close green (close > open) before entering.
3. Tighten the RSI zone to 45–55.

### Problem: Max drawdown > 15%
**Diagnosis:** Either the regime filter isn't aggressive enough or position sizing is too large.
**Fixes:**
1. Add a VIX filter: no new trades if VIX > 25.
2. Reduce MAX_POSITIONS from 3 to 2.
3. Reduce RISK_PER_TRADE from 1% to 0.75%.

### Problem: Average win < average loss
**Diagnosis:** Cutting winners too early or letting losers run too long.
**Fixes:**
1. Increase TARGET_ATR_MULTIPLE from 3.0 to 3.5 or 4.0.
2. Decrease TIME_STOP_DAYS from 10 to 7 (cut stalled trades faster).
3. Activate trailing stop earlier (reduce TRAILING_ACTIVATION_ATR from 1.5 to 1.0).

### Problem: Too few trades (< 50 over backtest period)
**Diagnosis:** Filters are too restrictive.
**Fixes:**
1. Expand WATCHLIST_SIZE from 25 to 35.
2. Widen RSI range to 35–65.
3. Relax the volume decline requirement — instead of "3-day avg < 20-day avg," use "3-day avg < 1.2 × 20-day avg."

### Problem: All profit comes from 2–3 large trades
**Diagnosis:** Strategy is not consistent; it's lucky.
**Fixes:**
1. This is a fundamental problem. Consider reducing the TARGET_ATR_MULTIPLE to take profits faster and increasing trade frequency.
2. If the issue persists, re-examine the core thesis.

---

## 8. Known Limitations

1. **Survivorship Bias:** We're using the current S&P 500 list and applying it historically. Stocks that were removed from the index (often due to poor performance) are missing. This makes the backtest look ~1-3% better per year than reality. Mitigation: Be conservative in interpreting results and add a buffer to acceptance criteria.

2. **No Short Selling:** This is a long-only strategy. It will underperform or sit in cash during bear markets. This is by design (simplicity and capital preservation), but it means our benchmark comparison during bear markets may look worse than a long-short system.

3. **Gap Risk:** We enter at the next day's open. If a stock gaps significantly (earnings, news), our actual entry will be much worse than expected. The 2% gap filter helps but doesn't eliminate this risk.

4. **Data Quality:** `yfinance` data is free but occasionally has errors (missing days, incorrect splits). For production use (live alerting), consider a paid data source.

5. **Sector Data:** GICS sector assignments change over time. We use current sector assignments historically, which is a minor inaccuracy.

---

## 9. Technology Stack

### Core Dependencies
```
# requirements.txt
pandas>=2.0
numpy>=1.24
yfinance>=0.2.30
ta>=0.11.0           # Technical analysis indicators (EMA, RSI, ATR)
matplotlib>=3.7
seaborn>=0.12
plotly>=5.15          # Interactive charts for reports
tqdm>=4.65            # Progress bars for long backtests
pyarrow>=12.0         # Parquet file support
```

### Optional (Phase 2 — Live Alerts)
```
schedule>=1.2         # Job scheduling
twilio>=8.0           # SMS alerts
python-dotenv>=1.0    # Environment variable management
```

### Development
```
pytest>=7.0
black>=23.0           # Code formatting
```

---

## 10. Phase 2: Live Alert System (Build After Backtesting)

Once the strategy passes all acceptance criteria, the live system works as follows:

### Daily Workflow (Automated)

1. **6:00 PM ET (after market close):** `scanner.py` runs:
   - Downloads today's closing data for all S&P 500 stocks and SPY.
   - Runs the full pipeline (Stages 0–3).
   - Outputs a list of trade candidates with: ticker, entry price (suggested limit order), stop loss, profit target, position size (shares), and RS rank.

2. **6:05 PM ET:** `alerter.py` sends you an SMS/email/push notification with the trade candidates. Format:
   ```
   [MPS ALERT] 2 trades for tomorrow:
   
   1. NVDA | Buy limit: $142.50 | Stop: $136.80 | Target: $151.05 | Shares: 45
   2. COST | Buy limit: $985.00 | Stop: $962.10 | Target: $1019.35 | Shares: 12
   
   Market regime: BULLISH | Open positions: 1/3
   ```

3. **You manually:** Place limit orders before market open. Review stops and targets for existing positions.

4. **Throughout day:** The system can optionally run an intraday check at 3:30 PM ET to alert you if any stops need updating (trailing stop adjustments).

### Infrastructure

- Run on a small cloud instance (AWS Lambda, Google Cloud Function, or a $5/month VPS).
- Use a cron job or `schedule` library to trigger the daily scan.
- Store trade history in a simple SQLite database or CSV for ongoing performance tracking.

---

## 11. Build Order

When building this system, follow this sequence:

### Step 1: Data Layer
Build `data/fetcher.py`, `data/historical.py`, `data/universe.py`, and `scripts/download_data.py`. Verify you can download and load data correctly.

### Step 2: Pipeline Modules (one at a time)
Build and unit-test each module independently:
1. `pipeline/regime_filter.py` — test with SPY data
2. `pipeline/universe_filter.py` — test with a handful of stocks
3. `pipeline/momentum_rank.py` — verify ranking logic with known data
4. `pipeline/entry_trigger.py` — test against manually identified setups
5. `pipeline/risk_manager.py` — verify position sizing math

### Step 3: Backtest Engine
Build `backtest/engine.py` and `backtest/portfolio.py`. Start with a single stock to verify the day-by-day simulation works correctly. Then scale to the full universe.

### Step 4: Metrics and Reporting
Build `backtest/metrics.py` and `reports/generator.py`. Generate the full performance report.

### Step 5: Visual Sanity Check
Run Phase B (visual check on 5 stocks) before trusting the full results.

### Step 6: Full Backtest + Analysis
Run Phases C through H. Evaluate against acceptance criteria. Iterate if needed using the Tweak Protocol.

### Step 7 (Later): Live System
Only after the strategy passes all tests: build `live/scanner.py` and `live/alerter.py`.

---

## 12. Key Questions to Resolve During Development

These are decisions that may need adjustment based on what we discover during implementation:

1. **Daily vs. weekly watchlist update:** Does recalculating the RS ranking daily vs. weekly change performance meaningfully?
2. **EMA vs. VWAP for entry:** VWAP is intraday only and harder to backtest on daily bars. We start with EMA-20 but may revisit.
3. **Entry at open vs. limit order:** Backtesting assumes entry at next day's open, but in practice a limit order near the prior close may get better fills.
4. **Same-day stop check:** Do we check if the stop was hit intraday (using the low) or only at close? The spec says use the low — this is more conservative and more realistic.
5. **Handling earnings:** Should we avoid entries within N days of earnings? Earnings cause gaps that our gap filter partly handles, but a dedicated earnings exclusion might help.
6. **Mid-day check:** Should we add a mid-day check to account for large gap-ups?

---

*End of specification. This document should be version-controlled and updated as decisions are made during development.*
