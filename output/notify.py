"""Notification channels for sending analysis reports.

Stock-agents-specific: markdown_to_email_html, build_report_email_html.
Core send functions re-exported from genai-common.
"""

from __future__ import annotations

import re

# Re-export core notification functions from genai-common
from genai_common.notify import (
    send_email,
    send_telegram,
    send_wechat_webhook,
    send_pushplus,
    send_all,
)


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
