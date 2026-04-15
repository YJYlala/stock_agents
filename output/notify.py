"""Notification channels for sending analysis reports.

Supports: Email (SMTP), Telegram Bot, 企业微信 Webhook, PushPlus (个人微信推送).
Each channel is optional — if credentials are missing, it logs a warning and skips.

Edit the `schedule.notification` section in config.yaml to enable channels.
"""

from __future__ import annotations

import json
import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


# ── Markdown → inline-styled HTML (email-safe) ───────────────────────

def markdown_to_email_html(md_text: str) -> str:
    """Convert markdown report to inline-styled HTML suitable for email clients.

    Email clients strip <style> tags, so all CSS must be inline.
    Handles: headers, tables (with scroll wrapper), lists, blockquotes, bold,
    horizontal rules, and <details> blocks (converted to collapsible sections).
    """
    # Convert <details>/<summary> to visible sections with a styled header
    converted_lines: list[str] = []
    in_details = False
    for line in md_text.split("\n"):
        if "<details>" in line:
            in_details = True
            continue
        if "<summary>" in line and "</summary>" in line:
            # Extract summary text and render as a styled sub-header
            import re as _re
            m = _re.search(r"<summary>(.*?)</summary>", line)
            title = m.group(1) if m else "原始数据"
            converted_lines.append(f"### 📊 {title}")
            continue
        if "</details>" in line:
            in_details = False
            converted_lines.append("---")
            continue
        converted_lines.append(line)

    lines = converted_lines
    html: list[str] = []
    in_table = False
    in_list = False
    in_blockquote = False
    row_even = False

    _FONT = "-apple-system,PingFang SC,Microsoft YaHei,sans-serif"

    for line in lines:
        s = line.strip()

        # Empty line — close open blocks
        if not s:
            if in_table:
                html.append("</table></div>")
                in_table = False
            if in_list:
                html.append("</ul>")
                in_list = False
            if in_blockquote:
                html.append("</blockquote>")
                in_blockquote = False
            continue

        # Headers
        if s.startswith("# ") and not s.startswith("## "):
            html.append(
                f'<h1 style="color:#1a73e8;font-size:20px;border-bottom:3px solid #1a73e8;'
                f'padding-bottom:8px;font-family:{_FONT};">{s[2:]}</h1>'
            )
            continue
        if s.startswith("## "):
            html.append(
                f'<h2 style="color:#333;font-size:15px;margin-top:16px;padding:6px 10px;'
                f'background:#f0f4ff;border-left:4px solid #1a73e8;border-radius:4px;'
                f'font-family:{_FONT};">{s[3:]}</h2>'
            )
            continue
        if s.startswith("### "):
            html.append(
                f'<h3 style="color:#555;font-size:14px;font-family:{_FONT};">{s[4:]}</h3>'
            )
            continue

        # Blockquote
        if s.startswith("> "):
            if not in_blockquote:
                html.append(
                    '<blockquote style="background:#fff8e1;border-left:4px solid #ffc107;'
                    'padding:8px 12px;margin:8px 0;font-size:13px;color:#795548;">'
                )
                in_blockquote = True
            html.append(s[2:])
            continue

        # Table
        if "|" in s and s.startswith("|"):
            cols = [c.strip() for c in s.split("|")[1:-1]]
            # Skip separator row (|---|---|)
            if all(set(c) <= set("-: ") for c in cols):
                continue
            if not in_table:
                html.append(
                    '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;margin:8px 0;">'
                    '<table style="border-collapse:collapse;width:100%;min-width:500px;'
                    f'font-size:12px;font-family:{_FONT};table-layout:auto;">'
                )
                html.append("<tr>")
                for c in cols:
                    html.append(
                        f'<th style="background:#1a73e8;color:white;padding:6px 8px;'
                        f'text-align:left;white-space:nowrap;font-size:12px;">{c}</th>'
                    )
                html.append("</tr>")
                in_table = True
                row_even = False
            else:
                row_even = not row_even
                bg = "#f8f9ff" if row_even else "white"
                html.append("<tr>")
                for c in cols:
                    st = (
                        f"padding:5px 8px;border-bottom:1px solid #e8e8e8;"
                        f"white-space:nowrap;font-size:12px;background:{bg};"
                    )
                    if c in ("BUY", "买入"):
                        st += "color:#d32f2f;font-weight:bold;"
                    elif c in ("SELL", "卖出"):
                        st += "color:#2e7d32;font-weight:bold;"
                    elif c in ("HOLD", "持有"):
                        st += "color:#f57c00;font-weight:bold;"
                    if re.match(r"^[+-].*%$", c):
                        st += "color:#d32f2f;" if c.startswith("+") else "color:#2e7d32;"
                    html.append(f'<td style="{st}">{c}</td>')
                html.append("</tr>")
            continue

        # Horizontal rule
        if s == "---":
            if in_table:
                html.append("</table></div>")
                in_table = False
            html.append('<hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">')
            continue

        # List item
        if s.startswith("- "):
            if not in_list:
                html.append('<ul style="padding-left:20px;margin:6px 0;">')
                in_list = True
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s[2:])
            html.append(
                f'<li style="margin:3px 0;font-size:13px;line-height:1.6;color:#333;">{text}</li>'
            )
            continue

        # Paragraph
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        html.append(f'<p style="font-size:13px;line-height:1.8;color:#333;margin:6px 0;">{text}</p>')

    # Close any open blocks
    if in_table:
        html.append("</table></div>")
    if in_list:
        html.append("</ul>")
    if in_blockquote:
        html.append("</blockquote>")

    return "\n".join(html)


def build_report_email_html(
    title: str,
    subtitle: str,
    reports_markdown: list[str],
) -> str:
    """Wrap multiple markdown report sections into a complete styled HTML email."""
    body = (
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "</head>"
        '<body style="font-family:-apple-system,PingFang SC,Microsoft YaHei,sans-serif;'
        'max-width:800px;margin:0 auto;padding:12px;color:#1a1a1a;background:#f5f5f5;">'
        '<div style="background:white;border-radius:12px;padding:16px 20px;'
        'margin-bottom:12px;box-shadow:0 2px 8px rgba(0,0,0,0.06);">'
        f'<h1 style="color:#1a73e8;font-size:22px;margin:0 0 4px 0;">{title}</h1>'
        f'<p style="color:#888;font-size:13px;margin:0;">{subtitle}</p>'
        "</div>"
    )

    for md in reports_markdown:
        body += (
            '<div style="background:white;border-radius:12px;padding:16px 20px;'
            'margin-bottom:12px;box-shadow:0 2px 8px rgba(0,0,0,0.06);">'
            f"{markdown_to_email_html(md)}</div>"
        )

    body += (
        '<p style="text-align:center;color:#aaa;font-size:11px;margin-top:16px;">'
        "Generated by Stock Agents Multi-Agent System</p>"
        "</body></html>"
    )
    return body


def _resolve_env_or_value(key: str) -> str:
    """Resolve a config value — try as env var name first, then use as direct value."""
    env_val = os.getenv(key, "")
    if env_val:
        return env_val
    # If the key looks like a direct value (contains @ or non-ASCII), use it directly
    if "@" in key or not key.replace("_", "").isupper():
        return key
    return ""


def send_email(
    subject: str,
    body_html: str,
    to_addr: str | list[str],
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
    from_addr_env: str = "EMAIL_FROM",
    password_env: str = "EMAIL_PASSWORD",
) -> bool:
    """Send an email via SMTP. Supports single or multiple recipients. Returns True on success."""
    from_addr = _resolve_env_or_value(from_addr_env)
    password = _resolve_env_or_value(password_env)
    if not from_addr or not password:
        logger.warning(
            "Email skipped: set %s and %s environment variables",
            from_addr_env, password_env,
        )
        return False

    # Normalize to list
    recipients = to_addr if isinstance(to_addr, list) else [to_addr]
    recipients = [r for r in recipients if r]
    if not recipients:
        logger.warning("Email skipped: no recipients configured")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        if smtp_port == 465:
            # SSL connection (163, QQ)
            with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30) as server:
                server.login(from_addr, password)
                server.sendmail(from_addr, recipients, msg.as_string())
        elif smtp_port == 25:
            # Plain SMTP, try STARTTLS if available (163 port 25)
            with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                try:
                    server.starttls()
                except smtplib.SMTPNotSupportedError:
                    pass
                server.login(from_addr, password)
                server.sendmail(from_addr, recipients, msg.as_string())
        else:
            # STARTTLS (Gmail 587)
            with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                server.starttls()
                server.login(from_addr, password)
                server.sendmail(from_addr, recipients, msg.as_string())
        logger.info("Email sent to %s", ", ".join(recipients))
        return True
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return False


def send_telegram(
    body_text: str,
    bot_token_env: str = "TELEGRAM_BOT_TOKEN",
    chat_id_env: str = "TELEGRAM_CHAT_ID",
) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    bot_token = os.getenv(bot_token_env, "")
    chat_id = os.getenv(chat_id_env, "")
    if not bot_token or not chat_id:
        logger.warning(
            "Telegram skipped: set %s and %s environment variables",
            bot_token_env, chat_id_env,
        )
        return False

    import urllib.request
    import urllib.error

    # Telegram max message length is 4096 chars — split if needed
    chunks = _split_text(body_text, 4000)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    success = True
    for chunk in chunks:
        payload = json.dumps({
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    logger.error("Telegram API returned %d", resp.status)
                    success = False
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.error("Telegram send failed: %s", e)
            success = False

    if success:
        logger.info("Telegram message sent to chat %s", chat_id)
    return success


def send_wechat_webhook(
    body_text: str,
    webhook_url_env: str = "WECHAT_WEBHOOK_URL",
) -> bool:
    """Send a message via 企业微信 Webhook. Returns True on success."""
    webhook_url = os.getenv(webhook_url_env, "")
    if not webhook_url:
        logger.warning(
            "WeChat skipped: set %s environment variable", webhook_url_env,
        )
        return False

    import urllib.request
    import urllib.error

    # WeChat webhook max 4096 chars per message
    chunks = _split_text(body_text, 4000)

    success = True
    for chunk in chunks:
        payload = json.dumps({
            "msgtype": "markdown",
            "markdown": {"content": chunk},
        }).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                if result.get("errcode") != 0:
                    logger.error("WeChat webhook error: %s", result)
                    success = False
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.error("WeChat send failed: %s", e)
            success = False

    if success:
        logger.info("WeChat webhook message sent")
    return success


def send_pushplus(
    subject: str,
    body_html: str,
    token_env: str = "PUSHPLUS_TOKEN",
) -> bool:
    """Send a message via PushPlus to personal WeChat. Returns True on success.

    Sign up at https://www.pushplus.plus — follow the 公众号, get your token
    from the dashboard, then set PUSHPLUS_TOKEN in .env or environment.
    """
    token = os.getenv(token_env, "")
    if not token:
        logger.warning("PushPlus skipped: set %s environment variable", token_env)
        return False

    import urllib.request
    import urllib.error

    payload = json.dumps({
        "token": token,
        "title": subject,
        "content": body_html,
        "template": "html",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if result.get("code") != 200:
                logger.error("PushPlus error: %s", result)
                return False
        logger.info("PushPlus message sent to WeChat")
        return True
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        logger.error("PushPlus send failed: %s", e)
        return False


def send_all(
    subject: str,
    body_markdown: str,
    body_html: str,
    notification_config,
) -> dict[str, bool]:
    """Send via all enabled channels. Returns {channel: success} dict."""
    results: dict[str, bool] = {}

    if getattr(notification_config, "email", None) and notification_config.email.enabled:
        cfg = notification_config.email
        results["email"] = send_email(
            subject=subject,
            body_html=body_html,
            to_addr=cfg.to_addr,
            smtp_server=cfg.smtp_server,
            smtp_port=cfg.smtp_port,
            from_addr_env=cfg.from_addr_env,
            password_env=cfg.password_env,
        )

    if getattr(notification_config, "telegram", None) and notification_config.telegram.enabled:
        cfg = notification_config.telegram
        results["telegram"] = send_telegram(
            body_text=body_markdown,
            bot_token_env=cfg.bot_token_env,
            chat_id_env=cfg.chat_id_env,
        )

    if getattr(notification_config, "wechat", None) and notification_config.wechat.enabled:
        cfg = notification_config.wechat
        results["wechat"] = send_wechat_webhook(
            body_text=body_markdown,
            webhook_url_env=cfg.webhook_url_env,
        )

    if getattr(notification_config, "pushplus", None) and notification_config.pushplus.enabled:
        cfg = notification_config.pushplus
        results["pushplus"] = send_pushplus(
            subject=subject,
            body_html=body_html,
            token_env=cfg.token_env,
        )

    if not results:
        logger.info("No notification channels enabled")

    return results


def _split_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks, preferring line breaks."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find last newline within limit
        cut = text.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks
