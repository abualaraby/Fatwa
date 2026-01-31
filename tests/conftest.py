"""Pytest fixtures for Fatwa Management System tests."""

import os
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Database, Ticket, TicketStatus, SourcePlatform


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
    # Cleanup
    try:
        os.unlink(f.name)
    except Exception:
        pass


@pytest.fixture
def database(temp_db_path):
    """Create a test database instance."""
    db = Database(temp_db_path)
    yield db


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return {
        "database": {
            "path": "test_fatwa.db"
        },
        "facebook": {
            "email": "test@facebook.com",
            "password": "testpass",
            "page_url": "https://www.facebook.com/testpage",
            "check_interval_minutes": 5,
            "enabled": True,
            "headless": True
        },
        "instagram": {
            "username": "testuser",
            "password": "testpass",
            "check_interval_minutes": 5,
            "enabled": True,
            "headless": True
        },
        "email": {
            "imap_server": "imap.gmail.com",
            "imap_port": 993,
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "email_address": "test@gmail.com",
            "password": "testpass",
            "check_interval_minutes": 2,
            "enabled": True
        },
        "whatsapp": {
            "node_bridge_port": 3001,
            "session_path": "./test_session"
        },
        "shaikhs": [
            {
                "id": 1,
                "name": "Shaikh Ahmed",
                "phone": "966501234567",
                "specialization": "Fiqh"
            },
            {
                "id": 2,
                "name": "Shaikh Mohammed",
                "phone": "966507654321",
                "specialization": "Aqeedah"
            }
        ],
        "settings": {
            "auto_dispatch_replies": False,
            "stealth_mode": True,
            "headless_browser": True,
            "capture_loop_enabled": True,
            "listener_loop_enabled": True
        }
    }


@pytest.fixture
def sample_ticket():
    """Create a sample ticket for testing."""
    return Ticket(
        source_platform=SourcePlatform.EMAIL,
        sender_id="test_sender_123",
        sender_name="أحمد محمد",
        sender_contact="ahmed@example.com",
        question_text="ما حكم صلاة الجمعة في البيت؟",
        original_message_id="msg_12345",
    )


@pytest.fixture
def sample_fb_ticket():
    """Create a sample Facebook ticket."""
    return Ticket(
        source_platform=SourcePlatform.FACEBOOK_DM,
        sender_id="fb_user_123",
        sender_name="محمد علي",
        sender_contact="https://facebook.com/user123",
        question_text="هل يجوز الصيام بدون نية؟",
        original_message_id="fb_msg_456",
    )


@pytest.fixture
def sample_ig_ticket():
    """Create a sample Instagram ticket."""
    return Ticket(
        source_platform=SourcePlatform.INSTAGRAM_COMMENT,
        sender_id="ig_user_456",
        sender_name="سارة أحمد",
        sender_contact="https://instagram.com/sara_ahmed",
        question_text="ما هي شروط الزكاة؟",
        original_message_id="ig_comment_789",
        original_post_id="ABC123",
    )


@pytest.fixture
def assigned_ticket(database, sample_ticket):
    """Create an assigned ticket in database."""
    ticket_id = database.create_ticket(sample_ticket)
    database.assign_shaikh(ticket_id, 1, "966501234567")
    return database.get_ticket(ticket_id)


@pytest.fixture
def replied_ticket(database, sample_ticket):
    """Create a replied ticket in database."""
    ticket_id = database.create_ticket(sample_ticket)
    database.assign_shaikh(ticket_id, 1, "966501234567")
    database.mark_sent_to_shaikh(ticket_id)
    database.record_reply(ticket_id, "الجواب هو أن صلاة الجمعة واجبة في المسجد")
    return database.get_ticket(ticket_id)


@pytest.fixture
def mock_whatsapp_bridge():
    """Create a mock WhatsApp bridge."""
    bridge = AsyncMock()
    bridge.is_connected.return_value = True
    bridge.send_message.return_value = {"success": True, "messageId": "wa_msg_123"}
    bridge.get_messages.return_value = []
    bridge.get_status.return_value = {"status": "connected"}
    bridge.get_qr_code.return_value = None
    return bridge


@pytest.fixture
def mock_playwright_page():
    """Create a mock Playwright page."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.wait_for_load_state = AsyncMock()
    page.url = "https://www.facebook.com/"
    page.close = AsyncMock()
    return page


@pytest.fixture
def mock_imap_client():
    """Create a mock IMAP client."""
    imap = MagicMock()
    imap.login = MagicMock()
    imap.select = MagicMock(return_value=("OK", [b"10"]))
    imap.search = MagicMock(return_value=("OK", [b"1 2 3"]))
    imap.fetch = MagicMock(return_value=("OK", [(b"1", b"email content")]))
    imap.logout = MagicMock()
    return imap
