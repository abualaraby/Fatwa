"""Facebook Page capture module using Playwright with session persistence."""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from playwright_stealth import Stealth
from loguru import logger

from database import Database, Ticket, SourcePlatform
from .base import BaseCaptureModule


class FacebookCapture(BaseCaptureModule):
    """Capture inquiries from Facebook Page (Inbox and Comments).

    Supports:
    - Session persistence (login once, reuse cookies)
    - 2FA (manual code entry during first login)
    - Facebook Page inbox (not personal Messenger)
    - Page post comments
    """

    def __init__(self, config: dict, database: Database):
        """Initialize Facebook Page capture module."""
        super().__init__(config, database)
        self.email = config.get("email", "")
        self.password = config.get("password", "")
        self.page_url = config.get("page_url", "")
        self.page_id = config.get("page_id", "")  # Facebook Page ID

        # Session persistence
        self.session_dir = Path(config.get("session_dir", "./sessions"))
        self.session_file = self.session_dir / "facebook_session.json"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Browser instances
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        # Track processed message IDs to avoid duplicates
        self._processed_dm_ids: set = set()
        self._processed_comment_ids: set = set()

        # 2FA settings
        self.login_timeout = config.get("login_timeout_seconds", 120)  # Wait for manual 2FA

    @property
    def platform_name(self) -> str:
        return "Facebook"

    async def _init_browser(self, headless: bool = False):
        """Initialize Playwright browser with stealth mode and session."""
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

        # Load saved session if exists
        if self._context is None:
            if self.session_file.exists():
                logger.info("Loading saved Facebook session...")
                try:
                    self._context = await self._browser.new_context(
                        storage_state=str(self.session_file),
                        viewport={"width": 1920, "height": 1080},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        locale="ar-SA"
                    )
                except Exception as e:
                    logger.warning(f"Failed to load session: {e}, creating new context")
                    self._context = await self._browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        locale="ar-SA"
                    )
            else:
                self._context = await self._browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="ar-SA"
                )

        if self._page is None:
            self._page = await self._context.new_page()
            stealth = Stealth()
            await stealth.apply_stealth_async(self._page)

    async def _save_session(self):
        """Save browser session (cookies + localStorage) for reuse."""
        if self._context:
            try:
                await self._context.storage_state(path=str(self.session_file))
                logger.info(f"Session saved to {self.session_file}")
            except Exception as e:
                logger.error(f"Failed to save session: {e}")

    async def _check_logged_in(self) -> bool:
        """Check if we're currently logged in to Facebook."""
        try:
            await self._page.goto("https://www.facebook.com/", wait_until="networkidle")
            await asyncio.sleep(2)

            # Check for login indicators
            current_url = self._page.url.lower()

            # If redirected to login page, not logged in
            if "login" in current_url or "/login" in current_url:
                return False

            # Check for user menu or profile elements
            user_menu = await self._page.query_selector('[aria-label="Your profile"], [aria-label="Account"], [aria-label="الملف الشخصي"]')
            if user_menu:
                return True

            # Check for login button (means not logged in)
            login_btn = await self._page.query_selector('a[href*="/login"]')
            if login_btn:
                return False

            return True
        except Exception as e:
            logger.debug(f"Error checking login status: {e}")
            return False

    async def login(self) -> bool:
        """Login to Facebook with 2FA support.

        If 2FA is enabled, the browser will wait for manual code entry.
        Session is saved after successful login for future use.
        """
        try:
            # Always use visible browser for login (need to see 2FA prompt)
            await self._init_browser(headless=False)

            # Check if already logged in via saved session
            if await self._check_logged_in():
                logger.info("Already logged in via saved session")
                self._is_logged_in = True
                return True

            logger.info("Session expired or not found. Starting login...")
            logger.info("=" * 50)
            logger.info("⚠️  2FA SUPPORT: If you have 2FA enabled,")
            logger.info("    please enter the code when prompted in the browser.")
            logger.info("=" * 50)

            # Navigate to login page
            await self._page.goto("https://www.facebook.com/login", wait_until="networkidle")
            await asyncio.sleep(2)

            # Fill login form
            email_input = await self._page.query_selector('input[name="email"], #email')
            pass_input = await self._page.query_selector('input[name="pass"], #pass')

            if email_input and pass_input:
                await email_input.fill(self.email)
                await pass_input.fill(self.password)

                # Click login button
                login_btn = await self._page.query_selector('button[name="login"], button[type="submit"], #loginbutton')
                if login_btn:
                    await login_btn.click()

            # Wait for login completion (including potential 2FA)
            logger.info(f"Waiting up to {self.login_timeout}s for login (including 2FA)...")

            for i in range(self.login_timeout):
                await asyncio.sleep(1)

                current_url = self._page.url.lower()

                # Check for successful login
                if "facebook.com" in current_url and "login" not in current_url and "checkpoint" not in current_url:
                    # Verify we're actually logged in
                    user_menu = await self._page.query_selector('[aria-label="Your profile"], [aria-label="Account"], [aria-label="الملف الشخصي"]')
                    if user_menu:
                        logger.info("✅ Login successful!")
                        self._is_logged_in = True
                        await self._save_session()
                        return True

                # Check if still on 2FA/checkpoint page
                if "checkpoint" in current_url or "two_step" in current_url:
                    if i % 10 == 0:
                        logger.info(f"⏳ Waiting for 2FA code entry... ({i}s)")
                    continue

                # Check for error messages
                error_msg = await self._page.query_selector('[data-testid="royal_login_form_error"], .uiContextualLayerBelowLeft')
                if error_msg:
                    error_text = await error_msg.inner_text()
                    logger.error(f"Login error: {error_text}")
                    return False

            logger.error("Login timeout - please try again")
            return False

        except Exception as e:
            logger.error(f"Facebook login error: {e}")
            self._is_logged_in = False
            return False

    async def capture_messages(self) -> list[Ticket]:
        """Capture messages from Facebook Page Inbox.

        Uses Meta Business Suite / Facebook Page Inbox instead of personal Messenger.
        """
        tickets = []

        try:
            logger.info("Capturing Facebook Page inbox messages...")

            # Try Meta Business Suite inbox first (recommended)
            inbox_urls = [
                f"https://business.facebook.com/latest/inbox/all?asset_id={self.page_id}" if self.page_id else None,
                "https://www.facebook.com/messages/t/",  # Fallback to page messages
                f"{self.page_url}/inbox/" if self.page_url else None,
            ]

            inbox_loaded = False
            for url in inbox_urls:
                if not url:
                    continue
                try:
                    await self._page.goto(url, wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(3)

                    # Check if inbox loaded
                    conversations = await self._page.query_selector_all('[role="row"], [role="listitem"], [data-testid="mwthreadlist-item"]')
                    if conversations:
                        inbox_loaded = True
                        logger.info(f"Loaded inbox from: {url}")
                        break
                except Exception as e:
                    logger.debug(f"Failed to load {url}: {e}")
                    continue

            if not inbox_loaded:
                logger.warning("Could not load Page inbox")
                return tickets

            # Get conversation list
            conversations = await self._page.query_selector_all('[role="row"], [role="listitem"], [data-testid="mwthreadlist-item"]')
            logger.info(f"Found {len(conversations)} conversations")

            for conv in conversations[:15]:  # Process last 15 conversations
                try:
                    # Click on conversation
                    await conv.click()
                    await asyncio.sleep(2)

                    # Extract sender info
                    sender_name = "Unknown"
                    sender_elements = await self._page.query_selector_all('h2, h1, [role="heading"]')
                    for elem in sender_elements:
                        text = await elem.inner_text()
                        if text and len(text) > 1 and len(text) < 100:
                            sender_name = text.strip()
                            break

                    # Get conversation URL as contact
                    conversation_url = self._page.url

                    # Get messages in conversation
                    messages = await self._page.query_selector_all('[dir="auto"], [data-testid="message-text"]')

                    for msg in messages[-10:]:  # Last 10 messages
                        try:
                            message_text = await msg.inner_text()
                            message_text = message_text.strip()

                            if not message_text or len(message_text) < 5:
                                continue

                            message_id = f"fb_page_dm_{hash(message_text + sender_name + conversation_url)}"

                            if message_id in self._processed_dm_ids:
                                continue

                            # Check if message looks like a question
                            if self._is_question(message_text):
                                ticket = Ticket(
                                    source_platform=SourcePlatform.FACEBOOK_DM,
                                    sender_id=message_id,
                                    sender_name=sender_name,
                                    sender_contact=conversation_url,
                                    question_text=message_text,
                                    original_message_id=message_id,
                                )

                                saved_id = self.save_ticket(ticket)
                                if saved_id:
                                    tickets.append(ticket)
                                    self._processed_dm_ids.add(message_id)
                                    logger.debug(f"Captured message from {sender_name}")

                        except Exception as e:
                            logger.debug(f"Error processing message: {e}")
                            continue

                except Exception as e:
                    logger.debug(f"Error processing conversation: {e}")
                    continue

            logger.info(f"Captured {len(tickets)} new messages from Page inbox")

        except Exception as e:
            logger.error(f"Error capturing Facebook Page messages: {e}")

        return tickets

    async def capture_comments(self) -> list[Ticket]:
        """Capture comments from Facebook Page posts."""
        tickets = []

        if not self.page_url:
            logger.warning("No Facebook page URL configured")
            return tickets

        try:
            logger.info("Capturing Facebook Page comments...")

            # Navigate to page
            await self._page.goto(self.page_url, wait_until="networkidle")
            await asyncio.sleep(3)

            # Scroll to load more posts
            for _ in range(5):
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)

            # Find posts
            posts = await self._page.query_selector_all('[data-pagelet="FeedUnit"], [role="article"]')
            logger.info(f"Found {len(posts)} posts")

            for post in posts[:10]:  # Process last 10 posts
                try:
                    # Get post URL/ID
                    post_link = await post.query_selector('a[href*="/posts/"], a[href*="/photo"], a[href*="permalink"]')
                    post_id = ""
                    if post_link:
                        post_href = await post_link.get_attribute("href")
                        post_id = post_href if post_href else ""

                    # Try to expand comments
                    expand_selectors = [
                        'span:has-text("View more comments")',
                        'span:has-text("عرض المزيد من التعليقات")',
                        '[aria-label*="comments"]',
                        'div[role="button"]:has-text("comment")'
                    ]

                    for selector in expand_selectors:
                        try:
                            expand_btn = await post.query_selector(selector)
                            if expand_btn:
                                await expand_btn.click()
                                await asyncio.sleep(1)
                        except Exception:
                            pass

                    # Get comments
                    comments = await post.query_selector_all('[aria-label*="Comment"], [data-testid="UFI2Comment/root_depth_0"]')

                    for comment in comments:
                        try:
                            # Get commenter name
                            name_elem = await comment.query_selector('a[role="link"] span, a[href*="/user/"] span')
                            sender_name = await name_elem.inner_text() if name_elem else "Unknown"

                            # Get comment text
                            text_elem = await comment.query_selector('[dir="auto"], [data-ad-comet-preview="message"]')
                            comment_text = await text_elem.inner_text() if text_elem else ""
                            comment_text = comment_text.strip()

                            if not comment_text:
                                continue

                            comment_id = f"fb_page_comment_{hash(comment_text + sender_name + post_id)}"

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
                                    logger.debug(f"Captured comment from {sender_name}")

                        except Exception as e:
                            logger.debug(f"Error processing comment: {e}")
                            continue

                except Exception as e:
                    logger.debug(f"Error processing post: {e}")
                    continue

            logger.info(f"Captured {len(tickets)} new comments from Page posts")

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
            "أفتوني", "أريد أن أسأل", "هل يجوز", "ما حكم", "أسأل",
            "افتوني", "ما رأي", "ما رأيكم", "اريد ان اعرف", "محتاج فتوى"
        ]

        # English question indicators
        english_indicators = [
            "?", "what is", "how", "why", "when", "where", "can i",
            "is it", "question", "fatwa", "ruling", "permissible",
            "halal", "haram", "allowed", "please tell", "sheikh"
        ]

        for indicator in arabic_indicators + english_indicators:
            if indicator in text_lower:
                return True

        return False

    async def clear_session(self):
        """Clear saved session (force new login next time)."""
        if self.session_file.exists():
            self.session_file.unlink()
            logger.info("Session cleared")

    async def close(self):
        """Close browser and cleanup (but preserve session)."""
        try:
            # Save session before closing
            if self._is_logged_in:
                await self._save_session()

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
