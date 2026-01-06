import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.telegram import TelegramAdapter
from src.config import TelegramConfig


@pytest.fixture
def telegram_config() -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        bot_token="123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
    )


class TestTelegramAdapter:
    def test_init(self, telegram_config: TelegramConfig) -> None:
        adapter = TelegramAdapter(telegram_config)

        assert adapter.platform_name == "telegram"
        assert adapter.config == telegram_config
        assert adapter.application is None

    async def test_connect_starts_polling(self, telegram_config: TelegramConfig) -> None:
        with patch("src.adapters.telegram.Application") as mock_app_class:
            mock_app = AsyncMock()
            mock_builder = MagicMock()
            mock_builder.token.return_value = mock_builder
            mock_builder.build.return_value = mock_app

            mock_app_class.builder.return_value = mock_builder

            mock_bot_info = MagicMock()
            mock_bot_info.username = "test_bot"
            mock_app.bot.get_me.return_value = mock_bot_info

            adapter = TelegramAdapter(telegram_config)
            await adapter.connect()

            mock_app.initialize.assert_called_once()
            mock_app.start.assert_called_once()
            mock_app.updater.start_polling.assert_called_once()

    async def test_disconnect_stops_application(self, telegram_config: TelegramConfig) -> None:
        with patch("src.adapters.telegram.Application"):
            adapter = TelegramAdapter(telegram_config)
            adapter.application = AsyncMock()

            await adapter.disconnect()

            adapter.application.updater.stop.assert_called_once()
            adapter.application.stop.assert_called_once()
            adapter.application.shutdown.assert_called_once()

    async def test_on_file_message_queues_document(self, telegram_config: TelegramConfig) -> None:
        adapter = TelegramAdapter(telegram_config)

        mock_update = MagicMock()
        mock_message = MagicMock()
        mock_update.message = mock_message

        mock_message.chat.id = 12345
        mock_message.chat.title = "Test Group"
        mock_message.chat.username = None

        mock_message.from_user.id = 67890
        mock_message.from_user.full_name = "John Doe"
        mock_message.from_user.username = "johndoe"

        mock_message.message_id = 100
        mock_message.date = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        mock_message.document = MagicMock()
        mock_message.document.file_id = "file_123"
        mock_message.document.file_name = "document.pdf"
        mock_message.document.mime_type = "application/pdf"
        mock_message.document.file_size = 12345

        mock_message.photo = None
        mock_message.video = None
        mock_message.audio = None
        mock_message.voice = None
        mock_message.video_note = None

        mock_context = MagicMock()

        await adapter._on_file_message(mock_update, mock_context)

        file_message = await asyncio.wait_for(
            adapter._file_queue.get(),
            timeout=1.0,
        )

        assert file_message.platform == "telegram"
        assert file_message.room_name == "Test Group"
        assert file_message.sender_name == "John Doe"
        assert file_message.filename == "document.pdf"
        assert file_message.mimetype == "application/pdf"
        assert file_message.download_url == "file_123"

    async def test_on_file_message_queues_photo(self, telegram_config: TelegramConfig) -> None:
        adapter = TelegramAdapter(telegram_config)

        mock_update = MagicMock()
        mock_message = MagicMock()
        mock_update.message = mock_message

        mock_message.chat.id = 12345
        mock_message.chat.title = "Photo Group"
        mock_message.chat.username = None

        mock_message.from_user.id = 67890
        mock_message.from_user.full_name = "Jane Doe"
        mock_message.from_user.username = None

        mock_message.message_id = 200
        mock_message.date = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        mock_message.document = None
        mock_message.video = None
        mock_message.audio = None
        mock_message.voice = None
        mock_message.video_note = None

        # Photos come as a list, largest last
        mock_photo = MagicMock()
        mock_photo.file_id = "photo_456"
        mock_photo.file_size = 54321
        mock_message.photo = [MagicMock(), mock_photo]

        mock_context = MagicMock()

        await adapter._on_file_message(mock_update, mock_context)

        file_message = await asyncio.wait_for(
            adapter._file_queue.get(),
            timeout=1.0,
        )

        assert file_message.platform == "telegram"
        assert file_message.filename == "photo_200.jpg"
        assert file_message.mimetype == "image/jpeg"
        assert file_message.download_url == "photo_456"

    async def test_on_file_message_ignores_empty_message(self, telegram_config: TelegramConfig) -> None:
        adapter = TelegramAdapter(telegram_config)

        mock_update = MagicMock()
        mock_update.message = None

        mock_context = MagicMock()

        await adapter._on_file_message(mock_update, mock_context)

        assert adapter._file_queue.empty()

    async def test_on_file_message_private_chat_name(self, telegram_config: TelegramConfig) -> None:
        adapter = TelegramAdapter(telegram_config)

        mock_update = MagicMock()
        mock_message = MagicMock()
        mock_update.message = mock_message

        # Private chat - no title
        mock_message.chat.id = 12345
        mock_message.chat.title = None
        mock_message.chat.username = "private_user"

        mock_message.from_user.id = 12345
        mock_message.from_user.full_name = "Private User"
        mock_message.from_user.username = "private_user"

        mock_message.message_id = 300
        mock_message.date = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        mock_message.document = MagicMock()
        mock_message.document.file_id = "file_789"
        mock_message.document.file_name = "file.txt"
        mock_message.document.mime_type = "text/plain"
        mock_message.document.file_size = 100

        mock_message.photo = None
        mock_message.video = None
        mock_message.audio = None
        mock_message.voice = None
        mock_message.video_note = None

        mock_context = MagicMock()

        await adapter._on_file_message(mock_update, mock_context)

        file_message = await asyncio.wait_for(
            adapter._file_queue.get(),
            timeout=1.0,
        )

        assert file_message.room_name == "@private_user"

    async def test_download_file(
        self, telegram_config: TelegramConfig, tmp_path: Path
    ) -> None:
        adapter = TelegramAdapter(telegram_config)
        adapter.application = MagicMock()

        mock_tg_file = AsyncMock()
        adapter.application.bot.get_file = AsyncMock(return_value=mock_tg_file)

        mock_file_message = MagicMock()
        mock_file_message.download_url = "file_123"
        mock_file_message.filename = "test.pdf"

        destination = tmp_path / "test.pdf"

        result = await adapter.download_file(mock_file_message, destination)

        assert result == destination
        adapter.application.bot.get_file.assert_called_once_with("file_123")
        mock_tg_file.download_to_drive.assert_called_once_with(destination)

    async def test_download_file_not_connected_raises_error(
        self, telegram_config: TelegramConfig, tmp_path: Path
    ) -> None:
        adapter = TelegramAdapter(telegram_config)
        adapter.application = None

        mock_file_message = MagicMock()
        mock_file_message.download_url = "file_123"
        mock_file_message.filename = "test.pdf"

        destination = tmp_path / "test.pdf"

        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.download_file(mock_file_message, destination)
