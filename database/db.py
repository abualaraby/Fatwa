"""Database connection and operations for the Fatwa Management System."""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
from loguru import logger

from .models import Ticket, TicketStatus, SourcePlatform


class Database:
    """SQLite database manager for Fatwa tickets."""

    def __init__(self, db_path: str = "fatwa_tickets.db"):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self._ensure_database()

    def _ensure_database(self):
        """Create database and tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_platform TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    sender_contact TEXT,
                    question_text TEXT NOT NULL,
                    assigned_shaikh_id INTEGER,
                    assigned_shaikh_phone TEXT,
                    answer_text TEXT,
                    status TEXT NOT NULL DEFAULT 'Pending',
                    original_message_id TEXT,
                    original_post_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent_to_shaikh_at TIMESTAMP,
                    replied_at TIMESTAMP,
                    final_sent_at TIMESTAMP,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0
                )
            """)

            # Create index for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tickets_status
                ON tickets(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tickets_source
                ON tickets(source_platform)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tickets_sender_id
                ON tickets(sender_id, source_platform)
            """)

            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Get a database connection with context management."""
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_ticket(self, ticket: Ticket) -> int:
        """Create a new ticket and return its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tickets (
                    source_platform, sender_id, sender_name, sender_contact,
                    question_text, assigned_shaikh_id, assigned_shaikh_phone,
                    answer_text, status, original_message_id, original_post_id,
                    created_at, updated_at, sent_to_shaikh_at, replied_at,
                    final_sent_at, error_message, retry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticket.source_platform.value,
                ticket.sender_id,
                ticket.sender_name,
                ticket.sender_contact,
                ticket.question_text,
                ticket.assigned_shaikh_id,
                ticket.assigned_shaikh_phone,
                ticket.answer_text,
                ticket.status.value,
                ticket.original_message_id,
                ticket.original_post_id,
                ticket.created_at,
                ticket.updated_at,
                ticket.sent_to_shaikh_at,
                ticket.replied_at,
                ticket.final_sent_at,
                ticket.error_message,
                ticket.retry_count
            ))
            conn.commit()
            ticket_id = cursor.lastrowid
            logger.info(f"Created ticket #{ticket_id} from {ticket.source_platform.value}")
            return ticket_id

    def get_ticket(self, ticket_id: int) -> Optional[Ticket]:
        """Get a ticket by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_ticket(row)
            return None

    def update_ticket(self, ticket: Ticket) -> bool:
        """Update an existing ticket."""
        if ticket.id is None:
            raise ValueError("Cannot update ticket without ID")

        ticket.updated_at = datetime.now()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tickets SET
                    source_platform = ?,
                    sender_id = ?,
                    sender_name = ?,
                    sender_contact = ?,
                    question_text = ?,
                    assigned_shaikh_id = ?,
                    assigned_shaikh_phone = ?,
                    answer_text = ?,
                    status = ?,
                    original_message_id = ?,
                    original_post_id = ?,
                    updated_at = ?,
                    sent_to_shaikh_at = ?,
                    replied_at = ?,
                    final_sent_at = ?,
                    error_message = ?,
                    retry_count = ?
                WHERE id = ?
            """, (
                ticket.source_platform.value,
                ticket.sender_id,
                ticket.sender_name,
                ticket.sender_contact,
                ticket.question_text,
                ticket.assigned_shaikh_id,
                ticket.assigned_shaikh_phone,
                ticket.answer_text,
                ticket.status.value,
                ticket.original_message_id,
                ticket.original_post_id,
                ticket.updated_at,
                ticket.sent_to_shaikh_at,
                ticket.replied_at,
                ticket.final_sent_at,
                ticket.error_message,
                ticket.retry_count,
                ticket.id
            ))
            conn.commit()
            logger.info(f"Updated ticket #{ticket.id}")
            return cursor.rowcount > 0

    def get_tickets_by_status(self, status: TicketStatus) -> list[Ticket]:
        """Get all tickets with a specific status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY created_at DESC",
                (status.value,)
            )
            return [self._row_to_ticket(row) for row in cursor.fetchall()]

    def get_all_tickets(self, limit: int = 100, offset: int = 0) -> list[Ticket]:
        """Get all tickets with pagination."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tickets ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            return [self._row_to_ticket(row) for row in cursor.fetchall()]

    def get_pending_tickets(self) -> list[Ticket]:
        """Get all tickets that are pending assignment."""
        return self.get_tickets_by_status(TicketStatus.PENDING)

    def get_assigned_tickets(self) -> list[Ticket]:
        """Get all tickets that have been assigned but not sent."""
        return self.get_tickets_by_status(TicketStatus.ASSIGNED)

    def get_awaiting_reply_tickets(self) -> list[Ticket]:
        """Get all tickets sent to Shaikhs awaiting reply."""
        return self.get_tickets_by_status(TicketStatus.SENT_TO_SHAIKH)

    def get_replied_tickets(self) -> list[Ticket]:
        """Get all tickets with replies ready to be dispatched."""
        return self.get_tickets_by_status(TicketStatus.REPLIED)

    def check_duplicate(self, sender_id: str, source_platform: SourcePlatform,
                       question_text: str) -> bool:
        """Check if a similar ticket already exists (prevent duplicates)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM tickets
                WHERE sender_id = ? AND source_platform = ? AND question_text = ?
            """, (sender_id, source_platform.value, question_text))
            count = cursor.fetchone()[0]
            return count > 0

    def assign_shaikh(self, ticket_id: int, shaikh_id: int, shaikh_phone: str) -> bool:
        """Assign a Shaikh to a ticket."""
        ticket = self.get_ticket(ticket_id)
        if ticket:
            ticket.assigned_shaikh_id = shaikh_id
            ticket.assigned_shaikh_phone = shaikh_phone
            ticket.status = TicketStatus.ASSIGNED
            return self.update_ticket(ticket)
        return False

    def mark_sent_to_shaikh(self, ticket_id: int) -> bool:
        """Mark a ticket as sent to Shaikh."""
        ticket = self.get_ticket(ticket_id)
        if ticket:
            ticket.status = TicketStatus.SENT_TO_SHAIKH
            ticket.sent_to_shaikh_at = datetime.now()
            return self.update_ticket(ticket)
        return False

    def record_reply(self, ticket_id: int, answer_text: str) -> bool:
        """Record a Shaikh's reply."""
        ticket = self.get_ticket(ticket_id)
        if ticket:
            ticket.answer_text = answer_text
            ticket.status = TicketStatus.REPLIED
            ticket.replied_at = datetime.now()
            return self.update_ticket(ticket)
        return False

    def mark_final_sent(self, ticket_id: int) -> bool:
        """Mark a ticket as final reply sent to the original sender."""
        ticket = self.get_ticket(ticket_id)
        if ticket:
            ticket.status = TicketStatus.FINAL_SENT
            ticket.final_sent_at = datetime.now()
            return self.update_ticket(ticket)
        return False

    def mark_failed(self, ticket_id: int, error_message: str) -> bool:
        """Mark a ticket as failed with an error message."""
        ticket = self.get_ticket(ticket_id)
        if ticket:
            ticket.status = TicketStatus.FAILED
            ticket.error_message = error_message
            ticket.retry_count += 1
            return self.update_ticket(ticket)
        return False

    def get_ticket_counts(self) -> dict:
        """Get count of tickets by status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM tickets
                GROUP BY status
            """)
            return {row["status"]: row["count"] for row in cursor.fetchall()}

    def search_tickets(self, query: str) -> list[Ticket]:
        """Search tickets by question text or sender name."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            search_term = f"%{query}%"
            cursor.execute("""
                SELECT * FROM tickets
                WHERE question_text LIKE ? OR sender_name LIKE ?
                ORDER BY created_at DESC
            """, (search_term, search_term))
            return [self._row_to_ticket(row) for row in cursor.fetchall()]

    def _row_to_ticket(self, row: sqlite3.Row) -> Ticket:
        """Convert a database row to a Ticket object."""
        return Ticket.from_dict(dict(row))


# Global database instance
_database: Optional[Database] = None


def get_database(config_path: str = "config.json") -> Database:
    """Get or create the global database instance."""
    global _database
    if _database is None:
        # Load config
        with open(config_path) as f:
            config = json.load(f)
        db_path = config.get("database", {}).get("path", "fatwa_tickets.db")
        _database = Database(db_path)
    return _database
