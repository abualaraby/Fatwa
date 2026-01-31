"""Integration tests for the complete Fatwa Management System."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from database import Database, Ticket, TicketStatus, SourcePlatform
from capture import FacebookCapture, InstagramCapture, EmailCapture
from whatsapp import WhatsAppBridge, WhatsAppSender, WhatsAppListener
from dispatch import Dispatcher


class TestCompleteWorkflow:
    """Test complete workflow from capture to dispatch."""

    @pytest.mark.asyncio
    async def test_email_complete_flow(self, database, sample_config, mock_whatsapp_bridge):
        """Test complete flow for email inquiry."""
        wa_config = sample_config["whatsapp"]
        wa_config["shaikhs"] = sample_config["shaikhs"]

        # Step 1: Capture - Create email inquiry
        email_capture = EmailCapture(sample_config["email"], database)

        ticket = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="email_user_1",
            sender_name="محمد أحمد",
            sender_contact="mohammed@example.com",
            question_text="ما حكم صلاة التراويح في البيت؟",
            original_message_id="<msg123@example.com>"
        )

        ticket_id = email_capture.save_ticket(ticket)
        assert ticket_id is not None

        # Verify ticket saved
        saved_ticket = database.get_ticket(ticket_id)
        assert saved_ticket.status == TicketStatus.PENDING

        # Step 2: Assignment - Assign to Shaikh
        database.assign_shaikh(ticket_id, 1, "966501234567")

        assigned_ticket = database.get_ticket(ticket_id)
        assert assigned_ticket.status == TicketStatus.ASSIGNED
        assert assigned_ticket.assigned_shaikh_phone == "966501234567"

        # Step 3: Send to Shaikh via WhatsApp
        sender = WhatsAppSender(wa_config, database, mock_whatsapp_bridge)
        mock_whatsapp_bridge.is_connected = AsyncMock(return_value=True)
        mock_whatsapp_bridge.send_message = AsyncMock(return_value={"success": True})

        sent = await sender.send_to_shaikh(assigned_ticket)
        assert sent is True

        sent_ticket = database.get_ticket(ticket_id)
        assert sent_ticket.status == TicketStatus.SENT_TO_SHAIKH

        # Step 4: Receive Shaikh reply
        listener = WhatsAppListener(wa_config, database, mock_whatsapp_bridge)

        mock_whatsapp_bridge.get_messages = AsyncMock(return_value=[
            {
                "id": "wa_msg_1",
                "from": "966501234567",
                "text": f"#{ticket_id} صلاة التراويح سنة مؤكدة ويجوز أداؤها في البيت",
                "timestamp": datetime.now().isoformat()
            }
        ])
        mock_whatsapp_bridge.clear_messages = AsyncMock(return_value=True)

        processed = await listener.check_for_replies()
        assert processed == 1

        replied_ticket = database.get_ticket(ticket_id)
        assert replied_ticket.status == TicketStatus.REPLIED
        assert "التراويح" in replied_ticket.answer_text

        # Step 5: Dispatch reply back to email
        dispatcher = Dispatcher(sample_config, database)

        mock_email = AsyncMock()
        mock_email.send_reply = AsyncMock(return_value=True)
        dispatcher._email = mock_email

        result = await dispatcher.dispatch_ticket(replied_ticket)
        assert result is True

        final_ticket = database.get_ticket(ticket_id)
        assert final_ticket.status == TicketStatus.FINAL_SENT

        await dispatcher.close()

    @pytest.mark.asyncio
    async def test_facebook_complete_flow(self, database, sample_config, mock_whatsapp_bridge):
        """Test complete flow for Facebook inquiry."""
        wa_config = sample_config["whatsapp"]
        wa_config["shaikhs"] = sample_config["shaikhs"]

        # Step 1: Capture Facebook DM
        fb_capture = FacebookCapture(sample_config["facebook"], database)

        ticket = Ticket(
            source_platform=SourcePlatform.FACEBOOK_DM,
            sender_id="fb_user_123",
            sender_name="أحمد علي",
            sender_contact="https://facebook.com/user123",
            question_text="هل يجوز الصيام بدون سحور؟",
            original_message_id="fb_msg_456"
        )

        ticket_id = fb_capture.save_ticket(ticket)
        assert ticket_id is not None

        # Step 2: Assign
        database.assign_shaikh(ticket_id, 2, "966507654321")

        # Step 3: Send to Shaikh
        sender = WhatsAppSender(wa_config, database, mock_whatsapp_bridge)
        mock_whatsapp_bridge.is_connected = AsyncMock(return_value=True)
        mock_whatsapp_bridge.send_message = AsyncMock(return_value={"success": True})

        await sender.send_to_shaikh(database.get_ticket(ticket_id))

        # Step 4: Shaikh replies
        listener = WhatsAppListener(wa_config, database, mock_whatsapp_bridge)

        mock_whatsapp_bridge.get_messages = AsyncMock(return_value=[
            {
                "id": "wa_msg_2",
                "from": "966507654321",
                "text": f"#{ticket_id} السحور سنة ويصح الصيام بدونه",
                "timestamp": datetime.now().isoformat()
            }
        ])
        mock_whatsapp_bridge.clear_messages = AsyncMock(return_value=True)

        await listener.check_for_replies()

        # Step 5: Dispatch to Facebook
        dispatcher = Dispatcher(sample_config, database)

        mock_fb = AsyncMock()
        mock_fb.send_reply = AsyncMock(return_value=True)
        dispatcher._facebook = mock_fb

        replied_ticket = database.get_ticket(ticket_id)
        result = await dispatcher.dispatch_ticket(replied_ticket)
        assert result is True

        await dispatcher.close()

    @pytest.mark.asyncio
    async def test_multiple_tickets_parallel(self, database, sample_config, mock_whatsapp_bridge):
        """Test handling multiple tickets from different platforms."""
        wa_config = sample_config["whatsapp"]
        wa_config["shaikhs"] = sample_config["shaikhs"]

        # Create tickets from different platforms
        tickets_data = [
            (SourcePlatform.EMAIL, "email_1", "user1@example.com", "سؤال من البريد؟"),
            (SourcePlatform.FACEBOOK_DM, "fb_1", "https://fb.com/1", "سؤال من فيسبوك؟"),
            (SourcePlatform.INSTAGRAM_DM, "ig_1", "https://ig.com/1", "سؤال من انستغرام؟"),
        ]

        ticket_ids = []
        for platform, sender_id, contact, question in tickets_data:
            ticket = Ticket(
                source_platform=platform,
                sender_id=sender_id,
                sender_name=f"User {sender_id}",
                sender_contact=contact,
                question_text=question
            )
            tid = database.create_ticket(ticket)
            ticket_ids.append(tid)

        # All should be pending
        assert len(database.get_pending_tickets()) == 3

        # Assign all to Shaikh 1
        for tid in ticket_ids:
            database.assign_shaikh(tid, 1, "966501234567")

        # All should be assigned
        assert len(database.get_assigned_tickets()) == 3
        assert len(database.get_pending_tickets()) == 0

        # Send all to Shaikh
        sender = WhatsAppSender(wa_config, database, mock_whatsapp_bridge)
        mock_whatsapp_bridge.is_connected = AsyncMock(return_value=True)
        mock_whatsapp_bridge.send_message = AsyncMock(return_value={"success": True})

        sent_count = await sender.send_pending_tickets()
        assert sent_count == 3

        # All should be awaiting reply
        assert len(database.get_awaiting_reply_tickets()) == 3

    @pytest.mark.asyncio
    async def test_failed_ticket_retry(self, database, sample_config, mock_whatsapp_bridge):
        """Test retry mechanism for failed tickets."""
        wa_config = sample_config["whatsapp"]
        wa_config["shaikhs"] = sample_config["shaikhs"]

        # Create and assign ticket
        ticket = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="retry_test",
            sender_name="Retry User",
            sender_contact="retry@example.com",
            question_text="سؤال للاختبار؟"
        )
        ticket_id = database.create_ticket(ticket)
        database.assign_shaikh(ticket_id, 1, "966501234567")

        # First send fails
        sender = WhatsAppSender(wa_config, database, mock_whatsapp_bridge)
        mock_whatsapp_bridge.is_connected = AsyncMock(return_value=True)
        mock_whatsapp_bridge.send_message = AsyncMock(return_value={"success": False, "error": "Network error"})

        result = await sender.send_to_shaikh(database.get_ticket(ticket_id))
        assert result is False

        # Ticket should be failed
        failed_ticket = database.get_ticket(ticket_id)
        assert failed_ticket.status == TicketStatus.FAILED
        assert failed_ticket.retry_count == 1

        # Retry succeeds
        mock_whatsapp_bridge.send_message = AsyncMock(return_value={"success": True})

        retried = await sender.resend_failed_tickets(max_retries=3)
        assert retried == 1

        # Ticket should be sent
        retried_ticket = database.get_ticket(ticket_id)
        assert retried_ticket.status == TicketStatus.SENT_TO_SHAIKH


class TestStatusFlow:
    """Test ticket status transitions."""

    def test_valid_status_transitions(self, database, sample_ticket):
        """Test valid status transition flow."""
        ticket_id = database.create_ticket(sample_ticket)

        # Pending -> Assigned
        database.assign_shaikh(ticket_id, 1, "966501234567")
        ticket = database.get_ticket(ticket_id)
        assert ticket.status == TicketStatus.ASSIGNED

        # Assigned -> Sent_to_Shaikh
        database.mark_sent_to_shaikh(ticket_id)
        ticket = database.get_ticket(ticket_id)
        assert ticket.status == TicketStatus.SENT_TO_SHAIKH

        # Sent_to_Shaikh -> Replied
        database.record_reply(ticket_id, "الجواب هنا")
        ticket = database.get_ticket(ticket_id)
        assert ticket.status == TicketStatus.REPLIED

        # Replied -> Final_Sent
        database.mark_final_sent(ticket_id)
        ticket = database.get_ticket(ticket_id)
        assert ticket.status == TicketStatus.FINAL_SENT

    def test_timestamps_set_correctly(self, database, sample_ticket):
        """Test that timestamps are set at each stage."""
        ticket_id = database.create_ticket(sample_ticket)

        ticket = database.get_ticket(ticket_id)
        assert ticket.created_at is not None

        database.assign_shaikh(ticket_id, 1, "966501234567")
        ticket = database.get_ticket(ticket_id)
        assert ticket.updated_at is not None

        database.mark_sent_to_shaikh(ticket_id)
        ticket = database.get_ticket(ticket_id)
        assert ticket.sent_to_shaikh_at is not None

        database.record_reply(ticket_id, "Answer")
        ticket = database.get_ticket(ticket_id)
        assert ticket.replied_at is not None

        database.mark_final_sent(ticket_id)
        ticket = database.get_ticket(ticket_id)
        assert ticket.final_sent_at is not None


class TestDuplicatePrevention:
    """Test duplicate ticket prevention."""

    def test_same_sender_same_question(self, database):
        """Test duplicate detection for same sender and question."""
        ticket1 = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="dup_sender",
            sender_name="Dup User",
            question_text="نفس السؤال؟"
        )
        database.create_ticket(ticket1)

        # Same sender, same question
        is_dup = database.check_duplicate(
            "dup_sender",
            SourcePlatform.EMAIL,
            "نفس السؤال؟"
        )
        assert is_dup is True

    def test_same_sender_different_question(self, database):
        """Test that different questions from same sender are allowed."""
        ticket1 = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="multi_q_sender",
            sender_name="Multi Q User",
            question_text="السؤال الأول؟"
        )
        database.create_ticket(ticket1)

        # Same sender, different question
        is_dup = database.check_duplicate(
            "multi_q_sender",
            SourcePlatform.EMAIL,
            "السؤال الثاني؟"
        )
        assert is_dup is False

    def test_different_platform_same_question(self, database):
        """Test that same question from different platform is allowed."""
        ticket1 = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="cross_platform",
            sender_name="Cross User",
            question_text="سؤال عبر منصات؟"
        )
        database.create_ticket(ticket1)

        # Different platform
        is_dup = database.check_duplicate(
            "cross_platform",
            SourcePlatform.FACEBOOK_DM,  # Different platform
            "سؤال عبر منصات؟"
        )
        assert is_dup is False


class TestTicketCounts:
    """Test ticket statistics and counts."""

    def test_counts_by_status(self, database):
        """Test getting accurate counts by status."""
        # Create tickets with different statuses
        for i in range(3):
            t = Ticket(
                source_platform=SourcePlatform.EMAIL,
                sender_id=f"pending_{i}",
                sender_name=f"User {i}",
                question_text=f"Question {i}?"
            )
            database.create_ticket(t)

        for i in range(2):
            t = Ticket(
                source_platform=SourcePlatform.EMAIL,
                sender_id=f"assigned_{i}",
                sender_name=f"Assigned User {i}",
                question_text=f"Assigned Q {i}?"
            )
            tid = database.create_ticket(t)
            database.assign_shaikh(tid, 1, "966501234567")

        counts = database.get_ticket_counts()

        assert counts.get("Pending", 0) == 3
        assert counts.get("Assigned", 0) == 2

    def test_search_arabic_text(self, database):
        """Test searching Arabic text."""
        t1 = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="search_1",
            sender_name="باحث",
            question_text="ما حكم الصلاة في السفر؟"
        )
        t2 = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="search_2",
            sender_name="مستفسر",
            question_text="ما حكم الصيام للمسافر؟"
        )
        database.create_ticket(t1)
        database.create_ticket(t2)

        # Search by keyword
        results = database.search_tickets("الصلاة")
        assert len(results) == 1
        assert "الصلاة" in results[0].question_text

        # Search by name
        results = database.search_tickets("باحث")
        assert len(results) == 1
