"""Facebook dispatch module for sending replies."""

import asyncio
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from playwright_stealth import Stealth
from loguru import logger

from database import Database, Ticket, SourcePlatform


class FacebookDispatch:
    """Send replies back to Facebook (DMs and Comments)."""

    def __init__(self, config: dict, database: Database):
        """Initialize Facebook dispatch module."""
        self.config = config
        self.database = database
        self.email = config.get("email", "")
        self.password = config.get("password", "")

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._is_logged_in = False

    async def _init_browser(self, headless: bool = False):
        """Initialize Playwright browser with stealth mode."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        if self._browser is None:
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )

        if self._context is None:
            self._context = await self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        if self._page is None:
            self._page = await self._context.new_page()
            stealth = Stealth()
            await stealth.apply_stealth_async(self._page)

    async def login(self) -> bool:
        """Login to Facebook."""
        try:
            await self._init_browser(headless=self.config.get("headless", False))

            logger.info("Navigating to Facebook login page...")
            await self._page.goto("https://www.facebook.com/login", wait_until="networkidle")

            # Check if already logged in
            if "login" not in self._page.url.lower():
                logger.info("Already logged in to Facebook")
                self._is_logged_in = True
                return True

            # Fill login form
            await self._page.fill('input[name="email"]', self.email)
            await self._page.fill('input[name="pass"]', self.password)

            # Click login button
            await self._page.click('button[name="login"]')

            # Wait for navigation
            await asyncio.sleep(3)
            await self._page.wait_for_load_state("networkidle")

            # Check for login success
            if "login" in self._page.url.lower() or "checkpoint" in self._page.url.lower():
                logger.error("Facebook login failed")
                self._is_logged_in = False
                return False

            logger.info("Successfully logged in to Facebook")
            self._is_logged_in = True
            return True

        except Exception as e:
            logger.error(f"Facebook login error: {e}")
            self._is_logged_in = False
            return False

    async def send_dm_reply(self, ticket: Ticket) -> bool:
        """Send a reply via Facebook Messenger DM.

        Args:
            ticket: The ticket with the reply to send

        Returns:
            True if sent successfully
        """
        if not self._is_logged_in:
            if not await self.login():
                return False

        try:
            # Format the reply
            reply_message = self._format_reply(ticket)

            # Navigate to Messenger
            await self._page.goto("https://www.facebook.com/messages/t/", wait_until="networkidle")
            await asyncio.sleep(2)

            # Search for the conversation by sender name
            search_box = await self._page.query_selector('[aria-label="Search Messenger"]')
            if search_box:
                await search_box.click()
                await search_box.fill(ticket.sender_name)
                await asyncio.sleep(2)

                # Click on the first search result
                results = await self._page.query_selector_all('[role="listitem"]')
                if results:
                    await results[0].click()
                    await asyncio.sleep(1)

            # Find message input
            message_input = await self._page.query_selector(
                '[aria-label*="message"], [contenteditable="true"]'
            )

            if message_input:
                await message_input.click()
                await message_input.fill(reply_message)

                # Send message (Enter or click send button)
                await self._page.keyboard.press("Enter")
                await asyncio.sleep(2)

                logger.info(f"DM reply sent for ticket #{ticket.id}")
                return True
            else:
                logger.error("Could not find message input")
                return False

        except Exception as e:
            logger.error(f"Error sending Facebook DM reply: {e}")
            return False

    async def send_comment_reply(self, ticket: Ticket) -> bool:
        """Send a reply as a comment on Facebook.

        Args:
            ticket: The ticket with the reply to send

        Returns:
            True if sent successfully
        """
        if not self._is_logged_in:
            if not await self.login():
                return False

        try:
            # Format the reply
            reply_message = self._format_reply(ticket)

            # Navigate to the original post
            post_url = ticket.original_post_id
            if not post_url:
                logger.warning(f"No post URL for ticket #{ticket.id}")
                return False

            await self._page.goto(post_url, wait_until="networkidle")
            await asyncio.sleep(2)

            # Find comment input or reply button
            comment_input = await self._page.query_selector(
                '[aria-label*="Write a comment"], [aria-label*="Reply"]'
            )

            if comment_input:
                await comment_input.click()
                await asyncio.sleep(0.5)

                # Type the reply (mentioning the sender if possible)
                await comment_input.fill(f"@{ticket.sender_name} {reply_message}")

                # Submit comment
                await self._page.keyboard.press("Enter")
                await asyncio.sleep(2)

                logger.info(f"Comment reply sent for ticket #{ticket.id}")
                return True
            else:
                logger.error("Could not find comment input")
                return False

        except Exception as e:
            logger.error(f"Error sending Facebook comment reply: {e}")
            return False

    async def send_reply(self, ticket: Ticket) -> bool:
        """Send a reply based on the source platform type.

        Args:
            ticket: The ticket to reply to

        Returns:
            True if sent successfully
        """
        if ticket.source_platform == SourcePlatform.FACEBOOK_DM:
            return await self.send_dm_reply(ticket)
        elif ticket.source_platform == SourcePlatform.FACEBOOK_COMMENT:
            return await self.send_comment_reply(ticket)
        else:
            logger.warning(f"Invalid platform for Facebook dispatch: {ticket.source_platform}")
            return False

    def _format_reply(self, ticket: Ticket) -> str:
        """Format the reply message."""
        return (
            f"السلام عليكم ورحمة الله وبركاته\n\n"
            f"بخصوص سؤالكم:\n"
            f"«{ticket.question_text[:200]}{'...' if len(ticket.question_text) > 200 else ''}»\n\n"
            f"الجواب:\n{ticket.answer_text}\n\n"
            f"والله تعالى أعلم\n"
            f"─────────────────\n"
            f"Fatwa #{ticket.id}"
        )

    async def close(self):
        """Close browser and cleanup."""
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()

            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self._is_logged_in = False

            logger.info("Facebook dispatch module closed")
        except Exception as e:
            logger.error(f"Error closing Facebook dispatch: {e}")
