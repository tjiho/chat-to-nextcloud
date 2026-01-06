from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class FileMessage:
    platform: str
    room_id: str
    room_name: str
    sender_id: str
    sender_name: str
    filename: str
    mimetype: str
    size: int
    timestamp: datetime
    download_url: str
    message_id: str


class BaseAdapter(ABC):
    platform_name: str = "unknown"

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def listen(self) -> AsyncIterator[FileMessage]:
        yield  # type: ignore

    @abstractmethod
    async def download_file(self, file_message: FileMessage, destination: Path) -> Path:
        pass
