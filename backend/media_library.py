"""Normalized MEDIA library and bounded public Internet Archive discovery.

Catalog entries describe the source's metadata, not a rights determination.
The starter catalog is a bundled snapshot and never performs network I/O.
Call search/expand/resolve from the host's bounded background worker, not Qt's
GUI thread. VOD entries deliberately use ``media='vod', is_live=False``.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.parse import quote, unquote, urlencode, urlsplit
import urllib.request

from backend.application_paths import PROJECT_ROOT

SEED_PATH = PROJECT_ROOT / "config" / "media-library.json"
MAX_SEED_BYTES = 8 * 1024 * 1024
CACHE_TTL = 6 * 3600
HTTP_TIMEOUT = 20.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_FILES = 8000
MAX_ITEMS = 2400
ENCODING_GROUPS_VERSION = 2
MAX_SEARCH = 200
_NETWORK_SLOTS = threading.BoundedSemaphore(3)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
_VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".mpg", ".mpeg", ".ogv"}
_AUDIO_EXT = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac"}
_SEASON_EPISODE = re.compile(
    r"(?i)(?<![a-z0-9])(?:s[ ._-]*(\d{1,2})[ ._-]*e[ ._-]*(\d{1,3})"
    r"|(\d{1,2})x(\d{1,3})|(?:season|säsong)[ ._-]*(\d{1,2})"
    r"[ ._-]*(?:episode|episod|avsnitt|ep)[ ._-]*(\d{1,3}))")
_EPISODE = re.compile(r"(?i)(?<![a-z0-9])(?:episode|episod|avsnitt|ep|e)[ ._#-]*(\d{1,3})(?!\d)")
_COMMA_EPISODE = re.compile(r"(?i)[ _]*-[ _]*(\d{2}),(\d{2,3})[ _]*-")
_ENCODE_SUFFIX = re.compile(r"(?i)(?:[ ._-]+(?:\d{3,4}p|\d+kb|h[ ._-]?26[45]|x26[45]|hevc|av1|web[ ._-]?dl|dvdrip|bluray|hq|hd))+$")
_SERIES_SIGNAL = re.compile(r"(?i)\b(?:episodes?|avsnitt|seasons?|säsonger?|complete\s+series|TV\s+show|TV[ -]series|cartoons|collection|recordings|tapes)\b")
_LANGUAGES = {"swe": "sv", "swedish": "sv", "svenska": "sv", "eng": "en", "english": "en",
              "en-us": "en", "en-gb": "en", "nor": "no", "nob": "no", "norsk": "no",
              "dan": "da", "danish": "da", "fin": "fi", "finnish": "fi", "deu": "de", "ger": "de",
              "german": "de", "fra": "fr", "fre": "fr", "french": "fr", "spa": "es", "spanish": "es"}


def _text(value: Any, limit: int = 300) -> str:
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(part) for part in value[:20])
    if not isinstance(value, (str, int, float)):
        return ""
    return " ".join(str(value).replace("\x00", "").split())[:limit]


def _number(value: Any, maximum: int = 999) -> int:
    try:
        return max(0, min(maximum, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _language(value: Any) -> str:
    parts = value if isinstance(value, list) else re.split(r"[;,/]", _text(value, 200))
    languages = []
    for part in parts[:12]:
        cleaned = _text(part, 30).casefold()
        if cleaned:
            languages.append(_LANGUAGES.get(cleaned, cleaned))
    return "; ".join(dict.fromkeys(languages))


def _year(value: Any) -> int:
    match = re.match(r"\s*((?:18|19|20|21)\d{2})(?:\D|$)", _text(value, 40))
    return int(match.group(1)) if match else 0


def _label(value: str) -> str:
    value = re.sub(r"[._]+", " ", str(value))
    return " ".join(value.split()).strip(" -–_/")


def _name(source: str) -> str:
    path = urlsplit(source).path if "://" in source else source
    return unquote(re.split(r"[\\/]", path)[-1])


def _episode_info(text: str) -> tuple[int, int, str, str]:
    match = _SEASON_EPISODE.search(text)
    if match:
        groups = match.groups()
        for offset in (0, 2, 4):
            if groups[offset] is not None:
                return int(groups[offset]), int(groups[offset + 1]), _label(text[:match.start()]), _label(text[match.end():])
    match = _COMMA_EPISODE.search(text)
    if match:
        return int(match[1]), int(match[2]), _label(text[:match.start()]), _label(text[match.end():])
    match = _EPISODE.search(text)
    if match:
        return 0, int(match.group(1)), _label(text[:match.start()]), _label(text[match.end():])
    return 0, 0, "", ""


def _category(text: str, content_type: str) -> str:
    hay = text.casefold()
    for category, tokens in (
        ("Animation", ("cartoon", "animation", "animated", "popeye", "betty boop", "superman", "felix the cat", "turtles", "tecknat")),
        ("Documentary", ("documentary", "dokumentär", "nasa", "science", "educational", "prelinger", "space to ground")),
        ("Western", ("western", "bonanza", "lone ranger")),
        ("Horror", ("horror", "haunted", "living dead", "skräck")),
        ("Science fiction", ("science fiction", "sci-fi", "flash gordon", "outer space")),
        ("Comedy", ("comedy", "komedi", "chaplin", "keaton", "hillbillies", "van dyke")),
        ("Crime", ("crime", "noir", "detective", "sherlock", "dragnet", "detour")),
    ):
        if any(token in hay for token in tokens):
            return category
    return "Classic TV" if content_type in ("series", "episode") else "Archive"


def annotate(row: dict[str, Any]) -> dict[str, Any]:
    """Copy/enrich one row; absent season/episode numbers remain zero.

    Existing provider metadata wins over filename inference. The filename is
    inspected before the user-facing title, so shortening a title is harmless.
    """
    item = dict(row)
    source = _text(item.get("source"), 3000)
    basename = _name(source)
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    stem = _ENCODE_SUFFIX.sub("", stem)
    title = _text(item.get("title"), 180) or _label(stem)
    season, episode, prefix, suffix = _episode_info(stem)
    if not episode:
        season, episode, prefix, suffix = _episode_info(title)
    season = _number(item.get("season", season), 99)
    episode = _number(item.get("episode", episode))
    kind = _text(item.get("kind"), 20).upper() or "TV"
    extension = Path(basename).suffix.casefold()
    content_type = _text(item.get("content_type"), 30).casefold()
    if content_type not in {"movie", "series", "episode", "live", "music", "game"}:
        if kind == "GAME":
            content_type = "game"
        elif kind in ("MUSIC", "RADIO") or extension in _AUDIO_EXT:
            content_type = "music"
        elif episode:
            content_type = "episode"
        elif item.get("is_live") is True or (item.get("media") == "stream" and extension not in _VIDEO_EXT):
            content_type = "live"
        else:
            content_type = "movie"
    series_title = _text(item.get("series_title"), 180)
    if content_type == "episode" and not series_title:
        series_title = prefix
        if not series_title and "://" not in source:
            folders = re.split(r"[\\/]", source)[:-1]
            folders = [folder for folder in folders if folder and not re.fullmatch(r"(?i)(?:season|säsong|s)[ ._-]*\d+", folder)]
            series_title = _label(folders[-1]) if folders else ""
        series_title = series_title or _text(item.get("archive_title"), 180) or "Unsorted episodes"
    elif content_type == "series":
        series_title = series_title or title
    year = _year(item.get("year"))
    if not year:
        match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", title)
        year = int(match.group(1)) if match else 0
    item.update(title=title, source=source, kind=kind, content_type=content_type,
                season=season, episode=episode, series_title=series_title,
                language=_language(item.get("language")), year=year,
                provider=_text(item.get("provider"), 80) or ("Local" if item.get("media") == "file" else "Custom"),
                category=_text(item.get("category"), 80) or _category(title + " " + series_title + " " + _text(item.get("subject"), 1000), content_type),
                is_live=content_type == "live")
    if content_type in ("movie", "episode") and "://" in source:
        item.update(media="vod", player="qml", play="video", stream=False)
    if series_title:
        basis = _text(item.get("archive_id"), 200) or (item["provider"] + ":" + series_title.casefold())
        item["series_id"] = _text(item.get("series_id"), 100) or "series:" + hashlib.sha256(basis.encode()).hexdigest()[:16]
    if episode:
        item["episode_title"] = _text(item.get("episode_title"), 180) or suffix or title
    return item


def natural_key(value: str) -> tuple:
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold()) for part in re.split(r"(\d+)", value))


def _row_key(row: dict[str, Any]) -> tuple:
    return (natural_key(str(row.get("series_title") or row.get("title") or "")),
            _number(row.get("season")), _number(row.get("episode")), natural_key(str(row.get("title") or "")))


def _seed_paths():
    return (SEED_PATH, SEED_PATH.with_name("media-library-sv.json"),
            SEED_PATH.with_name("media-library-nostalgia-sv.json"),
            SEED_PATH.with_name("media-library-nostalgia-us.json"))


def starter_revision() -> str:
    """Version the local bundles so updates import once on a worker."""
    digest = hashlib.sha256()
    for path in _seed_paths():
        digest.update(path.name.encode())
        try:
            if path.stat().st_size > MAX_SEED_BYTES:
                continue
            data = path.read_bytes()
            if len(data) <= MAX_SEED_BYTES:
                digest.update(data)
        except OSError:
            continue
    return digest.hexdigest()


def starter_catalog() -> list[dict[str, Any]]:
    """Load bounded local source bundles; readiness requires a separate proof."""
    rows, seen = [], set()
    for path in _seed_paths():
        try:
            if path.stat().st_size > MAX_SEED_BYTES:
                continue
            data = path.read_bytes()
            if len(data) > MAX_SEED_BYTES:
                continue
            payload = json.loads(data.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("schema") != "gg.media.library.v1" or not isinstance(payload.get("items"), list):
                continue
        except (OSError, ValueError, UnicodeError):
            continue
        for row in payload["items"]:
            if not isinstance(row, dict) or not _IDENTIFIER.fullmatch(_text(row.get("archive_id"), 220)):
                continue
            item = annotate(row)
            if not item.get("id") or item["id"] in seen or not item["source"].startswith("https://archive.org/"):
                continue
            seen.add(item["id"])
            rows.append(item)
    return rows


def _cache_dir() -> Path:
    # Lazy import prevents a cycle when media_contract uses this catalog.
    from backend.media_contract import ensure_state_dir
    root = ensure_state_dir() / "catalog" / "archive"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _download_json(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "archive.org" or parsed.username or parsed.password:
        raise ValueError("MEDIA_ARCHIVE_SOURCE_INVALID")
    request = urllib.request.Request(url, headers={"User-Agent": "GG-AI-Desktop-Media/1.0", "Accept": "application/json"})
    if not _NETWORK_SLOTS.acquire(timeout=HTTP_TIMEOUT):
        raise TimeoutError("MEDIA_ARCHIVE_BUSY")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            target = urlsplit(response.geturl())
            if target.scheme != "https" or target.netloc != "archive.org":
                raise ValueError("MEDIA_ARCHIVE_REDIRECT_INVALID")
            # read1 bounds each socket operation; a trickle response cannot
            # renew the deadline indefinitely as a single read(n) can.
            chunks, size = [], 0
            deadline = time.monotonic() + HTTP_TIMEOUT
            read = getattr(response, "read1", response.read)
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("MEDIA_ARCHIVE_TIMEOUT")
                block = read(min(64 * 1024, MAX_RESPONSE_BYTES + 1 - size))
                if not block:
                    break
                chunks.append(block)
                size += len(block)
                if size > MAX_RESPONSE_BYTES:
                    raise ValueError("MEDIA_ARCHIVE_RESPONSE_TOO_LARGE")
            raw = b"".join(chunks)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("MEDIA_ARCHIVE_RESPONSE_INVALID")
        return payload
    finally:
        _NETWORK_SLOTS.release()


def _cached_json(url: str, validate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    path = _cache_dir() / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")
    stale = None
    try:
        if path.stat().st_size <= MAX_RESPONSE_BYTES + 1024:
            cached = json.loads(path.read_text(encoding="utf-8"))
            payload = cached.get("payload") if isinstance(cached, dict) and cached.get("schema") == "gg.media.archive-cache.v1" else None
            if isinstance(payload, dict) and validate(payload):
                stale = payload
                if time.time() - path.stat().st_mtime < CACHE_TTL:
                    return payload
    except (OSError, ValueError, UnicodeError):
        pass
    try:
        payload = _download_json(url)
        if not validate(payload):
            raise ValueError("MEDIA_ARCHIVE_RESPONSE_INVALID")
    except (OSError, ValueError, TimeoutError):
        if stale is not None:
            return stale
        raise RuntimeError("MEDIA_ARCHIVE_UNAVAILABLE") from None
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".archive-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"schema": "gg.media.archive-cache.v1", "payload": payload}, handle, ensure_ascii=False, separators=(",", ":"))
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError:
        # An unwritable cache must not discard a successful provider response.
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return payload


def _valid_search(payload: dict[str, Any]) -> bool:
    response = payload.get("response")
    return isinstance(response, dict) and isinstance(response.get("docs"), list) and isinstance(response.get("numFound"), (int, float))


def _valid_metadata(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("metadata"), dict) and isinstance(payload.get("files"), list)


def _descriptor(metadata: dict[str, Any]) -> dict[str, Any] | None:
    identifier = _text(metadata.get("identifier"), 220)
    if not _IDENTIFIER.fullmatch(identifier):
        return None
    title = _text(metadata.get("title"), 180) or identifier
    season, episode, prefix, suffix = _episode_info(title)
    content_type = "episode" if episode else "series" if _SERIES_SIGNAL.search(title) else "movie"
    source = "https://archive.org/details/" + quote(identifier, safe="")
    row = {"id": "archive:" + identifier, "kind": "TV", "title": title, "archive_title": title,
           "source": source, "source_page": source, "archive_id": identifier,
           "media": "collection" if content_type == "series" else "vod", "player": "qml", "play": "video",
           "content_type": content_type, "provider": "Internet Archive", "is_live": False, "stream": False,
           "language": metadata.get("language"), "year": metadata.get("year") or metadata.get("date"),
           "subject": _text(metadata.get("subject"), 1000), "rights": _text(metadata.get("rights"), 1600),
           "licenseurl": _text(metadata.get("licenseurl"), 1000), "availability": "metadata", "playable": False}
    if episode:
        row.update(season=season, episode=episode, series_title=prefix, episode_title=suffix)
    elif content_type == "series":
        known_season = re.search(r"(?i)\b(?:season|säsong)[ ._-]*(\d{1,2})(?!\d)", title)
        if known_season:
            row["season"] = int(known_season.group(1))
    return annotate(row)


def search_archive(query: str, limit: int = 100) -> list[dict[str, Any]]:
    """Search public movie metadata; matches still require file resolution.

    User input is quoted as terms instead of accepting arbitrary Lucene fields.
    Multiple spelling variants find Swedish archival titles without promising
    that any particular channel, dub, season or video is present.
    """
    cleaned = _text(query, 160)
    terms = re.findall(r"[\w]+", cleaned, flags=re.UNICODE)[:12]
    clauses = []
    for term in terms:
        variants = [term]
        if term.casefold() == "tmnt":
            variants = ["tmnt", "turtles"]
        elif term.casefold() in {"mediadubb", "mediadub"}:
            variants = ["mediadubb", "media dubb"]
        elif term.casefold() in {"svenska", "swedish", "swe"}:
            clauses.append('(language:"swe" OR language:"Swedish" OR title:"svenska" OR subject:"svenska" OR description:"svenska")')
            continue
        clauses.append("(" + " OR ".join(field + ':"' + variant + '"' for variant in variants for field in ("title", "subject", "description")) + ")")
    expression = " AND ".join(clauses) if clauses else "(collection:classic_cartoons OR collection:classic_tv OR collection:feature_films)"
    params = {"q": "mediatype:movies AND -access-restricted-item:true AND (" + expression + ")",
              "fl[]": ["identifier", "title", "year", "date", "language", "subject", "rights", "licenseurl"],
              "rows": str(max(1, min(_number(limit, MAX_SEARCH), MAX_SEARCH))), "page": "1", "sort[]": "downloads desc", "output": "json"}
    payload = _cached_json("https://archive.org/advancedsearch.php?" + urlencode(params, doseq=True), _valid_search)
    rows, seen = [], set()
    for metadata in payload["response"]["docs"][:MAX_SEARCH]:
        if not isinstance(metadata, dict):
            continue
        row = _descriptor(metadata)
        if row and row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)
        if len(rows) >= max(1, min(_number(limit, MAX_SEARCH), MAX_SEARCH)):
            break
    return rows


def _restricted(payload: dict[str, Any]) -> bool:
    metadata = payload.get("metadata") or {}
    return any(str(container.get(key, "")).casefold() in {"true", "1", "yes"}
               for container in (payload, metadata) for key in ("is_dark", "access-restricted-item", "restricted"))


def _file_allowed(row: dict[str, Any]) -> bool:
    name = row.get("name")
    if not isinstance(name, str) or not name or len(name) > 1000 or "\x00" in name or "\\" in name:
        return False
    if name.startswith("/") or any(part in {"..", "."} for part in name.split("/")):
        return False
    if Path(name).suffix.casefold() not in _VIDEO_EXT:
        return False
    if any(str(row.get(key, "")).casefold() in {"true", "1", "yes"} for key in ("private", "restricted")):
        return False
    if row.get("size") is not None and _number(row.get("size"), 10**15) <= 0:
        return False
    # Archive-generated thumbnail videos and previews are never episodes.
    return not re.search(r"(?i)(?:^|[/_. -])(?:thumbs?|thumbnails?|preview|sample|trailer)(?:[/_. -]|$)", name)


def _encoding_key(row: dict[str, Any], indexed: dict[str, dict[str, Any]]) -> str:
    name = str(row["name"])
    original = _text(row.get("original"), 1000)
    seen = {name}
    for _ in range(10):
        if not original or original in seen or not _file_allowed({"name": original}):
            break
        seen.add(original)
        name = original
        original = _text((indexed.get(original) or {}).get("original"), 1000)
    stem = name.rsplit(".", 1)[0]
    return _ENCODE_SUFFIX.sub("", stem).casefold()


def _encoding_rank(row: dict[str, Any]) -> tuple:
    name = str(row["name"]).casefold()
    extension = Path(name).suffix
    container = {".mp4": 8, ".m4v": 7, ".webm": 6, ".mkv": 5, ".mov": 4, ".ogv": 3, ".avi": 2}.get(extension, 1)
    low = bool(re.search(r"(?i)(?:512kb|256kb|240p|360p)", name + " " + _text(row.get("format"))))
    return (container, not low, _number(row.get("height"), 4320), _number(row.get("width"), 7680), _number(row.get("size"), 10**15))


def _duration(row: dict[str, Any]) -> float:
    try:
        value = float(row.get("length") or 0)
        return value if math.isfinite(value) and value > 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def expand_item(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand an archive item into one preferred encoding per film/episode."""
    identifier = _text(row.get("archive_id"), 220)
    if not identifier:
        return [annotate(row)]
    if not _IDENTIFIER.fullmatch(identifier):
        raise ValueError("MEDIA_ARCHIVE_ID_INVALID")
    payload = _cached_json("https://archive.org/metadata/" + quote(identifier, safe=""), _valid_metadata)
    if _restricted(payload):
        raise RuntimeError("MEDIA_ARCHIVE_RESTRICTED")
    metadata = payload["metadata"]
    base = _descriptor(dict(metadata, identifier=identifier))
    if base is None:
        return []
    # Curated categorization and known series identity survive API refreshes.
    for key in ("category", "series_title", "series_id", "content_type", "season", "episode", "episode_title"):
        if row.get(key) not in (None, "", 0):
            base[key] = row[key]
    # Do not replace a known language/year when the provider omits it.
    for key in ("language", "year"):
        if not base.get(key) and row.get(key):
            base[key] = row[key]
    entries = [entry for entry in payload["files"][:MAX_FILES] if isinstance(entry, dict)]
    indexed = {str(entry.get("name")): entry for entry in entries}
    groups: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not _file_allowed(entry):
            continue
        group = _encoding_key(entry, indexed)
        if group not in groups or _encoding_rank(entry) > _encoding_rank(groups[group]):
            groups[group] = entry
    files = sorted(groups.values(), key=lambda file: natural_key(str(file["name"])))
    numbered = any(_episode_info(str(file["name"]))[1] for file in files)
    series = base.get("content_type") == "series" or numbered or (len(files) > 1 and row.get("content_type") != "movie")
    if not series and len(files) > 1:
        # Film archives often host restored/original/low-bitrate versions
        # without derivative links. Prefer a full-length compatible encoding,
        # not several fictitious episodes or an unrelated short extra.
        longest = max(_duration(file) for file in files)
        candidates = [file for file in files if not longest or _duration(file) >= longest * .95]
        files = [max(candidates, key=_encoding_rank)]
    rows = []
    seen_episodes = set()
    for file in files[:MAX_ITEMS]:
        name = str(file["name"])
        stem = _ENCODE_SUFFIX.sub("", _name(name).rsplit(".", 1)[0])
        season, episode, prefix, suffix = _episode_info(stem)
        if not episode and base.get("content_type") == "episode":
            season, episode = _number(base.get("season"), 99), _number(base.get("episode"))
        elif not _SEASON_EPISODE.search(stem) and base.get("season"):
            season = _number(base["season"], 99)
        # Duplicated uploads with different names but explicit S/E identity
        # should still occupy only one episode row.
        if episode and (season, episode) in seen_episodes:
            continue
        if episode:
            seen_episodes.add((season, episode))
        source = "https://archive.org/download/" + quote(identifier, safe="") + "/" + quote(name, safe="/")
        item = dict(base, id="tv:" + hashlib.sha256(source.encode()).hexdigest()[:16], source=source,
                    media="vod", stream=False, is_live=False, archive_file=name, play="video", player="qml",
                    availability="listed", playable=True,
                    content_type="episode" if series or base.get("content_type") == "episode" else "movie",
                    season=season, episode=episode)
        item["_encoding_groups_version"] = ENCODING_GROUPS_VERSION
        if series:
            item["series_title"] = _text(base.get("series_title"), 180) or base["title"]
            item["title"] = _label(stem)
            item["episode_title"] = suffix or _text(file.get("title"), 180) or _label(stem)
        else:
            item["title"] = base["title"]
        item["duration"] = _duration(file)
        item["bytes"] = _number(file.get("size"), 10**15)
        rows.append(annotate(item))
    return sorted(rows, key=_row_key)


def resolve_item(row: dict[str, Any]) -> dict[str, Any]:
    """Resolve a metadata descriptor; direct catalog files are already ready."""
    item = annotate(row)
    if not item.get("archive_id"):
        return item
    parsed = urlsplit(item["source"])
    if item.get("archive_file"):
        expected = "/download/" + quote(str(item["archive_id"]), safe="") + "/" + quote(str(item["archive_file"]), safe="/")
        if parsed.scheme == "https" and parsed.netloc == "archive.org" and parsed.path == expected and not parsed.query and not parsed.fragment:
            return item
        raise ValueError("MEDIA_ARCHIVE_SOURCE_INVALID")
    choices = expand_item(item)
    if not choices:
        raise RuntimeError("MEDIA_ARCHIVE_NO_PLAYABLE_VIDEO")
    if len(choices) > 1:
        raise RuntimeError("MEDIA_ARCHIVE_CHOOSE_EPISODE")
    selected = choices[0]
    # Preserve the descriptor's ID so selection/buffering markers stay stable.
    selected["id"] = item.get("id") or selected["id"]
    return selected
