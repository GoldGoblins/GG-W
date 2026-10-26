from __future__ import annotations

from backend.application_paths import DATA_HOME, HOME, STATE_ROOT

import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCHEMA = "gg.ai-desktop.media-status.v1"
STATE_DIR = Path(str(STATE_ROOT / 'media'))
MODES = ("MUSIC", "RADIO", "TV", "GAME", "FETCH")
DEFAULT_MODE = "MUSIC"
MAX_ITEMS = 16000
MAX_SCAN_DEPTH = 4
MAX_TITLE = 96
VOLUME_DEFAULT = 70

AUDIO_EXT = frozenset(
    {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac", ".wma", ".aiff"}
)
VIDEO_EXT = frozenset(
    {".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v", ".mpg", ".mpeg", ".ts"}
)
DENIED_TOKENS = (
    "ps3",
    "ps4",
    "ps5",
    "switch",
    "xbox360",
    "xboxone",
    "seriesx",
    "series-x",
)

SYSTEMS: dict[str, dict[str, Any]] = {
    "nes": {
        "label": "NES",
        "ext": {".nes", ".fds"},
        "folders": ("nes", "famicom"),
        "bins": ("mednafen", "fceux", "nestopia", "retroarch"),
        "tokens": ("mednafen", "fceux", "nestopia", "retroarch"),
    },
    "snes": {
        "label": "SNES",
        "ext": {".smc", ".sfc"},
        "folders": ("snes", "sfc"),
        "bins": ("mednafen", "snes9x", "snes9x-gtk", "zsnes", "retroarch"),
        "tokens": ("mednafen", "snes9x", "zsnes", "retroarch"),
    },
    "n64": {
        "label": "N64",
        "ext": {".n64", ".z64", ".v64"},
        "folders": ("n64",),
        "bins": ("mupen64plus", "retroarch"),
        "tokens": ("mupen64plus", "retroarch"),
    },
    "gb": {
        "label": "GAME BOY",
        "ext": {".gb", ".gbc"},
        "folders": ("gb", "gbc", "gameboy"),
        "bins": ("mednafen", "mgba", "vbam", "sameboy", "retroarch"),
        "tokens": ("mednafen", "mgba", "vbam", "sameboy", "retroarch"),
    },
    "gba": {
        "label": "GBA",
        "ext": {".gba"},
        "folders": ("gba",),
        "bins": ("mednafen", "mgba", "vbam", "retroarch"),
        "tokens": ("mednafen", "mgba", "vbam", "retroarch"),
    },
    "nds": {
        "label": "NDS",
        "ext": {".nds"},
        "bins": ("melonds", "desmume", "retroarch"),
        "tokens": ("melonds", "desmume", "retroarch"),
    },
    "genesis": {
        "label": "GENESIS",
        "ext": {".md", ".gen", ".smd"},
        "folders": ("genesis", "md", "megadrive"),
        "bins": ("mednafen", "retroarch"),
        "tokens": ("mednafen", "retroarch"),
    },
    "ps1": {
        "label": "PS1",
        "ext": {".cue", ".chd", ".pbp", ".ccd"},
        "folders": ("ps1", "psx", "playstation"),
        "bins": ("duckstation", "duckstation-qt", "pcsxr", "mednafen", "retroarch"),
        "tokens": ("duckstation", "pcsxr", "mednafen", "retroarch"),
    },
    "ps2": {
        "label": "PS2",
        "ext": {".iso", ".chd", ".cso", ".bin"},
        "folders": ("ps2", "playstation2"),
        "bins": ("pcsx2", "pcsx2-qt", "retroarch"),
        "tokens": ("pcsx2", "retroarch"),
    },
    "psp": {
        "label": "PSP",
        "ext": {".iso", ".cso", ".pbp"},
        "folders": ("psp",),
        "bins": ("ppsspp", "PPSSPPSDL", "retroarch"),
        "tokens": ("ppsspp", "retroarch"),
    },
    "gc": {
        "label": "GAMECUBE",
        "ext": {".gcm", ".gcz", ".rvz", ".iso"},
        "folders": ("gc", "gamecube", "gcn"),
        "bins": ("dolphin-emu", "retroarch"),
        "tokens": ("dolphin-emu", "dolphin", "retroarch"),
    },
    "wii": {
        "label": "WII",
        "ext": {".wbfs", ".wad", ".rvz", ".iso"},
        "folders": ("wii",),
        "bins": ("dolphin-emu", "retroarch"),
        "tokens": ("dolphin-emu", "dolphin", "retroarch"),
    },
    "xbox": {
        "label": "XBOX",
        "ext": {".xiso", ".iso"},
        "folders": ("xbox", "ogxbox"),
        "bins": ("xemu",),
        "tokens": ("xemu",),
    },
    "dreamcast": {
        "label": "DREAMCAST",
        "ext": {".gdi", ".cdi", ".chd"},
        "bins": ("flycast", "redream", "retroarch"),
        "tokens": ("flycast", "redream", "retroarch"),
    },
}

TOOL_BINS = {
    "cliamp": ("cliamp",),
    "vlc": ("cvlc", "vlc"),
    "ffplay": ("ffplay",),
    "torlink": ("torlnk", "torlink"),
    "yt-dlp": ("yt-dlp",),
    "retroarch": ("retroarch",),
}

TOOL_DIRS = (
    Path(str(HOME / '.local/bin')),
    Path.home() / ".local/bin",
    Path(str(DATA_HOME / 'goldgoblins/tools')),
    Path(str(DATA_HOME / 'goldgoblins/tools/emu/usr/bin')),
    Path(str(DATA_HOME / 'goldgoblins/tools/node/bin')),
    Path(str(DATA_HOME / 'pnpm')),
    Path(str(DATA_HOME / 'pnpm/bin')),
)

RADIO_API = "https://de1.api.radio-browser.info/json/stations/search"
IPTV_PLAYLISTS = (
    "https://iptv-org.github.io/iptv/index.category.m3u",
    "https://iptv-org.github.io/iptv/countries/se.m3u",
    "https://iptv-org.github.io/iptv/countries/fi.m3u",
    "https://iptv-org.github.io/iptv/countries/no.m3u",
    "https://iptv-org.github.io/iptv/countries/dk.m3u",
    "https://iptv-org.github.io/iptv/countries/uk.m3u",
    "https://iptv-org.github.io/iptv/languages/swe.m3u",
)
IPTV_PER_SOURCE = 16000
MAX_HTTP_BYTES = 12 * 1024 * 1024
BUNDLED_CHANNELS = Path(__file__).resolve().parents[1] / "config/media-channels.m3u"
RADIO_BROWSER_LIMIT = 250
RADIO_BROWSER_COUNTRIES = (
    ("SE", 220),
    ("NO", 50),
    ("DK", 50),
    ("FI", 50),
)
HOMEBREW_API = "https://hh3.gbdev.io/api"
HOMEBREW_PAGES = 2
HOMEBREW_DENIED_TYPES = frozenset({"hackrom"})
HOMEBREW_PLATFORM = {
    "GB": "gb",
    "GBC": "gb",
    "GBA": "gba",
    "NES": "nes",
}
HOMEBREW_REPO = {
    "gb": "https://github.com/gbdev/database",
    "gba": "https://github.com/gbadev-org/games",
    "nes": "https://github.com/nesdev-org/homebrew-db",
}
MAX_ROM_BYTES = 16 * 1024 * 1024
HTTP_UA = "gg-ai-desktop/media"
CACHE_TTL = 6 * 3600

RADIO_PRESETS = (
    {
        "title": "SR P1",
        "url": "https://live1.sr.se/p1-mp3-192",
        "fm_mhz": 92.4,
    },
    {
        "title": "SR P2",
        "url": "https://live1.sr.se/p2-mp3-192",
        "fm_mhz": 96.2,
    },
    {
        "title": "SR P3",
        "url": "https://live1.sr.se/p3-mp3-96",
        "fm_mhz": 99.3,
    },
    {
        "title": "SR P4 Stockholm",
        "url": "https://edge1.sr.se/p4sth-aac-320",
        "fm_mhz": 102.3,
    },
    {
        "title": "SR P4 Göteborg",
        "url": "https://live1.sr.se/p4gbg-mp3-192",
        "fm_mhz": 101.9,
    },
    {
        "title": "SR P4 Malmöhus",
        "url": "https://live1.sr.se/p4mal-mp3-192",
        "fm_mhz": 100.6,
    },
    {
        "title": "SR P4 Uppsala",
        "url": "https://live1.sr.se/p4upp-mp3-192",
        "fm_mhz": 98.2,
    },
    {
        "title": "SR P4 Östergötland",
        "url": "https://live1.sr.se/p4ost-mp3-192",
        "fm_mhz": 101.3,
    },
    {
        "title": "SR P4 Jönköping",
        "url": "https://live1.sr.se/p4jon-mp3-192",
        "fm_mhz": 100.2,
    },
    {
        "title": "SR P4 Norrbotten",
        "url": "https://live1.sr.se/p4nbd-mp3-192",
        "fm_mhz": 98.7,
    },
    {
        "title": "BBC World Service",
        "url": "https://stream.live.vc.bbcmedia.co.uk/bbc_world_service",
    },
    {
        "title": "cliamp Lofi",
        "url": "http://radio.cliamp.stream/lofi/stream",
    },
    {
        "title": "SomaFM Groove Salad",
        "url": "https://ice2.somafm.com/groovesalad-128-mp3",
    },
)
FM_BAND_LO = 87.5
FM_BAND_HI = 108.0
_RTL_SDR_USB = frozenset({"0bda:2832", "0bda:2838", "0bda:2831"})

LIBRARY_DIRS = (
    Path(str(HOME / 'Musik')),
    Path.home() / "Musik",
    Path.home() / "Music",
    Path(str(HOME / 'Videor')),
    Path.home() / "Videor",
    Path.home() / "Videos",
    Path(str(HOME / 'ROMs')),
    Path.home() / "ROMs",
    Path(str(HOME / 'Spel')),
    Path.home() / "Spel",
    Path.home() / "Games",
    STATE_DIR / "library",
)
FETCH_DIR = Path.home() / "Downloads" / "torlink"
FETCH_TUI_TITLE = "gg-ai-torlink"
KONSOLE_BIN = Path("/usr/bin/konsole")


def ensure_state_dir() -> Path:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return STATE_DIR


def which_first(names: tuple[str, ...]) -> str:
    parts = [str(path) for path in TOOL_DIRS if path.is_dir()]
    inherited = str(os.environ.get("PATH") or "")
    if inherited:
        parts.append(inherited)
    search = os.pathsep.join(parts)
    for name in names:
        found = shutil.which(name, path=search)
        if found:
            return found
        if os.name == "nt":
            from backend.platform_support import find_executable
            found = find_executable(name)
            if found:
                return found
    return ""


_PROBE_TTL = 30.0
_probe_cache: tuple[float, dict[str, dict[str, Any]]] | None = None


def probe_tools() -> dict[str, dict[str, Any]]:
    global _probe_cache
    now = time.monotonic()
    hit = _probe_cache
    if hit is not None and now - hit[0] < _PROBE_TTL:
        return hit[1]
    rows: dict[str, dict[str, Any]] = {}
    for key, names in TOOL_BINS.items():
        path = which_first(names)
        rows[key] = {
            "present": bool(path),
            "path": path,
            "names": list(names),
        }
    cores: dict[str, dict[str, Any]] = {}
    for system, spec in SYSTEMS.items():
        path = which_first(tuple(spec["bins"]))
        cores[system] = {
            "label": spec["label"],
            "present": bool(path),
            "path": path,
        }
    rows["cores"] = cores
    _probe_cache = (now, rows)
    return rows


def _library_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for folder in LIBRARY_DIRS + (ensure_state_dir() / "library",):
        try:
            resolved = folder.expanduser()
            if not resolved.exists() or not resolved.is_dir():
                continue
            resolved = resolved.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def library_roots() -> list[Path]:
    return _library_roots()


def fetch_download_dir() -> Path:
    return FETCH_DIR


def fetch_terminal() -> str:
    found = which_first(("konsole",))
    if found:
        return found
    if KONSOLE_BIN.is_file() and os.access(KONSOLE_BIN, os.X_OK):
        return str(KONSOLE_BIN)
    return ""


def ensure_rom_library() -> Path:
    root = Path(str(HOME / 'ROMs'))
    home = Path.home() / "ROMs"
    if not root.exists() and home.exists():
        root = home
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for system in SYSTEMS:
        (root / system).mkdir(mode=0o700, exist_ok=True)
    return root


def _denied_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    return any(token in parts for token in DENIED_TOKENS)


def item_id(kind: str, source: str) -> str:
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return kind.lower() + ":" + digest


def _title_of(path: Path) -> str:
    name = path.stem.replace("_", " ").replace("-", " ").strip()
    return (name or path.name)[:MAX_TITLE]


def system_for(path: Path) -> str:
    if _denied_path(path):
        return ""
    suffix = path.suffix.lower()
    folders = {part.lower() for part in path.parts}
    ranked: list[tuple[int, str]] = []
    ambiguous = {".iso", ".bin", ".chd", ".cue", ".cso"}
    for system, spec in SYSTEMS.items():
        score = 0
        folder_names = {str(name).lower() for name in spec.get("folders") or ()}
        if folder_names & folders:
            score += 2
        if suffix in spec["ext"]:
            score += 1
        if score:
            ranked.append((score, system))
    if not ranked:
        return ""
    ranked.sort(reverse=True)
    best_score, system = ranked[0]
    if suffix in ambiguous and best_score < 2:
        return ""
    return system


def confined(path: Path, roots: list[Path] | None = None) -> Path:
    resolved = path.expanduser().resolve()
    if _denied_path(resolved):
        raise ValueError("MEDIA_SYSTEM_DENIED")
    bases = roots if roots is not None else library_roots()
    for root in bases:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError("MEDIA_PATH_DENIED")


def stream_allowed(url: str) -> str:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("MEDIA_STREAM_DENIED")
    if not parsed.netloc:
        raise ValueError("MEDIA_STREAM_DENIED")
    if parsed.username or parsed.password:
        raise ValueError("MEDIA_STREAM_DENIED")
    return raw


def parse_m3u_text(text: str, kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    title = ""
    attrs: dict[str, str] = {}
    hints: dict[str, str] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF:"):
            match = re.match(r'#EXTINF:((?:[^",]|"[^"]*")*),(.*)$', line)
            title = (match.group(2) if match else line.rsplit(",", 1)[-1]).strip()[:MAX_TITLE]
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', match.group(1) if match else line))
            hints = {}
            continue
        if line.startswith("#EXTVLCOPT:"):
            name, _, value = line[len("#EXTVLCOPT:"):].partition("=")
            field = {"http-referrer": "referrer", "http-user-agent": "user_agent"}.get(name.casefold())
            if field:
                hints[field] = value
            continue
        if line.startswith("#"):
            continue
        try:
            url = stream_allowed(line)
        except ValueError:
            title = ""
            attrs = {}
            hints = {}
            continue
        try:
            from backend.media_request import public_headers
            public_headers(hints)
        except ValueError:
            title, attrs, hints = "", {}, {}
            continue
        rows.append(
            {
                "id": item_id(kind, url),
                "kind": kind,
                "title": title or urlparse(url).path.rsplit("/", 1)[-1] or kind,
                "source": url,
                "media": "stream",
                "system": "",
                "content_type": "live" if kind == "TV" else "music",
                "is_live": True,
                "channel_id": attrs.get("tvg-id", ""),
                "category": attrs.get("group-title", ""),
                "language": attrs.get("tvg-language", ""),
                "country": attrs.get("tvg-country", ""),
                "logo": attrs.get("tvg-logo", ""),
                "provider": "IPTV" if kind == "TV" else "Radio",
                "play": "video" if kind == "TV" else "audio",
                **hints,
            }
        )
        title = ""
        attrs = {}
        hints = {}
        if len(rows) >= MAX_ITEMS:
            break
    return rows


def parse_m3u(path: Path, kind: str) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return parse_m3u_text(text, kind)


def _http_get(url: str, timeout: float = 12.0) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": HTTP_UA, "Accept": "*/*"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_HTTP_BYTES + 1)
        if len(data) > MAX_HTTP_BYTES:
            raise ValueError("MEDIA_RESPONSE_TOO_LARGE")
        return data


def _cache_path(name: str) -> Path:
    return ensure_state_dir() / name


def _cache_fresh(path: Path) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age < CACHE_TTL


def _cached_bytes(name: str, url: str, *, timeout: float = 12.0) -> bytes:
    path = _cache_path(name)
    if _cache_fresh(path):
        try:
            return path.read_bytes()
        except OSError:
            pass
    stale = b""
    try:
        stale = path.read_bytes()
    except OSError:
        pass
    try:
        raw = _http_get(url, timeout=timeout)
        if name.endswith(".m3u") and not raw.lstrip(b"\xef\xbb\xbf\r\n ").startswith(b"#EXTM3U"):
            raise ValueError("MEDIA_PLAYLIST_INVALID")
        if name.endswith(".json"):
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, (list, dict)):
                raise ValueError("MEDIA_RESPONSE_INVALID")
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, UnicodeError):
        if stale:
            return stale
        raise
    # Publish complete files only; a crash must not replace the good cache.
    temporary = path.with_suffix(path.suffix + ".tmp-" + str(os.getpid()) + "-" + str(time.monotonic_ns()))
    try:
        temporary.write_bytes(raw)
        temporary.chmod(0o600)
        temporary.replace(path)
    except OSError:
        pass
    finally:
        temporary.unlink(missing_ok=True)
    return raw


def radio_browser_stations(
    query: str = "",
    country: str = "SE",
    limit: int = 80,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {
        "hidebroken": "true",
        "order": "clickcount",
        "reverse": "true",
        "limit": str(max(1, min(int(limit), RADIO_BROWSER_LIMIT))),
    }
    cleaned = str(query or "").strip()
    if cleaned:
        params["name"] = cleaned[:80]
    elif country:
        params["countrycode"] = country
    url = RADIO_API + "?" + urllib.parse.urlencode(params)
    cache_name = "radio-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".json"
    try:
        raw = _cached_bytes(cache_name, url)
        payload = json.loads(raw.decode("utf-8"))
    except (
        OSError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeError,
    ):
        return []
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        source = str(item.get("url_resolved") or item.get("url") or "").strip()
        try:
            source = stream_allowed(source)
        except ValueError:
            continue
        if source in seen:
            continue
        seen.add(source)
        title = str(item.get("name") or "station").strip()[:MAX_TITLE]
        rows.append(
            {
                "id": item_id("RADIO", source),
                "kind": "RADIO",
                "title": title,
                "source": source,
                "media": "stream",
                "system": "",
                "player": "cliamp",
            }
        )
        if len(rows) >= MAX_ITEMS:
            break
    return rows


def _iptv_playlist(url: str, *, refresh: bool = True) -> list[dict[str, Any]]:
    name = "tv-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".m3u"
    try:
        # A dead IPTV mirror must not hold the GUI for the generic 12-second
        # HTTP timeout.  The catalog can still use its last successful cache.
        text = (_cached_bytes(name, url, timeout=5.0) if refresh else _cache_path(name).read_bytes()).decode("utf-8", "replace")
        if not text.lstrip("\ufeff\r\n ").startswith("#EXTM3U"):
            return []
    except (OSError, urllib.error.URLError, TimeoutError, UnicodeError, ValueError):
        return []
    rows: list[dict[str, Any]] = []
    for item in parse_m3u_text(text, "TV"):
        item["player"] = "qml"
        item["source_page"] = url
        if not item["category"] and "/categories/" in url:
            item["category"] = url.rsplit("/", 1)[-1].split(".")[0].title()
        if not item["language"] and "/languages/" in url:
            item["language"] = url.rsplit("/", 1)[-1].split(".")[0]
        rows.append(item)
    return rows


def _iptv_playlists() -> list[list[dict[str, Any]]]:
    """Fetch country/category playlists concurrently, keeping source order."""
    if not IPTV_PLAYLISTS:
        return []
    workers = min(6, len(IPTV_PLAYLISTS))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gg-tv") as pool:
        futures = [pool.submit(_iptv_playlist, url) for url in IPTV_PLAYLISTS]
        rows: list[list[dict[str, Any]]] = []
        for future in futures:
            try:
                rows.append(future.result())
            except Exception:
                rows.append([])
        return rows


def iptv_catalog(*, refresh: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    playlists = _iptv_playlists() if refresh else [_iptv_playlist(url, refresh=False) for url in IPTV_PLAYLISTS]
    if BUNDLED_CHANNELS.is_file():
        playlists.append(parse_m3u(BUNDLED_CHANNELS, "TV"))
    for playlist in playlists:
        taken = 0
        for item in playlist:
            if item["source"] in seen:
                continue
            seen.add(item["source"])
            rows.append(item)
            taken += 1
            if taken >= IPTV_PER_SOURCE or len(rows) >= MAX_ITEMS:
                break
        if len(rows) >= MAX_ITEMS:
            break
    return rows


def library_catalog(*, refresh: bool = False) -> list[dict[str, Any]]:
    """One video library. Network refresh is only called by the library worker."""
    from backend.media_library import annotate, starter_catalog
    rows = _scan_files("TV", VIDEO_EXT)
    rows.extend(row for row in fetch_catalog() if row.get("play") == "video")
    playlist = ensure_state_dir() / "tv.m3u"
    if playlist.is_file():
        rows.extend(parse_m3u(playlist, "TV"))
    rows.extend(starter_catalog())
    rows.extend(iptv_catalog(refresh=refresh))
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw in rows:
        row = annotate(raw)
        source = str(row.get("source") or row.get("id") or "")
        if not source or source in seen:
            continue
        seen.add(source)
        result.append(row)
        if len(result) >= MAX_ITEMS:
            break
    return sort_title_rows(result)


def _title_sort_key(title: str) -> str:
    text = str(title or "").strip().casefold()
    return text.translate(
        str.maketrans(
            {
                "å": "zz",
                "ä": "zza",
                "ö": "zzb",
                "é": "e",
                "ü": "u",
            }
        )
    )


def _radio_pin(title: str) -> int:
    text = " ".join(str(title or "").strip().casefold().split())
    text = text.replace("sveriges radio", "sr")
    if text == "sr p1" or text.startswith("sr p1 ") or text.startswith("sr p1-"):
        return 0
    if text == "sr p2" or text.startswith("sr p2 ") or text.startswith("sr p2-"):
        return 1
    if text == "sr p3" or text.startswith("sr p3 ") or text.startswith("sr p3-"):
        return 2
    if text.startswith("sr p4"):
        return 3
    return 10


def sort_title_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda item: _title_sort_key(str(item.get("title") or "")),
    )


def sort_radio_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda item: (
            _radio_pin(str(item.get("title") or "")),
            _title_sort_key(str(item.get("title") or "")),
        ),
    )


def looks_like_url(value: str) -> bool:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def query_item(kind: str, query: str) -> dict[str, Any] | None:
    raw = str(query or "").strip()
    if not looks_like_url(raw):
        return None
    source = stream_allowed(raw)
    parsed = urlparse(source)
    title = parsed.path.rsplit("/", 1)[-1] or source
    row = {
        "id": item_id(kind, source),
        "kind": kind,
        "title": title[:MAX_TITLE],
        "source": source,
        "media": "stream",
        "system": "",
        "player": "cliamp" if kind == "RADIO" else "qml",
    }
    if kind == "TV":
        host = (parsed.hostname or "").lower()
        parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
        if host in {"archive.org", "www.archive.org"} and len(parts) >= 2 and parts[0] in {"details", "metadata", "download"}:
            identifier = parts[1]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", identifier):
                raise ValueError("MEDIA_ARCHIVE_ID_INVALID")
            row.update(archive_id=identifier, title=identifier, provider="Internet Archive", content_type="movie",
                       media="vod", is_live=False, stream=False, play="video",
                       source_page="https://archive.org/details/" + urllib.parse.quote(identifier, safe=""))
            if parts[0] != "download" or len(parts) < 3:
                row["source"] = row["source_page"]
            else:
                row["archive_file"] = "/".join(parts[2:])
        elif Path(parsed.path).suffix.lower() in VIDEO_EXT:
            row.update(content_type="movie", media="vod", is_live=False, stream=False, play="video")
    return row


def _scan_files(kind: str, suffixes: frozenset[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in library_roots():
        stack = [(root, 0)]
        while stack and len(rows) < MAX_ITEMS:
            folder, depth = stack.pop()
            if depth > MAX_SCAN_DEPTH:
                continue
            try:
                children = sorted(folder.iterdir(), key=lambda item: item.name.lower())
            except OSError:
                continue
            for child in children:
                if child.is_symlink() or child.name.startswith("."):
                    continue
                if child.is_dir():
                    if not _denied_path(child):
                        stack.append((child, depth + 1))
                    continue
                if child.suffix.lower() not in suffixes:
                    continue
                if _denied_path(child):
                    continue
                try:
                    source = str(confined(child))
                except ValueError:
                    continue
                if source in seen:
                    continue
                seen.add(source)
                rows.append(
                    {
                        "id": item_id(kind, source),
                        "kind": kind,
                        "title": _title_of(child),
                        "source": source,
                        "media": "file",
                        "system": "",
                    }
                )
                if len(rows) >= MAX_ITEMS:
                    break
    return rows


def music_catalog() -> list[dict[str, Any]]:
    return _scan_files("MUSIC", AUDIO_EXT)


def video_catalog() -> list[dict[str, Any]]:
    rows = _scan_files("TV", VIDEO_EXT)
    for item in rows:
        item["player"] = "qml"
    playlist = ensure_state_dir() / "tv.m3u"
    if playlist.is_file():
        rows.extend(parse_m3u(playlist, "TV"))
    live = iptv_catalog()
    seen = {item["source"] for item in rows}
    for item in live:
        if item["source"] in seen:
            continue
        seen.add(item["source"])
        rows.append(item)
        if len(rows) >= MAX_ITEMS:
            break
    return sort_title_rows(rows)[:MAX_ITEMS]


def radio_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for preset in RADIO_PRESETS:
        url = stream_allowed(str(preset["url"]))
        row = {
            "id": item_id("RADIO", url),
            "title": str(preset["title"])[:MAX_TITLE],
            "kind": "RADIO",
            "source": url,
            "media": "stream",
            "system": "",
            "player": "cliamp",
        }
        mhz = preset.get("fm_mhz")
        if mhz:
            row["fm_mhz"] = float(mhz)
        rows.append(row)
        seen.add(url)
    playlist = ensure_state_dir() / "radio.m3u"
    if playlist.is_file():
        for item in parse_m3u(playlist, "RADIO"):
            if item["source"] in seen:
                continue
            item["player"] = "cliamp"
            rows.append(item)
            seen.add(item["source"])
    for country, cap in RADIO_BROWSER_COUNTRIES:
        for item in radio_browser_stations(country=country, limit=cap):
            if item["source"] in seen:
                continue
            rows.append(item)
            seen.add(item["source"])
            if len(rows) >= MAX_ITEMS:
                break
        if len(rows) >= MAX_ITEMS:
            break
    return sort_radio_rows(rows)[:MAX_ITEMS]


def radio_tuner_marks() -> list[dict[str, Any]]:
    marks: list[dict[str, Any]] = []
    for preset in RADIO_PRESETS:
        mhz = preset.get("fm_mhz")
        if not mhz:
            continue
        url = stream_allowed(str(preset["url"]))
        marks.append(
            {
                "title": str(preset["title"])[:MAX_TITLE],
                "mhz": float(mhz),
                "id": item_id("RADIO", url),
            }
        )
    return marks


def freq_for_now(now: dict[str, Any] | None) -> float:
    if not now:
        return 0.0
    try:
        listed = float(now.get("fm_mhz") or 0)
    except (TypeError, ValueError):
        listed = 0.0
    if listed > 0:
        return listed
    title = str(now.get("title") or "")
    source = str(now.get("source") or "")
    tail = source.rsplit("/", 1)[-1]
    for preset in RADIO_PRESETS:
        mhz = preset.get("fm_mhz")
        if not mhz:
            continue
        url = str(preset["url"])
        if str(preset["title"]) == title or url == source or url.endswith(tail) or tail and tail in url:
            return float(mhz)
    return 0.0


def nearest_radio_preset(mhz: float) -> dict[str, Any] | None:
    try:
        target = float(mhz)
    except (TypeError, ValueError):
        return None
    if target < FM_BAND_LO - 1 or target > FM_BAND_HI + 1:
        return None
    best: dict[str, Any] | None = None
    best_delta = 1.6
    for preset in RADIO_PRESETS:
        marked = preset.get("fm_mhz")
        if not marked:
            continue
        delta = abs(float(marked) - target)
        if delta < best_delta:
            best_delta = delta
            best = dict(preset)
    return best


def probe_rf_frontend() -> dict[str, str]:
    radio = Path("/dev/radio0")
    if radio.exists() and not radio.is_symlink():
        return {"kind": "V4L_FM", "label": "V4L FM", "path": str(radio)}
    swradio = Path("/dev/swradio0")
    if swradio.exists():
        return {"kind": "RTL_SDR", "label": "RTL-SDR", "path": str(swradio)}
    root = Path("/sys/bus/usb/devices")
    try:
        nodes = list(root.iterdir())
    except OSError:
        nodes = []
    for node in nodes:
        try:
            vid = (node / "idVendor").read_text(encoding="ascii").strip()
            pid = (node / "idProduct").read_text(encoding="ascii").strip()
        except OSError:
            continue
        if f"{vid}:{pid}" in _RTL_SDR_USB:
            return {"kind": "RTL_SDR", "label": "RTL-SDR", "path": str(node)}
    return {
        "kind": "NONE",
        "label": "NO RF",
        "detail": "wifi-2.4/5g",
    }


def fetch_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    root = fetch_download_dir()
    try:
        root = root.expanduser()
        if not root.exists() or not root.is_dir():
            return rows
        root = root.resolve()
    except OSError:
        return rows
    suffixes = AUDIO_EXT | VIDEO_EXT
    stack = [(root, 0)]
    while stack and len(rows) < MAX_ITEMS:
        folder, depth = stack.pop()
        if depth > MAX_SCAN_DEPTH:
            continue
        try:
            children = sorted(folder.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            if child.is_symlink() or child.name.startswith("."):
                continue
            if child.is_dir():
                if not _denied_path(child):
                    stack.append((child, depth + 1))
                continue
            suffix = child.suffix.lower()
            if suffix not in suffixes or _denied_path(child):
                continue
            try:
                source = str(confined(child, roots=[root]))
            except ValueError:
                continue
            if source in seen:
                continue
            seen.add(source)
            rows.append(
                {
                    "id": item_id("FETCH", source),
                    "kind": "FETCH",
                    "title": _title_of(child),
                    "source": source,
                    "media": "file",
                    "system": "",
                    "play": "video" if suffix in VIDEO_EXT else "audio",
                }
            )
            if len(rows) >= MAX_ITEMS:
                break
    return rows


def search_items(mode: str, query: str) -> list[dict[str, Any]]:
    kind = str(mode or DEFAULT_MODE).strip().upper()
    cleaned = str(query or "").strip()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    if kind == "FETCH":
        needle = cleaned.lower()
        for item in fetch_catalog():
            if needle and needle not in str(item.get("title") or "").lower():
                continue
            rows.append(item)
        return rows[:MAX_ITEMS]
    direct = query_item("RADIO" if kind == "RADIO" else "TV", cleaned)
    if direct is not None:
        rows.append(direct)
        seen.add(direct["source"])
    if kind == "RADIO":
        for item in radio_browser_stations(query=cleaned, limit=120):
            if item["source"] in seen:
                continue
            rows.append(item)
            seen.add(item["source"])
        for item in radio_catalog():
            if cleaned.lower() not in str(item.get("title") or "").lower():
                continue
            if item["source"] in seen:
                continue
            rows.append(item)
            seen.add(item["source"])
        return sort_radio_rows(rows)[:MAX_ITEMS]
    if kind == "TV":
        needle = cleaned.lower()
        for playlist in _iptv_playlists():
            for item in playlist:
                hay = (str(item.get("title") or "") + " " + str(item.get("source") or "")).lower()
                if needle and needle not in hay:
                    continue
                if item["source"] in seen:
                    continue
                rows.append(item)
                seen.add(item["source"])
                if len(rows) >= MAX_ITEMS:
                    return rows
        for item in _scan_files("TV", VIDEO_EXT):
            if needle and needle not in str(item.get("title") or "").lower():
                continue
            if item["source"] in seen:
                continue
            item["player"] = "qml"
            rows.append(item)
        return sort_title_rows(rows)[:MAX_ITEMS]
    if kind == "MUSIC":
        needle = cleaned.lower()
        for item in music_catalog():
            if needle and needle not in str(item.get("title") or "").lower():
                continue
            rows.append(item)
        return rows[:MAX_ITEMS]
    if kind == "GAME":
        needle = cleaned.lower()
        for item in game_catalog():
            hay = (str(item.get("title") or "") + " " + str(item.get("system_label") or "")).lower()
            if needle and needle not in hay:
                continue
            rows.append(item)
            seen.add(item["id"])
        for item in homebrew_search(query=cleaned, pages=3):
            if item["id"] in seen:
                continue
            rows.append(item)
            seen.add(item["id"])
            if len(rows) >= MAX_ITEMS:
                break
        return rows[:MAX_ITEMS]
    return rows


def game_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    suffixes: set[str] = set()
    for spec in SYSTEMS.values():
        suffixes.update(spec["ext"])
    for root in library_roots():
        stack = [(root, 0)]
        while stack and len(rows) < MAX_ITEMS:
            folder, depth = stack.pop()
            if depth > MAX_SCAN_DEPTH:
                continue
            try:
                children = sorted(folder.iterdir(), key=lambda item: item.name.lower())
            except OSError:
                continue
            for child in children:
                if child.is_symlink() or child.name.startswith("."):
                    continue
                if child.is_dir():
                    if not _denied_path(child):
                        stack.append((child, depth + 1))
                    continue
                system = system_for(child)
                if not system:
                    continue
                if child.suffix.lower() not in suffixes:
                    continue
                try:
                    source = str(confined(child))
                except ValueError:
                    continue
                if source in seen:
                    continue
                seen.add(source)
                rows.append(
                    {
                        "id": item_id("GAME", source),
                        "kind": "GAME",
                        "title": _title_of(child),
                        "source": source,
                        "media": "rom",
                        "system": system,
                        "system_label": SYSTEMS[system]["label"],
                    }
                )
    return rows


def _homebrew_file(entry: dict[str, Any]) -> dict[str, Any] | None:
    files = entry.get("files")
    if not isinstance(files, list):
        return None
    chosen: dict[str, Any] | None = None
    for row in files:
        if not isinstance(row, dict) or not row.get("playable"):
            continue
        if row.get("default"):
            return row
        if chosen is None:
            chosen = row
    return chosen


def homebrew_entry_item(entry: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    kind = str(entry.get("typetag") or "").strip().lower()
    if kind in HOMEBREW_DENIED_TYPES:
        return None
    if kind not in ("game", "homebrew", "demo"):
        return None
    platform = str(entry.get("platform") or "").strip().upper()
    system = HOMEBREW_PLATFORM.get(platform)
    if not system:
        return None
    slug = str(entry.get("slug") or "").strip()
    title = str(entry.get("title") or slug).strip()
    if not slug or not title:
        return None
    playable = _homebrew_file(entry)
    if playable is None:
        return None
    filename = str(playable.get("filename") or "").strip().lstrip("/")
    if not filename or ".." in Path(filename).parts:
        return None
    leaf = Path(filename).name
    spec = SYSTEMS[system]
    if Path(leaf).suffix.lower() not in spec["ext"]:
        return None
    repo = str(entry.get("baserepo") or HOMEBREW_REPO.get(system) or "").strip().rstrip("/")
    if not repo.startswith("https://github.com/"):
        return None
    gh = repo[len("https://github.com/") :].strip("/")
    parts = [urllib.parse.quote(slug, safe="-_.")] + [
        urllib.parse.quote(part, safe="-_.") for part in Path(filename).parts
    ]
    source = "https://raw.githubusercontent.com/" + gh + "/master/entries/" + "/".join(parts)
    return {
        "id": item_id("GAME", "homebrew:" + slug),
        "kind": "GAME",
        "title": title[:MAX_TITLE],
        "source": source,
        "media": "homebrew",
        "system": system,
        "system_label": spec["label"],
        "slug": slug,
        "filename": leaf,
        "player": "mednafen",
    }


def homebrew_search(
    query: str = "",
    platform: str = "",
    pages: int = HOMEBREW_PAGES,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    params_base: dict[str, str] = {}
    cleaned = str(query or "").strip()
    if cleaned:
        params_base["q"] = cleaned[:80]
    else:
        params_base["typetag"] = "game"
    if platform:
        params_base["platform"] = str(platform).strip().upper()[:8]
    for page in range(1, max(1, int(pages)) + 1):
        params = dict(params_base)
        params["page"] = str(page)
        url = HOMEBREW_API + "/search?" + urllib.parse.urlencode(params)
        cache_name = "hb-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".json"
        try:
            payload = json.loads(_cached_bytes(cache_name, url).decode("utf-8"))
        except (
            OSError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeError,
        ):
            break
        if not isinstance(payload, dict):
            break
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            break
        for entry in entries:
            item = homebrew_entry_item(entry)
            if item is None or item["id"] in seen:
                continue
            seen.add(item["id"])
            rows.append(item)
            if len(rows) >= MAX_ITEMS:
                return rows
        try:
            total = int(payload.get("page_total") or page)
        except (TypeError, ValueError):
            total = page
        if page >= total:
            break
    return rows


def homebrew_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for platform in HOMEBREW_PLATFORM:
        for item in homebrew_search(platform=platform, pages=HOMEBREW_PAGES):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            rows.append(item)
            if len(rows) >= MAX_ITEMS:
                return rows
    return rows


def materialize_homebrew(item: dict[str, Any]) -> dict[str, Any]:
    system = str(item.get("system") or "")
    spec = SYSTEMS.get(system)
    if spec is None:
        raise ValueError("MEDIA_SYSTEM_UNKNOWN")
    leaf = Path(str(item.get("filename") or "")).name
    if not leaf or Path(leaf).suffix.lower() not in spec["ext"]:
        raise ValueError("MEDIA_HOMEBREW_FILE")
    root = ensure_rom_library()
    dest = confined(root / system / leaf, roots=[root])
    if dest.is_file() and dest.stat().st_size > 16:
        out = dict(item)
        out["source"] = str(dest)
        out["media"] = "rom"
        return out
    url = stream_allowed(str(item.get("source") or ""))
    raw = _http_get(url, timeout=30.0)
    if len(raw) < 16 or len(raw) > MAX_ROM_BYTES:
        raise RuntimeError("MEDIA_HOMEBREW_SIZE")
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    dest.write_bytes(raw)
    dest.chmod(0o600)
    out = dict(item)
    out["source"] = str(dest)
    out["media"] = "rom"
    return out


def catalog_for(mode: str) -> list[dict[str, Any]]:
    kind = str(mode or DEFAULT_MODE).strip().upper()
    if kind == "MUSIC":
        return music_catalog()
    if kind == "RADIO":
        return radio_catalog()
    if kind == "TV":
        return video_catalog()
    if kind == "GAME":
        ensure_rom_library()
        rows = game_catalog()
        seen = {item["id"] for item in rows}
        for item in homebrew_catalog():
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            rows.append(item)
            if len(rows) >= MAX_ITEMS:
                break
        return rows[:MAX_ITEMS]
    if kind == "FETCH":
        return fetch_catalog()
    return []


_PREFS_CACHE: tuple[str, float, dict[str, Any]] | None = None


def load_prefs() -> dict[str, Any]:
    global _PREFS_CACHE
    path = ensure_state_dir() / "prefs.json"
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    hit = _PREFS_CACHE
    if hit is not None and hit[0] == key and hit[1] == mtime:
        return dict(hit[2])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    mode = str(payload.get("mode") or DEFAULT_MODE).upper()
    if mode not in MODES:
        mode = DEFAULT_MODE
    try:
        volume = int(payload.get("volume", VOLUME_DEFAULT))
    except (TypeError, ValueError):
        volume = VOLUME_DEFAULT
    volume = max(0, min(100, volume))
    current = {
        "mode": mode,
        "volume": volume,
        "last_id": str(payload.get("last_id") or ""),
    }
    _PREFS_CACHE = (key, mtime, dict(current))
    return current


def save_prefs(prefs: dict[str, Any]) -> dict[str, Any]:
    global _PREFS_CACHE
    current = load_prefs()
    current.update(prefs)
    mode = str(current.get("mode") or DEFAULT_MODE).upper()
    if mode not in MODES:
        mode = DEFAULT_MODE
    try:
        volume = int(current.get("volume", VOLUME_DEFAULT))
    except (TypeError, ValueError):
        volume = VOLUME_DEFAULT
    current["mode"] = mode
    current["volume"] = max(0, min(100, volume))
    current["last_id"] = str(current.get("last_id") or "")[:80]
    path = ensure_state_dir() / "prefs.json"
    path.write_text(json.dumps(current) + "\n", encoding="utf-8")
    path.chmod(0o600)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    _PREFS_CACHE = (str(path), mtime, dict(current))
    return current


def player_bin() -> str:
    tools = probe_tools()
    vlc = tools["vlc"]["path"]
    if vlc:
        return vlc
    return tools["ffplay"]["path"]


def format_clock(seconds: float | int | None) -> str:
    try:
        value = max(0, int(seconds or 0))
    except (TypeError, ValueError):
        return "00:00"
    minutes, rest = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{rest:02d}"
    return f"{minutes:02d}:{rest:02d}"


SPECTRUM_BARS = 120
EQ_PRESETS = (
    "Flat",
    "Rock",
    "Pop",
    "Jazz",
    "Classical",
    "Bass Boost",
    "Treble Boost",
    "Vocal",
    "Electronic",
    "Acoustic",
)


def normalize_spectrum(raw: Any, count: int = SPECTRUM_BARS) -> list[float]:
    count = max(1, int(count))
    vals: list[float] = []
    if isinstance(raw, list):
        for item in raw:
            try:
                vals.append(max(0.0, float(item)))
            except (TypeError, ValueError):
                continue
    if not vals:
        return [0.0] * count
    peak = max(vals)
    if peak > 1.5:
        vals = [min(1.0, v / peak) for v in vals]
    else:
        vals = [min(1.0, v) for v in vals]
    if len(vals) == count:
        return vals
    last = len(vals) - 1
    out: list[float] = []
    for i in range(count):
        pos = 0.0 if last == 0 else (i * last / (count - 1))
        lo = int(pos)
        hi = min(last, lo + 1)
        frac = pos - lo
        out.append(vals[lo] * (1.0 - frac) + vals[hi] * frac)
    return out


def normalize_eq(raw: Any, count: int = 10) -> list[float]:
    vals: list[float] = []
    if isinstance(raw, list):
        for item in raw[: max(1, int(count))]:
            try:
                vals.append(max(-12.0, min(12.0, float(item))))
            except (TypeError, ValueError):
                vals.append(0.0)
    while len(vals) < count:
        vals.append(0.0)
    return vals[:count]
