"""Main dispatcher coordinating replies across all platforms."""

import asyncio
from typing import Optional
from loguru import logger

from database import Database, Ticket, TicketStatus, SourcePlatform
from .facebook_reply import FacebookDispatch
from .instagram_reply import InstagramDispatch
from .email_reply import EmailDispatch


class Dispatcher:
    """Coordinate sending replies across all platforms."""

    def __init__(self, config: dict, database: Database):
        """Initialize the dispatcher.

        Args:
            config: Full configuration dictionary
            database: Database instance
        """
        self.config = config
        self.database = database

        # Initialize platform-specific dispatchers
        self._facebook: Optional[FacebookDispatch] = None
        self._instagram: Optional[InstagramDispatch] = None
        self._email: Optional[EmailDispatch] = None

        # Track which dispatchers are enabled
        self._facebook_enabled = config.get("facebook", {}).get("enabled", False)
        self._instagram_enabled = config.get("instagram", {}).get("enabled", False)
        self._email_enabled = config.get("email", {}).get("enabled", False)

    async def _get_facebook(self) -> FacebookDispatch:
        """Get or create Facebook dispatcher."""
        if self._facebook is None:
            self._facebook = FacebookDispatch(self.config.get("facebook", {}), self.database)
        return self._facebook

    async def _get_instagram(self) -> InstagramDispatch:
        """Get or create Instagram dispatcher."""
        if self._instagram is None:
            self._instagram = InstagramDispatch(self.config.get("instagram", {}), self.database)
        return self._instagram

    async def _get_email(self) -> EmailDispatch:
        """Get or create Email dispatcher."""
        if self._email is None:
            self._email = EmailDispatch(self.config.get("email", {}), self.database)
        return self._email

    async def dispatch_ticket(self, ticket: Ticket) -> bool:
        """Dispatch a single ticket reply to its original platform.

        Args:
            ticket: The ticket to dispatch

        Returns:
            True if dispatched successfully
        """
        if ticket.status != TicketStatus.REPLIED:
            logger.warning(f"Ticket #{ticket.id} is not in REPLIED status")
            return False

        if not ticket.answer_text:
            logger.warning(f"Ticket #{ticket.id} has no answer text")
            return False

        try:
            success = False

            # Route to appropriate dispatcher based on source platform
            if ticket.source_platform in [SourcePlatform.FACEBOOK_DM, SourcePlatform.FACEBOOK_COMMENT]:
                if not self._facebook_enabled:
                    logger.warning("Facebook dispatch is disabled")
                    return False

                dispatcher = await self._get_facebook()
                success = await dispatcher.send_reply(ticket)

            elif ticket.source_platform in [SourcePlatform.INSTAGRAM_DM, SourcePlatform.INSTAGRAM_COMMENT]:
                if not self._instagram_enabled:
                    logger.warning("Instagram dispatch is disabled")
                    return False

                dispatcher = await self._get_instagram()
                success = await dispatcher.send_reply(ticket)

            elif ticket.source_platform == SourcePlatform.EMAIL:
                if not self._email_enabled:
                    logger.warning("Email dispatch is disabled")
                    return False

                dispatcher = await self._get_email()
                success = await dispatcher.send_reply(ticket)

            else:
                logger.error(f"Unknown source platform: {ticket.source_platform}")
                return False

            # Update ticket status
            if success:
                self.database.mark_final_sent(ticket.id)
                logger.info(f"Successfully dispatched ticket #{ticket.id}")
            else:
                self.database.mark_failed(
                    ticket.id,
                    f"Failed to dispatch to {ticket.source_platform.value}"
                )

            return success

        except Exception as e:
            logger.error(f"Error dispatching ticket #{ticket.id}: {e}")
            self.database.mark_failed(ticket.id, str(e))
            return False

    async def dispatch_all_replied(self) -> dict:
        """Dispatch all tickets that have been replied to.

        Returns:
            Dict with counts: {'total': N, 'success': N, 'failed': N}
        """
        replied_tickets = self.database.get_replied_tickets()

        if not replied_tickets:
            logger.debug("No replied tickets to dispatch")
            return {"total": 0, "success": 0, "failed": 0}

        results = {"total": len(replied_tickets), "success": 0, "failed": 0}

        for ticket in replied_tickets:
            success = await self.dispatch_ticket(ticket)
            if success:
                results["success"] += 1
            else:
                results["failed"] += 1

            # Delay between dispatches to avoid rate limiting
            await asyncio.sleep(3)

        logger.info(
            f"Dispatched {results['success']}/{results['total']} tickets "
            f"({results['failed']} failed)"
        )

        return results

    async def dispatch_by_id(self, ticket_id: int) -> bool:
        """Dispatch a specific ticket by ID.

        Args:
            ticket_id: The ticket ID to dispatch

        Returns:
            True if dispatched successfully
        """
        ticket = self.database.get_ticket(ticket_id)
        if not ticket:
            logger.error(f"Ticket #{ticket_id} not found")
            return False

        return await self.dispatch_ticket(ticket)

    async def close(self):
        """Close all dispatcher connections."""
        if self._facebook:
            await self._facebook.close()
            self._facebook = None

        if self._instagram:
            await self._instagram.close()
            self._instagram = None

        if self._email:
            await self._email.close()
            self._email = None

        logger.info("All dispatchers closed")
