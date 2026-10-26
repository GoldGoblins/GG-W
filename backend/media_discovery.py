"""Bounded, resumable metadata import with no fixed catalogue-size target."""
from __future__ import annotations

import hashlib
import html
import re
import threading
from urllib.parse import urlencode

from backend import media_library as library
from backend import media_languages as languages

PAGE_ITEMS = 200
MAX_PAGES_PER_RUN = 64

QUERIES = {
    "movies": 'mediatype:movies AND collection:feature_films AND -access-restricted-item:true',
    "series": ('mediatype:movies AND -access-restricted-item:true AND '
               '(collection:classic_tv OR title:"complete series" OR title:"complete season" OR '
               'title:"full series" OR title:"full season" OR title:"entire series" OR '
               'title:"TV series" OR title:"TV show" OR title:"television series" OR '
               'title:season* OR title:säsong* OR title:S0* OR title:S1* OR title:S2* OR '
               'title:S3* OR title:S4* OR title:S5* OR title:S6* OR title:S7* OR title:S8* OR title:S9* OR '
               '(title:"complete collection" AND (subject:"TV series" OR subject:"television series" '
               'OR subject:"TV show" OR subject:cartoons)))'),
}


def _valid(payload, *, query=None, after=""):
    """Reject stale/wrong-query pages before they can poison the checkpoint."""
    if not library._valid_search(payload):
        return False
    response = payload["response"]
    params = (payload.get("responseHeader") or {}).get("params") or {}
    echoed = params.get("qin") or params.get("query") or params.get("q")
    if query is not None and html.unescape(str(echoed or "")) != query:
        return False
    if response.get("start") != 0 or len(response["docs"]) > PAGE_ITEMS:
        return False
    identifiers = []
    for doc in response["docs"]:
        if not isinstance(doc, dict):
            return False
        identifier = str(doc.get("identifier") or "")
        if not library._IDENTIFIER.fullmatch(identifier) or (after and identifier.casefold() <= after.casefold()):
            return False
        if doc.get("mediatype") not in (None, "movies"):
            return False
        identifiers.append(identifier)
    ordered = [identifier.casefold() for identifier in identifiers]
    return len(identifiers) == len(set(identifiers)) and ordered == sorted(ordered)


_NOT_SERIES = re.compile(r"(?i)\b(?:commercials?|continuity|bumpers?|"
                         r"promos?|trailers?|gameplay|walkthrough|playthrough|vtuber|twitch|podcasts?|livestream)\b")
_RECORDING_FORMAT = re.compile(r"(?i)\b(?:vhs|woc|tapes?|recordings?)\b")
_NAMED_SERIES_EVIDENCE = re.compile(r"(?i)\b(?:(?:complete|full|entire)\s+(?:series|seasons?)|"
                                    r"(?:TV|television)[ -](?:series|show))\b")
_SEASON_SUFFIX = re.compile(r"(?i)\s*[\[( -]*(?:\b(?:the\s+)?(?:complete|full|entire)\s+(?:series|season|collection)|"
                            r"\b(?:TV|television)[ -](?:series|show)\b|\b(?:seasons?|säsong(?:er)?)\s*\d+|"
                            r"\bS\d{1,2}(?:E\d{1,3})?\b)")
_SERIES_EVIDENCE = re.compile(r"(?i)\b(?:(?:complete|full|entire)\s+(?:series|seasons?)|"
                              r"(?:TV|television)[ -](?:series|show)|(?:seasons?|säsong(?:er)?)\s*\d+|"
                              r"S\d{1,2}(?:E\d{1,3})?\b)")
_TV_SUBJECT = re.compile(r"(?i)\b(?:(?:TV|television)[ -](?:series|show)|episodes?|seasons?|säsong(?:er)?|cartoons?)\b")
_SERIES_QUERY_WORDS = re.compile(r"(?i)\b(?:seasons?\w*|säsong\w*|series|collection|s\d+\w*)\b")
_QUALITY = re.compile(r"(?i)\s*[\[( -]*(?:\b(?:\d{3,4}p|hd|hq|ipod|remastered|restored|"
                      r"colori[sz]ed|dvd[ ._-]?rip|blu[ ._-]?ray|full\s+movie)\b)[\]) ._-]*")


def _candidate(metadata, page):
    row = library._descriptor(metadata)
    if row is None:
        return None
    if page == "movies":
        if row["content_type"] != "movie":
            return None
        # Preserve the literal provider title in archive_title; cosmetic
        # encoding suffixes must not create another candidate for one film.
        row["title"] = _QUALITY.sub(" ", row["title"]).strip(" []()-") or row["title"]
    else:
        if _NOT_SERIES.search(row["title"]):
            return None
        explicit = library._text(metadata.get("series_title") or metadata.get("series"), 180)
        subject = library._text(metadata.get("subject"), 2000)
        episode_prefix = library._episode_info(row["title"])[2] if row["content_type"] == "episode" else ""
        named_episode = bool(_RECORDING_FORMAT.sub("", episode_prefix).strip(" []()-"))
        if (_RECORDING_FORMAT.search(row["title"]) and not (explicit or named_episode
                or _NAMED_SERIES_EVIDENCE.search(row["title"]) or _NAMED_SERIES_EVIDENCE.search(subject))):
            return None
        evidence = bool(explicit or _SERIES_EVIDENCE.search(row["title"]) or _TV_SUBJECT.search(subject))
        cartoon_collection = bool(re.search(r"(?i)\bcollection\b", row["title"])
                                  and re.search(r"(?i)\bcartoons?\b", row["title"]))
        # A collection can contain unrelated films. Require actual television
        # evidence rather than turning every batch into a fictitious series.
        if re.search(r"(?i)\bcollection\b", row["title"]) and not (evidence or cartoon_collection):
            return None
        if not evidence and not cartoon_collection:
            # Exact-query validation establishes catalogue membership. A plain
            # title such as Get Smart can match this TV query only through
            # classic_tv; season-like film names still need genuine evidence.
            if _SERIES_QUERY_WORDS.search(row["title"]):
                return None
        if row["content_type"] == "episode":
            # annotate() falls back to archive_title for unnamed episodes;
            # bare s01e03_360 uploads must not become another television show.
            title = explicit or episode_prefix
        else:
            title = explicit or _SEASON_SUFFIX.split(row["title"], maxsplit=1)[0]
        title = title.strip(" []()-")
        if not title or title.casefold() in {"cartoons", "classic cartoons", "classic tv", "tv", "television"}:
            return None
        row["series_title"] = title
        if row["content_type"] != "episode":
            row.update(title=title, content_type="series", media="collection")
    row.update(availability="metadata", playable=False)
    return row


def discover(index, page: str, *, cancel: threading.Event | None = None, max_pages: int = MAX_PAGES_PER_RUN,
             selected_languages=languages.DEFAULT_LANGUAGES):
    """Import the next bounded portion of real provider metadata.

    A television upload can be one episode or a duplicate. Series are grouped
    using actual series/episode metadata; raw uploads never count as new shows.
    The per-run request budget bounds work, not the total catalogue size.
    Further refreshes resume the cursor until the provider is exhausted.
    """
    page = "series" if page == "series" else "movies"
    clause = languages.archive_clause(selected_languages)
    base_query = QUERIES[page] + (" AND " + clause if clause else "")
    signature = hashlib.sha256(base_query.encode()).hexdigest()[:16]
    checkpoint = "discovery_last_" + page + "_" + signature
    last_identifier = index.meta(checkpoint)
    def unique_count():
        with index.connection() as db:
            return db.execute("SELECT COUNT(DISTINCT group_key) FROM items WHERE type=?", ("series" if page == "series" else "movie",)).fetchone()[0]
    imported = unique_count()
    initial = imported
    added = 0
    calls = failures = 0
    error = ""
    exhaustion_key = "discovery_exhausted_" + page + "_" + signature
    exhausted = index.meta(exhaustion_key) == "true"
    # The limit includes retries, rather than silently doubling a64-page run.
    for _ in range(max(0, min(MAX_PAGES_PER_RUN, int(max_pages)))):
        if cancel and cancel.is_set():
            break
        query = base_query
        if last_identifier:
            query = "(" + query + ') AND identifier:{"' + last_identifier + '" TO *}'
        params = {"q": query, "rows": str(PAGE_ITEMS),
                  "fl[]": ["identifier", "title", "year", "date", "language", "description", "subject", "mediatype", "series", "series_title"],
                  "sort[]": "identifier asc", "output": "json"}
        validator = lambda payload: _valid(payload, query=query, after=last_identifier)
        calls += 1
        try:
            payload = library._cached_json("https://archive.org/advancedsearch.php?" + urlencode(params, doseq=True), validator)
            if not validator(payload):
                error = "provider_page_mismatch"
                break
            failures = 0
        except (OSError, RuntimeError, ValueError, TimeoutError):
            failures += 1
            error = "provider_unavailable"
            if failures >= 2:
                break
            continue
        if cancel and cancel.is_set():
            break
        error = ""
        rows = []
        for metadata in payload["response"]["docs"]:
            if not isinstance(metadata, dict):
                continue
            row = _candidate(metadata, page)
            if row is not None and (languages.matches(row.get("language"), selected_languages) or not row.get("language")):
                rows.append(row)
        index.ingest_discovered(rows)
        added += len(rows)
        imported = unique_count()
        identifiers = [str(row.get("identifier") or "") for row in payload["response"]["docs"] if isinstance(row, dict)]
        next_identifier = identifiers[-1] if identifiers else ""
        if next_identifier and library._IDENTIFIER.fullmatch(next_identifier):
            index.meta(checkpoint, next_identifier)
        index.meta("discovery_imported_" + page, imported)
        index.meta("discovery_total_" + page, int(payload["response"].get("numFound") or 0))
        if not payload["response"]["docs"] or next_identifier == last_identifier:
            index.meta(exhaustion_key, "true")
            exhausted = True
            break
        exhausted = len(payload["response"]["docs"]) >= int(payload["response"]["numFound"])
        index.meta(exhaustion_key, "true" if exhausted else "false")
        last_identifier = next_identifier
        if exhausted:
            break
    return {"candidates_imported": imported, "new_candidates": max(0, imported - initial), "staged_uploads": added,
            "catalog_limit": None, "more_sources": not exhausted,
            "provider_calls": calls, "source_exhausted": exhausted, "error": error,
            "cancelled": bool(cancel and cancel.is_set())}
