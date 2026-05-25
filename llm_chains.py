"""
emailer.py — Email dispatcher for the OCP AI Monitoring Agent.

Supports two backends, selected via cfg.email_backend:
  - smtp     : Standard SMTP with STARTTLS (default, works with Gmail/Exchange)
  - sendgrid : SendGrid API v3 (for cloud/containerised deployments)

Public API:
    dispatch(subject, html_body)

    Called by send_email_node() in nodes.py. Never raises — errors are logged
    and surfaced as EmailDispatchError so the caller can decide how to handle.

Design decisions:
  - Backend is selected once per call from cfg; no global state
  - HTML body is always sent with a plain-text fallback (strips tags)
  - SMTP connection is opened and closed per dispatch — safe for long-running
    processes where the SMTP server may drop idle connections
  - SendGrid path uses httpx (already in requirements) — no extra dependency
  - All credentials come from cfg; nothing is hardcoded here
"""

from __future__ import annotations

import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

import httpx

from agent.config import get_settings
from agent.logger import get_logger

log = get_logger(__name__)
cfg = get_settings()


# ──────────────────────────────────────────────────────────────────────────────
# Custom exception
# ──────────────────────────────────────────────────────────────────────────────

class EmailDispatchError(RuntimeError):
    """Raised when email dispatch fails after all retries."""


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _html_to_plaintext(html: str) -> str:
    """
    Minimal HTML → plain text conversion for the fallback MIME part.
    Strips tags, collapses whitespace, and decodes common HTML entities.
    Not a full parser — just enough for a readable fallback.
    """
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _build_mime(subject: str, html_body: str, recipients: List[str]) -> MIMEMultipart:
    """Construct a multipart/alternative MIME message."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = cfg.email_from
    msg["To"]      = ", ".join(recipients)

    plain = _html_to_plaintext(html_body)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


# ──────────────────────────────────────────────────────────────────────────────
# SMTP backend
# ──────────────────────────────────────────────────────────────────────────────

def _dispatch_smtp(subject: str, html_body: str, recipients: List[str]) -> None:
    """
    Send via SMTP with STARTTLS.

    Opens a fresh connection per call so long-lived agent processes
    don't hit idle-timeout disconnections from the SMTP server.
    """
    log.info(
        "smtp_dispatch_start",
        host=cfg.smtp_host,
        port=cfg.smtp_port,
        recipients=recipients,
    )

    msg = _build_mime(subject, html_body, recipients)

    context = ssl.create_default_context()

    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as server:
            server.ehlo()
            if cfg.smtp_use_tls:
                server.starttls(context=context)
                server.ehlo()
            server.login(cfg.smtp_user, cfg.smtp_password)
            server.sendmail(cfg.email_from, recipients, msg.as_string())

        log.info("smtp_dispatch_done", recipients=recipients, subject=subject[:80])

    except smtplib.SMTPAuthenticationError as exc:
        raise EmailDispatchError(f"SMTP authentication failed: {exc}") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise EmailDispatchError(f"All recipients refused: {exc}") from exc
    except smtplib.SMTPException as exc:
        raise EmailDispatchError(f"SMTP error: {exc}") from exc
    except OSError as exc:
        raise EmailDispatchError(f"SMTP connection error ({cfg.smtp_host}:{cfg.smtp_port}): {exc}") from exc


# ──────────────────────────────────────────────────────────────────────────────
# SendGrid backend
# ──────────────────────────────────────────────────────────────────────────────

_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


def _dispatch_sendgrid(subject: str, html_body: str, recipients: List[str]) -> None:
    """
    Send via SendGrid Mail Send API v3.
    Uses httpx (already a project dependency) — no sendgrid SDK needed at runtime.
    """
    log.info("sendgrid_dispatch_start", recipients=recipients)

    payload = {
        "personalizations": [
            {"to": [{"email": addr} for addr in recipients]}
        ],
        "from":    {"email": cfg.email_from},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": _html_to_plaintext(html_body)},
            {"type": "text/html",  "value": html_body},
        ],
    }

    try:
        response = httpx.post(
            _SENDGRID_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {cfg.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
        log.info(
            "sendgrid_dispatch_done",
            status_code=response.status_code,
            recipients=recipients,
        )

    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:200]
        raise EmailDispatchError(
            f"SendGrid API error {exc.response.status_code}: {body}"
        ) from exc
    except httpx.RequestError as exc:
        raise EmailDispatchError(f"SendGrid connection error: {exc}") from exc


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def dispatch(subject: str, html_body: str) -> None:
    """
    Send the HTML report email via the configured backend.

    Args:
        subject:   Email subject line (pre-formatted by send_email_node).
        html_body: Complete HTML report string from reporter.build_html_report().

    Raises:
        EmailDispatchError: If the selected backend fails to deliver.
            send_email_node catches this and logs it without re-raising.

    The recipient list is always read from cfg.email_recipients so this
    function stays stateless and easy to test.
    """
    recipients = cfg.email_recipients
    if not recipients:
        raise EmailDispatchError("No email recipients configured (EMAIL_TO is empty).")

    backend = cfg.email_backend.lower()

    if backend == "smtp":
        _dispatch_smtp(subject, html_body, recipients)
    elif backend == "sendgrid":
        _dispatch_sendgrid(subject, html_body, recipients)
    else:
        raise EmailDispatchError(
            f"Unknown email backend '{backend}'. Set EMAIL_BACKEND to 'smtp' or 'sendgrid'."
        )
