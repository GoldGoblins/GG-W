"""One local reference policy for the runtime, editor and research adapters."""
from __future__ import annotations

import base64
from pathlib import Path
import stat
from urllib.parse import unquote, unquote_to_bytes, urlparse

from backend import game_workflow_common as common
from backend.platform_files import is_link


def reference(path: Path, uri: str, root: Path, limit: int) -> Path:
    if not isinstance(uri, str) or not uri or len(uri) > 4096:
        raise ValueError("LOCAL_RESOURCE_URI_REQUIRED")
    decoded = unquote(uri)
    parsed = urlparse(decoded)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in decoded or "\0" in decoded or Path(decoded).is_absolute():
        raise ValueError("LOCAL_RESOURCE_URI_REQUIRED")
    root = root.resolve()
    candidate = path.parent / decoded
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError("RESOURCE_OUTSIDE_SELECTED_ROOT")
    # Refuse symlink components, even when their current target is inside root.
    for part in (candidate, *candidate.parents):
        if is_link(part):
            raise ValueError("RESOURCE_SYMLINK_NOT_SUPPORTED")
        if part == root:
            break
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("RESOURCE_REGULAR_FILE_REQUIRED")
    if info.st_size > limit:
        raise ValueError("RESOURCE_BYTE_LIMIT")
    return resolved


def read_reference(path: Path, uri: str, root: Path, limit: int) -> tuple[Path, bytes]:
    candidate = reference(path, uri, root, limit)
    return common.read_file(candidate, limit, root=root)


def data_uri(uri: str, limit: int) -> bytes:
    if not uri.startswith("data:") or "," not in uri:
        raise ValueError("INVALID_DATA_URI")
    header, payload = uri.split(",", 1)
    if ";base64" in header.lower():
        if len(payload) > 4 * ((limit + 2) // 3):
            raise ValueError("DATA_URI_BYTE_LIMIT")
        data = base64.b64decode(payload, validate=True)
    else:
        if len(payload) > limit * 3:
            raise ValueError("DATA_URI_BYTE_LIMIT")
        data = unquote_to_bytes(payload)
    if len(data) > limit:
        raise ValueError("DATA_URI_BYTE_LIMIT")
    return data
