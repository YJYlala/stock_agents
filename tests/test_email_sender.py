"""Tests for email_sender module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_news_digest.config import Settings
from ai_news_digest.email_sender import EmailSender
from ai_news_digest.models import ArticleSummary, SummaryDigest


@pytest.fixture
def settings() -> Settings:
    return Settings(
        email={
            "smtp_host": "smtp.test.com",
            "smtp_port": 587,
            "sender_env": "EMAIL_SENDER",
            "password_env": "EMAIL_PASSWORD",
            "recipients": ["user@example.com"],
        },
        cache={"enabled": False},
    )


@pytest.fixture
def sample_digest() -> SummaryDigest:
    return SummaryDigest(
        date="2026-04-14",
        overall_summary="Big day in AI: GPT-5 released and EU passes new regulation.",
        key_trends=["Model releases", "AI regulation", "Open source"],
        article_summaries=[
            ArticleSummary(
                title="GPT-5 Released",
                source="TechCrunch",
                url="https://tc.com/gpt5",
                summary="OpenAI releases GPT-5 with improved reasoning.",
                relevance="Major upgrade to the most popular LLM.",
            ),
            ArticleSummary(
                title="EU AI Act Passed",
                source="BBC",
                url="https://bbc.com/eu-ai",
                summary="European Union passes comprehensive AI regulation.",
                relevance="Sets precedent for global AI governance.",
            ),
        ],
        total_articles_fetched=15,
    )


# ------------------------------------------------------------------
# HTML Rendering
# ------------------------------------------------------------------

class TestHTMLRendering:
    def test_render_html_contains_content(self, settings, sample_digest):
        sender = EmailSender(settings)
        html = sender.render_html(sample_digest)

        assert "AI News Digest" in html
        assert "GPT-5 Released" in html
        assert "EU AI Act Passed" in html
        assert "Model releases" in html
        assert "2026-04-14" in html
        assert "15 articles curated" in html
        assert "https://tc.com/gpt5" in html

    def test_render_html_is_valid_html(self, settings, sample_digest):
        sender = EmailSender(settings)
        html = sender.render_html(sample_digest)

        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<body>" in html

    def test_render_html_empty_trends(self, settings):
        digest = SummaryDigest(
            overall_summary="Quiet day.",
            article_summaries=[],
            total_articles_fetched=0,
        )
        sender = EmailSender(settings)
        html = sender.render_html(digest)
        assert "Quiet day." in html


# ------------------------------------------------------------------
# Plain text rendering
# ------------------------------------------------------------------

class TestPlainText:
    def test_plain_text_contains_content(self, settings, sample_digest):
        sender = EmailSender(settings)
        text = sender._plain_text(sample_digest)

        assert "AI News Digest" in text
        assert "GPT-5 Released" in text
        assert "Model releases" in text
        assert "https://tc.com/gpt5" in text


# ------------------------------------------------------------------
# Email sending (mocked SMTP)
# ------------------------------------------------------------------

class TestEmailSend:
    @patch("ai_news_digest.email_sender.smtplib.SMTP")
    def test_send_success(self, mock_smtp_class, settings, sample_digest):
        """Successful email send."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", {
            "EMAIL_SENDER": "test@gmail.com",
            "EMAIL_PASSWORD": "app-password-123",
        }):
            sender = EmailSender(Settings(
                email={
                    "sender_env": "EMAIL_SENDER",
                    "password_env": "EMAIL_PASSWORD",
                    "recipients": ["user@example.com"],
                },
                cache={"enabled": False},
            ))
            result = sender.send(sample_digest)

        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test@gmail.com", "app-password-123")
        mock_server.sendmail.assert_called_once()

    def test_send_no_recipients(self, settings, sample_digest):
        """No recipients → returns False."""
        settings_no_recip = Settings(
            email={"recipients": []},
            cache={"enabled": False},
        )
        sender = EmailSender(settings_no_recip)
        result = sender.send(sample_digest)
        assert result is False

    def test_send_no_credentials(self, settings, sample_digest):
        """Missing credentials → returns False."""
        with patch.dict("os.environ", {}, clear=True):
            sender = EmailSender(Settings(
                email={
                    "sender_env": "NONEXISTENT_SENDER",
                    "password_env": "NONEXISTENT_PASS",
                    "recipients": ["user@example.com"],
                },
                cache={"enabled": False},
            ))
            result = sender.send(sample_digest)
        assert result is False

    @patch("ai_news_digest.email_sender.smtplib.SMTP")
    def test_send_smtp_auth_error(self, mock_smtp_class, settings, sample_digest):
        """SMTP auth failure → returns False."""
        import smtplib
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", {
            "EMAIL_SENDER": "test@gmail.com",
            "EMAIL_PASSWORD": "wrong-password",
        }):
            sender = EmailSender(Settings(
                email={
                    "sender_env": "EMAIL_SENDER",
                    "password_env": "EMAIL_PASSWORD",
                    "recipients": ["user@example.com"],
                },
                cache={"enabled": False},
            ))
            result = sender.send(sample_digest)

        assert result is False
