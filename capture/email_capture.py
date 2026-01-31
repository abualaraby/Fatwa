"""Email capture module using IMAP."""

import email
import imaplib
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Optional
from loguru import logger

from database import Database, Ticket, SourcePlatform
from .base import BaseCaptureModule


class EmailCapture(BaseCaptureModule):
    """Capture inquiries from email using IMAP."""

    def __init__(self, config: dict, database: Database):
        """Initialize email capture module."""
        super().__init__(config, database)
        self.imap_server = config.get("imap_server", "imap.gmail.com")
        self.imap_port = config.get("imap_port", 993)
        self.email_address = config.get("email_address", "")
        self.password = config.get("password", "")

        self._imap: Optional[imaplib.IMAP4_SSL] = None
        self._processed_email_ids: set = set()

    @property
    def platform_name(self) -> str:
        return "Email"

    async def login(self) -> bool:
        """Login to email server via IMAP."""
        try:
            logger.info(f"Connecting to IMAP server {self.imap_server}...")

            self._imap = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self._imap.login(self.email_address, self.password)

            logger.info("Successfully logged in to email")
            self._is_logged_in = True
            return True

        except Exception as e:
            logger.error(f"Email login error: {e}")
            self._is_logged_in = False
            return False

    async def capture_messages(self) -> list[Ticket]:
        """Capture new email messages."""
        tickets = []

        try:
            logger.info("Capturing email messages...")

            # Select inbox
            self._imap.select("INBOX")

            # Search for unread emails from last 7 days
            date_since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
            _, message_ids = self._imap.search(None, f'(SINCE {date_since})')

            email_ids = message_ids[0].split()
            logger.info(f"Found {len(email_ids)} emails from last 7 days")

            for email_id in email_ids[-50:]:  # Process last 50 emails
                try:
                    email_id_str = email_id.decode() if isinstance(email_id, bytes) else str(email_id)

                    if email_id_str in self._processed_email_ids:
                        continue

                    # Fetch email
                    _, msg_data = self._imap.fetch(email_id, "(RFC822)")

                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])

                            # Decode subject
                            subject = self._decode_header(msg["Subject"])

                            # Get sender
                            sender = self._decode_header(msg["From"])
                            sender_name, sender_email = self._parse_sender(sender)

                            # Get message ID
                            message_id = msg.get("Message-ID", email_id_str)

                            # Get email body
                            body = self._get_email_body(msg)

                            # Combine subject and body for the question
                            question_text = f"Subject: {subject}\n\n{body}"

                            if self._is_question(question_text):
                                ticket = Ticket(
                                    source_platform=SourcePlatform.EMAIL,
                                    sender_id=message_id,
                                    sender_name=sender_name,
                                    sender_contact=sender_email,
                                    question_text=question_text,
                                    original_message_id=message_id,
                                )

                                saved_id = self.save_ticket(ticket)
                                if saved_id:
                                    tickets.append(ticket)
                                    self._processed_email_ids.add(email_id_str)

                except Exception as e:
                    logger.debug(f"Error processing email {email_id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error capturing emails: {e}")

        return tickets

    async def capture_comments(self) -> list[Ticket]:
        """Email doesn't have comments, return empty list."""
        return []

    def _decode_header(self, header: Optional[str]) -> str:
        """Decode email header."""
        if not header:
            return ""

        decoded_parts = []
        for part, encoding in decode_header(header):
            if isinstance(part, bytes):
                try:
                    decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
                except Exception:
                    decoded_parts.append(part.decode("utf-8", errors="replace"))
            else:
                decoded_parts.append(part)

        return " ".join(decoded_parts)

    def _parse_sender(self, sender: str) -> tuple[str, str]:
        """Parse sender string into name and email."""
        if not sender:
            return "Unknown", ""

        # Handle format: "Name <email@example.com>"
        if "<" in sender and ">" in sender:
            parts = sender.split("<")
            name = parts[0].strip().strip('"')
            email_addr = parts[1].rstrip(">").strip()
            return name if name else email_addr, email_addr

        # Just email address
        return sender, sender

    def _get_email_body(self, msg) -> str:
        """Extract email body text."""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
                    except Exception:
                        continue

            # If no plain text, try HTML
            if not body:
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        try:
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or "utf-8"
                            html = payload.decode(charset, errors="replace")
                            # Simple HTML to text conversion
                            body = self._html_to_text(html)
                            break
                        except Exception:
                            continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
            except Exception:
                body = str(msg.get_payload())

        # Truncate if too long
        if len(body) > 2000:
            body = body[:2000] + "..."

        return body.strip()

    def _html_to_text(self, html: str) -> str:
        """Simple HTML to text conversion."""
        import re

        # Remove script and style tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Replace br and p tags with newlines
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)

        # Remove all other HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # Decode HTML entities
        text = text.replace("&nbsp;", " ")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&amp;", "&")
        text = text.replace("&quot;", '"')

        # Clean up whitespace
        text = re.sub(r"\n\s*\n", "\n\n", text)
        text = re.sub(r" +", " ", text)

        return text.strip()

    def _is_question(self, text: str) -> bool:
        """Check if text appears to be a question or inquiry."""
        if not text or len(text) < 10:
            return False

        text_lower = text.lower()

        # Arabic question indicators
        arabic_indicators = [
            "؟", "ما هو", "ما هي", "هل", "كيف", "لماذا", "متى", "أين",
            "حكم", "فتوى", "سؤال", "استفسار", "جزاكم الله", "شيخ",
            "أفتوني", "أريد أن أسأل", "هل يجوز", "ما حكم"
        ]

        # English question indicators
        english_indicators = [
            "?", "what is", "how", "why", "when", "where", "can i",
            "is it", "question", "fatwa", "ruling", "permissible",
            "halal", "haram", "allowed"
        ]

        for indicator in arabic_indicators + english_indicators:
            if indicator in text_lower:
                return True

        return False

    async def close(self):
        """Close IMAP connection."""
        try:
            if self._imap:
                try:
                    self._imap.logout()
                except Exception:
                    pass
                self._imap = None

            self._is_logged_in = False
            logger.info("Email capture module closed")
        except Exception as e:
            logger.error(f"Error closing email capture: {e}")
