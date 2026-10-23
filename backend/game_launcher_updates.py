"""Verified updater for versioned Linux game packages on GitHub Releases."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import threading
import tempfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any


OWNER = "GoldGoblins"
REPOSITORY = "GG"
ASSET_NAME = "gg-game-linux-x86_64.tar.gz"
API_URL = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/latest"
MAX_RELEASE_JSON_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 1536 * 1024 * 1024
MAX_EXPANDED_BYTES = 3 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 25000
CHUNK_BYTES = 1024 * 1024


class GameUpdateError(RuntimeError):
    """Raised when a game release fails its download or package contract."""


def _request(url: str, *, accept: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "Gold-Goblins-Game-Launcher",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _release_json(cancel: threading.Event | None = None) -> dict[str, Any]:
    if cancel is not None and cancel.is_set():
        raise GameUpdateError("UPDATE_CANCELLED")
    request = _request(API_URL, accept="application/vnd.github+json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read(MAX_RELEASE_JSON_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise GameUpdateError("NO_STABLE_RELEASE") from exc
        raise GameUpdateError("UPDATE_CHECK_FAILED") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise GameUpdateError("UPDATE_CHECK_NETWORK_ERROR") from exc
    if len(raw) > MAX_RELEASE_JSON_BYTES:
        raise GameUpdateError("UPDATE_METADATA_TOO_LARGE")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GameUpdateError("UPDATE_METADATA_INVALID") from exc
    if not isinstance(value, dict):
        raise GameUpdateError("UPDATE_METADATA_INVALID")
    if cancel is not None and cancel.is_set():
        raise GameUpdateError("UPDATE_CANCELLED")
    return value


def _safe_version(value: object) -> str:
    version = str(value or "").strip()
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version)
        or ".." in version
    ):
        raise GameUpdateError("GAME_RELEASE_VERSION_INVALID")
    return version


def _current_install(home: Path) -> tuple[str, Path] | None:
    pointer = home / "current.json"
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
        version = _safe_version(data.get("version"))
    except (OSError, json.JSONDecodeError, AttributeError, GameUpdateError):
        return None
    root = home / "versions" / version
    if not _is_game_package(root, version):
        return None
    return version, root


def installed_game_directory(game_home: Path) -> Path | None:
    current = _current_install(Path(game_home).expanduser())
    return current[1] if current is not None else None


def is_game_package(root: Path) -> bool:
    return _is_game_package(Path(root).expanduser())


def _is_game_package(root: Path, version: str | None = None) -> bool:
    try:
        if root.is_symlink():
            return False
    except OSError:
        return False
    try:
        data = json.loads((root / "version.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(data, dict)
        and data.get("schema") == "gg.game-client.release.v1"
        and data.get("platform") == "linux-x86_64"
        and (version is None or data.get("version") == version)
        and (root / "game_client_main.py").is_file()
        and (root / "backend" / "game_client_host.py").is_file()
        and (root / "qml" / "components" / "GameEngineSurface.qml").is_file()
    )


def _download_asset(
    url: str,
    expected_size: int,
    expected_digest: str,
    target: Path,
    cancel: threading.Event | None = None,
) -> None:
    if not url.startswith(
        f"https://github.com/{OWNER}/{REPOSITORY}/releases/download/"
    ):
        raise GameUpdateError("GAME_RELEASE_DOWNLOAD_URL_INVALID")
    if expected_size < 1 or expected_size > MAX_ARCHIVE_BYTES:
        raise GameUpdateError("GAME_RELEASE_SIZE_INVALID")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_digest):
        raise GameUpdateError("GAME_RELEASE_DIGEST_MISSING")

    request = _request(url, accept="application/octet-stream")
    digest = hashlib.sha256()
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=5) as response, target.open("wb") as output:
            while True:
                if cancel is not None and cancel.is_set():
                    raise GameUpdateError("UPDATE_CANCELLED")
                block = response.read(CHUNK_BYTES)
                if not block:
                    break
                received += len(block)
                if received > expected_size or received > MAX_ARCHIVE_BYTES:
                    raise GameUpdateError("GAME_RELEASE_SIZE_MISMATCH")
                digest.update(block)
                output.write(block)
            if cancel is not None and cancel.is_set():
                raise GameUpdateError("UPDATE_CANCELLED")
            output.flush()
            os.fsync(output.fileno())
    except GameUpdateError:
        target.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError) as exc:
        target.unlink(missing_ok=True)
        raise GameUpdateError("GAME_RELEASE_DOWNLOAD_FAILED") from exc
    if received != expected_size:
        target.unlink(missing_ok=True)
        raise GameUpdateError("GAME_RELEASE_SIZE_MISMATCH")
    if digest.hexdigest().casefold() != expected_digest.casefold():
        target.unlink(missing_ok=True)
        raise GameUpdateError("GAME_RELEASE_DIGEST_MISMATCH")


def _extract_validated(
    archive_path: Path,
    stage: Path,
    version: str,
    cancel: threading.Event | None = None,
) -> Path:
    expected_root = f"gg-game-linux-x86_64-{version}"
    total_size = 0
    names: set[str] = set()
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise GameUpdateError("GAME_RELEASE_ARCHIVE_INVALID") from exc
    with archive:
        members = archive.getmembers()
        if not members or len(members) > MAX_ARCHIVE_MEMBERS:
            raise GameUpdateError("GAME_RELEASE_MEMBER_LIMIT")
        stage_resolved = stage.resolve()
        for member in members:
            if cancel is not None and cancel.is_set():
                raise GameUpdateError("UPDATE_CANCELLED")
            name = member.name
            relative = PurePosixPath(name)
            if (
                not name
                or relative.is_absolute()
                or any(part in ("", ".", "..") for part in relative.parts)
                or relative.parts[0] != expected_root
                or not (member.isdir() or member.isfile())
            ):
                raise GameUpdateError("GAME_RELEASE_PATH_INVALID")
            if name in names:
                raise GameUpdateError("GAME_RELEASE_DUPLICATE_PATH")
            names.add(name)
            total_size += int(member.size)
            if total_size > MAX_EXPANDED_BYTES:
                raise GameUpdateError("GAME_RELEASE_EXPANDED_LIMIT")
            destination = stage.joinpath(*relative.parts)
            if not destination.resolve().is_relative_to(stage_resolved):
                raise GameUpdateError("GAME_RELEASE_PATH_INVALID")
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise GameUpdateError("GAME_RELEASE_ARCHIVE_INVALID")
            with source, destination.open("xb") as output:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise GameUpdateError("UPDATE_CANCELLED")
                    block = source.read(CHUNK_BYTES)
                    if not block:
                        break
                    output.write(block)
            executable = bool(member.mode & 0o111)
            destination.chmod(0o755 if executable else 0o644)

    package_root = stage / expected_root
    if not _is_game_package(package_root, version):
        raise GameUpdateError("GAME_RELEASE_CONTENT_INVALID")
    return package_root


def install_latest_release(
    game_home: Path,
    *,
    local_source: Path | None = None,
    cancel: threading.Event | None = None,
) -> tuple[str, Path | None]:
    """Check the public stable release and install its verified player package.

    The returned directory may be the included local source when no compatible
    release exists or the network is unavailable.  Existing source files are
    never replaced; downloaded builds live under ``game_home/versions``.
    """
    home = Path(game_home).expanduser()
    current = _current_install(home)
    fallback = Path(local_source).resolve() if local_source is not None else None
    if fallback is not None and not _is_game_package(fallback):
        fallback = None
    if current is not None:
        fallback = current[1]

    try:
        release = _release_json(cancel)
    except GameUpdateError as exc:
        if str(exc) == "UPDATE_CANCELLED":
            return "UPDATE CHECK CANCELLED · CURRENT GAME KEPT", fallback
        if str(exc) == "NO_STABLE_RELEASE":
            return "NO STABLE GAME BUILD PUBLISHED · USING CURRENT GAME", fallback
        if str(exc) == "UPDATE_CHECK_NETWORK_ERROR":
            return "UPDATE CHECK OFFLINE · USING CURRENT GAME", fallback
        return "UPDATE CHECK FAILED · USING CURRENT GAME", fallback

    if release.get("draft") or release.get("prerelease"):
        return "NO STABLE GAME BUILD PUBLISHED · USING CURRENT GAME", fallback
    try:
        version = _safe_version(release.get("tag_name"))
    except GameUpdateError:
        return "RELEASE VERSION INVALID · USING CURRENT GAME", fallback

    assets = release.get("assets")
    asset = next(
        (
            row
            for row in assets
            if isinstance(row, dict) and row.get("name") == ASSET_NAME
        ),
        None,
    ) if isinstance(assets, list) else None
    if asset is None:
        return "NO LINUX GAME PACKAGE PUBLISHED · USING CURRENT GAME", fallback

    current_version = current[0] if current is not None else ""
    if current_version == version:
        return f"GAME IS CURRENT · {version}", current[1]
    if fallback is not None and (fallback / "version.json").is_file():
        try:
            local_version = json.loads(
                (fallback / "version.json").read_text(encoding="utf-8")
            ).get("version")
        except (OSError, json.JSONDecodeError, AttributeError):
            local_version = None
        if local_version == version:
            return f"GAME IS CURRENT · {version}", fallback

    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:"):
        return "RELEASE HAS NO SHA-256 DIGEST · USING CURRENT GAME", fallback
    url = str(asset.get("browser_download_url") or "")
    size = asset.get("size")
    try:
        size_value = int(size)
    except (TypeError, ValueError):
        return "RELEASE SIZE INVALID · USING CURRENT GAME", fallback

    home.mkdir(parents=True, exist_ok=True)
    versions = home / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    destination = versions / version
    if _is_game_package(destination, version):
        _write_current(home, version)
        return f"GAME UPDATED · {version}", destination

    try:
        with tempfile.TemporaryDirectory(
            prefix="gg-game-update-", dir=str(home)
        ) as temp_name:
            temp = Path(temp_name)
            archive_path = temp / ASSET_NAME
            stage = temp / "stage"
            stage.mkdir()
            _download_asset(
                url,
                size_value,
                digest.removeprefix("sha256:"),
                archive_path,
                cancel,
            )
            package_root = _extract_validated(
                archive_path, stage, version, cancel
            )
            if destination.exists():
                if destination.is_symlink() or destination.is_file():
                    destination.unlink()
                else:
                    shutil.rmtree(destination)
            os.replace(package_root, destination)
    except GameUpdateError:
        return "RELEASE PACKAGE REJECTED · CURRENT GAME KEPT", fallback

    _write_current(home, version)
    return f"GAME UPDATED · {version}", destination


def _write_current(home: Path, version: str) -> None:
    pointer = home / "current.json"
    temp_path = home / ".current.json.tmp"
    payload = {
        "schema": "gg.game-client.install.v1",
        "version": version,
        "asset": ASSET_NAME,
    }
    with temp_path.open("w", encoding="utf-8") as output:
        json.dump(payload, output, separators=(",", ":"))
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp_path, pointer)


__all__ = [
    "GameUpdateError",
    "install_latest_release",
    "installed_game_directory",
    "is_game_package",
]
