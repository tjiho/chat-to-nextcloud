import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.matrix import MatrixAdapter, MatrixAuthError
from src.config import MatrixConfig


@pytest.fixture
def matrix_config() -> MatrixConfig:
    return MatrixConfig(
        enabled=True,
        homeserver="https://matrix.example.com",
        user_id="@bot:example.com",
        access_token="test_access_token",
    )


class TestMatrixAdapter:
    def test_init(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            adapter = MatrixAdapter(matrix_config)

            mock_client_class.assert_called_once_with(
                "https://matrix.example.com",
                "@bot:example.com",
            )
            assert adapter.platform_name == "matrix"

    async def test_connect_registers_callbacks(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Mock whoami response
            mock_whoami = MagicMock()
            mock_whoami.user_id = "@bot:example.com"
            mock_client.whoami.return_value = mock_whoami

            # Mock sync response
            mock_sync = MagicMock()
            mock_client.sync.return_value = mock_sync
            mock_client.rooms = {}

            adapter = MatrixAdapter(matrix_config)
            await adapter.connect()

            assert mock_client.add_event_callback.call_count == 5
            mock_client.whoami.assert_called_once()
            assert mock_client.sync.call_count == 1

    async def test_disconnect_closes_client(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            adapter = MatrixAdapter(matrix_config)
            await adapter.disconnect()

            mock_client.close.assert_called_once()

    async def test_on_invite_joins_room(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            adapter = MatrixAdapter(matrix_config)

            mock_room = MagicMock()
            mock_room.room_id = "!test:example.com"
            mock_room.display_name = "Test Room"

            mock_event = MagicMock()
            mock_event.membership = "invite"
            mock_event.state_key = "@bot:example.com"

            await adapter._on_invite(mock_room, mock_event)

            mock_client.join.assert_called_once_with("!test:example.com")

    async def test_on_invite_ignores_other_users(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            adapter = MatrixAdapter(matrix_config)

            mock_room = MagicMock()
            mock_event = MagicMock()
            mock_event.membership = "invite"
            mock_event.state_key = "@other:example.com"

            await adapter._on_invite(mock_room, mock_event)

            mock_client.join.assert_not_called()

    async def test_on_message_queues_file(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            adapter = MatrixAdapter(matrix_config)

            mock_room = MagicMock()
            mock_room.room_id = "!test:example.com"
            mock_room.display_name = "Test Room"
            mock_room.user_name.return_value = "Alice"

            mock_event = MagicMock()
            mock_event.sender = "@alice:example.com"
            mock_event.body = "photo.jpg"
            mock_event.event_id = "$event123"
            mock_event.server_timestamp = 1718452800000
            mock_event.source = {
                "content": {
                    "url": "mxc://example.com/abc123",
                    "info": {
                        "mimetype": "image/jpeg",
                        "size": 12345,
                    },
                }
            }

            await adapter._on_message(mock_room, mock_event)

            file_message = await asyncio.wait_for(
                adapter._file_queue.get(),
                timeout=1.0,
            )

            assert file_message.platform == "matrix"
            assert file_message.room_name == "Test Room"
            assert file_message.sender_name == "Alice"
            assert file_message.filename == "photo.jpg"
            assert file_message.download_url == "mxc://example.com/abc123"

    async def test_on_message_ignores_own_messages(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            adapter = MatrixAdapter(matrix_config)

            mock_room = MagicMock()
            mock_event = MagicMock()
            mock_event.sender = "@bot:example.com"

            await adapter._on_message(mock_room, mock_event)

            assert adapter._file_queue.empty()

    async def test_on_message_ignores_non_mxc_urls(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            adapter = MatrixAdapter(matrix_config)

            mock_room = MagicMock()
            mock_event = MagicMock()
            mock_event.sender = "@alice:example.com"
            mock_event.source = {
                "content": {
                    "url": "https://example.com/file.jpg",
                }
            }

            await adapter._on_message(mock_room, mock_event)

            assert adapter._file_queue.empty()

    async def test_download_file(
        self, matrix_config: MatrixConfig, tmp_path: Path
    ) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            adapter = MatrixAdapter(matrix_config)

            mock_file_message = MagicMock()
            mock_file_message.download_url = "mxc://example.com/abc123"
            mock_file_message.filename = "test.jpg"

            destination = tmp_path / "test.jpg"

            with patch("src.adapters.matrix.aiohttp.ClientSession") as mock_session_class:
                async def mock_iter_chunked(size: int):
                    yield b"fake image data"

                mock_response = MagicMock()
                mock_response.raise_for_status = MagicMock()
                mock_response.content.iter_chunked = mock_iter_chunked

                mock_get_cm = AsyncMock()
                mock_get_cm.__aenter__.return_value = mock_response

                mock_session = MagicMock()
                mock_session.get.return_value = mock_get_cm

                mock_session_cm = AsyncMock()
                mock_session_cm.__aenter__.return_value = mock_session
                mock_session_class.return_value = mock_session_cm

                result = await adapter.download_file(mock_file_message, destination)

                assert result == destination
                assert destination.exists()
                assert destination.read_bytes() == b"fake image data"

                mock_session.get.assert_called_once_with(
                    "https://matrix.example.com/_matrix/media/r0/download/example.com/abc123"
                )

    async def test_connect_fails_on_invalid_token(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Mock WhoamiError response
            from nio import WhoamiError

            mock_whoami = WhoamiError(message="Invalid token")
            mock_client.whoami.return_value = mock_whoami

            adapter = MatrixAdapter(matrix_config)

            with pytest.raises(MatrixAuthError) as exc_info:
                await adapter.connect()

            assert "invalid or expired" in str(exc_info.value).lower()

    async def test_connect_fails_on_user_id_mismatch(self, matrix_config: MatrixConfig) -> None:
        with patch("src.adapters.matrix.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Mock whoami response with different user
            mock_whoami = MagicMock()
            mock_whoami.user_id = "@different:example.com"
            mock_client.whoami.return_value = mock_whoami

            adapter = MatrixAdapter(matrix_config)

            with pytest.raises(MatrixAuthError) as exc_info:
                await adapter.connect()

            assert "mismatch" in str(exc_info.value).lower()
            assert "@bot:example.com" in str(exc_info.value)
            assert "@different:example.com" in str(exc_info.value)

    def test_encryption_disabled_by_default(self, matrix_config: MatrixConfig) -> None:
        assert matrix_config.encryption is False

    def test_encryption_enabled_without_dependencies_raises_error(self) -> None:
        config = MatrixConfig(
            enabled=True,
            homeserver="https://matrix.example.com",
            user_id="@bot:example.com",
            access_token="test_token",
            encryption=True,
        )

        with patch("src.adapters.matrix._check_encryption_dependencies", return_value=False):
            with pytest.raises(MatrixAuthError) as exc_info:
                MatrixAdapter(config)

            assert "encryption" in str(exc_info.value).lower()
            assert "uv sync --extra encryption" in str(exc_info.value)
