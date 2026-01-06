from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class NextcloudConfig:
    url: str
    username: str
    password: str
    base_path: str = "/ChatUploads"


@dataclass
class MatrixConfig:
    enabled: bool
    homeserver: str
    user_id: str
    access_token: str
    encryption: bool = False


@dataclass
class TelegramConfig:
    enabled: bool
    bot_token: str


@dataclass
class AdaptersConfig:
    matrix: MatrixConfig | None = None
    telegram: TelegramConfig | None = None


@dataclass
class Config:
    nextcloud: NextcloudConfig
    path_template: str
    adapters: AdaptersConfig

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        nc_data = data.get("nextcloud", {})
        nextcloud = NextcloudConfig(
            url=nc_data["url"],
            username=nc_data["username"],
            password=nc_data["password"],
            base_path=nc_data.get("base_path", "/ChatUploads"),
        )

        adapters_data = data.get("adapters", {})
        matrix_data = adapters_data.get("matrix")
        matrix = None
        if matrix_data and matrix_data.get("enabled", False):
            matrix = MatrixConfig(
                enabled=True,
                homeserver=matrix_data["homeserver"],
                user_id=matrix_data["user_id"],
                access_token=matrix_data["access_token"],
                encryption=matrix_data.get("encryption", False),
            )

        telegram_data = adapters_data.get("telegram")
        telegram = None
        if telegram_data and telegram_data.get("enabled", False):
            telegram = TelegramConfig(
                enabled=True,
                bot_token=telegram_data["bot_token"],
            )

        adapters = AdaptersConfig(matrix=matrix, telegram=telegram)

        return cls(
            nextcloud=nextcloud,
            path_template=data.get("path_template", "{platform}/{room}/{filename}"),
            adapters=adapters,
        )

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)
