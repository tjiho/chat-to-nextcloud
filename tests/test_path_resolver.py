from datetime import datetime, timezone

import pytest

from src.path_resolver import FileMetadata, resolve_path, sanitize_path_component


class TestSanitizePathComponent:
    def test_removes_invalid_characters(self) -> None:
        assert sanitize_path_component('file<>:"/\\|?*name') == "file_name"

    def test_strips_dots_and_spaces(self) -> None:
        assert sanitize_path_component("  ..name..  ") == "name"

    def test_collapses_multiple_underscores(self) -> None:
        assert sanitize_path_component("a:::b") == "a_b"

    def test_returns_unknown_for_empty(self) -> None:
        assert sanitize_path_component("") == "unknown"
        assert sanitize_path_component("...") == "unknown"
        assert sanitize_path_component("   ") == "unknown"

    def test_preserves_valid_characters(self) -> None:
        assert sanitize_path_component("valid-name_123") == "valid-name_123"


class TestResolvePath:
    def test_basic_template(self) -> None:
        metadata = FileMetadata(
            platform="matrix",
            room="General Chat",
            sender="alice",
            filename="photo.jpg",
        )

        result = resolve_path("{platform}/{room}/{filename}", metadata)
        assert result == "matrix/General Chat/photo.jpg"

    def test_date_variables(self) -> None:
        metadata = FileMetadata(
            platform="matrix",
            room="test",
            sender="bob",
            filename="file.txt",
            timestamp=datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc),
        )

        result = resolve_path("{year}/{month}/{day}/{filename}", metadata)
        assert result == "2024/03/15/file.txt"

    def test_date_combined(self) -> None:
        metadata = FileMetadata(
            platform="matrix",
            room="test",
            sender="bob",
            filename="file.txt",
            timestamp=datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc),
        )

        result = resolve_path("{date}/{filename}", metadata)
        assert result == "2024-03-15/file.txt"

    def test_sender_variable(self) -> None:
        metadata = FileMetadata(
            platform="telegram",
            room="group",
            sender="Charlie",
            filename="doc.pdf",
        )

        result = resolve_path("{platform}/{sender}/{filename}", metadata)
        assert result == "telegram/Charlie/doc.pdf"

    def test_filename_base_and_ext(self) -> None:
        metadata = FileMetadata(
            platform="matrix",
            room="test",
            sender="user",
            filename="document.backup.tar.gz",
        )

        result = resolve_path("{filename_base}.{ext}", metadata)
        assert result == "document.backup.tar.gz"

    def test_filename_without_extension(self) -> None:
        metadata = FileMetadata(
            platform="matrix",
            room="test",
            sender="user",
            filename="README",
        )

        result = resolve_path("{filename_base}.{ext}", metadata)
        assert result == "README."

    def test_sanitizes_room_name(self) -> None:
        metadata = FileMetadata(
            platform="matrix",
            room="Room: Test/Chat",
            sender="user",
            filename="file.txt",
        )

        result = resolve_path("{room}/{filename}", metadata)
        assert result == "Room_ Test_Chat/file.txt"

    def test_uses_current_time_if_no_timestamp(self) -> None:
        metadata = FileMetadata(
            platform="matrix",
            room="test",
            sender="user",
            filename="file.txt",
            timestamp=None,
        )

        result = resolve_path("{year}/{filename}", metadata)
        current_year = datetime.now().strftime("%Y")
        assert result == f"{current_year}/file.txt"

    def test_complex_template(self) -> None:
        metadata = FileMetadata(
            platform="matrix",
            room="Family Photos",
            sender="Mom",
            filename="vacation.jpg",
            timestamp=datetime(2024, 7, 4, 14, 30, 0, tzinfo=timezone.utc),
        )

        result = resolve_path(
            "{platform}/{room}/{year}/{month}/{sender}_{filename}",
            metadata,
        )
        assert result == "matrix/Family Photos/2024/07/Mom_vacation.jpg"
