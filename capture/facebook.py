"""Facebook capture module using Playwright with stealth mode."""

import asyncio
import re
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from playwright_stealth import Stealth
from loguru import logger

from database import Database, Ticket, SourcePlatform
from .base import BaseCaptureModule


class FacebookCapture(BaseCaptureModule):
    """Capture inquiries from Facebook (DMs and Comments)."""

    def __init__(self, config: dict, database: Database):
        """Initialize Facebook capture module."""
        super().__init__(config, database)
        self.email = config.get("email", "")
        self.password = config.get("password", "")
        self.page_url = config.get("page_url", "")

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        # Track processed message IDs to avoid duplicates
        self._processed_dm_ids: set = set()
        self._processed_comment_ids: set = set()

    @property
    def platform_name(self) -> str:
        return "Facebook"

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
                logger.error("Facebook login failed - check credentials or security checkpoint")
                self._is_logged_in = False
                return False

            logger.info("Successfully logged in to Facebook")
            self._is_logged_in = True
            return True

        except Exception as e:
            logger.error(f"Facebook login error: {e}")
            self._is_logged_in = False
            return False

    async def capture_messages(self) -> list[Ticket]:
        """Capture Facebook direct messages (Messenger)."""
        tickets = []

        try:
            logger.info("Capturing Facebook DMs...")

            # Navigate to Messenger inbox
            await self._page.goto("https://www.facebook.com/messages/t/", wait_until="networkidle")
            await asyncio.sleep(2)

            # Get conversation list
            conversations = await self._page.query_selector_all('[role="row"]')

            for conv in conversations[:10]:  # Process last 10 conversations
                try:
                    # Click on conversation
                    await conv.click()
                    await asyncio.sleep(1)

                    # Extract conversation data
                    sender_element = await self._page.query_selector('h1, [data-scope="messages_table"] span')
                    sender_name = await sender_element.inner_text() if sender_element else "Unknown"

                    # Get messages
                    messages = await self._page.query_selector_all('[data-scope="messages_table"] [dir="auto"]')

                    for msg in messages[-5:]:  # Last 5 messages
                        try:
                            message_text = await msg.inner_text()
                            message_id = f"fb_dm_{hash(message_text + sender_name)}"

                            if message_id in self._processed_dm_ids:
                                continue

                            # Check if message looks like a question (basic heuristic)
                            if self._is_question(message_text):
                                ticket = Ticket(
                                    source_platform=SourcePlatform.FACEBOOK_DM,
                                    sender_id=message_id,
                                    sender_name=sender_name,
                                    sender_contact=self._page.url,
                                    question_text=message_text,
                                    original_message_id=message_id,
                                )

                                saved_id = self.save_ticket(ticket)
                                if saved_id:
                                    tickets.append(ticket)
                                    self._processed_dm_ids.add(message_id)

                        except Exception as e:
                            logger.debug(f"Error processing message: {e}")
                            continue

                except Exception as e:
                    logger.debug(f"Error processing conversation: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error capturing Facebook DMs: {e}")

        return tickets

    async def capture_comments(self) -> list[Ticket]:
        """Capture comments from Facebook page posts."""
        tickets = []

        if not self.page_url:
            logger.warning("No Facebook page URL configured")
            return tickets

        try:
            logger.info("Capturing Facebook comments...")

            # Navigate to page
            await self._page.goto(self.page_url, wait_until="networkidle")
            await asyncio.sleep(2)

            # Scroll to load more posts
            for _ in range(3):
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)

            # Find posts with comments
            posts = await self._page.query_selector_all('[data-pagelet="FeedUnit"]')

            for post in posts[:5]:  # Process last 5 posts
                try:
                    # Get post ID
                    post_link = await post.query_selector('a[href*="/posts/"], a[href*="/photo"]')
                    post_id = ""
                    if post_link:
                        post_href = await post_link.get_attribute("href")
                        post_id = post_href if post_href else ""

                    # Click "View more comments" if available
                    view_more = await post.query_selector('span:has-text("View more comments")')
                    if view_more:
                        await view_more.click()
                        await asyncio.sleep(1)

                    # Get comments
                    comments = await post.query_selector_all('[aria-label*="Comment"]')

                    for comment in comments:
                        try:
                            # Get commenter name
                            name_elem = await comment.query_selector('a[role="link"] span')
                            sender_name = await name_elem.inner_text() if name_elem else "Unknown"

                            # Get comment text
                            text_elem = await comment.query_selector('[dir="auto"]')
                            comment_text = await text_elem.inner_text() if text_elem else ""

                            comment_id = f"fb_comment_{hash(comment_text + sender_name + post_id)}"

                            if comment_id in self._processed_comment_ids:
                                continue

                            if self._is_question(comment_text):
                                ticket = Ticket(
                                    source_platform=SourcePlatform.FACEBOOK_COMMENT,
                                    sender_id=comment_id,
                                    sender_name=sender_name,
                                    sender_contact=self.page_url,
                                    question_text=comment_text,
                                    original_message_id=comment_id,
                                    original_post_id=post_id,
                                )

                                saved_id = self.save_ticket(ticket)
                                if saved_id:
                                    tickets.append(ticket)
                                    self._processed_comment_ids.add(comment_id)

                        except Exception as e:
                            logger.debug(f"Error processing comment: {e}")
                            continue

                except Exception as e:
                    logger.debug(f"Error processing post: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error capturing Facebook comments: {e}")

        return tickets

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

            logger.info("Facebook capture module closed")
        except Exception as e:
            logger.error(f"Error closing Facebook capture: {e}")
