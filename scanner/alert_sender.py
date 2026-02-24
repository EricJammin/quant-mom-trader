from __future__ import annotations

"""Alert formatter and sender for email and Telegram.

Each channel is activated only if its credentials are configured.
Email receives the full formatted HTML report (live scans only).
Telegram receives a concise HTML summary suited for mobile.
Dry-run mode sends Telegram tagged [DRY RUN] but skips email.

Exit alerts (from position tracking) are included in the same message as
entry signals — exits appear first in both email and Telegram.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import requests

from scanner.signal_detector import ScanResult, Signal

logger = logging.getLogger(__name__)


# ── Public API ─────────────────────────────────────────────────────────────────

def send_alerts(
    result: ScanResult,
    config,
    dry_run: bool = False,
    exit_alerts: list | None = None,
) -> None:
    """Send scan results via all configured channels.

    In live mode: sends email + Telegram.
    In dry-run mode: sends Telegram only, tagged [DRY RUN]. Email is skipped.
    Exit alerts (if any) appear before entry signals in both channels.
    Logs a warning if neither channel is configured.

    Parameters
    ----------
    result : ScanResult
        The output of run_scan for the current day.
    config : LiveConfig
        Strategy + credentials configuration.
    dry_run : bool
        If True, tag Telegram message as [DRY RUN] and skip email.
    exit_alerts : list[ExitAlert] | None
        Exit conditions triggered for open positions. None or [] means no exits.
    """
    exits = exit_alerts or []
    telegram_text = _format_telegram(result, config, exits)
    if dry_run:
        telegram_text = f"🔎 <b>[DRY RUN]</b>\n{telegram_text}"

    sent_any = False

    # Email: live mode only
    if not dry_run:
        if config.EMAIL_SENDER and config.EMAIL_PASSWORD and config.EMAIL_RECIPIENT:
            subject, html_body = _format_email(result, config, exits)
            if _send_email(subject, html_body, config):
                sent_any = True
        else:
            logger.debug("Email not configured — skipping.")

    # Telegram: both live and dry-run
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        if _send_telegram(telegram_text, config):
            sent_any = True
    else:
        logger.debug("Telegram not configured — skipping.")

    if not sent_any:
        logger.warning(
            "No alert channels configured. Set EMAIL_* or TELEGRAM_* environment variables."
        )


def send_test_alerts(config) -> None:
    """Send a test message through all configured channels with dummy data.

    Use this to verify credentials and delivery before going live.
    Both channels are tagged [TEST] so they are clearly distinguishable.

    Parameters
    ----------
    config : LiveConfig
        Strategy + credentials configuration.
    """
    test_signal = Signal(
        ticker="TEST",
        close=150.00,
        rsi_2=4.5,
        sma_200=135.00,
        atr=3.00,
        stop_loss=142.50,
        pct_above_sma200=11.1,
        is_supplemental=False,
    )
    result = ScanResult(
        date=pd.Timestamp.today().normalize(),
        is_bullish=True,
        signals=[test_signal],
        tickers_scanned=503,
        tickers_passed_universe=319,
    )

    subject, html_body = _format_email(result, config, [])
    telegram_text = _format_telegram(result, config, [])

    sent_any = False

    if config.EMAIL_SENDER and config.EMAIL_PASSWORD and config.EMAIL_RECIPIENT:
        if _send_email(f"[TEST] {subject}", html_body, config):
            sent_any = True
            logger.info("Test email sent successfully.")
    else:
        logger.warning("Email not configured — skipping test email.")

    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        if _send_telegram(f"🧪 <b>[TEST]</b>\n{telegram_text}", config):
            sent_any = True
            logger.info("Test Telegram message sent successfully.")
    else:
        logger.warning("Telegram not configured — skipping test Telegram.")

    if not sent_any:
        logger.warning("No alert channels configured. Nothing was sent.")


def send_error_alert(error_msg: str, config) -> None:
    """Send an error notification via all configured channels.

    Called when the scanner encounters an unhandled exception, so the user
    knows the system is broken rather than silently not running.

    Parameters
    ----------
    error_msg : str
        A brief description of the error.
    config : LiveConfig
        Strategy + credentials configuration.
    """
    telegram_text = f"⚠️ <b>Scanner error</b>\n<code>{_escape_html(error_msg)}</code>"
    subject = f"{config.EMAIL_SUBJECT_PREFIX} ERROR — scanner failed"
    html_body = f"""<!DOCTYPE html><html><head><style>{_CSS}</style></head><body>
    <h2>MPS Scanner — Error</h2>
    <span class="tag bearish">Scanner Failed</span>
    <div class="notice">
        <strong>Error:</strong> {_escape_html(error_msg)}<br><br>
        Check logs for the full traceback.
    </div>
    </body></html>"""

    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        _send_telegram(telegram_text, config)

    if config.EMAIL_SENDER and config.EMAIL_PASSWORD and config.EMAIL_RECIPIENT:
        _send_email(subject, html_body, config)


def format_dry_run_output(result: ScanResult, config, exit_alerts: list | None = None) -> str:
    """Return a console-friendly summary string for --dry-run mode."""
    exits = exit_alerts or []
    date_str = result.date.strftime("%Y-%m-%d")
    lines = []

    # Exit alerts section
    if exits:
        lines.append(f"\n{'='*58}")
        lines.append(f"EXIT ALERTS — {len(exits)} position(s) to close")
        lines.append(f"{'='*58}")
        for ex in exits:
            pos = ex.position
            if ex.reason == "STOP":
                lines.append(
                    f"  STOP  {pos.ticker}: closed ${ex.current_price:.2f} "
                    f"below stop ${pos.stop_loss:.2f}"
                )
            elif ex.reason == "RSI":
                lines.append(
                    f"  RSI   {pos.ticker}: RSI(2) at {ex.rsi_2:.1f}, above 75. "
                    f"Close next open."
                )
            else:
                lines.append(
                    f"  TIME  {pos.ticker}: held {ex.days_held} trading days. "
                    f"Close next open."
                )
        lines.append("")

    if not result.is_bullish:
        lines.append(f"[{date_str}] Regime: BEARISH — no scan performed.\n")
        return "\n".join(lines)

    if not result.signals:
        lines.append(
            f"[{date_str}] Regime: BULLISH — no signals today.\n"
            f"Scanned {result.tickers_scanned} tickers → "
            f"{result.tickers_passed_universe} passed universe filter → 0 signals.\n"
        )
        return "\n".join(lines)

    lines += [
        f"[{date_str}] Regime: BULLISH — {len(result.signals)} signal(s)",
        f"Scanned {result.tickers_scanned} tickers → "
        f"{result.tickers_passed_universe} passed universe filter\n",
        f"{'Ticker':<10} {'Close':>8} {'RSI(2)':>8} {'%>SMA200':>10} "
        f"{'ATR':>8} {'Stop':>10}",
        "-" * 58,
    ]
    for s in result.signals:
        label = " (SPY)" if s.is_supplemental else ""
        lines.append(
            f"{s.ticker + label:<10} {s.close:>8.2f} {s.rsi_2:>8.2f} "
            f"{s.pct_above_sma200:>9.1f}% {s.atr:>8.2f} {s.stop_loss:>10.2f}"
        )

    lines.append(_checklist_text(config))
    return "\n".join(lines) + "\n"


# ── Email ──────────────────────────────────────────────────────────────────────

def _send_email(subject: str, html_body: str, config) -> bool:
    """Send an HTML email via SMTP. Returns True on success."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_SENDER
    msg["To"] = config.EMAIL_RECIPIENT
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
            server.sendmail(config.EMAIL_SENDER, config.EMAIL_RECIPIENT, msg.as_string())
        logger.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False


# ── Telegram ───────────────────────────────────────────────────────────────────

def _send_telegram(text: str, config) -> bool:
    """Send an HTML-formatted message via the Telegram Bot API. Returns True on success."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Telegram message sent.")
        return True
    except Exception as e:
        logger.error(f"Telegram failed: {e}")
        return False


# ── Formatters ─────────────────────────────────────────────────────────────────

def _format_email(result: ScanResult, config, exits: list) -> tuple[str, str]:
    """Return (subject, html_body) for the scan result, with exits first if present."""
    date_str = result.date.strftime("%Y-%m-%d")
    has_exits = bool(exits)
    has_signals = bool(result.signals)

    # Subject reflects the most urgent content
    if has_exits and has_signals:
        subject = (
            f"{config.EMAIL_SUBJECT_PREFIX} {date_str} — "
            f"{len(exits)} exit(s) + {len(result.signals)} signal(s)"
        )
    elif has_exits:
        subject = f"{config.EMAIL_SUBJECT_PREFIX} {date_str} — {len(exits)} exit alert(s)"
    elif not result.is_bullish:
        subject = f"{config.EMAIL_SUBJECT_PREFIX} {date_str} — Regime BEARISH"
    elif not has_signals:
        subject = f"{config.EMAIL_SUBJECT_PREFIX} {date_str} — No signals today"
    else:
        subject = f"{config.EMAIL_SUBJECT_PREFIX} {date_str} — {len(result.signals)} signal(s)"

    body = _email_body(date_str, result, config, exits)
    return subject, body


def _format_telegram(result: ScanResult, config, exits: list) -> str:
    """Return a concise Telegram message, with exit alerts before entry signals."""
    date_str = result.date.strftime("%Y-%m-%d")
    parts = []

    # Exit section — always shown first if exits exist
    if exits:
        parts.append("🚨 <b>EXIT ALERTS</b>")
        for ex in exits:
            pos = ex.position
            if ex.reason == "STOP":
                parts.append(
                    f"⛔ <b>EXIT (STOP): {pos.ticker}</b>\n"
                    f"  Closed ${ex.current_price:.2f}, below stop ${pos.stop_loss:.2f}\n"
                    f"  Close position at next open."
                )
            elif ex.reason == "RSI":
                parts.append(
                    f"✅ <b>EXIT: {pos.ticker}</b>\n"
                    f"  RSI(2) at {ex.rsi_2:.1f}, above 75 threshold.\n"
                    f"  Close position at next open."
                )
            else:
                parts.append(
                    f"⏰ <b>EXIT (TIME): {pos.ticker}</b>\n"
                    f"  Held {ex.days_held} trading days without RSI exit.\n"
                    f"  Close position at next open."
                )
        parts.append("─" * 20)

    # Entry signals section
    if not result.is_bullish:
        parts.append(
            f"📉 <b>MPS Scanner {date_str}</b>\nRegime: BEARISH — no new trades today."
        )
    elif not result.signals:
        parts.append(
            f"📊 <b>MPS Scanner {date_str}</b>\n"
            f"Regime: BULLISH — no RSI(2) signals today.\n"
            f"({result.tickers_scanned} tickers scanned)"
        )
    else:
        parts.append(f"🔔 <b>MPS Scanner {date_str} — {len(result.signals)} signal(s)</b>\n")
        for s in result.signals:
            label = " 〔SPY〕" if s.is_supplemental else ""
            parts.append(
                f"<b>{s.ticker}</b>{label}\n"
                f"  Close: ${s.close:.2f}  |  RSI(2): {s.rsi_2:.1f}\n"
                f"  Stop: ${s.stop_loss:.2f}  |  ATR: {s.atr:.2f}"
            )
        parts.append(f"\n⚠️ Gap filter: confirm &lt;{config.GAP_FILTER_PCT}% at open")

    return "\n".join(parts)


# ── Checklist helpers ──────────────────────────────────────────────────────────

def _checklist_text(config) -> str:
    return (
        f"\nPre-Trade Checklist:\n"
        f"  1. IV Rank > 30\n"
        f"  2. Expiration 5-8 calendar days out\n"
        f"  3. Sell put at delta -0.25 to -0.35 with $3-5 wide spread\n"
        f"  4. Premium >= 30% of spread width\n"
        f"  5. Bid-ask < 10% of mid-price\n"
        f"  6. Confirm gap from prior close < {config.GAP_FILTER_PCT}% (check manually at open)"
    )


def _escape_html(text: str) -> str:
    """Escape special HTML characters for safe embedding in HTML/Telegram."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── HTML email body ────────────────────────────────────────────────────────────

_CSS = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           max-width: 680px; margin: 0 auto; padding: 24px; color: #333; }
    h2 { color: #1a1a2e; margin-bottom: 4px; }
    h3 { color: #333; margin: 20px 0 8px; }
    .tag { display: inline-block; padding: 4px 10px; border-radius: 4px;
           font-size: 13px; font-weight: 600; margin-bottom: 16px; }
    .bullish { background: #d4edda; color: #155724; }
    .bearish { background: #f8d7da; color: #721c24; }
    .meta { color: #6c757d; font-size: 13px; margin-bottom: 20px; }
    .notice { background: #f8f9fa; border-left: 4px solid #6c757d;
              padding: 12px 16px; border-radius: 4px; }
    table { border-collapse: collapse; width: 100%; margin: 12px 0 20px; }
    th { background: #1a1a2e; color: white; padding: 10px 12px;
         text-align: left; font-size: 13px; }
    td { padding: 9px 12px; border-bottom: 1px solid #eee; font-size: 14px; }
    tr:hover td { background: #f8f9fa; }
    .spy td { background: #e8f4fd; font-style: italic; }
    .spy:hover td { background: #d1ecf1; }
    .exit-table th { background: #721c24; }
    .exit-stop td { background: #fff0f0; }
    .exit-rsi  td { background: #f0fff4; }
    .exit-time td { background: #fffbf0; }
    .checklist { background: #fffbf0; border: 1px solid #ffeeba;
                 border-radius: 6px; padding: 16px 20px; margin-top: 24px; }
    .checklist h3 { margin: 0 0 10px; color: #856404; font-size: 13px;
                    text-transform: uppercase; letter-spacing: 0.5px; }
    .checklist ol { margin: 0; padding-left: 20px; }
    .checklist li { margin: 5px 0; font-size: 14px; }
    hr { border: none; border-top: 1px solid #eee; margin: 24px 0; }
"""


def _email_body(date_str: str, result: ScanResult, config, exits: list) -> str:
    """Build the full HTML email body."""
    regime_tag = (
        '<span class="tag bullish">Regime: BULLISH</span>'
        if result.is_bullish
        else '<span class="tag bearish">Regime: BEARISH</span>'
    )

    sections = [
        f'<!DOCTYPE html><html><head><style>{_CSS}</style></head><body>',
        f'<h2>MPS Scanner — {date_str}</h2>',
        regime_tag,
    ]

    # ── Exit alerts section (above entry signals) ──────────────────────────────
    if exits:
        exit_rows = ""
        for ex in exits:
            pos = ex.position
            if ex.reason == "STOP":
                css = "exit-stop"
                label = "⛔ Stop Loss"
                detail = f"Closed ${ex.current_price:.2f}, below stop ${pos.stop_loss:.2f}"
            elif ex.reason == "RSI":
                css = "exit-rsi"
                label = "✅ RSI Exit"
                detail = f"RSI(2) = {ex.rsi_2:.1f} (above 75)"
            else:
                css = "exit-time"
                label = "⏰ Time Stop"
                detail = f"Held {ex.days_held} trading days"
            exit_rows += f"""<tr class="{css}">
                <td><strong>{pos.ticker}</strong></td>
                <td>{label}</td>
                <td>${ex.current_price:.2f}</td>
                <td>{detail}</td>
                <td>Close at next open</td>
            </tr>"""

        sections.append(f"""
        <h3>⚠️ Exit Alerts — {len(exits)} position(s) to close</h3>
        <table>
            <tr class="exit-table">
                <th>Ticker</th><th>Reason</th><th>Last Close</th>
                <th>Detail</th><th>Action</th>
            </tr>
            {exit_rows}
        </table>
        <hr>""")

    # ── Entry signals section ──────────────────────────────────────────────────
    if not result.is_bullish:
        sections.append("""<div class="notice">
            SPY is below SMA-200 or SMA-50 is below SMA-200.<br>
            No new trades today. Existing positions are managed normally.
        </div>""")
    elif not result.signals:
        sections.append(f"""<div class="notice">
            No RSI(2) signals triggered today.<br>
            <span class="meta">
                {result.tickers_scanned} tickers scanned →
                {result.tickers_passed_universe} passed universe filter → 0 signals.
            </span>
        </div>""")
    else:
        rows = ""
        for s in result.signals:
            row_class = "spy" if s.is_supplemental else ""
            label = " (SPY)" if s.is_supplemental else ""
            rows += f"""<tr class="{row_class}">
                <td><strong>{s.ticker}</strong>{label}</td>
                <td>${s.close:.2f}</td>
                <td><strong>{s.rsi_2:.2f}</strong></td>
                <td>+{s.pct_above_sma200:.1f}%</td>
                <td>{s.atr:.2f}</td>
                <td>${s.stop_loss:.2f}</td>
            </tr>"""

        checklist_items = "".join([
            "<li>Check IV Rank &gt; 30</li>",
            "<li>Select expiration 5–8 calendar days out</li>",
            "<li>Sell put at delta −0.25 to −0.35 with $3–5 wide spread</li>",
            "<li>Verify premium ≥ 30% of spread width</li>",
            "<li>Check bid-ask &lt; 10% of mid-price</li>",
            f"<li>Confirm gap from prior close &lt; {config.GAP_FILTER_PCT}% "
            f"(check manually at open)</li>",
        ])

        sections.append(f"""
        <p class="meta">
            {result.tickers_scanned} tickers scanned →
            {result.tickers_passed_universe} passed universe filter →
            <strong>{len(result.signals)} signal(s)</strong> &nbsp;|&nbsp;
            sorted by RSI(2) ascending (most oversold first)
        </p>
        <table>
            <tr>
                <th>Ticker</th><th>Close</th><th>RSI(2)</th>
                <th>% Above SMA-200</th><th>ATR(14)</th><th>Stop Loss</th>
            </tr>
            {rows}
        </table>
        <div class="checklist">
            <h3>Pre-Trade Checklist</h3>
            <ol>{checklist_items}</ol>
        </div>""")

    sections.append("</body></html>")
    return "\n".join(sections)
