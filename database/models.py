"""Database models for the Fatwa Management System."""

from enum import Enum
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field


class TicketStatus(str, Enum):
    """Status of a fatwa ticket."""
    PENDING = "Pending"
    ASSIGNED = "Assigned"
    SENT_TO_SHAIKH = "Sent_to_Shaikh"
    REPLIED = "Replied"
    FINAL_SENT = "Final_Sent"
    FAILED = "Failed"


class SourcePlatform(str, Enum):
    """Source platform where the question originated."""
    FACEBOOK_DM = "Facebook_DM"
    FACEBOOK_COMMENT = "Facebook_Comment"
    INSTAGRAM_DM = "Instagram_DM"
    INSTAGRAM_COMMENT = "Instagram_Comment"
    EMAIL = "Email"


@dataclass
class Ticket:
    """Represents a Fatwa ticket/inquiry."""
    id: Optional[int] = None
    source_platform: SourcePlatform = SourcePlatform.EMAIL
    sender_id: str = ""  # Platform-specific sender identifier
    sender_name: str = ""
    sender_contact: str = ""  # Email address or profile URL
    question_text: str = ""
    assigned_shaikh_id: Optional[int] = None
    assigned_shaikh_phone: Optional[str] = None
    answer_text: Optional[str] = None
    status: TicketStatus = TicketStatus.PENDING

    # Metadata for reply routing
    original_message_id: Optional[str] = None  # For threading replies
    original_post_id: Optional[str] = None  # For comment replies

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    sent_to_shaikh_at: Optional[datetime] = None
    replied_at: Optional[datetime] = None
    final_sent_at: Optional[datetime] = None

    # Error tracking
    error_message: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> dict:
        """Convert ticket to dictionary."""
        return {
            "id": self.id,
            "source_platform": self.source_platform.value if isinstance(self.source_platform, SourcePlatform) else self.source_platform,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "sender_contact": self.sender_contact,
            "question_text": self.question_text,
            "assigned_shaikh_id": self.assigned_shaikh_id,
            "assigned_shaikh_phone": self.assigned_shaikh_phone,
            "answer_text": self.answer_text,
            "status": self.status.value if isinstance(self.status, TicketStatus) else self.status,
            "original_message_id": self.original_message_id,
            "original_post_id": self.original_post_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "sent_to_shaikh_at": self.sent_to_shaikh_at.isoformat() if self.sent_to_shaikh_at else None,
            "replied_at": self.replied_at.isoformat() if self.replied_at else None,
            "final_sent_at": self.final_sent_at.isoformat() if self.final_sent_at else None,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Ticket":
        """Create a Ticket from a dictionary."""
        ticket = cls()
        ticket.id = data.get("id")

        source = data.get("source_platform")
        if isinstance(source, str):
            ticket.source_platform = SourcePlatform(source)
        elif isinstance(source, SourcePlatform):
            ticket.source_platform = source

        ticket.sender_id = data.get("sender_id", "")
        ticket.sender_name = data.get("sender_name", "")
        ticket.sender_contact = data.get("sender_contact", "")
        ticket.question_text = data.get("question_text", "")
        ticket.assigned_shaikh_id = data.get("assigned_shaikh_id")
        ticket.assigned_shaikh_phone = data.get("assigned_shaikh_phone")
        ticket.answer_text = data.get("answer_text")

        status = data.get("status", TicketStatus.PENDING)
        if isinstance(status, str):
            ticket.status = TicketStatus(status)
        elif isinstance(status, TicketStatus):
            ticket.status = status

        ticket.original_message_id = data.get("original_message_id")
        ticket.original_post_id = data.get("original_post_id")

        # Parse datetime fields
        for dt_field in ["created_at", "updated_at", "sent_to_shaikh_at", "replied_at", "final_sent_at"]:
            value = data.get(dt_field)
            if isinstance(value, str):
                setattr(ticket, dt_field, datetime.fromisoformat(value))
            elif isinstance(value, datetime):
                setattr(ticket, dt_field, value)

        ticket.error_message = data.get("error_message")
        ticket.retry_count = data.get("retry_count", 0)

        return ticket

    def get_whatsapp_message(self) -> str:
        """Generate the WhatsApp message to send to the Shaikh."""
        return (
            f"📩 *New Fatwa Request #{self.id}*\n\n"
            f"*From:* {self.sender_name}\n"
            f"*Platform:* {self.source_platform.value}\n\n"
            f"*Question:*\n{self.question_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Reply with: #{self.id} followed by your answer"
        )
