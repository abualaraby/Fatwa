"""Tests for dispatch modules."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from database import Database, Ticket, TicketStatus, SourcePlatform
from dispatch import Dispatcher, FacebookDispatch, InstagramDispatch, EmailDispatch


class TestFacebookDispatch:
    """Tests for Facebook dispatch module."""

    @pytest.fixture
    def fb_dispatch(self, database, sample_config):
        """Create Facebook dispatch instance."""
        return FacebookDispatch(sample_config["facebook"], database)

    def test_initialization(self, fb_dispatch):
        """Test Facebook dispatch initialization."""
        assert fb_dispatch.email == "test@facebook.com"
        assert fb_dispatch._is_logged_in is False

    def test_format_reply(self, fb_dispatch, replied_ticket):
        """Test reply formatting."""
        reply = fb_dispatch._format_reply(replied_ticket)

        assert "السلام عليكم" in reply
        assert str(replied_ticket.id) in reply
        assert replied_ticket.answer_text in reply

    @pytest.mark.asyncio
    async def test_send_reply_dm(self, fb_dispatch, replied_ticket):
        """Test sending DM reply."""
        replied_ticket.source_platform = SourcePlatform.FACEBOOK_DM

        # Mock login and page
        fb_dispatch._is_logged_in = True
        fb_dispatch._page = AsyncMock()

        fb_dispatch.send_dm_reply = AsyncMock(return_value=True)

        result = await fb_dispatch.send_reply(replied_ticket)

        assert result is True

    @pytest.mark.asyncio
    async def test_send_reply_comment(self, fb_dispatch, replied_ticket):
        """Test sending comment reply."""
        replied_ticket.source_platform = SourcePlatform.FACEBOOK_COMMENT
        replied_ticket.original_post_id = "https://facebook.com/post/123"

        fb_dispatch._is_logged_in = True
        fb_dispatch.send_comment_reply = AsyncMock(return_value=True)

        result = await fb_dispatch.send_reply(replied_ticket)

        assert result is True

    @pytest.mark.asyncio
    async def test_send_reply_wrong_platform(self, fb_dispatch, replied_ticket):
        """Test sending reply for wrong platform."""
        replied_ticket.source_platform = SourcePlatform.EMAIL

        result = await fb_dispatch.send_reply(replied_ticket)

        assert result is False

    @pytest.mark.asyncio
    async def test_close(self, fb_dispatch):
        """Test closing dispatch module."""
        await fb_dispatch.close()
        assert fb_dispatch._is_logged_in is False


class TestInstagramDispatch:
    """Tests for Instagram dispatch module."""

    @pytest.fixture
    def ig_dispatch(self, database, sample_config):
        """Create Instagram dispatch instance."""
        return InstagramDispatch(sample_config["instagram"], database)

    def test_initialization(self, ig_dispatch):
        """Test Instagram dispatch initialization."""
        assert ig_dispatch.username == "testuser"
        assert ig_dispatch._is_logged_in is False

    def test_format_reply_full(self, ig_dispatch, replied_ticket):
        """Test full reply formatting."""
        reply = ig_dispatch._format_reply(replied_ticket, short=False)

        assert "السلام عليكم" in reply
        assert str(replied_ticket.id) in reply

    def test_format_reply_short(self, ig_dispatch, replied_ticket):
        """Test short reply formatting for comments."""
        reply = ig_dispatch._format_reply(replied_ticket, short=True)

        assert "الجواب" in reply
        assert len(reply) < 500  # Short format should be limited

    @pytest.mark.asyncio
    async def test_send_reply_dm(self, ig_dispatch, replied_ticket):
        """Test sending Instagram DM reply."""
        replied_ticket.source_platform = SourcePlatform.INSTAGRAM_DM

        ig_dispatch._is_logged_in = True
        ig_dispatch.send_dm_reply = AsyncMock(return_value=True)

        result = await ig_dispatch.send_reply(replied_ticket)

        assert result is True

    @pytest.mark.asyncio
    async def test_send_reply_comment(self, ig_dispatch, sample_ig_ticket):
        """Test sending Instagram comment reply."""
        sample_ig_ticket.answer_text = "هذا هو الجواب"
        sample_ig_ticket.status = TicketStatus.REPLIED

        ig_dispatch._is_logged_in = True
        ig_dispatch.send_comment_reply = AsyncMock(return_value=True)

        result = await ig_dispatch.send_reply(sample_ig_ticket)

        assert result is True


class TestEmailDispatch:
    """Tests for Email dispatch module."""

    @pytest.fixture
    def email_dispatch(self, database, sample_config):
        """Create Email dispatch instance."""
        return EmailDispatch(sample_config["email"], database)

    def test_initialization(self, email_dispatch):
        """Test Email dispatch initialization."""
        assert email_dispatch.smtp_server == "smtp.gmail.com"
        assert email_dispatch.smtp_port == 587

    def test_format_reply_text(self, email_dispatch, replied_ticket):
        """Test plain text email formatting."""
        text = email_dispatch._format_reply_text(replied_ticket)

        assert "السلام عليكم" in text
        assert replied_ticket.sender_name in text
        assert replied_ticket.question_text in text
        assert replied_ticket.answer_text in text
        assert str(replied_ticket.id) in text

    def test_format_reply_html(self, email_dispatch, replied_ticket):
        """Test HTML email formatting."""
        html = email_dispatch._format_reply_html(replied_ticket)

        assert "<!DOCTYPE html>" in html
        assert replied_ticket.sender_name in html
        assert "dir=\"rtl\"" in html  # Arabic RTL support
        assert str(replied_ticket.id) in html

    @pytest.mark.asyncio
    async def test_send_reply_wrong_platform(self, email_dispatch, replied_ticket):
        """Test sending reply for non-email platform."""
        replied_ticket.source_platform = SourcePlatform.FACEBOOK_DM

        result = await email_dispatch.send_reply(replied_ticket)

        assert result is False

    @pytest.mark.asyncio
    async def test_send_reply_no_contact(self, email_dispatch, replied_ticket):
        """Test sending reply without contact info."""
        replied_ticket.source_platform = SourcePlatform.EMAIL
        replied_ticket.sender_contact = ""

        result = await email_dispatch.send_reply(replied_ticket)

        assert result is False

    @pytest.mark.asyncio
    async def test_send_reply_success(self, email_dispatch, replied_ticket):
        """Test successful email sending."""
        replied_ticket.source_platform = SourcePlatform.EMAIL
        replied_ticket.sender_contact = "test@example.com"

        # Mock SMTP
        mock_smtp = MagicMock()
        email_dispatch._smtp = mock_smtp
        email_dispatch._connect = MagicMock(return_value=True)

        result = await email_dispatch.send_reply(replied_ticket)

        assert result is True
        mock_smtp.sendmail.assert_called_once()


class TestDispatcher:
    """Tests for main Dispatcher module."""

    @pytest.fixture
    def dispatcher(self, database, sample_config):
        """Create Dispatcher instance."""
        return Dispatcher(sample_config, database)

    def test_initialization(self, dispatcher):
        """Test Dispatcher initialization."""
        assert dispatcher._facebook_enabled is True
        assert dispatcher._instagram_enabled is True
        assert dispatcher._email_enabled is True

    @pytest.mark.asyncio
    async def test_dispatch_ticket_not_replied(self, dispatcher, assigned_ticket):
        """Test dispatching ticket that hasn't been replied."""
        result = await dispatcher.dispatch_ticket(assigned_ticket)
        assert result is False

    @pytest.mark.asyncio
    async def test_dispatch_ticket_no_answer(self, dispatcher, replied_ticket):
        """Test dispatching ticket without answer."""
        replied_ticket.answer_text = None

        result = await dispatcher.dispatch_ticket(replied_ticket)
        assert result is False

    @pytest.mark.asyncio
    async def test_dispatch_ticket_email(self, dispatcher, replied_ticket):
        """Test dispatching email ticket."""
        replied_ticket.source_platform = SourcePlatform.EMAIL
        replied_ticket.sender_contact = "test@example.com"

        # Mock email dispatch
        mock_email = AsyncMock()
        mock_email.send_reply = AsyncMock(return_value=True)
        dispatcher._email = mock_email

        result = await dispatcher.dispatch_ticket(replied_ticket)

        assert result is True
        mock_email.send_reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_ticket_facebook(self, dispatcher, replied_ticket):
        """Test dispatching Facebook ticket."""
        replied_ticket.source_platform = SourcePlatform.FACEBOOK_DM

        # Mock Facebook dispatch
        mock_fb = AsyncMock()
        mock_fb.send_reply = AsyncMock(return_value=True)
        dispatcher._facebook = mock_fb

        result = await dispatcher.dispatch_ticket(replied_ticket)

        assert result is True

    @pytest.mark.asyncio
    async def test_dispatch_ticket_instagram(self, dispatcher, replied_ticket):
        """Test dispatching Instagram ticket."""
        replied_ticket.source_platform = SourcePlatform.INSTAGRAM_DM

        # Mock Instagram dispatch
        mock_ig = AsyncMock()
        mock_ig.send_reply = AsyncMock(return_value=True)
        dispatcher._instagram = mock_ig

        result = await dispatcher.dispatch_ticket(replied_ticket)

        assert result is True

    @pytest.mark.asyncio
    async def test_dispatch_all_replied(self, dispatcher, database, sample_ticket):
        """Test dispatching all replied tickets."""
        # Create and reply to ticket
        sample_ticket.source_platform = SourcePlatform.EMAIL
        ticket_id = database.create_ticket(sample_ticket)
        database.assign_shaikh(ticket_id, 1, "966501234567")
        database.mark_sent_to_shaikh(ticket_id)
        database.record_reply(ticket_id, "الجواب هنا")

        # Mock email dispatch
        mock_email = AsyncMock()
        mock_email.send_reply = AsyncMock(return_value=True)
        dispatcher._email = mock_email

        results = await dispatcher.dispatch_all_replied()

        assert results["total"] == 1
        assert results["success"] == 1
        assert results["failed"] == 0

    @pytest.mark.asyncio
    async def test_dispatch_by_id(self, dispatcher, replied_ticket):
        """Test dispatching by ticket ID."""
        replied_ticket.source_platform = SourcePlatform.EMAIL
        replied_ticket.sender_contact = "test@example.com"

        mock_email = AsyncMock()
        mock_email.send_reply = AsyncMock(return_value=True)
        dispatcher._email = mock_email

        result = await dispatcher.dispatch_by_id(replied_ticket.id)

        assert result is True

    @pytest.mark.asyncio
    async def test_dispatch_by_id_not_found(self, dispatcher):
        """Test dispatching non-existent ticket."""
        result = await dispatcher.dispatch_by_id(99999)
        assert result is False

    @pytest.mark.asyncio
    async def test_dispatch_disabled_platform(self, dispatcher, replied_ticket, sample_config):
        """Test dispatching when platform is disabled."""
        # Create dispatcher with Facebook disabled
        sample_config["facebook"]["enabled"] = False
        dispatcher_disabled = Dispatcher(sample_config, dispatcher.database)

        replied_ticket.source_platform = SourcePlatform.FACEBOOK_DM

        result = await dispatcher_disabled.dispatch_ticket(replied_ticket)

        assert result is False

    @pytest.mark.asyncio
    async def test_close(self, dispatcher):
        """Test closing all dispatchers."""
        # Mock all dispatchers
        mock_fb = AsyncMock()
        mock_ig = AsyncMock()
        mock_email = AsyncMock()

        dispatcher._facebook = mock_fb
        dispatcher._instagram = mock_ig
        dispatcher._email = mock_email

        await dispatcher.close()

        mock_fb.close.assert_called_once()
        mock_ig.close.assert_called_once()
        mock_email.close.assert_called_once()


class TestDispatchIntegration:
    """Integration tests for dispatch flow."""

    @pytest.mark.asyncio
    async def test_full_dispatch_flow(self, database, sample_config):
        """Test complete dispatch flow."""
        dispatcher = Dispatcher(sample_config, database)

        # Create email ticket
        ticket = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="email_test",
            sender_name="Test User",
            sender_contact="user@example.com",
            question_text="ما حكم كذا؟"
        )
        ticket_id = database.create_ticket(ticket)

        # Process through status flow
        database.assign_shaikh(ticket_id, 1, "966501234567")
        database.mark_sent_to_shaikh(ticket_id)
        database.record_reply(ticket_id, "الجواب الشرعي هنا")

        # Mock email dispatch
        mock_email = AsyncMock()
        mock_email.send_reply = AsyncMock(return_value=True)
        dispatcher._email = mock_email

        # Dispatch
        result = await dispatcher.dispatch_by_id(ticket_id)

        assert result is True

        # Verify final status
        final_ticket = database.get_ticket(ticket_id)
        assert final_ticket.status == TicketStatus.FINAL_SENT
        assert final_ticket.final_sent_at is not None

        await dispatcher.close()
