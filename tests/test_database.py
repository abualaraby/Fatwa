"""Tests for database module."""

import pytest
from datetime import datetime

from database import Database, Ticket, TicketStatus, SourcePlatform


class TestTicketModel:
    """Tests for Ticket data model."""

    def test_ticket_creation(self):
        """Test creating a new ticket."""
        ticket = Ticket(
            source_platform=SourcePlatform.EMAIL,
            sender_id="test123",
            sender_name="Test User",
            question_text="Test question?"
        )

        assert ticket.source_platform == SourcePlatform.EMAIL
        assert ticket.sender_id == "test123"
        assert ticket.sender_name == "Test User"
        assert ticket.status == TicketStatus.PENDING
        assert ticket.id is None

    def test_ticket_to_dict(self, sample_ticket):
        """Test converting ticket to dictionary."""
        data = sample_ticket.to_dict()

        assert data["source_platform"] == "Email"
        assert data["sender_name"] == "أحمد محمد"
        assert data["status"] == "Pending"
        assert "created_at" in data

    def test_ticket_from_dict(self):
        """Test creating ticket from dictionary."""
        data = {
            "id": 1,
            "source_platform": "Facebook_DM",
            "sender_id": "fb123",
            "sender_name": "Test User",
            "sender_contact": "test@fb.com",
            "question_text": "What is halal?",
            "status": "Assigned",
            "assigned_shaikh_id": 1,
            "assigned_shaikh_phone": "966501234567",
        }

        ticket = Ticket.from_dict(data)

        assert ticket.id == 1
        assert ticket.source_platform == SourcePlatform.FACEBOOK_DM
        assert ticket.status == TicketStatus.ASSIGNED
        assert ticket.assigned_shaikh_phone == "966501234567"

    def test_ticket_whatsapp_message(self, sample_ticket):
        """Test generating WhatsApp message."""
        sample_ticket.id = 42
        message = sample_ticket.get_whatsapp_message()

        assert "#42" in message
        assert "ما حكم صلاة الجمعة" in message
        assert "أحمد محمد" in message


class TestDatabase:
    """Tests for Database operations."""

    def test_database_initialization(self, database):
        """Test database creates tables on init."""
        # If we get here without error, tables were created
        assert database.db_path.exists()

    def test_create_ticket(self, database, sample_ticket):
        """Test creating a ticket in database."""
        ticket_id = database.create_ticket(sample_ticket)

        assert ticket_id is not None
        assert ticket_id > 0

    def test_get_ticket(self, database, sample_ticket):
        """Test retrieving a ticket by ID."""
        ticket_id = database.create_ticket(sample_ticket)
        retrieved = database.get_ticket(ticket_id)

        assert retrieved is not None
        assert retrieved.id == ticket_id
        assert retrieved.sender_name == sample_ticket.sender_name
        assert retrieved.question_text == sample_ticket.question_text

    def test_get_nonexistent_ticket(self, database):
        """Test getting a ticket that doesn't exist."""
        ticket = database.get_ticket(99999)
        assert ticket is None

    def test_update_ticket(self, database, sample_ticket):
        """Test updating a ticket."""
        ticket_id = database.create_ticket(sample_ticket)
        ticket = database.get_ticket(ticket_id)

        ticket.answer_text = "الجواب هنا"
        ticket.status = TicketStatus.REPLIED

        result = database.update_ticket(ticket)
        assert result is True

        updated = database.get_ticket(ticket_id)
        assert updated.answer_text == "الجواب هنا"
        assert updated.status == TicketStatus.REPLIED

    def test_assign_shaikh(self, database, sample_ticket):
        """Test assigning a Shaikh to a ticket."""
        ticket_id = database.create_ticket(sample_ticket)

        result = database.assign_shaikh(ticket_id, 1, "966501234567")
        assert result is True

        ticket = database.get_ticket(ticket_id)
        assert ticket.assigned_shaikh_id == 1
        assert ticket.assigned_shaikh_phone == "966501234567"
        assert ticket.status == TicketStatus.ASSIGNED

    def test_mark_sent_to_shaikh(self, database, sample_ticket):
        """Test marking ticket as sent to Shaikh."""
        ticket_id = database.create_ticket(sample_ticket)
        database.assign_shaikh(ticket_id, 1, "966501234567")

        result = database.mark_sent_to_shaikh(ticket_id)
        assert result is True

        ticket = database.get_ticket(ticket_id)
        assert ticket.status == TicketStatus.SENT_TO_SHAIKH
        assert ticket.sent_to_shaikh_at is not None

    def test_record_reply(self, database, sample_ticket):
        """Test recording a Shaikh's reply."""
        ticket_id = database.create_ticket(sample_ticket)
        database.assign_shaikh(ticket_id, 1, "966501234567")
        database.mark_sent_to_shaikh(ticket_id)

        answer = "هذا هو الجواب الشرعي"
        result = database.record_reply(ticket_id, answer)
        assert result is True

        ticket = database.get_ticket(ticket_id)
        assert ticket.answer_text == answer
        assert ticket.status == TicketStatus.REPLIED
        assert ticket.replied_at is not None

    def test_mark_final_sent(self, database, replied_ticket):
        """Test marking ticket as final sent."""
        result = database.mark_final_sent(replied_ticket.id)
        assert result is True

        ticket = database.get_ticket(replied_ticket.id)
        assert ticket.status == TicketStatus.FINAL_SENT
        assert ticket.final_sent_at is not None

    def test_mark_failed(self, database, sample_ticket):
        """Test marking ticket as failed."""
        ticket_id = database.create_ticket(sample_ticket)

        result = database.mark_failed(ticket_id, "Connection error")
        assert result is True

        ticket = database.get_ticket(ticket_id)
        assert ticket.status == TicketStatus.FAILED
        assert ticket.error_message == "Connection error"
        assert ticket.retry_count == 1

    def test_get_tickets_by_status(self, database, sample_ticket, sample_fb_ticket):
        """Test getting tickets by status."""
        database.create_ticket(sample_ticket)
        database.create_ticket(sample_fb_ticket)

        pending = database.get_tickets_by_status(TicketStatus.PENDING)
        assert len(pending) == 2

    def test_get_pending_tickets(self, database, sample_ticket):
        """Test getting pending tickets."""
        ticket_id = database.create_ticket(sample_ticket)

        pending = database.get_pending_tickets()
        assert len(pending) == 1
        assert pending[0].id == ticket_id

    def test_get_assigned_tickets(self, database, assigned_ticket):
        """Test getting assigned tickets."""
        assigned = database.get_assigned_tickets()
        assert len(assigned) == 1
        assert assigned[0].id == assigned_ticket.id

    def test_get_awaiting_reply_tickets(self, database, sample_ticket):
        """Test getting tickets awaiting Shaikh reply."""
        ticket_id = database.create_ticket(sample_ticket)
        database.assign_shaikh(ticket_id, 1, "966501234567")
        database.mark_sent_to_shaikh(ticket_id)

        awaiting = database.get_awaiting_reply_tickets()
        assert len(awaiting) == 1

    def test_get_replied_tickets(self, database, replied_ticket):
        """Test getting replied tickets."""
        replied = database.get_replied_tickets()
        assert len(replied) == 1
        assert replied[0].answer_text is not None

    def test_check_duplicate_true(self, database, sample_ticket):
        """Test duplicate detection - finds duplicate."""
        database.create_ticket(sample_ticket)

        is_dup = database.check_duplicate(
            sample_ticket.sender_id,
            sample_ticket.source_platform,
            sample_ticket.question_text
        )
        assert is_dup is True

    def test_check_duplicate_false(self, database, sample_ticket):
        """Test duplicate detection - no duplicate."""
        database.create_ticket(sample_ticket)

        is_dup = database.check_duplicate(
            "different_sender",
            sample_ticket.source_platform,
            sample_ticket.question_text
        )
        assert is_dup is False

    def test_get_ticket_counts(self, database, sample_ticket, sample_fb_ticket):
        """Test getting ticket counts by status."""
        database.create_ticket(sample_ticket)
        ticket_id = database.create_ticket(sample_fb_ticket)
        database.assign_shaikh(ticket_id, 1, "966501234567")

        counts = database.get_ticket_counts()

        assert counts.get("Pending", 0) == 1
        assert counts.get("Assigned", 0) == 1

    def test_search_tickets(self, database, sample_ticket, sample_fb_ticket):
        """Test searching tickets."""
        database.create_ticket(sample_ticket)
        database.create_ticket(sample_fb_ticket)

        # Search by question
        results = database.search_tickets("صلاة")
        assert len(results) == 1
        assert "صلاة" in results[0].question_text

        # Search by name
        results = database.search_tickets("أحمد")
        assert len(results) >= 1

    def test_get_all_tickets_pagination(self, database, sample_ticket):
        """Test getting all tickets with pagination."""
        # Create 5 tickets
        for i in range(5):
            ticket = Ticket(
                source_platform=SourcePlatform.EMAIL,
                sender_id=f"sender_{i}",
                sender_name=f"User {i}",
                question_text=f"Question {i}?"
            )
            database.create_ticket(ticket)

        # Get first 2
        page1 = database.get_all_tickets(limit=2, offset=0)
        assert len(page1) == 2

        # Get next 2
        page2 = database.get_all_tickets(limit=2, offset=2)
        assert len(page2) == 2

        # Check they're different
        assert page1[0].id != page2[0].id


class TestTicketStatusEnum:
    """Tests for TicketStatus enum."""

    def test_all_statuses_defined(self):
        """Test all required statuses are defined."""
        statuses = [s.value for s in TicketStatus]

        assert "Pending" in statuses
        assert "Assigned" in statuses
        assert "Sent_to_Shaikh" in statuses
        assert "Replied" in statuses
        assert "Final_Sent" in statuses
        assert "Failed" in statuses


class TestSourcePlatformEnum:
    """Tests for SourcePlatform enum."""

    def test_all_platforms_defined(self):
        """Test all required platforms are defined."""
        platforms = [p.value for p in SourcePlatform]

        assert "Facebook_DM" in platforms
        assert "Facebook_Comment" in platforms
        assert "Instagram_DM" in platforms
        assert "Instagram_Comment" in platforms
        assert "Email" in platforms
