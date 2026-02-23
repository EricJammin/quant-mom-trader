# MPS Live Scanner

Daily RSI(2) alert scanner for the Momentum Pullback System. Detects mean-reversion
entry signals on S&P 500 stocks and SPY after market close, then sends alerts via
email and/or Telegram.

---

## Setup

### 1. Install dependencies

```bash
pip install -r scanner/requirements.txt
```

### 2. Configure credentials

```bash
cp scanner/.env.example .env
```

Edit `.env` with your values. Both alert channels are optional — configure one or both.

**Email (Gmail):**
Gmail requires an **App Password** (not your regular password).
- Enable 2-Step Verification on your Google account.
- Create an App Password at: https://myaccount.google.com/apppasswords
- Use that 16-character password as `EMAIL_PASSWORD`.

**Telegram:**
1. Message [@BotFather](https://t.me/botfather) → `/newbot` → follow prompts → copy token.
2. Start a chat with your new bot.
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser.
4. Send any message to your bot, refresh the page, and find `"chat": {"id": ...}` — that's your `TELEGRAM_CHAT_ID`.

---

## Usage

Run all commands from the **project root** (not the `scanner/` directory).

```bash
# Live scan — sends alerts if signals are found
python -m scanner.daily_scan

# Dry run — prints output to console, no alerts sent
python -m scanner.daily_scan --dry-run

# Scan a historical date (dry-run implied)
python -m scanner.daily_scan --date 2024-06-14

# Force re-download all ticker data
python -m scanner.daily_scan --refresh --dry-run
```

---

## Signal Logic

| | S&P 500 Stocks | SPY |
|---|---|---|
| **RSI(2) threshold** | < 10 | < 15 (looser — SPY doesn't swing as hard) |
| **Close vs SMA-5** | Close < SMA-5 | Close < SMA-5 |
| **Universe filter** | Price > $10, Avg Vol > 500K, Close > SMA-200 | Always included |

**Regime gate:** if SPY close < SMA-200 or SMA-50 < SMA-200, no scan is run.
Signals are ranked by RSI(2) ascending (most oversold first).

---

## Alert Channels

| Channel | Content | When sent |
|---|---|---|
| **Email** | Full HTML report with signal table + checklist | If `EMAIL_SENDER` is set |
| **Telegram** | Concise text summary for mobile | If `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` are set |

Both channels get the same signal data. If neither is configured, the scan still runs
but only logs to console — useful for testing.

---

## Pre-Trade Checklist

The scanner detects signals on the **underlying stock**. The trade is a short put spread
(options), executed manually the following morning:

1. Check IV Rank > 30
2. Select expiration 5–8 calendar days out
3. Sell put at delta −0.25 to −0.35 with $3–5 wide spread
4. Verify premium ≥ 30% of spread width
5. Check bid-ask < 10% of mid-price
6. Confirm gap from prior close < 3% at the open (manual check)

---

## Data & Caching

- Ticker data is cached in `scanner/cache/` as Parquet files.
- Cache is refreshed automatically when last data is more than 3 days old.
- S&P 500 ticker list is cached in `scanner/cache/sp500_tickers.csv` and refreshed weekly.
- **Historical date limit:** `--date` requires the requested date to be within the last
  ~365 days (the cache lookback window). Earlier dates are not cached.
- On the first run, ~503 tickers are downloaded — this takes a few minutes.

---

## Running Tests

```bash
pytest scanner/tests/
```

---

## Project Structure

```
scanner/
├── config_live.py        # All parameters and env-var-backed credentials
├── daily_scan.py         # CLI entry point
├── data_fetcher.py       # yfinance download with Parquet caching
├── signal_detector.py    # RSI(2) pipeline (reuses momentum_pullback_system)
├── alert_sender.py       # Email (SMTP) + Telegram (Bot API) formatting & sending
├── sp500_tickers.py      # Wikipedia fetch + local CSV cache
├── requirements.txt
├── .env.example          # Credential template
└── tests/
    └── test_signal_detector.py
```

---

## Future: Lambda Deployment

The scanner is structured for CLI use today, but is Lambda-ready:
- No persistent state — each run is independent.
- Credentials via environment variables (Lambda env vars work the same as `.env`).
- **Note:** Lambda packaging will need to include the `momentum_pullback_system` package
  alongside `scanner/`, since `signal_detector.py` imports from it.
