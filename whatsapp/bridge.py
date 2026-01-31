"""WhatsApp Bridge - Python client for Node.js WhatsApp bridge."""

import asyncio
import subprocess
import sys
import os
from pathlib import Path
from typing import Optional
import aiohttp
from loguru import logger


class WhatsAppBridge:
    """Client for the Node.js WhatsApp bridge."""

    def __init__(self, config: dict):
        """Initialize WhatsApp bridge client.

        Args:
            config: WhatsApp configuration from config.json
        """
        self.port = config.get("node_bridge_port", 3001)
        self.base_url = f"http://localhost:{self.port}"
        self.session_path = config.get("session_path", "./whatsapp_node/session")

        self._node_process: Optional[subprocess.Popen] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def start_bridge(self) -> bool:
        """Start the Node.js bridge server."""
        try:
            # Check if already running
            if await self.is_connected():
                logger.info("WhatsApp bridge already running")
                return True

            # Find the Node.js bridge directory
            bridge_dir = Path(__file__).parent.parent / "whatsapp_node"

            if not bridge_dir.exists():
                logger.error(f"WhatsApp Node bridge not found at {bridge_dir}")
                return False

            # Check if node_modules exists
            if not (bridge_dir / "node_modules").exists():
                logger.info("Installing Node.js dependencies...")
                install_result = subprocess.run(
                    ["npm", "install"],
                    cwd=bridge_dir,
                    capture_output=True,
                    text=True
                )
                if install_result.returncode != 0:
                    logger.error(f"npm install failed: {install_result.stderr}")
                    return False

            # Start the Node.js server
            logger.info("Starting WhatsApp bridge server...")

            env = os.environ.copy()
            env["PORT"] = str(self.port)
            env["SESSION_PATH"] = str(Path(bridge_dir) / "session")

            self._node_process = subprocess.Popen(
                ["node", "index.js"],
                cwd=bridge_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            # Wait for server to start
            for _ in range(30):  # Wait up to 30 seconds
                await asyncio.sleep(1)
                try:
                    status = await self.get_status()
                    if status:
                        logger.info("WhatsApp bridge server started")
                        return True
                except Exception:
                    continue

            logger.error("WhatsApp bridge failed to start within timeout")
            return False

        except Exception as e:
            logger.error(f"Error starting WhatsApp bridge: {e}")
            return False

    async def stop_bridge(self):
        """Stop the Node.js bridge server."""
        if self._node_process:
            self._node_process.terminate()
            try:
                self._node_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._node_process.kill()
            self._node_process = None
            logger.info("WhatsApp bridge server stopped")

        if self._session:
            await self._session.close()
            self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_status(self) -> dict:
        """Get WhatsApp connection status."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/status") as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception as e:
            logger.debug(f"Status check failed: {e}")
            return None

    async def is_connected(self) -> bool:
        """Check if WhatsApp is connected."""
        status = await self.get_status()
        return status and status.get("status") == "connected"

    async def get_qr_code(self) -> Optional[str]:
        """Get QR code for WhatsApp Web scanning."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/qr") as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("qrCode")
                return None
        except Exception as e:
            logger.error(f"Error getting QR code: {e}")
            return None

    async def send_message(self, phone: str, message: str, ticket_id: Optional[int] = None) -> dict:
        """Send a WhatsApp message.

        Args:
            phone: Phone number (with country code)
            message: Message text
            ticket_id: Optional ticket ID for tracking replies

        Returns:
            Response dict with success status and message ID
        """
        try:
            session = await self._get_session()
            payload = {
                "phone": phone,
                "message": message,
            }
            if ticket_id:
                payload["ticketId"] = ticket_id

            async with session.post(f"{self.base_url}/send", json=payload) as response:
                result = await response.json()
                if response.status == 200:
                    logger.info(f"Message sent to {phone}")
                    return result
                else:
                    logger.error(f"Failed to send message: {result}")
                    return {"success": False, "error": result.get("error", "Unknown error")}
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return {"success": False, "error": str(e)}

    async def get_messages(self, since: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Get incoming messages.

        Args:
            since: ISO timestamp to get messages after
            limit: Maximum number of messages to return

        Returns:
            List of message dicts
        """
        try:
            session = await self._get_session()
            params = {"limit": limit}
            if since:
                params["since"] = since

            async with session.get(f"{self.base_url}/messages", params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("messages", [])
                return []
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []

    async def clear_messages(self, message_ids: list[str]) -> bool:
        """Clear processed messages from the queue.

        Args:
            message_ids: List of message IDs to clear

        Returns:
            True if successful
        """
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/messages/clear",
                json={"messageIds": message_ids}
            ) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Error clearing messages: {e}")
            return False

    async def logout(self) -> bool:
        """Logout from WhatsApp."""
        try:
            session = await self._get_session()
            async with session.post(f"{self.base_url}/logout") as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Error logging out: {e}")
            return False
