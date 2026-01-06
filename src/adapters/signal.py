import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from signalbot import Command, Context, SignalBot

from ..config import SignalConfig
from .base import BaseAdapter, FileMessage

logger = logging.getLogger(__name__)


class FileCollectorCommand(Command):
    """Command that collects all messages with attachments."""

    def __init__(self, file_queue: asyncio.Queue[FileMessage]) -> None:
        super().__init__()
        self._file_queue = file_queue

    async def handle(self, context: Context) -> None:
        message = context.message

        # Log all messages for debugging
        source = message.source or "unknown"
        group = message.group or "private"
        has_attachments = bool(message.base64_attachments)

        logger.debug(
            f"[Signal] Message from '{source}' in '{group}': "
            f"text={len(message.text or '')} chars, has_attachments={has_attachments}"
        )

        # Check if message has attachments
        if not message.base64_attachments:
            return

        # Get room info
        if message.group:
            room_id = message.group
            room_name = f"group_{message.group}"
        else:
            room_id = message.source or "unknown"
            room_name = message.source or "private"

        # Get sender info
        sender_id = message.source_uuid or message.source or "unknown"
        sender_name = message.source or "unknown"

        timestamp = datetime.fromtimestamp(
            message.timestamp / 1000, tz=timezone.utc
        ) if message.timestamp else datetime.now(timezone.utc)

        # Process each attachment
        filenames = message.attachments_local_filenames or []

        for i, b64_data in enumerate(message.base64_attachments):
            # Get filename if available
            if i < len(filenames):
                filename = filenames[i]
            else:
                filename = f"attachment_{message.timestamp}_{i}"

            # Try to determine mimetype from filename
            mimetype = "application/octet-stream"
            ext = Path(filename).suffix.lower()
            mime_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".mp4": "video/mp4",
                ".mov": "video/quicktime",
                ".mp3": "audio/mpeg",
                ".ogg": "audio/ogg",
                ".pdf": "application/pdf",
                ".doc": "application/msword",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
            if ext in mime_map:
                mimetype = mime_map[ext]

            # Calculate size from base64 data
            try:
                decoded = base64.b64decode(b64_data)
                size = len(decoded)
            except Exception:
                size = 0

            file_message = FileMessage(
                platform="signal",
                room_id=room_id,
                room_name=room_name,
                sender_id=sender_id,
                sender_name=sender_name,
                filename=filename,
                mimetype=mimetype,
                size=size,
                timestamp=timestamp,
                download_url=b64_data,  # Store base64 data as download_url
                message_id=str(message.timestamp),
            )

            await self._file_queue.put(file_message)
            logger.info(
                f"[Signal] File received: {filename} ({size} bytes) "
                f"from {sender_name} in {room_name}"
            )


class SignalAdapter(BaseAdapter):
    platform_name = "signal"

    def __init__(self, config: SignalConfig):
        self.config = config
        self.bot: SignalBot | None = None
        self._file_queue: asyncio.Queue[FileMessage] = asyncio.Queue()
        self._running = False
        self._bot_task: asyncio.Task | None = None

    async def connect(self) -> None:
        logger.info("Connecting to Signal...")

        self.bot = SignalBot({
            "signal_service": self.config.signal_service,
            "phone_number": self.config.phone_number,
        })

        # Register our file collector command
        file_collector = FileCollectorCommand(self._file_queue)
        self.bot.register(file_collector)

        # Start the bot in a background task
        self._bot_task = asyncio.create_task(self._run_bot())

        logger.info(f"Connected to Signal as {self.config.phone_number}")

    async def _run_bot(self) -> None:
        """Run the signalbot in a background task."""
        try:
            # signalbot.start() is blocking, run it in executor
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.bot.start)
        except Exception as e:
            logger.error(f"Signal bot error: {e}")

    async def disconnect(self) -> None:
        self._running = False
        if self._bot_task:
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass
        logger.info("Disconnected from Signal")

    async def listen(self) -> AsyncIterator[FileMessage]:
        self._running = True

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
            pass

    async def download_file(self, file_message: FileMessage, destination: Path) -> Path:
        # The base64 data is stored in download_url
        b64_data = file_message.download_url

        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            decoded = base64.b64decode(b64_data)
            destination.write_bytes(decoded)
        except Exception as e:
            raise RuntimeError(f"Failed to decode Signal attachment: {e}") from e

        logger.debug(f"Downloaded {file_message.filename} to {destination}")
        return destination
