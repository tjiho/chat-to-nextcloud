import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from telegram import Bot, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from ..config import TelegramConfig
from .base import BaseAdapter, FileMessage

logger = logging.getLogger(__name__)


class TelegramAdapter(BaseAdapter):
    platform_name = "telegram"

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.application: Application | None = None
        self._file_queue: asyncio.Queue[FileMessage] = asyncio.Queue()
        self._running = False

    async def connect(self) -> None:
        logger.info("Connecting to Telegram...")

        self.application = (
            Application.builder()
            .token(self.config.bot_token)
            .build()
        )

        # Log all messages for debugging (lower priority)
        self.application.add_handler(
            MessageHandler(filters.ALL, self._on_any_message),
            group=1,
        )

        # Handle all file types (higher priority)
        file_filter = (
            filters.Document.ALL
            | filters.PHOTO
            | filters.VIDEO
            | filters.AUDIO
            | filters.VOICE
            | filters.VIDEO_NOTE
        )
        self.application.add_handler(
            MessageHandler(file_filter, self._on_file_message),
            group=0,
        )

        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

        bot_info = await self.application.bot.get_me()
        logger.info(f"Connected to Telegram as @{bot_info.username}")

    async def disconnect(self) -> None:
        self._running = False
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
        logger.info("Disconnected from Telegram")

    async def _on_any_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Log all messages for debugging."""
        if not update.message:
            logger.debug(f"Received update without message: {update}")
            return

        message = update.message
        chat = message.chat
        sender = message.from_user

        # Determine chat name
        chat_name = chat.title or (f"@{chat.username}" if chat.username else f"chat_{chat.id}")
        sender_name = sender.full_name if sender else "unknown"

        # Determine message type
        msg_types = []
        if message.text:
            msg_types.append(f"text({len(message.text)} chars)")
        if message.document:
            msg_types.append(f"document({message.document.file_name})")
        if message.photo:
            msg_types.append(f"photo({len(message.photo)} sizes)")
        if message.video:
            msg_types.append("video")
        if message.audio:
            msg_types.append("audio")
        if message.voice:
            msg_types.append("voice")
        if message.video_note:
            msg_types.append("video_note")
        if message.sticker:
            msg_types.append("sticker")
        if message.animation:
            msg_types.append("animation")
        if message.contact:
            msg_types.append("contact")
        if message.location:
            msg_types.append("location")

        msg_type_str = ", ".join(msg_types) if msg_types else "empty/unknown"
        has_file = any([
            message.document, message.photo, message.video,
            message.audio, message.voice, message.video_note
        ])

        logger.debug(
            f"[TG] Message from '{sender_name}' in '{chat_name}': "
            f"type=[{msg_type_str}] has_file={has_file}"
        )

    async def _on_file_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not update.message:
            return

        message = update.message
        chat = message.chat

        # Determine file info based on message type
        file_id: str | None = None
        filename: str = "file"
        mimetype: str = "application/octet-stream"
        size: int = 0

        if message.document:
            file_id = message.document.file_id
            filename = message.document.file_name or "document"
            mimetype = message.document.mime_type or mimetype
            size = message.document.file_size or 0
        elif message.photo:
            # Get largest photo
            photo = message.photo[-1]
            file_id = photo.file_id
            filename = f"photo_{message.message_id}.jpg"
            mimetype = "image/jpeg"
            size = photo.file_size or 0
        elif message.video:
            file_id = message.video.file_id
            filename = message.video.file_name or f"video_{message.message_id}.mp4"
            mimetype = message.video.mime_type or "video/mp4"
            size = message.video.file_size or 0
        elif message.audio:
            file_id = message.audio.file_id
            filename = message.audio.file_name or f"audio_{message.message_id}.mp3"
            mimetype = message.audio.mime_type or "audio/mpeg"
            size = message.audio.file_size or 0
        elif message.voice:
            file_id = message.voice.file_id
            filename = f"voice_{message.message_id}.ogg"
            mimetype = message.voice.mime_type or "audio/ogg"
            size = message.voice.file_size or 0
        elif message.video_note:
            file_id = message.video_note.file_id
            filename = f"video_note_{message.message_id}.mp4"
            mimetype = "video/mp4"
            size = message.video_note.file_size or 0

        if not file_id:
            return

        # Get chat name
        if chat.title:
            room_name = chat.title
        elif chat.username:
            room_name = f"@{chat.username}"
        else:
            room_name = f"chat_{chat.id}"

        # Get sender name
        sender = message.from_user
        if sender:
            sender_name = sender.full_name or sender.username or str(sender.id)
            sender_id = str(sender.id)
        else:
            sender_name = "unknown"
            sender_id = "unknown"

        timestamp = message.date.replace(tzinfo=timezone.utc) if message.date else datetime.now(timezone.utc)

        file_message = FileMessage(
            platform=self.platform_name,
            room_id=str(chat.id),
            room_name=room_name,
            sender_id=sender_id,
            sender_name=sender_name,
            filename=filename,
            mimetype=mimetype,
            size=size,
            timestamp=timestamp,
            download_url=file_id,  # Store file_id as download_url
            message_id=str(message.message_id),
        )

        await self._file_queue.put(file_message)
        logger.info(f"[TG] File received: {filename} ({size} bytes) from {sender_name} in {room_name}")

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
        if not self.application:
            raise RuntimeError("Not connected to Telegram")

        file_id = file_message.download_url  # We stored file_id here

        destination.parent.mkdir(parents=True, exist_ok=True)

        tg_file = await self.application.bot.get_file(file_id)
        await tg_file.download_to_drive(destination)

        logger.debug(f"Downloaded {file_message.filename} to {destination}")
        return destination
