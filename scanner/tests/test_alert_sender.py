from __future__ import annotations

"""Tests for alert_sender.py.

All HTTP and SMTP calls are mocked — no real messages are sent.

Run from the project root:
    pytest scanner/tests/test_alert_sender.py
"""

import smtplib
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scanner.alert_sender import (
    send_alerts,
    send_error_alert,
    send_test_alerts,
    format_dry_run_output,
)
from scanner.signal_detector import ScanResult, Signal


# ── Helpers ────────────────────────────────────────────────────────────────────

class _FullConfig:
    """Mock config with all credentials populated."""
    EMAIL_SENDER = "sender@example.com"
    EMAIL_PASSWORD = "app_password"
    EMAIL_RECIPIENT = "recipient@example.com"
    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587
    EMAIL_SUBJECT_PREFIX = "[MPS Scanner]"
    TELEGRAM_BOT_TOKEN = "fake_token"
    TELEGRAM_CHAT_ID = "fake_chat_id"
    GAP_FILTER_PCT = 3.0
    SUPPLEMENTAL_TICKERS = ["SPY"]


class _NoCredsConfig(_FullConfig):
    """Mock config with no credentials — both channels disabled."""
    EMAIL_SENDER = ""
    EMAIL_PASSWORD = ""
    EMAIL_RECIPIENT = ""
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""


def _make_result(signals: list[Signal] | None = None, is_bullish: bool = True) -> ScanResult:
    return ScanResult(
        date=pd.Timestamp("2025-12-31"),
        is_bullish=is_bullish,
        signals=signals or [],
        tickers_scanned=503,
        tickers_passed_universe=319,
    )


def _make_signal(ticker: str = "AAPL", rsi_2: float = 5.0) -> Signal:
    return Signal(
        ticker=ticker, close=150.0, rsi_2=rsi_2, sma_200=135.0,
        atr=3.0, stop_loss=142.5, pct_above_sma200=11.1,
    )


def _mock_smtp():
    """Return a context-manager-compatible SMTP mock."""
    mock_server = MagicMock()
    mock_smtp_cls = MagicMock()
    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_smtp_cls, mock_server


# ── send_alerts: live mode ──────────────────────────────────────────────────────

class TestSendAlertsLive:
    def test_signals_sends_email_and_telegram(self):
        result = _make_result([_make_signal()])
        mock_smtp_cls, mock_server = _mock_smtp()

        with patch("scanner.alert_sender.requests.post") as mock_post, \
             patch("scanner.alert_sender.smtplib.SMTP", mock_smtp_cls):
            mock_post.return_value.raise_for_status = MagicMock()
            send_alerts(result, _FullConfig())

        mock_server.sendmail.assert_called_once()
        mock_post.assert_called_once()

    def test_no_signals_sends_email_and_telegram(self):
        result = _make_result([])
        mock_smtp_cls, mock_server = _mock_smtp()

        with patch("scanner.alert_sender.requests.post") as mock_post, \
             patch("scanner.alert_sender.smtplib.SMTP", mock_smtp_cls):
            mock_post.return_value.raise_for_status = MagicMock()
            send_alerts(result, _FullConfig())

        mock_server.sendmail.assert_called_once()
        mock_post.assert_called_once()

    def test_bearish_sends_email_and_telegram(self):
        result = _make_result(is_bullish=False)
        mock_smtp_cls, mock_server = _mock_smtp()

        with patch("scanner.alert_sender.requests.post") as mock_post, \
             patch("scanner.alert_sender.smtplib.SMTP", mock_smtp_cls):
            mock_post.return_value.raise_for_status = MagicMock()
            send_alerts(result, _FullConfig())

        mock_server.sendmail.assert_called_once()
        mock_post.assert_called_once()

    def test_telegram_failure_does_not_block_email(self):
        """If Telegram raises, email should still be sent."""
        result = _make_result([_make_signal()])
        mock_smtp_cls, mock_server = _mock_smtp()

        with patch("scanner.alert_sender.requests.post", side_effect=Exception("network error")), \
             patch("scanner.alert_sender.smtplib.SMTP", mock_smtp_cls):
            send_alerts(result, _FullConfig())

        mock_server.sendmail.assert_called_once()

    def test_email_failure_does_not_block_telegram(self):
        """If SMTP raises, Telegram should still be sent."""
        result = _make_result([_make_signal()])
        mock_smtp_cls = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(side_effect=smtplib.SMTPException("auth failed"))
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scanner.alert_sender.requests.post") as mock_post, \
             patch("scanner.alert_sender.smtplib.SMTP", mock_smtp_cls):
            mock_post.return_value.raise_for_status = MagicMock()
            send_alerts(result, _FullConfig())

        mock_post.assert_called_once()


# ── send_alerts: dry-run mode ──────────────────────────────────────────────────

class TestSendAlertsDryRun:
    def test_dry_run_sends_telegram_not_email(self):
        """Dry-run should send Telegram but skip email."""
        result = _make_result([_make_signal()])
        mock_smtp_cls, mock_server = _mock_smtp()

        with patch("scanner.alert_sender.requests.post") as mock_post, \
             patch("scanner.alert_sender.smtplib.SMTP", mock_smtp_cls):
            mock_post.return_value.raise_for_status = MagicMock()
            send_alerts(result, _FullConfig(), dry_run=True)

        mock_post.assert_called_once()
        mock_server.sendmail.assert_not_called()

    def test_dry_run_telegram_message_contains_dry_run_tag(self):
        """Telegram message in dry-run must contain '[DRY RUN]' so it's clearly distinguishable."""
        result = _make_result([_make_signal()])
        captured = []

        def capture_post(url, json=None, timeout=None):
            captured.append(json)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("scanner.alert_sender.requests.post", side_effect=capture_post):
            send_alerts(result, _FullConfig(), dry_run=True)

        assert captured, "Telegram post was not called"
        assert "[DRY RUN]" in captured[0]["text"]


# ── send_test_alerts ───────────────────────────────────────────────────────────

class TestSendTestAlerts:
    def test_sends_via_both_channels(self):
        mock_smtp_cls, mock_server = _mock_smtp()

        with patch("scanner.alert_sender.requests.post") as mock_post, \
             patch("scanner.alert_sender.smtplib.SMTP", mock_smtp_cls):
            mock_post.return_value.raise_for_status = MagicMock()
            send_test_alerts(_FullConfig())

        mock_server.sendmail.assert_called_once()
        mock_post.assert_called_once()

    def test_email_subject_contains_test_tag(self):
        import email as email_lib
        from email.header import decode_header as decode_hdr

        mock_smtp_cls, mock_server = _mock_smtp()

        with patch("scanner.alert_sender.requests.post") as mock_post, \
             patch("scanner.alert_sender.smtplib.SMTP", mock_smtp_cls):
            mock_post.return_value.raise_for_status = MagicMock()
            send_test_alerts(_FullConfig())

        raw_message = mock_server.sendmail.call_args[0][2]
        msg = email_lib.message_from_string(raw_message)
        # Subject may be MIME-encoded (Base64/QP) — decode before asserting
        parts = decode_hdr(msg["Subject"])
        subject = "".join(
            p.decode(enc or "utf-8") if isinstance(p, bytes) else p
            for p, enc in parts
        )
        assert "[TEST]" in subject

    def test_telegram_message_contains_test_tag(self):
        captured = []

        def capture_post(url, json=None, timeout=None):
            captured.append(json)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("scanner.alert_sender.requests.post", side_effect=capture_post), \
             patch("scanner.alert_sender.smtplib.SMTP", _mock_smtp()[0]):
            send_test_alerts(_FullConfig())

        assert "[TEST]" in captured[0]["text"]

    def test_no_channels_configured_does_not_raise(self):
        """send_test_alerts should log a warning, not crash, when nothing is configured."""
        send_test_alerts(_NoCredsConfig())  # no mock needed — channels skipped


# ── send_error_alert ───────────────────────────────────────────────────────────

class TestSendErrorAlert:
    def test_sends_via_both_channels(self):
        mock_smtp_cls, mock_server = _mock_smtp()

        with patch("scanner.alert_sender.requests.post") as mock_post, \
             patch("scanner.alert_sender.smtplib.SMTP", mock_smtp_cls):
            mock_post.return_value.raise_for_status = MagicMock()
            send_error_alert("Something went wrong", _FullConfig())

        mock_server.sendmail.assert_called_once()
        mock_post.assert_called_once()

    def test_error_message_in_telegram_text(self):
        captured = []

        def capture_post(url, json=None, timeout=None):
            captured.append(json)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("scanner.alert_sender.requests.post", side_effect=capture_post):
            send_error_alert("SPY data unavailable", _FullConfig())

        assert "SPY data unavailable" in captured[0]["text"]

    def test_html_chars_escaped_in_error_message(self):
        """An error message with <, >, & must be escaped in the Telegram payload."""
        captured = []

        def capture_post(url, json=None, timeout=None):
            captured.append(json)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("scanner.alert_sender.requests.post", side_effect=capture_post):
            send_error_alert("KeyError: <date> & 'ticker'", _FullConfig())

        text = captured[0]["text"]
        assert "<date>" not in text       # raw angle brackets must not appear
        assert "&lt;date&gt;" in text


# ── format_dry_run_output ──────────────────────────────────────────────────────

class TestFormatDryRunOutput:
    def test_bearish_output(self):
        result = _make_result(is_bullish=False)
        output = format_dry_run_output(result, _FullConfig())
        assert "BEARISH" in output

    def test_no_signals_output(self):
        result = _make_result([])
        output = format_dry_run_output(result, _FullConfig())
        assert "no signals" in output.lower()

    def test_signals_output_contains_ticker(self):
        result = _make_result([_make_signal("AAPL")])
        output = format_dry_run_output(result, _FullConfig())
        assert "AAPL" in output

    def test_signals_output_contains_checklist(self):
        result = _make_result([_make_signal()])
        output = format_dry_run_output(result, _FullConfig())
        assert "Checklist" in output
