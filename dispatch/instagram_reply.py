"""Instagram dispatch module for sending replies."""

import asyncio
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from playwright_stealth import Stealth
from loguru import logger

from database import Database, Ticket, SourcePlatform


class InstagramDispatch:
    """Send replies back to Instagram (DMs and Comments)."""

    def __init__(self, config: dict, database: Database):
        """Initialize Instagram dispatch module."""
        self.config = config
        self.database = database
        self.username = config.get("username", "")
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
        """Login to Instagram."""
        try:
            await self._init_browser(headless=self.config.get("headless", False))

            logger.info("Navigating to Instagram login page...")
            await self._page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle")
            await asyncio.sleep(2)

            # Handle cookie consent if present
            try:
                cookie_btn = await self._page.query_selector('button:has-text("Allow"), button:has-text("Accept")')
                if cookie_btn:
                    await cookie_btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # Check if already logged in
            if "accounts/login" not in self._page.url.lower():
                logger.info("Already logged in to Instagram")
                self._is_logged_in = True
                return True

            # Fill login form
            await self._page.fill('input[name="username"]', self.username)
            await self._page.fill('input[name="password"]', self.password)

            # Click login button
            await self._page.click('button[type="submit"]')

            # Wait for navigation
            await asyncio.sleep(5)

            # Handle popups
            try:
                not_now_btn = await self._page.query_selector('button:has-text("Not Now")')
                if not_now_btn:
                    await not_now_btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # Check for login success
            if "accounts/login" in self._page.url.lower() or "challenge" in self._page.url.lower():
                logger.error("Instagram login failed")
                self._is_logged_in = False
                return False

            logger.info("Successfully logged in to Instagram")
            self._is_logged_in = True
            return True

        except Exception as e:
            logger.error(f"Instagram login error: {e}")
            self._is_logged_in = False
            return False

    async def send_dm_reply(self, ticket: Ticket) -> bool:
        """Send a reply via Instagram DM.

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

            # Navigate to Direct Messages
            await self._page.goto("https://www.instagram.com/direct/inbox/", wait_until="networkidle")
            await asyncio.sleep(2)

            # Search for the conversation
            # Look for search or new message button
            search_btn = await self._page.query_selector('[aria-label="Search"], [aria-label="New message"]')
            if search_btn:
                await search_btn.click()
                await asyncio.sleep(1)

            # Search for recipient
            search_input = await self._page.query_selector('input[placeholder*="Search"]')
            if search_input:
                await search_input.fill(ticket.sender_name)
                await asyncio.sleep(2)

                # Click on first result
                results = await self._page.query_selector_all('[role="button"]')
                for result in results:
                    text = await result.inner_text()
                    if ticket.sender_name.lower() in text.lower():
                        await result.click()
                        break
                await asyncio.sleep(1)

            # Find message input
            message_input = await self._page.query_selector(
                'textarea[placeholder*="Message"], [aria-label*="Message"]'
            )

            if message_input:
                await message_input.click()
                await message_input.fill(reply_message)

                # Send message
                send_btn = await self._page.query_selector('[aria-label="Send"]')
                if send_btn:
                    await send_btn.click()
                else:
                    await self._page.keyboard.press("Enter")

                await asyncio.sleep(2)
                logger.info(f"Instagram DM reply sent for ticket #{ticket.id}")
                return True
            else:
                logger.error("Could not find message input")
                return False

        except Exception as e:
            logger.error(f"Error sending Instagram DM reply: {e}")
            return False

    async def send_comment_reply(self, ticket: Ticket) -> bool:
        """Send a reply as a comment on Instagram.

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
            reply_message = self._format_reply(ticket, short=True)

            # Navigate to the original post
            post_id = ticket.original_post_id
            if not post_id:
                logger.warning(f"No post ID for ticket #{ticket.id}")
                return False

            post_url = f"https://www.instagram.com/p/{post_id}/"
            await self._page.goto(post_url, wait_until="networkidle")
            await asyncio.sleep(2)

            # Find comment input
            comment_input = await self._page.query_selector(
                'textarea[placeholder*="Add a comment"], [aria-label*="Add a comment"]'
            )

            if comment_input:
                await comment_input.click()
                await asyncio.sleep(0.5)

                # Type the reply (mentioning the sender)
                await comment_input.fill(f"@{ticket.sender_name} {reply_message}")

                # Submit comment
                post_btn = await self._page.query_selector('button:has-text("Post")')
                if post_btn:
                    await post_btn.click()
                else:
                    await self._page.keyboard.press("Enter")

                await asyncio.sleep(2)
                logger.info(f"Instagram comment reply sent for ticket #{ticket.id}")
                return True
            else:
                logger.error("Could not find comment input")
                return False

        except Exception as e:
            logger.error(f"Error sending Instagram comment reply: {e}")
            return False

    async def send_reply(self, ticket: Ticket) -> bool:
        """Send a reply based on the source platform type.

        Args:
            ticket: The ticket to reply to

        Returns:
            True if sent successfully
        """
        if ticket.source_platform == SourcePlatform.INSTAGRAM_DM:
            return await self.send_dm_reply(ticket)
        elif ticket.source_platform == SourcePlatform.INSTAGRAM_COMMENT:
            return await self.send_comment_reply(ticket)
        else:
            logger.warning(f"Invalid platform for Instagram dispatch: {ticket.source_platform}")
            return False

    def _format_reply(self, ticket: Ticket, short: bool = False) -> str:
        """Format the reply message."""
        if short:
            # Short format for comments (Instagram has character limits)
            return (
                f"الجواب: {ticket.answer_text[:400]}{'...' if len(ticket.answer_text) > 400 else ''}\n"
                f"والله أعلم | Fatwa #{ticket.id}"
            )
        else:
            return (
                f"السلام عليكم ورحمة الله\n\n"
                f"بخصوص سؤالكم:\n"
                f"«{ticket.question_text[:150]}{'...' if len(ticket.question_text) > 150 else ''}»\n\n"
                f"الجواب:\n{ticket.answer_text}\n\n"
                f"والله تعالى أعلم\n"
                f"──────────\n"
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

            logger.info("Instagram dispatch module closed")
        except Exception as e:
            logger.error(f"Error closing Instagram dispatch: {e}")
