"""WhatsApp Listener - Listen for Shaikh replies."""

import asyncio
import re
from datetime import datetime
from typing import Optional
from loguru import logger

from database import Database, Ticket, TicketStatus
from .bridge import WhatsAppBridge


class WhatsAppListener:
    """Listen for and process Shaikh replies via WhatsApp."""

    def __init__(self, config: dict, database: Database, bridge: WhatsAppBridge):
        """Initialize WhatsApp listener.

        Args:
            config: WhatsApp configuration
            database: Database instance
            bridge: WhatsApp bridge instance
        """
        self.config = config
        self.database = database
        self.bridge = bridge
        self.shaikhs = config.get("shaikhs", [])

        # Build phone number to Shaikh mapping
        self._shaikh_phones = {
            self._normalize_phone(s.get("phone", "")): s
            for s in self.shaikhs
        }

        # Track last processed message timestamp
        self._last_check: Optional[str] = None

        # Pattern to match ticket IDs in replies
        # Matches: #123, #123:, #123 answer, etc.
        self._ticket_pattern = re.compile(r"#(\d+)\s*:?\s*(.*)", re.DOTALL)

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number format."""
        # Remove non-digits
        cleaned = re.sub(r"\D", "", phone)
        # Remove leading zeros
        cleaned = cleaned.lstrip("0")
        return cleaned

    def _is_shaikh_phone(self, phone: str) -> bool:
        """Check if a phone number belongs to a registered Shaikh."""
        normalized = self._normalize_phone(phone)
        return normalized in self._shaikh_phones

    async def check_for_replies(self) -> int:
        """Check for new replies from Shaikhs.

        Returns:
            Number of replies processed
        """
        try:
            # Get new messages
            messages = await self.bridge.get_messages(since=self._last_check, limit=100)

            if not messages:
                return 0

            processed_count = 0
            processed_ids = []

            for msg in messages:
                sender_phone = msg.get("from", "")
                message_text = msg.get("text", "")
                message_id = msg.get("id", "")

                # Update last check timestamp
                timestamp = msg.get("timestamp")
                if timestamp:
                    self._last_check = timestamp

                # Check if from a Shaikh
                if not self._is_shaikh_phone(sender_phone):
                    logger.debug(f"Message from non-Shaikh {sender_phone}, skipping")
                    processed_ids.append(message_id)
                    continue

                # Try to extract ticket ID and answer
                result = self._parse_reply(message_text)

                if result:
                    ticket_id, answer_text = result
                    success = await self._process_reply(ticket_id, answer_text, sender_phone)

                    if success:
                        processed_count += 1
                        logger.info(f"Processed reply for ticket #{ticket_id}")
                    else:
                        logger.warning(f"Failed to process reply for ticket #{ticket_id}")

                processed_ids.append(message_id)

            # Clear processed messages
            if processed_ids:
                await self.bridge.clear_messages(processed_ids)

            return processed_count

        except Exception as e:
            logger.error(f"Error checking for replies: {e}")
            return 0

    def _parse_reply(self, text: str) -> Optional[tuple[int, str]]:
        """Parse a reply message to extract ticket ID and answer.

        Args:
            text: The message text

        Returns:
            Tuple of (ticket_id, answer_text) or None if not a valid reply
        """
        if not text:
            return None

        # Try to match the pattern
        match = self._ticket_pattern.match(text.strip())

        if match:
            try:
                ticket_id = int(match.group(1))
                answer_text = match.group(2).strip()

                if answer_text:
                    return (ticket_id, answer_text)
            except ValueError:
                pass

        return None

    async def _process_reply(self, ticket_id: int, answer_text: str, shaikh_phone: str) -> bool:
        """Process a Shaikh's reply.

        Args:
            ticket_id: The ticket ID
            answer_text: The answer text
            shaikh_phone: The Shaikh's phone number

        Returns:
            True if processed successfully
        """
        try:
            # Get the ticket
            ticket = self.database.get_ticket(ticket_id)

            if not ticket:
                logger.warning(f"Ticket #{ticket_id} not found")
                return False

            # Verify the reply is from the assigned Shaikh
            normalized_assigned = self._normalize_phone(ticket.assigned_shaikh_phone or "")
            normalized_sender = self._normalize_phone(shaikh_phone)

            if normalized_assigned != normalized_sender:
                logger.warning(
                    f"Reply for ticket #{ticket_id} from {shaikh_phone} "
                    f"but assigned to {ticket.assigned_shaikh_phone}"
                )
                # Still process it - the admin may have reassigned

            # Check ticket status
            if ticket.status not in [TicketStatus.SENT_TO_SHAIKH, TicketStatus.ASSIGNED]:
                logger.warning(
                    f"Ticket #{ticket_id} has status {ticket.status.value}, "
                    f"expected SENT_TO_SHAIKH or ASSIGNED"
                )
                # Still process - might be a follow-up or correction

            # Record the reply
            success = self.database.record_reply(ticket_id, answer_text)

            if success:
                logger.info(f"Recorded reply for ticket #{ticket_id}")

                # Send acknowledgment to Shaikh
                await self._send_acknowledgment(shaikh_phone, ticket_id)

                return True

            return False

        except Exception as e:
            logger.error(f"Error processing reply for ticket #{ticket_id}: {e}")
            return False

    async def _send_acknowledgment(self, phone: str, ticket_id: int):
        """Send acknowledgment to Shaikh that reply was received."""
        try:
            message = (
                f"✅ *Reply Received*\n\n"
                f"Your answer for Fatwa #{ticket_id} has been recorded.\n"
                f"The response will be sent to the questioner.\n\n"
                f"جزاكم الله خيرا"
            )

            await self.bridge.send_message(phone=phone, message=message)
        except Exception as e:
            logger.debug(f"Failed to send acknowledgment: {e}")

    async def start_listening(self, interval_seconds: int = 10):
        """Start continuous listening loop.

        Args:
            interval_seconds: How often to check for new messages
        """
        logger.info(f"Starting WhatsApp listener (checking every {interval_seconds}s)")

        while True:
            try:
                # Check if bridge is connected
                if not await self.bridge.is_connected():
                    logger.warning("WhatsApp not connected, waiting...")
                    await asyncio.sleep(30)
                    continue

                # Check for replies
                processed = await self.check_for_replies()

                if processed > 0:
                    logger.info(f"Processed {processed} replies")

            except asyncio.CancelledError:
                logger.info("WhatsApp listener stopped")
                break
            except Exception as e:
                logger.error(f"Error in listener loop: {e}")

            await asyncio.sleep(interval_seconds)
