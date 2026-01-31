"""Email dispatch module for sending replies via SMTP."""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import Optional
from loguru import logger

from database import Database, Ticket, SourcePlatform


class EmailDispatch:
    """Send replies back via Email."""

    def __init__(self, config: dict, database: Database):
        """Initialize email dispatch module."""
        self.config = config
        self.database = database

        self.smtp_server = config.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = config.get("smtp_port", 587)
        self.email_address = config.get("email_address", "")
        self.password = config.get("password", "")
        self.sender_name = config.get("sender_name", "Fatwa Office")

        self._smtp: Optional[smtplib.SMTP] = None

    def _connect(self) -> bool:
        """Connect to SMTP server."""
        try:
            self._smtp = smtplib.SMTP(self.smtp_server, self.smtp_port)
            self._smtp.starttls()
            self._smtp.login(self.email_address, self.password)
            logger.info("Connected to SMTP server")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to SMTP server: {e}")
            return False

    def _disconnect(self):
        """Disconnect from SMTP server."""
        if self._smtp:
            try:
                self._smtp.quit()
            except Exception:
                pass
            self._smtp = None

    async def send_reply(self, ticket: Ticket) -> bool:
        """Send a reply email.

        Args:
            ticket: The ticket with the reply to send

        Returns:
            True if sent successfully
        """
        if ticket.source_platform != SourcePlatform.EMAIL:
            logger.warning(f"Invalid platform for email dispatch: {ticket.source_platform}")
            return False

        if not ticket.sender_contact:
            logger.error(f"No email address for ticket #{ticket.id}")
            return False

        try:
            # Connect if not connected
            if not self._smtp:
                if not self._connect():
                    return False

            # Create email message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Re: Fatwa Response #{ticket.id}"
            msg["From"] = formataddr((self.sender_name, self.email_address))
            msg["To"] = ticket.sender_contact

            # Add In-Reply-To header if we have original message ID
            if ticket.original_message_id:
                msg["In-Reply-To"] = ticket.original_message_id
                msg["References"] = ticket.original_message_id

            # Create plain text and HTML versions
            text_content = self._format_reply_text(ticket)
            html_content = self._format_reply_html(ticket)

            part1 = MIMEText(text_content, "plain", "utf-8")
            part2 = MIMEText(html_content, "html", "utf-8")

            msg.attach(part1)
            msg.attach(part2)

            # Send email
            self._smtp.sendmail(
                self.email_address,
                ticket.sender_contact,
                msg.as_string()
            )

            logger.info(f"Email reply sent to {ticket.sender_contact} for ticket #{ticket.id}")
            return True

        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending email: {e}")
            # Try to reconnect on next attempt
            self._disconnect()
            return False
        except Exception as e:
            logger.error(f"Error sending email reply: {e}")
            return False

    def _format_reply_text(self, ticket: Ticket) -> str:
        """Format plain text email reply."""
        return f"""السلام عليكم ورحمة الله وبركاته

الأخ/الأخت الكريم(ة) {ticket.sender_name}،

شكراً لتواصلكم معنا.

بخصوص سؤالكم:
«{ticket.question_text}»

الجواب:
{ticket.answer_text}

والله تعالى أعلم.

─────────────────────────────────────
Fatwa Reference: #{ticket.id}
مكتب الفتوى

Note: This is an automated response. Please do not reply directly to this email.
"""

    def _format_reply_html(self, ticket: Ticket) -> str:
        """Format HTML email reply."""
        return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.8;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .greeting {{
            font-size: 18px;
            color: #2c5f2d;
            margin-bottom: 20px;
        }}
        .question-box {{
            background-color: #f5f5f5;
            border-right: 4px solid #2c5f2d;
            padding: 15px;
            margin: 20px 0;
            border-radius: 4px;
        }}
        .answer-box {{
            background-color: #fff;
            border: 1px solid #ddd;
            padding: 20px;
            margin: 20px 0;
            border-radius: 4px;
        }}
        .footer {{
            border-top: 2px solid #2c5f2d;
            margin-top: 30px;
            padding-top: 20px;
            font-size: 12px;
            color: #666;
        }}
        .ref-number {{
            background-color: #2c5f2d;
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 12px;
            display: inline-block;
        }}
    </style>
</head>
<body>
    <div class="greeting">
        السلام عليكم ورحمة الله وبركاته
    </div>

    <p>الأخ/الأخت الكريم(ة) <strong>{ticket.sender_name}</strong>،</p>

    <p>شكراً لتواصلكم معنا.</p>

    <p><strong>بخصوص سؤالكم:</strong></p>
    <div class="question-box">
        {ticket.question_text}
    </div>

    <p><strong>الجواب:</strong></p>
    <div class="answer-box">
        {ticket.answer_text}
    </div>

    <p>والله تعالى أعلم.</p>

    <div class="footer">
        <span class="ref-number">Fatwa #{ticket.id}</span>
        <p>مكتب الفتوى</p>
        <p style="font-style: italic;">
            Note: This is an automated response. Please do not reply directly to this email.
        </p>
    </div>
</body>
</html>"""

    async def close(self):
        """Close SMTP connection."""
        self._disconnect()
        logger.info("Email dispatch module closed")
