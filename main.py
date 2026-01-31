#!/usr/bin/env python3
"""
Fatwa Management System - Main Entry Point

This script runs the complete Fatwa management system including:
- Capture loops for Facebook, Instagram, and Email
- WhatsApp bridge for Shaikh communication
- Reply listener for processing Shaikh responses
- Dispatch module for sending replies back to users
"""

import asyncio
import json
import signal
import sys
from pathlib import Path
from typing import Optional
from loguru import logger

# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    "logs/fatwa_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG"
)

from database import Database, get_database
from capture import FacebookCapture, InstagramCapture, EmailCapture
from whatsapp import WhatsAppBridge, WhatsAppSender, WhatsAppListener
from dispatch import Dispatcher


class FatwaManagementSystem:
    """Main orchestrator for the Fatwa Management System."""

    def __init__(self, config_path: str = "config.json"):
        """Initialize the system.

        Args:
            config_path: Path to configuration file
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.database = get_database(str(self.config_path))

        # Modules
        self._facebook_capture: Optional[FacebookCapture] = None
        self._instagram_capture: Optional[InstagramCapture] = None
        self._email_capture: Optional[EmailCapture] = None
        self._whatsapp_bridge: Optional[WhatsAppBridge] = None
        self._whatsapp_sender: Optional[WhatsAppSender] = None
        self._whatsapp_listener: Optional[WhatsAppListener] = None
        self._dispatcher: Optional[Dispatcher] = None

        # Control flags
        self._running = False
        self._tasks: list[asyncio.Task] = []

    def _load_config(self) -> dict:
        """Load configuration from file."""
        if not self.config_path.exists():
            logger.error(f"Config file not found: {self.config_path}")
            sys.exit(1)

        with open(self.config_path) as f:
            return json.load(f)

    async def initialize(self):
        """Initialize all modules."""
        logger.info("Initializing Fatwa Management System...")

        # Initialize capture modules
        fb_config = self.config.get("facebook", {})
        if fb_config.get("enabled", False):
            self._facebook_capture = FacebookCapture(fb_config, self.database)
            logger.info("Facebook capture initialized")

        ig_config = self.config.get("instagram", {})
        if ig_config.get("enabled", False):
            self._instagram_capture = InstagramCapture(ig_config, self.database)
            logger.info("Instagram capture initialized")

        email_config = self.config.get("email", {})
        if email_config.get("enabled", False):
            self._email_capture = EmailCapture(email_config, self.database)
            logger.info("Email capture initialized")

        # Initialize WhatsApp bridge
        wa_config = self.config.get("whatsapp", {})
        wa_config["shaikhs"] = self.config.get("shaikhs", [])

        self._whatsapp_bridge = WhatsAppBridge(wa_config)
        self._whatsapp_sender = WhatsAppSender(wa_config, self.database, self._whatsapp_bridge)
        self._whatsapp_listener = WhatsAppListener(wa_config, self.database, self._whatsapp_bridge)
        logger.info("WhatsApp modules initialized")

        # Initialize dispatcher
        self._dispatcher = Dispatcher(self.config, self.database)
        logger.info("Dispatcher initialized")

    async def start_whatsapp_bridge(self):
        """Start the WhatsApp Node.js bridge."""
        logger.info("Starting WhatsApp bridge...")
        success = await self._whatsapp_bridge.start_bridge()

        if success:
            logger.info("WhatsApp bridge started successfully")

            # Wait for connection
            for i in range(60):  # Wait up to 60 seconds for QR scan
                if await self._whatsapp_bridge.is_connected():
                    logger.info("WhatsApp connected!")
                    return True

                qr = await self._whatsapp_bridge.get_qr_code()
                if qr and i % 10 == 0:
                    logger.info("Waiting for WhatsApp QR code scan...")

                await asyncio.sleep(1)

            logger.warning("WhatsApp connection timeout - please scan QR code")
            return False
        else:
            logger.error("Failed to start WhatsApp bridge")
            return False

    async def capture_loop(self):
        """Run the capture loop for all platforms."""
        settings = self.config.get("settings", {})

        if not settings.get("capture_loop_enabled", True):
            logger.info("Capture loop is disabled")
            return

        logger.info("Starting capture loop...")

        fb_interval = self.config.get("facebook", {}).get("check_interval_minutes", 5)
        ig_interval = self.config.get("instagram", {}).get("check_interval_minutes", 5)
        email_interval = self.config.get("email", {}).get("check_interval_minutes", 2)

        # Track last capture times
        last_fb_capture = 0
        last_ig_capture = 0
        last_email_capture = 0

        while self._running:
            try:
                current_time = asyncio.get_event_loop().time()

                # Facebook capture
                if self._facebook_capture and (current_time - last_fb_capture) >= fb_interval * 60:
                    try:
                        tickets = await self._facebook_capture.capture_all()
                        if tickets:
                            logger.info(f"Captured {len(tickets)} new tickets from Facebook")
                        last_fb_capture = current_time
                    except Exception as e:
                        logger.error(f"Facebook capture error: {e}")

                # Instagram capture
                if self._instagram_capture and (current_time - last_ig_capture) >= ig_interval * 60:
                    try:
                        tickets = await self._instagram_capture.capture_all()
                        if tickets:
                            logger.info(f"Captured {len(tickets)} new tickets from Instagram")
                        last_ig_capture = current_time
                    except Exception as e:
                        logger.error(f"Instagram capture error: {e}")

                # Email capture
                if self._email_capture and (current_time - last_email_capture) >= email_interval * 60:
                    try:
                        tickets = await self._email_capture.capture_all()
                        if tickets:
                            logger.info(f"Captured {len(tickets)} new tickets from Email")
                        last_email_capture = current_time
                    except Exception as e:
                        logger.error(f"Email capture error: {e}")

                # Sleep for a short interval
                await asyncio.sleep(30)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Capture loop error: {e}")
                await asyncio.sleep(60)

    async def sender_loop(self):
        """Run the WhatsApp sender loop."""
        logger.info("Starting WhatsApp sender loop...")

        while self._running:
            try:
                # Check if WhatsApp is connected
                if not await self._whatsapp_bridge.is_connected():
                    logger.warning("WhatsApp not connected, skipping sender loop iteration")
                    await asyncio.sleep(30)
                    continue

                # Send assigned tickets to Shaikhs
                sent_count = await self._whatsapp_sender.send_pending_tickets()

                if sent_count > 0:
                    logger.info(f"Sent {sent_count} tickets to Shaikhs")

                # Sleep before next check
                await asyncio.sleep(30)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sender loop error: {e}")
                await asyncio.sleep(60)

    async def listener_loop(self):
        """Run the WhatsApp listener loop."""
        settings = self.config.get("settings", {})

        if not settings.get("listener_loop_enabled", True):
            logger.info("Listener loop is disabled")
            return

        logger.info("Starting WhatsApp listener loop...")

        while self._running:
            try:
                # Check if WhatsApp is connected
                if not await self._whatsapp_bridge.is_connected():
                    await asyncio.sleep(30)
                    continue

                # Check for Shaikh replies
                processed = await self._whatsapp_listener.check_for_replies()

                if processed > 0:
                    logger.info(f"Processed {processed} Shaikh replies")

                await asyncio.sleep(10)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Listener loop error: {e}")
                await asyncio.sleep(60)

    async def dispatch_loop(self):
        """Run the dispatch loop for sending replies back to platforms."""
        settings = self.config.get("settings", {})

        if not settings.get("auto_dispatch_replies", False):
            logger.info("Auto dispatch is disabled - replies must be dispatched manually")
            return

        logger.info("Starting dispatch loop...")

        while self._running:
            try:
                results = await self._dispatcher.dispatch_all_replied()

                if results["success"] > 0:
                    logger.info(f"Dispatched {results['success']} replies")

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Dispatch loop error: {e}")
                await asyncio.sleep(120)

    async def run(self):
        """Run the complete system."""
        try:
            await self.initialize()

            # Start WhatsApp bridge
            await self.start_whatsapp_bridge()

            self._running = True

            # Create all async tasks
            self._tasks = [
                asyncio.create_task(self.capture_loop()),
                asyncio.create_task(self.sender_loop()),
                asyncio.create_task(self.listener_loop()),
                asyncio.create_task(self.dispatch_loop()),
            ]

            logger.info("Fatwa Management System is running")
            logger.info("Press Ctrl+C to stop")

            # Wait for all tasks
            await asyncio.gather(*self._tasks, return_exceptions=True)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Gracefully shutdown the system."""
        logger.info("Shutting down Fatwa Management System...")

        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Close all modules
        if self._facebook_capture:
            await self._facebook_capture.close()

        if self._instagram_capture:
            await self._instagram_capture.close()

        if self._email_capture:
            await self._email_capture.close()

        if self._dispatcher:
            await self._dispatcher.close()

        if self._whatsapp_bridge:
            await self._whatsapp_bridge.stop_bridge()

        logger.info("Shutdown complete")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Fatwa Management System")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to configuration file (default: config.json)"
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Run the Streamlit dashboard instead of the main system"
    )

    args = parser.parse_args()

    if args.dashboard:
        import subprocess
        dashboard_path = Path(__file__).parent / "dashboard" / "app.py"
        subprocess.run(["streamlit", "run", str(dashboard_path)])
    else:
        # Create logs directory
        Path("logs").mkdir(exist_ok=True)

        # Run the system
        system = FatwaManagementSystem(args.config)
        asyncio.run(system.run())


if __name__ == "__main__":
    main()
