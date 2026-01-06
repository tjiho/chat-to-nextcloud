import tempfile
from pathlib import Path

import pytest
import yaml

from src.config import Config, MatrixConfig, NextcloudConfig


class TestConfig:
    def test_load_valid_config(self, tmp_path: Path) -> None:
        config_data = {
            "nextcloud": {
                "url": "https://nextcloud.example.com",
                "username": "testuser",
                "password": "testpass",
                "base_path": "/TestUploads",
            },
            "path_template": "{platform}/{room}/{filename}",
            "adapters": {
                "matrix": {
                    "enabled": True,
                    "homeserver": "https://matrix.example.com",
                    "user_id": "@bot:example.com",
                    "access_token": "test_token",
                }
            },
        }

        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = Config.load(config_file)

        assert config.nextcloud.url == "https://nextcloud.example.com"
        assert config.nextcloud.username == "testuser"
        assert config.nextcloud.password == "testpass"
        assert config.nextcloud.base_path == "/TestUploads"
        assert config.path_template == "{platform}/{room}/{filename}"
        assert config.adapters.matrix is not None
        assert config.adapters.matrix.homeserver == "https://matrix.example.com"
        assert config.adapters.matrix.user_id == "@bot:example.com"
        assert config.adapters.matrix.access_token == "test_token"

    def test_load_config_with_defaults(self, tmp_path: Path) -> None:
        config_data = {
            "nextcloud": {
                "url": "https://nextcloud.example.com",
                "username": "testuser",
                "password": "testpass",
            },
            "adapters": {
                "matrix": {
                    "enabled": True,
                    "homeserver": "https://matrix.example.com",
                    "user_id": "@bot:example.com",
                    "access_token": "test_token",
                }
            },
        }

        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = Config.load(config_file)

        assert config.nextcloud.base_path == "/ChatUploads"
        assert config.path_template == "{platform}/{room}/{filename}"

    def test_load_config_matrix_disabled(self, tmp_path: Path) -> None:
        config_data = {
            "nextcloud": {
                "url": "https://nextcloud.example.com",
                "username": "testuser",
                "password": "testpass",
            },
            "adapters": {
                "matrix": {
                    "enabled": False,
                    "homeserver": "https://matrix.example.com",
                    "user_id": "@bot:example.com",
                    "access_token": "test_token",
                }
            },
        }

        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = Config.load(config_file)

        assert config.adapters.matrix is None

    def test_load_config_no_adapters(self, tmp_path: Path) -> None:
        config_data = {
            "nextcloud": {
                "url": "https://nextcloud.example.com",
                "username": "testuser",
                "password": "testpass",
            },
        }

        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = Config.load(config_file)

        assert config.adapters.matrix is None

    def test_load_config_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            Config.load("/nonexistent/config.yaml")

    def test_load_config_missing_required_field(self, tmp_path: Path) -> None:
        config_data = {
            "nextcloud": {
                "url": "https://nextcloud.example.com",
                # missing username and password
            },
        }

        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        with pytest.raises(KeyError):
            Config.load(config_file)
