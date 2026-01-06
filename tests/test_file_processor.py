from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.base import FileMessage
from src.file_processor import FileProcessor


@pytest.fixture
def file_message() -> FileMessage:
    return FileMessage(
        platform="matrix",
        room_id="!abc123:example.com",
        room_name="Test Room",
        sender_id="@alice:example.com",
        sender_name="Alice",
        filename="photo.jpg",
        mimetype="image/jpeg",
        size=12345,
        timestamp=datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        download_url="mxc://example.com/abc123",
        message_id="$event123",
    )


@pytest.fixture
def mock_uploader() -> MagicMock:
    uploader = MagicMock()
    uploader.upload_file.return_value = "/TestUploads/matrix/Test Room/2024-06-15/photo.jpg"
    return uploader


@pytest.fixture
def mock_adapter() -> AsyncMock:
    adapter = AsyncMock()
    adapter.platform_name = "matrix"

    async def mock_download(file_message: FileMessage, destination: Path) -> Path:
        destination.write_bytes(b"fake image data")
        return destination

    adapter.download_file.side_effect = mock_download
    return adapter


class TestFileProcessor:
    async def test_process_file_success(
        self,
        mock_uploader: MagicMock,
        mock_adapter: AsyncMock,
        file_message: FileMessage,
    ) -> None:
        processor = FileProcessor(
            uploader=mock_uploader,
            path_template="{platform}/{room}/{date}/{filename}",
        )

        result = await processor.process_file(mock_adapter, file_message)

        assert result == "/TestUploads/matrix/Test Room/2024-06-15/photo.jpg"
        mock_adapter.download_file.assert_called_once()
        mock_uploader.upload_file.assert_called_once()

        call_args = mock_uploader.upload_file.call_args
        assert call_args[0][1] == "matrix/Test Room/2024-06-15/photo.jpg"

    async def test_process_file_uses_correct_path_template(
        self,
        mock_uploader: MagicMock,
        mock_adapter: AsyncMock,
        file_message: FileMessage,
    ) -> None:
        processor = FileProcessor(
            uploader=mock_uploader,
            path_template="{platform}/{sender}/{filename}",
        )

        await processor.process_file(mock_adapter, file_message)

        call_args = mock_uploader.upload_file.call_args
        assert call_args[0][1] == "matrix/Alice/photo.jpg"

    async def test_process_file_download_error(
        self,
        mock_uploader: MagicMock,
        mock_adapter: AsyncMock,
        file_message: FileMessage,
    ) -> None:
        mock_adapter.download_file.side_effect = Exception("Download failed")

        processor = FileProcessor(
            uploader=mock_uploader,
            path_template="{platform}/{room}/{filename}",
        )

        result = await processor.process_file(mock_adapter, file_message)

        assert result is None
        mock_uploader.upload_file.assert_not_called()

    async def test_process_file_upload_error(
        self,
        mock_uploader: MagicMock,
        mock_adapter: AsyncMock,
        file_message: FileMessage,
    ) -> None:
        mock_uploader.upload_file.side_effect = Exception("Upload failed")

        processor = FileProcessor(
            uploader=mock_uploader,
            path_template="{platform}/{room}/{filename}",
        )

        result = await processor.process_file(mock_adapter, file_message)

        assert result is None

    async def test_process_file_cleans_up_temp_file(
        self,
        mock_uploader: MagicMock,
        mock_adapter: AsyncMock,
        file_message: FileMessage,
    ) -> None:
        temp_files_created: list[Path] = []

        async def track_download(fm: FileMessage, dest: Path) -> Path:
            temp_files_created.append(dest)
            dest.write_bytes(b"data")
            return dest

        mock_adapter.download_file.side_effect = track_download

        processor = FileProcessor(
            uploader=mock_uploader,
            path_template="{platform}/{filename}",
        )

        await processor.process_file(mock_adapter, file_message)

        assert len(temp_files_created) == 1
        assert not temp_files_created[0].exists()
