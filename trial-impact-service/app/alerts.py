"""Outbound alerts for market-moving trial readouts.

Two channels, both optional and independently configured:

* **Slack** — POST a formatted message to an incoming-webhook URL.
* **Email** — send via SMTP.

``notify`` fans out to whichever channels are configured and returns the list of
channels that actually sent, so the caller can record that an alert fired. It is
invoked at most once per event (guarded by the ``alert_sent`` bookkeeping flag in
the DB), mirroring the idempotent-comment pattern of the original bot.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

import requests

_TIMEOUT_SECONDS = 15


class Alerter:
    """Sends alerts over the channels enabled by config."""

    def __init__(self, config) -> None:
        self.cfg = config

    def notify(self, event: dict[str, Any], assessment: dict[str, Any]) -> list[str]:
        """Send the assessment to all configured channels; return channel names."""
        subject = _subject(event, assessment)
        body = assessment.get("commentary", "")
        sent: list[str] = []

        if self.cfg.slack_configured:
            try:
                self.send_slack(subject, body)
                sent.append("slack")
            except requests.RequestException:
                pass

        if self.cfg.email_configured:
            try:
                self.send_email(subject, body)
                sent.append("email")
            except OSError:  # smtplib raises socket/OSError subclasses
                pass

        return sent

    def send_slack(self, subject: str, body: str) -> None:
        resp = requests.post(
            self.cfg.slack_webhook_url,
            json={"text": f"*{subject}*\n```{body}```"},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()

    def send_email(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.cfg.email_from
        msg["To"] = self.cfg.email_to
        msg.set_content(body)

        with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=_TIMEOUT_SECONDS) as s:
            s.starttls()
            if self.cfg.smtp_user:
                s.login(self.cfg.smtp_user, self.cfg.smtp_password)
            s.send_message(msg)


def _subject(event: dict[str, Any], assessment: dict[str, Any]) -> str:
    tickers = ", ".join(
        c["ticker"] for c in assessment.get("price_calls", []) if c.get("ticker")
    )
    return (
        f"[Trial Impact] {event.get('sponsor', '')} {event.get('nct_id', '')} "
        f"endpoint {event.get('endpoint_outcome', 'unknown')} "
        f"(PoS {assessment.get('pos_delta', 0):+.2f}) — {tickers}"
    )
