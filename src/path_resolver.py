import re
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileMetadata:
    platform: str
    room: str
    sender: str
    filename: str
    timestamp: datetime | None = None


def sanitize_path_component(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    sanitized = sanitized.strip(". ")
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized or "unknown"


def resolve_path(template: str, metadata: FileMetadata) -> str:
    ts = metadata.timestamp or datetime.now()

    filename = metadata.filename
    ext = ""
    if "." in filename:
        parts = filename.rsplit(".", 1)
        filename_base = parts[0]
        ext = parts[1]
    else:
        filename_base = filename

    variables = {
        "platform": sanitize_path_component(metadata.platform),
        "room": sanitize_path_component(metadata.room),
        "sender": sanitize_path_component(metadata.sender),
        "filename": sanitize_path_component(metadata.filename),
        "filename_base": sanitize_path_component(filename_base),
        "ext": ext,
        "date": ts.strftime("%Y-%m-%d"),
        "year": ts.strftime("%Y"),
        "month": ts.strftime("%m"),
        "day": ts.strftime("%d"),
        "hour": ts.strftime("%H"),
        "minute": ts.strftime("%M"),
    }

    result = template
    for key, value in variables.items():
        result = result.replace("{" + key + "}", value)

    return result
