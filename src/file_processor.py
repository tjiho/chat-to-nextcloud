import logging
import tempfile
from pathlib import Path

from .adapters.base import BaseAdapter, FileMessage
from .path_resolver import FileMetadata, resolve_path
from .uploader import NextcloudUploader

logger = logging.getLogger(__name__)


class FileProcessor:
    def __init__(
        self,
        uploader: NextcloudUploader,
        path_template: str,
    ):
        self.uploader = uploader
        self.path_template = path_template

    async def process_file(self, adapter: BaseAdapter, file_message: FileMessage) -> str | None:
        try:
            metadata = FileMetadata(
                platform=file_message.platform,
                room=file_message.room_name,
                sender=file_message.sender_name,
                filename=file_message.filename,
                timestamp=file_message.timestamp,
            )

            remote_path = resolve_path(self.path_template, metadata)

            with tempfile.TemporaryDirectory() as temp_dir:
                local_path = Path(temp_dir) / file_message.filename

                await adapter.download_file(file_message, local_path)

                uploaded_path = self.uploader.upload_file(local_path, remote_path)

            logger.info(
                f"Processed: {file_message.filename} "
                f"from {file_message.sender_name} "
                f"in {file_message.room_name} -> {uploaded_path}"
            )
            return uploaded_path

        except Exception as e:
            logger.error(
                f"Failed to process {file_message.filename} "
                f"from {file_message.room_name}: {e}"
            )
            return None
