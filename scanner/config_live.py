from __future__ import annotations

"""Live scanner configuration.

All secrets (email/Telegram credentials) must be set as environment variables.
See .env.example for required variables. Never hardcode credentials here.
"""

import os
from pathlib import Path


class LiveConfig:
    # === Regime Filter ===
    REGIME_SMA_LONG: int = 200
    REGIME_SMA_SHORT: int = 50
    REGIME_INDEX: str = "SPY"

    # === Universe Filter (S&P 500 stocks) ===
    MIN_PRICE: float = 10.0
    MIN_AVG_VOLUME: int = 500_000
    TREND_SMA_PERIOD: int = 200
    EXCLUDED_SECTORS: list = []

    # === Entry Signal ===
    RSI_PERIOD: int = 2
    RSI_ENTRY_THRESHOLD: int = 10                    # Default: S&P 500 stocks
    RSI_ENTRY_OVERRIDES: dict = {"SPY": 15}          # SPY uses looser threshold
    SUPPLEMENTAL_TICKERS: list = ["SPY"]             # Always scanned, bypass universe filter
    REQUIRE_BELOW_SMA5: bool = True
    SMA5_PERIOD: int = 5

    # === Risk / Stop Calculation ===
    ATR_PERIOD: int = 14
    STOP_ATR_MULTIPLE: float = 2.5

    # === Manual Pre-Entry Reminder ===
    GAP_FILTER_PCT: float = 3.0                      # Check manually at open

    # === Data ===
    CACHE_DIR: Path = Path("scanner/cache")
    CACHE_LOOKBACK_DAYS: int = 365

    # === Email (loaded from environment variables) ===
    SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
    EMAIL_SENDER: str = os.environ.get("EMAIL_SENDER", "")
    EMAIL_PASSWORD: str = os.environ.get("EMAIL_PASSWORD", "")
    EMAIL_RECIPIENT: str = os.environ.get("EMAIL_RECIPIENT", "")
    EMAIL_SUBJECT_PREFIX: str = "[MPS Scanner]"

    # === Telegram (loaded from environment variables) ===
    # Leave unset to disable Telegram alerts.
    # TELEGRAM_BOT_TOKEN: get from @BotFather on Telegram.
    # TELEGRAM_CHAT_ID: your personal chat ID or a channel/group ID.
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
