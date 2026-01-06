import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.signal import FileCollectorCommand, SignalAdapter
from src.config import SignalConfig


@pytest.fixture
def signal_config() -> SignalConfig:
    return SignalConfig(
        enabled=True,
        signal_service="127.0.0.1:8080",
        phone_number="+33612345678",
    )


class TestSignalAdapter:
    def test_init(self, signal_config: SignalConfig) -> None:
        adapter = SignalAdapter(signal_config)

        assert adapter.platform_name == "signal"
        assert adapter.config == signal_config
        assert adapter.bot is None

    async def test_connect_creates_bot(self, signal_config: SignalConfig) -> None:
        with patch("src.adapters.signal.SignalBot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.start = MagicMock()
            mock_bot_class.return_value = mock_bot

            adapter = SignalAdapter(signal_config)

            # Mock the _run_bot to not actually run
            with patch.object(adapter, "_run_bot", new_callable=AsyncMock):
                await adapter.connect()

            mock_bot_class.assert_called_once_with({
                "signal_service": "127.0.0.1:8080",
                "phone_number": "+33612345678",
            })
            mock_bot.register.assert_called_once()
            assert adapter.bot is not None

    async def test_disconnect_cancels_task(self, signal_config: SignalConfig) -> None:
        adapter = SignalAdapter(signal_config)

        # Create a real task that we can cancel
        async def dummy_task() -> None:
            await asyncio.sleep(10)

        adapter._bot_task = asyncio.create_task(dummy_task())

        await adapter.disconnect()

        assert adapter._bot_task.cancelled()


class TestFileCollectorCommand:
    async def test_handle_message_without_attachments(self) -> None:
        file_queue: asyncio.Queue = asyncio.Queue()
        command = FileCollectorCommand(file_queue)

        mock_context = MagicMock()
        mock_context.message.source = "+33611111111"
        mock_context.message.group = None
        mock_context.message.text = "Hello"
        mock_context.message.base64_attachments = []

        await command.handle(mock_context)

        assert file_queue.empty()

    async def test_handle_message_with_attachment(self) -> None:
        file_queue: asyncio.Queue = asyncio.Queue()
        command = FileCollectorCommand(file_queue)

        # Create test data
        test_content = b"test file content"
        b64_content = base64.b64encode(test_content).decode("utf-8")

        mock_context = MagicMock()
        mock_context.message.source = "+33611111111"
        mock_context.message.source_uuid = "uuid-123"
        mock_context.message.group = "group-456"
        mock_context.message.text = ""
        mock_context.message.timestamp = 1718457600000  # 2024-06-15 12:00:00 UTC
        mock_context.message.base64_attachments = [b64_content]
        mock_context.message.attachments_local_filenames = ["photo.jpg"]

        await command.handle(mock_context)

        file_message = await asyncio.wait_for(
            file_queue.get(),
            timeout=1.0,
        )

        assert file_message.platform == "signal"
        assert file_message.room_id == "group-456"
        assert file_message.room_name == "group_group-456"
        assert file_message.sender_id == "uuid-123"
        assert file_message.sender_name == "+33611111111"
        assert file_message.filename == "photo.jpg"
        assert file_message.mimetype == "image/jpeg"
        assert file_message.size == len(test_content)

    async def test_handle_private_message_with_attachment(self) -> None:
        file_queue: asyncio.Queue = asyncio.Queue()
        command = FileCollectorCommand(file_queue)

        test_content = b"private file"
        b64_content = base64.b64encode(test_content).decode("utf-8")

        mock_context = MagicMock()
        mock_context.message.source = "+33611111111"
        mock_context.message.source_uuid = "uuid-123"
        mock_context.message.group = None  # Private message
        mock_context.message.text = ""
        mock_context.message.timestamp = 1718457600000
        mock_context.message.base64_attachments = [b64_content]
        mock_context.message.attachments_local_filenames = ["document.pdf"]

        await command.handle(mock_context)

        file_message = await asyncio.wait_for(
            file_queue.get(),
            timeout=1.0,
        )

        assert file_message.platform == "signal"
        assert file_message.room_id == "+33611111111"
        assert file_message.room_name == "+33611111111"
        assert file_message.mimetype == "application/pdf"

    async def test_handle_multiple_attachments(self) -> None:
        file_queue: asyncio.Queue = asyncio.Queue()
        command = FileCollectorCommand(file_queue)

        content1 = b"file 1"
        content2 = b"file 2"

        mock_context = MagicMock()
        mock_context.message.source = "+33611111111"
        mock_context.message.source_uuid = "uuid-123"
        mock_context.message.group = "group-789"
        mock_context.message.text = ""
        mock_context.message.timestamp = 1718457600000
        mock_context.message.base64_attachments = [
            base64.b64encode(content1).decode("utf-8"),
            base64.b64encode(content2).decode("utf-8"),
        ]
        mock_context.message.attachments_local_filenames = ["file1.png", "file2.mp4"]

        await command.handle(mock_context)

        # Should have 2 file messages
        file1 = await asyncio.wait_for(file_queue.get(), timeout=1.0)
        file2 = await asyncio.wait_for(file_queue.get(), timeout=1.0)

        assert file1.filename == "file1.png"
        assert file1.mimetype == "image/png"
        assert file2.filename == "file2.mp4"
        assert file2.mimetype == "video/mp4"


class TestSignalAdapterDownload:
    async def test_download_file(
        self, signal_config: SignalConfig, tmp_path: Path
    ) -> None:
        adapter = SignalAdapter(signal_config)

        test_content = b"test file data for download"
        b64_content = base64.b64encode(test_content).decode("utf-8")

        mock_file_message = MagicMock()
        mock_file_message.download_url = b64_content
        mock_file_message.filename = "test.txt"

        destination = tmp_path / "test.txt"

        result = await adapter.download_file(mock_file_message, destination)

        assert result == destination
        assert destination.exists()
        assert destination.read_bytes() == test_content

    async def test_download_file_creates_parent_dirs(
        self, signal_config: SignalConfig, tmp_path: Path
    ) -> None:
        adapter = SignalAdapter(signal_config)

        test_content = b"nested file"
        b64_content = base64.b64encode(test_content).decode("utf-8")

        mock_file_message = MagicMock()
        mock_file_message.download_url = b64_content
        mock_file_message.filename = "nested.txt"

        destination = tmp_path / "a" / "b" / "c" / "nested.txt"

        result = await adapter.download_file(mock_file_message, destination)

        assert result == destination
        assert destination.exists()
        assert destination.read_bytes() == test_content

    async def test_download_file_invalid_base64_raises_error(
        self, signal_config: SignalConfig, tmp_path: Path
    ) -> None:
        adapter = SignalAdapter(signal_config)

        mock_file_message = MagicMock()
        mock_file_message.download_url = "not-valid-base64!!!"
        mock_file_message.filename = "bad.txt"

        destination = tmp_path / "bad.txt"

        with pytest.raises(RuntimeError, match="Failed to decode"):
            await adapter.download_file(mock_file_message, destination)
