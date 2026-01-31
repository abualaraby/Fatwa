"""Tests for capture modules."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from database import Database, Ticket, SourcePlatform
from capture import FacebookCapture, InstagramCapture, EmailCapture


class TestFacebookCapture:
    """Tests for Facebook capture module."""

    @pytest.fixture
    def fb_capture(self, database, sample_config):
        """Create Facebook capture instance."""
        return FacebookCapture(sample_config["facebook"], database)

    def test_initialization(self, fb_capture):
        """Test Facebook capture initialization."""
        assert fb_capture.platform_name == "Facebook"
        assert fb_capture.enabled is True
        assert fb_capture._is_logged_in is False

    def test_is_question_arabic(self, fb_capture):
        """Test Arabic question detection."""
        # Arabic questions
        assert fb_capture._is_question("ما حكم الصلاة في البيت؟") is True
        assert fb_capture._is_question("هل يجوز الصيام بدون نية؟") is True
        assert fb_capture._is_question("سؤال عن الزكاة") is True
        assert fb_capture._is_question("أفتوني في هذه المسألة") is True

        # Not questions
        assert fb_capture._is_question("مرحبا") is False
        assert fb_capture._is_question("شكرا") is False
        assert fb_capture._is_question("") is False
        assert fb_capture._is_question("hi") is False

    def test_is_question_english(self, fb_capture):
        """Test English question detection."""
        assert fb_capture._is_question("What is the ruling on fasting?") is True
        assert fb_capture._is_question("Is it halal to eat this?") is True
        assert fb_capture._is_question("Can I pray at home?") is True

        assert fb_capture._is_question("Thank you") is False
        assert fb_capture._is_question("Hello") is False

    def test_save_ticket_new(self, fb_capture, database):
        """Test saving a new ticket."""
        ticket = Ticket(
            source_platform=SourcePlatform.FACEBOOK_DM,
            sender_id="fb_123",
            sender_name="Test User",
            question_text="ما حكم الصلاة؟"
        )

        ticket_id = fb_capture.save_ticket(ticket)

        assert ticket_id is not None
        saved = database.get_ticket(ticket_id)
        assert saved.sender_name == "Test User"

    def test_save_ticket_duplicate(self, fb_capture, database):
        """Test that duplicate tickets are not saved."""
        ticket = Ticket(
            source_platform=SourcePlatform.FACEBOOK_DM,
            sender_id="fb_123",
            sender_name="Test User",
            question_text="ما حكم الصلاة؟"
        )

        # First save
        ticket_id1 = fb_capture.save_ticket(ticket)
        assert ticket_id1 is not None

        # Duplicate save
        ticket_id2 = fb_capture.save_ticket(ticket)
        assert ticket_id2 is None

    @pytest.mark.asyncio
    async def test_capture_all_disabled(self, sample_config, database):
        """Test capture when disabled."""
        config = sample_config["facebook"].copy()
        config["enabled"] = False
        capture = FacebookCapture(config, database)

        tickets = await capture.capture_all()
        assert tickets == []

    @pytest.mark.asyncio
    async def test_close(self, fb_capture):
        """Test closing capture module."""
        await fb_capture.close()
        assert fb_capture._is_logged_in is False
        assert fb_capture._page is None


class TestInstagramCapture:
    """Tests for Instagram capture module."""

    @pytest.fixture
    def ig_capture(self, database, sample_config):
        """Create Instagram capture instance."""
        return InstagramCapture(sample_config["instagram"], database)

    def test_initialization(self, ig_capture):
        """Test Instagram capture initialization."""
        assert ig_capture.platform_name == "Instagram"
        assert ig_capture.enabled is True

    def test_is_question(self, ig_capture):
        """Test question detection."""
        assert ig_capture._is_question("ما هي شروط الزكاة؟") is True
        assert ig_capture._is_question("Is fasting required?") is True
        assert ig_capture._is_question("جزاكم الله خيرا على هذا السؤال") is True

    @pytest.mark.asyncio
    async def test_capture_all_disabled(self, sample_config, database):
        """Test capture when disabled."""
        config = sample_config["instagram"].copy()
        config["enabled"] = False
        capture = InstagramCapture(config, database)

        tickets = await capture.capture_all()
        assert tickets == []


class TestEmailCapture:
    """Tests for Email capture module."""

    @pytest.fixture
    def email_capture(self, database, sample_config):
        """Create Email capture instance."""
        return EmailCapture(sample_config["email"], database)

    def test_initialization(self, email_capture):
        """Test Email capture initialization."""
        assert email_capture.platform_name == "Email"
        assert email_capture.imap_server == "imap.gmail.com"

    def test_decode_header_plain(self, email_capture):
        """Test decoding plain header."""
        result = email_capture._decode_header("Test Subject")
        assert result == "Test Subject"

    def test_decode_header_none(self, email_capture):
        """Test decoding None header."""
        result = email_capture._decode_header(None)
        assert result == ""

    def test_parse_sender_with_name(self, email_capture):
        """Test parsing sender with name."""
        name, email_addr = email_capture._parse_sender("Ahmed <ahmed@example.com>")
        assert name == "Ahmed"
        assert email_addr == "ahmed@example.com"

    def test_parse_sender_email_only(self, email_capture):
        """Test parsing sender with email only."""
        name, email_addr = email_capture._parse_sender("test@example.com")
        assert name == "test@example.com"
        assert email_addr == "test@example.com"

    def test_parse_sender_empty(self, email_capture):
        """Test parsing empty sender."""
        name, email_addr = email_capture._parse_sender("")
        assert name == "Unknown"
        assert email_addr == ""

    def test_html_to_text(self, email_capture):
        """Test HTML to text conversion."""
        html = "<p>Hello <b>World</b></p><br><p>Test</p>"
        text = email_capture._html_to_text(html)

        assert "Hello" in text
        assert "World" in text
        assert "<p>" not in text
        assert "<b>" not in text

    def test_html_to_text_with_entities(self, email_capture):
        """Test HTML entity decoding."""
        html = "Test &amp; &lt;value&gt;"
        text = email_capture._html_to_text(html)

        assert "Test & <value>" in text

    def test_is_question(self, email_capture):
        """Test question detection in email."""
        assert email_capture._is_question("Subject: سؤال\n\nما حكم كذا؟") is True
        assert email_capture._is_question("Subject: Question\n\nIs this halal?") is True
        assert email_capture._is_question("Subject: Hello\n\nJust saying hi") is False

    @pytest.mark.asyncio
    async def test_capture_comments_returns_empty(self, email_capture):
        """Test that capture_comments returns empty for email."""
        result = await email_capture.capture_comments()
        assert result == []

    @pytest.mark.asyncio
    async def test_close(self, email_capture):
        """Test closing email capture."""
        await email_capture.close()
        assert email_capture._is_logged_in is False


class TestCaptureIntegration:
    """Integration tests for capture modules."""

    def test_ticket_saved_to_database(self, database, sample_config):
        """Test that captured tickets are saved to database."""
        fb_capture = FacebookCapture(sample_config["facebook"], database)

        ticket = Ticket(
            source_platform=SourcePlatform.FACEBOOK_DM,
            sender_id="unique_sender",
            sender_name="Test",
            question_text="ما هو حكم الصلاة؟"
        )

        ticket_id = fb_capture.save_ticket(ticket)

        # Verify in database
        saved = database.get_ticket(ticket_id)
        assert saved is not None
        assert saved.source_platform == SourcePlatform.FACEBOOK_DM

    def test_multiple_platforms_save_correctly(self, database, sample_config):
        """Test tickets from different platforms save correctly."""
        fb_capture = FacebookCapture(sample_config["facebook"], database)
        ig_capture = InstagramCapture(sample_config["instagram"], database)
        email_capture = EmailCapture(sample_config["email"], database)

        # Save from each platform
        fb_ticket = Ticket(
            source_platform=SourcePlatform.FACEBOOK_DM,
            sender_id="fb_1",
            sender_name="FB User",
            question_text="سؤال من فيسبوك؟"
        )
        fb_capture.save_ticket(fb_ticket)

        ig_ticket = Ticket(
            source_platform=SourcePlatform.INSTAGRAM_DM,
            sender_id="ig_1",
            sender_name="IG User",
            question_text="سؤال من انستغرام؟"
        )
        ig_capture.save_ticket(ig_ticket)

        email_ticket = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="email_1",
            sender_name="Email User",
            question_text="سؤال من البريد؟"
        )
        email_capture.save_ticket(email_ticket)

        # Verify all saved
        all_tickets = database.get_all_tickets()
        assert len(all_tickets) == 3

        platforms = [t.source_platform for t in all_tickets]
        assert SourcePlatform.FACEBOOK_DM in platforms
        assert SourcePlatform.INSTAGRAM_DM in platforms
        assert SourcePlatform.EMAIL in platforms
