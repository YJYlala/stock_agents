"""CLI entry point for AI News Digest.

Usage:
    python -m ai_news_digest                  # full pipeline: fetch → summarize → email
    python -m ai_news_digest --fetch-only     # just fetch and print articles
    python -m ai_news_digest --no-email       # fetch + summarize, skip email
    python -m ai_news_digest --save           # also save digest to reports/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.logging import RichHandler

from ai_news_digest.config import load_settings

console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    # Suppress noisy loggers
    for name in ("httpx", "openai", "urllib3", "feedparser"):
        logging.getLogger(name).setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ai-news-digest",
        description="Fetch, summarize, and email the latest AI news.",
    )
    parser.add_argument(
        "--fetch-only", action="store_true",
        help="Only fetch articles, don't summarize or email",
    )
    parser.add_argument(
        "--no-email", action="store_true",
        help="Fetch and summarize, but don't send email",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save digest to reports/ directory",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    console.print(Panel.fit(
        "[bold magenta]🤖 AI News Digest[/bold magenta]",
        subtitle="fetch → summarize → email",
    ))

    settings = load_settings()

    # ── Step 1: Fetch ──────────────────────────────────────────
    console.print("\n[bold cyan]Step 1:[/] Fetching AI news...")
    from ai_news_digest.news_fetcher import NewsFetcher

    fetcher = NewsFetcher(settings)
    articles = fetcher.fetch_all()

    if not articles:
        console.print("[bold red]No articles found![/] Check your network or config.")
        sys.exit(1)

    # Show fetched articles table
    table = Table(title=f"📰 {len(articles)} Articles Fetched", show_lines=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Title", max_width=55)
    table.add_column("Source", style="cyan", max_width=20)
    table.add_column("Date", style="green", width=12)
    for i, a in enumerate(articles[:20], 1):
        date_str = a.published_at.strftime("%Y-%m-%d") if a.published_at else "—"
        table.add_row(str(i), a.title[:55], a.source[:20], date_str)
    console.print(table)

    if args.fetch_only:
        console.print("[green]✓ Done (fetch only mode)[/]")
        return

    # ── Step 2: Summarize ──────────────────────────────────────
    console.print("\n[bold cyan]Step 2:[/] Summarizing with LLM...")
    from ai_news_digest.news_summarizer import NewsSummarizer

    summarizer = NewsSummarizer(settings)
    digest = summarizer.summarize(articles)

    # Display digest
    console.print(Panel(digest.overall_summary, title="📝 Overall Summary", border_style="blue"))

    if digest.key_trends:
        trends = " • ".join(digest.key_trends)
        console.print(f"\n[bold]🔥 Key Trends:[/] {trends}")

    console.print(f"\n[dim]Summarized {len(digest.article_summaries)} articles[/]")

    # Save if requested
    if args.save:
        _save_digest(digest)

    if args.no_email:
        console.print("[green]✓ Done (no-email mode)[/]")
        return

    # ── Step 3: Email ──────────────────────────────────────────
    console.print("\n[bold cyan]Step 3:[/] Sending email...")
    from ai_news_digest.email_sender import EmailSender

    sender = EmailSender(settings)
    success = sender.send(digest)

    if success:
        console.print("[bold green]✓ Email sent successfully![/]")
    else:
        console.print("[bold yellow]⚠ Email not sent — check logs above[/]")
        # Still save the digest so user has it
        if not args.save:
            _save_digest(digest)
            console.print("[dim]Digest saved to reports/ instead[/]")


def _save_digest(digest) -> None:
    """Save digest as JSON + rendered HTML to reports/."""
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON
    json_path = reports_dir / f"ai_digest_{ts}.json"
    json_path.write_text(
        digest.model_dump_json(indent=2),
        encoding="utf-8",
    )

    # HTML
    from ai_news_digest.email_sender import EmailSender
    from ai_news_digest.config import load_settings
    html_path = reports_dir / f"ai_digest_{ts}.html"
    sender = EmailSender(load_settings())
    html_path.write_text(sender.render_html(digest), encoding="utf-8")

    console.print(f"[green]✓ Saved:[/] {json_path} & {html_path}")
