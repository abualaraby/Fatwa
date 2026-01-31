"""Base class for capture modules."""

from abc import ABC, abstractmethod
from typing import Optional
from loguru import logger

from database import Database, Ticket


class BaseCaptureModule(ABC):
    """Abstract base class for all capture modules."""

    def __init__(self, config: dict, database: Database):
        """Initialize the capture module.

        Args:
            config: Configuration dictionary for this platform
            database: Database instance for storing tickets
        """
        self.config = config
        self.database = database
        self.enabled = config.get("enabled", True)
        self._is_logged_in = False

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform name."""
        pass

    @abstractmethod
    async def login(self) -> bool:
        """Login to the platform. Returns True on success."""
        pass

    @abstractmethod
    async def capture_messages(self) -> list[Ticket]:
        """Capture new direct messages. Returns list of new tickets."""
        pass

    @abstractmethod
    async def capture_comments(self) -> list[Ticket]:
        """Capture new comments. Returns list of new tickets."""
        pass

    async def capture_all(self) -> list[Ticket]:
        """Capture all new inquiries from this platform."""
        if not self.enabled:
            logger.info(f"{self.platform_name} capture is disabled")
            return []

        if not self._is_logged_in:
            success = await self.login()
            if not success:
                logger.error(f"Failed to login to {self.platform_name}")
                return []

        tickets = []

        try:
            dm_tickets = await self.capture_messages()
            tickets.extend(dm_tickets)
            logger.info(f"Captured {len(dm_tickets)} DMs from {self.platform_name}")
        except Exception as e:
            logger.error(f"Error capturing DMs from {self.platform_name}: {e}")

        try:
            comment_tickets = await self.capture_comments()
            tickets.extend(comment_tickets)
            logger.info(f"Captured {len(comment_tickets)} comments from {self.platform_name}")
        except Exception as e:
            logger.error(f"Error capturing comments from {self.platform_name}: {e}")

        return tickets

    def save_ticket(self, ticket: Ticket) -> Optional[int]:
        """Save a ticket to the database, checking for duplicates.

        Returns ticket ID if saved, None if duplicate.
        """
        # Check for duplicates
        if self.database.check_duplicate(
            ticket.sender_id,
            ticket.source_platform,
            ticket.question_text
        ):
            logger.debug(f"Skipping duplicate ticket from {ticket.sender_name}")
            return None

        ticket_id = self.database.create_ticket(ticket)
        return ticket_id

    @abstractmethod
    async def close(self):
        """Clean up resources."""
        pass
