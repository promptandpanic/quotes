"""
Email notifications on post success or failure.
Works with any SMTP provider — Gmail, Outlook, Yahoo, custom domain, etc.

Required env / GitHub secrets:
  SMTP_USERNAME   — sender address (e.g. yourname@gmail.com)
  SMTP_PASSWORD   — SMTP password or App Password
  NOTIFY_EMAILS   — comma-separated recipient list

Optional (defaults to Gmail):
  SMTP_HOST       — SMTP server hostname  (default: smtp.gmail.com)
  SMTP_PORT       — SMTP SSL port         (default: 465)

Common providers:
  Gmail:   SMTP_HOST=smtp.gmail.com       SMTP_PORT=465  (use App Password)
  Outlook: SMTP_HOST=smtp.office365.com   SMTP_PORT=587
  Yahoo:   SMTP_HOST=smtp.mail.yahoo.com  SMTP_PORT=465
"""
import logging
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))


def _recipients() -> list[str]:
    raw = os.environ.get("NOTIFY_EMAILS", "").strip()
    return [e.strip() for e in raw.split(",") if e.strip()]


def _sender() -> tuple[str, str]:
    return (
        os.environ.get("SMTP_USERNAME", ""),
        os.environ.get("SMTP_PASSWORD", ""),
    )


def _build_success_email(theme_name: str, quote: dict, post_id: str) -> tuple[str, str, str]:
    subject = f"✅ [Daily Wisdom] Posted — {theme_name}"
    ist_time = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    text = f"""\
Post went live successfully!

Theme   : {theme_name}
Time    : {ist_time}
Post ID : {post_id}

Quote
-----
"{quote.get('text', '')}"
— {quote.get('author', '@_daily_dose_of_wisdom__')}

Score   : {quote.get('score', 'N/A')} / 10  (LLM validation)

https://www.instagram.com/_daily_dose_of_wisdom__/
"""

    html = f"""\
<html><body style="font-family:sans-serif;max-width:520px;margin:auto;color:#222">
  <h2 style="color:#22c55e">✅ Post Live — {theme_name}</h2>
  <p style="color:#666;font-size:13px">{ist_time}</p>
  <blockquote style="border-left:4px solid #22c55e;padding:10px 16px;
                     background:#f0fdf4;border-radius:4px;margin:16px 0">
    <em style="font-size:17px">"{quote.get('text', '')}"</em><br>
    <strong style="color:#555">— {quote.get('author', '@_daily_dose_of_wisdom__')}</strong>
  </blockquote>
  {"<p><strong>LLM score:</strong> " + str(quote.get('score')) + " / 10</p>" if quote.get('score') else ""}
  <p><strong>Post ID:</strong> {post_id}</p>
  <p><a href="https://www.instagram.com/_daily_dose_of_wisdom__/"
        style="color:#6366f1">View on Instagram →</a></p>
</body></html>"""

    return subject, text, html


def _build_failure_email(theme_name: str, quote: dict | None, reason: str) -> tuple[str, str, str]:
    subject = f"❌ [Daily Wisdom] Post FAILED — {theme_name}"
    ist_time = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    quote_block = ""
    if quote:
        quote_block = f'\nQuote that failed to post\n-------------------------\n"{quote.get("text", "")}"\n— {quote.get("author", "")}\n'

    text = f"""\
The scheduled post failed.

Theme   : {theme_name}
Time    : {ist_time}
Reason  : {reason}
{quote_block}
Check the GitHub Actions log for details:
https://github.com/{os.environ.get("GITHUB_REPOSITORY", "your/repo")}/actions
"""

    html = f"""\
<html><body style="font-family:sans-serif;max-width:520px;margin:auto;color:#222">
  <h2 style="color:#ef4444">❌ Post Failed — {theme_name}</h2>
  <p style="color:#666;font-size:13px">{ist_time}</p>
  <div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:12px 16px;margin:16px 0">
    <strong>Reason:</strong> {reason}
  </div>
  {"<blockquote style='border-left:4px solid #f87171;padding:10px 16px;background:#fff5f5;border-radius:4px'><em>" + quote.get('text','') + "</em></blockquote>" if quote else ""}
  <p><a href="https://github.com/{os.environ.get('GITHUB_REPOSITORY','your/repo')}/actions"
        style="color:#6366f1">View Actions log →</a></p>
</body></html>"""

    return subject, text, html


def _send(subject: str, text_body: str, html_body: str) -> bool:
    recipients = _recipients()
    if not recipients:
        logger.info("NOTIFY_EMAILS not set — skipping email notification")
        return True

    username, password = _sender()
    if not username or not password:
        logger.warning("SMTP_USERNAME / SMTP_PASSWORD not set — skipping email")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    display_name = os.environ.get("SMTP_DISPLAY_NAME", "Daily Dose of Wisdom")
    msg["From"] = f"{display_name} <{username}>"
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        ctx = ssl.create_default_context()
        if SMTP_PORT == 587:
            # STARTTLS (Outlook, some custom providers)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.login(username, password)
                server.sendmail(username, recipients, msg.as_string())
        else:
            # SSL direct (Gmail, Yahoo, default)
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
                server.login(username, password)
                server.sendmail(username, recipients, msg.as_string())
        logger.info(f"✓ Email sent to: {', '.join(recipients)}")
        return True
    except Exception as exc:
        logger.error(f"Email send failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Public helpers called from main.py
# ---------------------------------------------------------------------------

def notify_success(theme_name: str, quote: dict, post_id: str) -> None:
    subject, text, html = _build_success_email(theme_name, quote, post_id)
    _send(subject, text, html)


def notify_failure(theme_name: str, quote: dict | None, reason: str) -> None:
    subject, text, html = _build_failure_email(theme_name, quote, reason)
    _send(subject, text, html)
