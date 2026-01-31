"""Instagram capture module using Playwright with stealth mode."""

import asyncio
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from playwright_stealth import Stealth
from loguru import logger

from database import Database, Ticket, SourcePlatform
from .base import BaseCaptureModule


class InstagramCapture(BaseCaptureModule):
    """Capture inquiries from Instagram (DMs and Comments)."""

    def __init__(self, config: dict, database: Database):
        """Initialize Instagram capture module."""
        super().__init__(config, database)
        self.username = config.get("username", "")
        self.password = config.get("password", "")

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        # Track processed message IDs to avoid duplicates
        self._processed_dm_ids: set = set()
        self._processed_comment_ids: set = set()

    @property
    def platform_name(self) -> str:
        return "Instagram"

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

            # Handle "Save Login Info" popup if present
            try:
                not_now_btn = await self._page.query_selector('button:has-text("Not Now")')
                if not_now_btn:
                    await not_now_btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # Handle notifications popup if present
            try:
                not_now_btn = await self._page.query_selector('button:has-text("Not Now")')
                if not_now_btn:
                    await not_now_btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # Check for login success
            if "accounts/login" in self._page.url.lower() or "challenge" in self._page.url.lower():
                logger.error("Instagram login failed - check credentials or security challenge")
                self._is_logged_in = False
                return False

            logger.info("Successfully logged in to Instagram")
            self._is_logged_in = True
            return True

        except Exception as e:
            logger.error(f"Instagram login error: {e}")
            self._is_logged_in = False
            return False

    async def capture_messages(self) -> list[Ticket]:
        """Capture Instagram direct messages."""
        tickets = []

        try:
            logger.info("Capturing Instagram DMs...")

            # Navigate to Direct Messages
            await self._page.goto("https://www.instagram.com/direct/inbox/", wait_until="networkidle")
            await asyncio.sleep(3)

            # Get conversation threads
            threads = await self._page.query_selector_all('[role="listitem"]')

            for thread in threads[:10]:  # Process last 10 conversations
                try:
                    # Click on thread
                    await thread.click()
                    await asyncio.sleep(2)

                    # Get sender name from thread header
                    header = await self._page.query_selector('[role="main"] header')
                    sender_name = "Unknown"
                    if header:
                        name_elem = await header.query_selector('span, div[style*="font-weight"]')
                        if name_elem:
                            sender_name = await name_elem.inner_text()

                    # Get messages in thread
                    messages = await self._page.query_selector_all('[role="main"] [role="row"]')

                    for msg in messages[-5:]:  # Last 5 messages
                        try:
                            # Get message text
                            text_elem = await msg.query_selector('[dir="auto"]')
                            if not text_elem:
                                continue

                            message_text = await text_elem.inner_text()
                            message_id = f"ig_dm_{hash(message_text + sender_name)}"

                            if message_id in self._processed_dm_ids:
                                continue

                            if self._is_question(message_text):
                                ticket = Ticket(
                                    source_platform=SourcePlatform.INSTAGRAM_DM,
                                    sender_id=message_id,
                                    sender_name=sender_name,
                                    sender_contact=f"https://www.instagram.com/{sender_name}/",
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
                    logger.debug(f"Error processing thread: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error capturing Instagram DMs: {e}")

        return tickets

    async def capture_comments(self) -> list[Ticket]:
        """Capture comments from Instagram posts."""
        tickets = []

        try:
            logger.info("Capturing Instagram comments...")

            # Navigate to profile page
            await self._page.goto(f"https://www.instagram.com/{self.username}/", wait_until="networkidle")
            await asyncio.sleep(2)

            # Get posts
            posts = await self._page.query_selector_all('article a[href*="/p/"]')

            for post in posts[:5]:  # Process last 5 posts
                try:
                    post_href = await post.get_attribute("href")
                    post_id = post_href.split("/p/")[1].rstrip("/") if "/p/" in post_href else ""

                    # Click on post
                    await post.click()
                    await asyncio.sleep(2)

                    # Get comments
                    comments = await self._page.query_selector_all('ul ul')

                    for comment in comments:
                        try:
                            # Get commenter username
                            username_elem = await comment.query_selector('a[role="link"]')
                            commenter_name = await username_elem.inner_text() if username_elem else "Unknown"

                            # Get comment text
                            text_elem = await comment.query_selector('span[dir="auto"]')
                            comment_text = await text_elem.inner_text() if text_elem else ""

                            comment_id = f"ig_comment_{hash(comment_text + commenter_name + post_id)}"

                            if comment_id in self._processed_comment_ids:
                                continue

                            if self._is_question(comment_text):
                                ticket = Ticket(
                                    source_platform=SourcePlatform.INSTAGRAM_COMMENT,
                                    sender_id=comment_id,
                                    sender_name=commenter_name,
                                    sender_contact=f"https://www.instagram.com/{commenter_name}/",
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

                    # Close post modal
                    close_btn = await self._page.query_selector('[aria-label="Close"]')
                    if close_btn:
                        await close_btn.click()
                        await asyncio.sleep(1)

                except Exception as e:
                    logger.debug(f"Error processing post: {e}")
                    # Try to close any open modal
                    try:
                        await self._page.keyboard.press("Escape")
                    except Exception:
                        pass
                    continue

        except Exception as e:
            logger.error(f"Error capturing Instagram comments: {e}")

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

            logger.info("Instagram capture module closed")
        except Exception as e:
            logger.error(f"Error closing Instagram capture: {e}")
