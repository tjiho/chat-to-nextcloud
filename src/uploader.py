import logging
from pathlib import Path, PurePosixPath

from webdav3.client import Client
from webdav3.exceptions import WebDavException

from .config import NextcloudConfig

logger = logging.getLogger(__name__)


class NextcloudUploader:
    def __init__(self, config: NextcloudConfig):
        self.config = config
        self.base_path = PurePosixPath(config.base_path)

        webdav_url = config.url.rstrip("/") + "/remote.php/dav/files/" + config.username

        options = {
            "webdav_hostname": webdav_url,
            "webdav_login": config.username,
            "webdav_password": config.password,
        }
        self.client = Client(options)

    def _full_path(self, relative_path: str) -> str:
        return str(self.base_path / relative_path)

    def ensure_directory(self, remote_path: str) -> None:
        full_path = PurePosixPath(self._full_path(remote_path))

        parts_to_create = []
        current = full_path
        while current != PurePosixPath("/"):
            if not self.client.check(str(current)):
                parts_to_create.append(current)
            else:
                break
            current = current.parent

        for path in reversed(parts_to_create):
            try:
                self.client.mkdir(str(path))
                logger.debug(f"Created directory: {path}")
            except WebDavException as e:
                if "already exists" not in str(e).lower():
                    raise

    def upload_file(self, local_path: Path, remote_path: str) -> str:
        full_remote_path = self._full_path(remote_path)

        parent_dir = str(PurePosixPath(remote_path).parent)
        if parent_dir != ".":
            self.ensure_directory(parent_dir)

        self.client.upload_sync(
            remote_path=full_remote_path,
            local_path=str(local_path),
        )

        logger.info(f"Uploaded {local_path.name} to {full_remote_path}")
        return full_remote_path

    def check_connection(self) -> bool:
        try:
            self.client.check(str(self.base_path))
            return True
        except WebDavException:
            return False


class DryRunUploader:
    """Uploader that logs operations without actually uploading."""

    def __init__(self, config: NextcloudConfig):
        self.config = config
        self.base_path = PurePosixPath(config.base_path)

    def _full_path(self, relative_path: str) -> str:
        return str(self.base_path / relative_path)

    def upload_file(self, local_path: Path, remote_path: str) -> str:
        full_remote_path = self._full_path(remote_path)
        file_size = local_path.stat().st_size if local_path.exists() else 0
        logger.info(
            f"[DRY-RUN] Would upload {local_path.name} ({file_size} bytes) "
            f"to {full_remote_path}"
        )
        return full_remote_path

    def check_connection(self) -> bool:
        logger.info(f"[DRY-RUN] Would connect to {self.config.url}")
        return True
