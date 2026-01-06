from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from webdav3.exceptions import WebDavException

from src.config import NextcloudConfig
from src.uploader import DryRunUploader, NextcloudUploader


@pytest.fixture
def nextcloud_config() -> NextcloudConfig:
    return NextcloudConfig(
        url="https://nextcloud.example.com",
        username="testuser",
        password="testpass",
        base_path="/TestUploads",
    )


class TestNextcloudUploader:
    def test_init_creates_client(self, nextcloud_config: NextcloudConfig) -> None:
        with patch("src.uploader.Client") as mock_client_class:
            uploader = NextcloudUploader(nextcloud_config)

            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args[0][0]
            assert "testuser" in call_args["webdav_hostname"]
            assert call_args["webdav_login"] == "testuser"
            assert call_args["webdav_password"] == "testpass"

    def test_full_path(self, nextcloud_config: NextcloudConfig) -> None:
        with patch("src.uploader.Client"):
            uploader = NextcloudUploader(nextcloud_config)

            result = uploader._full_path("matrix/room/file.jpg")
            assert result == "/TestUploads/matrix/room/file.jpg"

    def test_ensure_directory_creates_missing_dirs(
        self, nextcloud_config: NextcloudConfig
    ) -> None:
        with patch("src.uploader.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_client.check.side_effect = [False, False, True]

            uploader = NextcloudUploader(nextcloud_config)
            uploader.ensure_directory("a/b/c")

            assert mock_client.mkdir.call_count == 2

    def test_ensure_directory_skips_existing(
        self, nextcloud_config: NextcloudConfig
    ) -> None:
        with patch("src.uploader.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_client.check.return_value = True

            uploader = NextcloudUploader(nextcloud_config)
            uploader.ensure_directory("existing/path")

            mock_client.mkdir.assert_not_called()

    def test_upload_file(
        self, nextcloud_config: NextcloudConfig, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        with patch("src.uploader.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.check.return_value = True

            uploader = NextcloudUploader(nextcloud_config)
            result = uploader.upload_file(test_file, "matrix/room/test.txt")

            assert result == "/TestUploads/matrix/room/test.txt"
            mock_client.upload_sync.assert_called_once_with(
                remote_path="/TestUploads/matrix/room/test.txt",
                local_path=str(test_file),
            )

    def test_upload_file_creates_parent_directory(
        self, nextcloud_config: NextcloudConfig, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        with patch("src.uploader.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.check.side_effect = [False, False, True]

            uploader = NextcloudUploader(nextcloud_config)
            uploader.upload_file(test_file, "new/path/test.txt")

            assert mock_client.mkdir.call_count >= 1

    def test_check_connection_success(self, nextcloud_config: NextcloudConfig) -> None:
        with patch("src.uploader.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.check.return_value = True

            uploader = NextcloudUploader(nextcloud_config)
            assert uploader.check_connection() is True

    def test_check_connection_failure(self, nextcloud_config: NextcloudConfig) -> None:
        with patch("src.uploader.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.check.side_effect = WebDavException("Connection failed")

            uploader = NextcloudUploader(nextcloud_config)
            assert uploader.check_connection() is False


class TestDryRunUploader:
    def test_upload_file_logs_without_uploading(
        self, nextcloud_config: NextcloudConfig, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        uploader = DryRunUploader(nextcloud_config)
        result = uploader.upload_file(test_file, "matrix/room/test.txt")

        assert result == "/TestUploads/matrix/room/test.txt"

    def test_check_connection_always_returns_true(
        self, nextcloud_config: NextcloudConfig
    ) -> None:
        uploader = DryRunUploader(nextcloud_config)
        assert uploader.check_connection() is True

    def test_full_path(self, nextcloud_config: NextcloudConfig) -> None:
        uploader = DryRunUploader(nextcloud_config)
        result = uploader._full_path("matrix/room/file.jpg")
        assert result == "/TestUploads/matrix/room/file.jpg"
