"""Shared media-type choices and bounded, explicitly requested source searches."""
from __future__ import annotations

import re

from backend import media_contract as contract, media_library as library, media_languages as languages

TYPE_LABELS = {"live": "Kanaler", "movies": "Filmer", "series": "Serier", "music": "Musik",
               "radio": "Radio", "downloads": "Hämtat", "games": "Spel"}
DEFAULT_TYPES = tuple(TYPE_LABELS)
PREFERENCE_KEY = "media_discovery_types"


def types(value):
    if value == "all":
        return DEFAULT_TYPES
    parts = value if isinstance(value, (list, tuple, set)) else re.split(r"[;,]", str(value or ""))
    chosen = {str(part).strip() for part in parts}
    if not chosen or chosen - set(TYPE_LABELS):
        raise ValueError("Välj minst en giltig mediatyp.")
    return tuple(key for key in TYPE_LABELS if key in chosen)


def belongs(row, target):
    kind = str(row.get("kind") or "").upper()
    content = str(row.get("content_type") or "")
    if target == "downloads":
        return kind == "FETCH"
    if target in ("music", "radio", "games"):
        return kind == {"music": "MUSIC", "radio": "RADIO", "games": "GAME"}[target]
    return kind == "TV" and content in {"live": ("live",), "movies": ("movie",), "series": ("series", "episode")}[target]


def _admit(index, rows, target, selected_languages, cancel=None):
    accepted = []
    for raw in rows:
        if cancel and cancel.is_set():
            break
        row = library.annotate(raw)
        if belongs(row, target) and (not row.get("language") or languages.matches(row["language"], selected_languages)):
            accepted.append(row)
    if cancel and cancel.is_set():
        return 0
    if not accepted:
        return 0
    with index.connection() as db:
        before = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    index.ingest_discovered(accepted)
    with index.connection() as db:
        return max(0, db.execute("SELECT COUNT(*) FROM items").fetchone()[0] - before)


def collect(index, target, *, query="", selected_languages=languages.DEFAULT_LANGUAGES, cancel=None):
    """One provider slice; local types stay local and games use metadata only."""
    if cancel and cancel.is_set():
        return {"new_candidates": 0, "cancelled": True}
    if target == "live":
        from backend.media_sources import refresh
        return refresh(index, cancel=cancel, selected_languages=selected_languages)
    if target in ("movies", "series"):
        from backend.media_discovery import discover
        return discover(index, target, cancel=cancel, max_pages=1, selected_languages=selected_languages)
    if target == "music":
        rows = contract.music_catalog(cancel=cancel)
    elif target == "radio":
        # Presets and saved stations are local; only this explicit slice asks
        # the public directory for up to 120 additional station descriptors.
        rows = contract.radio_catalog(refresh=False)
        if not cancel or not cancel.is_set():
            rows += contract.radio_browser_stations(query=query, country="", limit=120)
    elif target == "games":
        rows = contract.game_catalog()
        if not cancel or not cancel.is_set():
            rows += contract.homebrew_search(query=query, pages=1)
    elif target == "downloads":
        rows = contract.fetch_catalog()
    else:
        raise ValueError("Okänd mediatyp.")
    if query:
        words = query.casefold().split()
        rows = [row for row in rows if all(word in " ".join(str(row.get(key) or "") for key in
                ("title", "artist", "album", "system_label")).casefold() for word in words)]
    return {"new_candidates": _admit(index, rows, target, selected_languages, cancel)}


def search(index, query, *, selected_types=DEFAULT_TYPES, selected_languages=languages.DEFAULT_LANGUAGES, cancel=None):
    chosen = types(selected_types)
    errors = []
    video = tuple(target for target in chosen if target in ("movies", "series"))
    if video and not (cancel and cancel.is_set()):
        try:
            options = {} if set(video) == {"movies", "series"} else {"selected_media_types": video}
            rows = library.search_archive(query, limit=200, selected_languages=selected_languages, **options)
            for target in video:
                _admit(index, rows, target, selected_languages, cancel)
        except (OSError, RuntimeError, ValueError, TimeoutError):
            errors.append("Arkivsökningen svarar inte.")
    for target in chosen:
        if cancel and cancel.is_set():
            break
        if target in video:
            continue
        try:
            result = collect(index, target, query=query, selected_languages=selected_languages, cancel=cancel)
            if result.get("error"):
                errors.append(TYPE_LABELS[target] + ": källsökningen kunde inte slutföras.")
        except (OSError, RuntimeError, ValueError, TimeoutError):
            errors.append(TYPE_LABELS[target] + ": källsökningen kunde inte slutföras.")
    return " ".join(errors) + (" Sparade träffar visas fortfarande." if errors else "")
