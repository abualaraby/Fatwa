"""WhatsApp Sender - Send fatwa questions to Shaikhs."""

import asyncio
from datetime import datetime
from typing import Optional
from loguru import logger

from database import Database, Ticket, TicketStatus
from .bridge import WhatsAppBridge


class WhatsAppSender:
    """Send fatwa questions to assigned Shaikhs via WhatsApp."""

    def __init__(self, config: dict, database: Database, bridge: WhatsAppBridge):
        """Initialize WhatsApp sender.

        Args:
            config: WhatsApp configuration
            database: Database instance
            bridge: WhatsApp bridge instance
        """
        self.config = config
        self.database = database
        self.bridge = bridge

    async def send_pending_tickets(self) -> int:
        """Send all assigned tickets to their Shaikhs.

        Returns:
            Number of tickets sent
        """
        # Get tickets that are assigned but not yet sent
        assigned_tickets = self.database.get_assigned_tickets()

        if not assigned_tickets:
            logger.debug("No assigned tickets to send")
            return 0

        sent_count = 0

        for ticket in assigned_tickets:
            success = await self.send_to_shaikh(ticket)
            if success:
                sent_count += 1
            # Small delay between messages to avoid rate limiting
            await asyncio.sleep(2)

        logger.info(f"Sent {sent_count}/{len(assigned_tickets)} tickets to Shaikhs")
        return sent_count

    async def send_to_shaikh(self, ticket: Ticket) -> bool:
        """Send a single ticket to its assigned Shaikh.

        Args:
            ticket: The ticket to send

        Returns:
            True if sent successfully
        """
        if not ticket.assigned_shaikh_phone:
            logger.warning(f"Ticket #{ticket.id} has no assigned Shaikh phone")
            return False

        try:
            # Check if WhatsApp is connected
            if not await self.bridge.is_connected():
                logger.error("WhatsApp not connected, cannot send message")
                return False

            # Generate the message
            message = ticket.get_whatsapp_message()

            # Send the message
            result = await self.bridge.send_message(
                phone=ticket.assigned_shaikh_phone,
                message=message,
                ticket_id=ticket.id
            )

            if result.get("success"):
                # Update ticket status
                self.database.mark_sent_to_shaikh(ticket.id)
                logger.info(f"Ticket #{ticket.id} sent to Shaikh at {ticket.assigned_shaikh_phone}")
                return True
            else:
                error = result.get("error", "Unknown error")
                logger.error(f"Failed to send ticket #{ticket.id}: {error}")
                self.database.mark_failed(ticket.id, f"WhatsApp send failed: {error}")
                return False

        except Exception as e:
            logger.error(f"Error sending ticket #{ticket.id}: {e}")
            self.database.mark_failed(ticket.id, str(e))
            return False

    async def resend_failed_tickets(self, max_retries: int = 3) -> int:
        """Resend failed tickets that haven't exceeded retry limit.

        Args:
            max_retries: Maximum number of retry attempts

        Returns:
            Number of tickets resent
        """
        failed_tickets = self.database.get_tickets_by_status(TicketStatus.FAILED)
        resent_count = 0

        for ticket in failed_tickets:
            if ticket.retry_count >= max_retries:
                logger.debug(f"Ticket #{ticket.id} exceeded max retries ({max_retries})")
                continue

            # Reset to assigned status to allow resending
            ticket.status = TicketStatus.ASSIGNED
            ticket.error_message = None
            self.database.update_ticket(ticket)

            success = await self.send_to_shaikh(ticket)
            if success:
                resent_count += 1

            await asyncio.sleep(2)

        if resent_count > 0:
            logger.info(f"Resent {resent_count} previously failed tickets")

        return resent_count

    async def send_reminder(self, ticket: Ticket) -> bool:
        """Send a reminder to the Shaikh about an unanswered ticket.

        Args:
            ticket: The ticket to remind about

        Returns:
            True if reminder sent successfully
        """
        if not ticket.assigned_shaikh_phone:
            return False

        try:
            message = (
                f"⏰ *Reminder: Fatwa Request #{ticket.id}*\n\n"
                f"This question is still awaiting your response:\n\n"
                f"*Question:*\n{ticket.question_text[:500]}...\n\n"
                f"Please reply with: #{ticket.id} followed by your answer"
            )

            result = await self.bridge.send_message(
                phone=ticket.assigned_shaikh_phone,
                message=message,
                ticket_id=ticket.id
            )

            if result.get("success"):
                logger.info(f"Reminder sent for ticket #{ticket.id}")
                return True
            return False

        except Exception as e:
            logger.error(f"Error sending reminder for ticket #{ticket.id}: {e}")
            return False
