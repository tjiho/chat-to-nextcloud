import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import aiohttp
from nio import (
    AsyncClient,
    InviteMemberEvent,
    LoginError,
    MatrixRoom,
    RoomMessageAudio,
    RoomMessageFile,
    RoomMessageImage,
    RoomMessageVideo,
    SyncError,
    SyncResponse,
    WhoamiError,
    WhoamiResponse,
)

from ..config import MatrixConfig
from .base import BaseAdapter, FileMessage

logger = logging.getLogger(__name__)


class MatrixAuthError(Exception):
    """Raised when Matrix authentication fails."""

    pass


def _check_encryption_dependencies() -> bool:
    """Check if encryption dependencies are available."""
    try:
        import olm  # noqa: F401

        return True
    except ImportError:
        return False


class MatrixAdapter(BaseAdapter):
    platform_name = "matrix"

    def __init__(self, config: MatrixConfig):
        self.config = config

        if config.encryption:
            if not _check_encryption_dependencies():
                raise MatrixAuthError(
                    "Encryption is enabled but dependencies are missing.\n"
                    "Install with: uv sync --extra encryption\n"
                    "Or disable encryption in config.yaml: encryption: false"
                )
            # Store path for encryption keys
            store_path = Path.home() / ".local" / "share" / "chat-to-nextcloud"
            store_path.mkdir(parents=True, exist_ok=True)
            self.client = AsyncClient(
                config.homeserver,
                config.user_id,
                store_path=str(store_path),
            )
        else:
            self.client = AsyncClient(config.homeserver, config.user_id)

        self.client.access_token = config.access_token

        self._file_queue: asyncio.Queue[FileMessage] = asyncio.Queue()
        self._running = False

    async def connect(self) -> None:
        # Verify credentials first
        await self._verify_credentials()

        self.client.add_event_callback(self._on_invite, InviteMemberEvent)
        self.client.add_event_callback(self._on_message, RoomMessageImage)
        self.client.add_event_callback(self._on_message, RoomMessageVideo)
        self.client.add_event_callback(self._on_message, RoomMessageAudio)
        self.client.add_event_callback(self._on_message, RoomMessageFile)

        # Initial sync
        logger.info("Starting initial sync (this may take a moment)...")
        response = await self.client.sync(timeout=30000, full_state=True)

        if isinstance(response, SyncError):
            raise MatrixAuthError(
                f"Sync failed: {response.message}\n"
                f"Check your access_token and homeserver URL."
            )

        logger.info(f"Connected to Matrix as {self.config.user_id}")
        logger.info(f"Joined {len(self.client.rooms)} rooms")

    async def _verify_credentials(self) -> None:
        """Verify the access token is valid before attempting sync."""
        logger.info(f"Verifying credentials for {self.config.user_id}...")

        try:
            response = await self.client.whoami()
        except Exception as e:
            raise MatrixAuthError(
                f"Failed to connect to homeserver: {e}\n"
                f"Check your homeserver URL: {self.config.homeserver}"
            ) from e

        if isinstance(response, WhoamiError):
            raise MatrixAuthError(
                f"Authentication failed: {response.message}\n"
                f"Your access_token is invalid or expired.\n"
                f"Generate a new token and update config.yaml."
            )

        if response.user_id != self.config.user_id:
            raise MatrixAuthError(
                f"User ID mismatch!\n"
                f"  Config says: {self.config.user_id}\n"
                f"  Token is for: {response.user_id}\n"
                f"Update user_id in config.yaml to match your token."
            )

        logger.info(f"Credentials verified for {response.user_id}")

    async def disconnect(self) -> None:
        self._running = False
        await self.client.close()
        logger.info("Disconnected from Matrix")

    async def _on_invite(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        if event.membership == "invite" and event.state_key == self.config.user_id:
            await self.client.join(room.room_id)
            logger.info(f"Joined room: {room.display_name} ({room.room_id})")

    async def _on_message(
        self,
        room: MatrixRoom,
        event: RoomMessageImage | RoomMessageVideo | RoomMessageAudio | RoomMessageFile,
    ) -> None:
        if event.sender == self.config.user_id:
            return

        content = event.source.get("content", {})
        url = content.get("url", "")

        if not url.startswith("mxc://"):
            return

        file_info = content.get("info", {})
        mimetype = file_info.get("mimetype", "application/octet-stream")
        size = file_info.get("size", 0)

        timestamp = datetime.fromtimestamp(event.server_timestamp / 1000, tz=timezone.utc)

        sender_name = room.user_name(event.sender) or event.sender

        file_message = FileMessage(
            platform=self.platform_name,
            room_id=room.room_id,
            room_name=room.display_name or room.room_id,
            sender_id=event.sender,
            sender_name=sender_name,
            filename=event.body,
            mimetype=mimetype,
            size=size,
            timestamp=timestamp,
            download_url=url,
            message_id=event.event_id,
        )

        await self._file_queue.put(file_message)
        logger.debug(f"Queued file: {event.body} from {sender_name} in {room.display_name}")

    async def listen(self) -> AsyncIterator[FileMessage]:
        self._running = True

        sync_task = asyncio.create_task(self._sync_forever())

        try:
            while self._running:
                try:
                    file_message = await asyncio.wait_for(
                        self._file_queue.get(),
                        timeout=1.0,
                    )
                    yield file_message
                except asyncio.TimeoutError:
                    continue
        finally:
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass

    async def _sync_forever(self) -> None:
        while self._running:
            try:
                await self.client.sync(timeout=30000)
            except Exception as e:
                logger.error(f"Sync error: {e}")
                await asyncio.sleep(5)

    async def download_file(self, file_message: FileMessage, destination: Path) -> Path:
        mxc_url = file_message.download_url

        parts = mxc_url[6:].split("/", 1)
        server_name = parts[0]
        media_id = parts[1]

        download_url = (
            f"{self.config.homeserver}/_matrix/media/r0/download/{server_name}/{media_id}"
        )

        destination.parent.mkdir(parents=True, exist_ok=True)

        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as response:
                response.raise_for_status()
                async with aiofiles.open(destination, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)

        logger.debug(f"Downloaded {file_message.filename} to {destination}")
        return destination
