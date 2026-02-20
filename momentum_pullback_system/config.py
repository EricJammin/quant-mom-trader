"""Single source of truth for all tunable strategy parameters."""


class Config:
    # === Stage 0: Market Regime ===
    REGIME_SMA_LONG = 200
    REGIME_SMA_SHORT = 50
    REGIME_INDEX = "SPY"

    # === Stage 1: Universe Filter ===
    MIN_PRICE = 10.0
    MIN_AVG_VOLUME = 500_000
    TREND_SMA_PERIOD = 200

    # === Stage 2: Momentum Ranking ===
    RS_LOOKBACK_SHORT = 21
    RS_LOOKBACK_MED = 63
    RS_LOOKBACK_LONG = 126
    RS_WEIGHT_SHORT = 0.20
    RS_WEIGHT_MED = 0.50
    RS_WEIGHT_LONG = 0.30
    WATCHLIST_SIZE = 25
    SECTOR_CAP = 8
    EXCLUDED_SECTORS = []
    RANK_UPDATE_FREQUENCY = "daily"

    # === Stage 3: RSI2 Mean Reversion Entry ===
    RSI_PERIOD = 2
    RSI_ENTRY_THRESHOLD = 15           # Enter when RSI(2) drops below this
    RSI_EXIT_THRESHOLD = 75            # Exit when RSI(2) rises above this
    REQUIRE_BELOW_SMA5 = True          # Toggleable: close must be < SMA-5
    SMA5_PERIOD = 5
    MAX_GAP_PERCENT = 2.0

    # === Stage 4: Risk Management ===
    ATR_PERIOD = 14
    STOP_ATR_MULTIPLE = 2.5
    MAX_STOP_PERCENT = 5.0
    RISK_PER_TRADE = 0.05
    MAX_POSITIONS = 5
    MAX_SECTOR_POSITIONS = 2
    TIME_STOP_DAYS = 5
    REENTRY_COOLDOWN_DAYS = 5           # Days before re-entering same ticker

    # === Backtesting ===
    INITIAL_CAPITAL = 100_000
    SLIPPAGE_PCT = 0.05
    COMMISSION_PER_TRADE = 0.00
    BACKTEST_START = "2021-01-01"
    BACKTEST_END = "2025-12-31"
    OOS_START = "2026-01-01"
    OOS_END = "2026-06-30"

    # === Data ===
    DATA_START = "2020-01-01"  # Extra lookback for SMA-200 / RS calcs
    CACHE_DIR = "data/cache"
