"""Cancellable checks of saved audio, downloads and game source metadata."""
from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

from backend import media_languages as languages, media_quick_availability as quick

KINDS = {"music": "MUSIC", "radio": "RADIO", "games": "GAME", "downloads": "FETCH"}


def _where(target, selected_languages, cycle_started):
    clause = ("i.kind=? AND i.checked_at<? AND COALESCE(json_extract(i.payload,'$.source'),'')<>'' "
              "AND NOT EXISTS (SELECT 1 FROM media_hidden_items h WHERE h.item_id=i.id) "
              "AND NOT EXISTS (SELECT 1 FROM media_hidden_groups h WHERE h.group_key=i.group_key) "
              "AND NOT EXISTS (SELECT 1 FROM media_hidden_sources h WHERE h.source_key=i.source_key)")
    args = [KINDS[target], cycle_started]
    chosen = languages.selection(selected_languages)
    if chosen is not None:
        clause += " AND (gg_language_match(i.language,?)=1 OR gg_language_match(i.language,'unknown')=1)"
        args.append("; ".join(chosen))
    return clause, args


def _game_check(row, cancel):
    from backend import media_availability as transport
    from backend.media_request import public_headers
    source = str(row.get("source") or "")
    report = dict(status="unknown", scope="http_resource", evidence={"decoded": False})
    try:
        if urlsplit(source).scheme == "file" or "://" not in source:
            path = quick._local_path(source)
            report["scope"] = "local_file"
            if not path.is_file():
                raise transport._Failed("local_not_found")
            with path.open("rb") as stream:
                if not stream.read(1):
                    raise transport._Failed("empty_media")
            report["evidence"].update(readable=True, local_file=True)
        else:
            budget = transport._Budget(cancel=cancel, max_seconds=4, max_bytes=1024, headers=public_headers(row))
            response = budget.fetch(source, count=768)
            if not response["data"] or response["content_type"].startswith("text/"):
                raise transport._Unknown("unrecognized_media")
            report["evidence"]["reachable"] = True
        report["status"] = "verified"
    except transport._Failed as error:
        report.update(status="failed", error=str(error))
    except (transport._Unknown, OSError, ValueError):
        report["error"] = "source_unconfirmed"
    now = time.time()
    return dict(report, checked_at=now, expires_at=now + 86400 if report["status"] == "verified" else 0)


def check_saved(index, selected_types, *, selected_languages, cycle_started, cancel, max_jobs=120):
    targets = tuple(target for target in selected_types if target in KINDS)
    result = dict(checked=0, available=0, failed=0, unknown=0, pending=False)
    while targets and result["checked"] < max_jobs and not cancel.is_set():
        progressed = False
        for target in targets:
            if cancel.is_set() or result["checked"] >= max_jobs:
                break
            where, args = _where(target, selected_languages, cycle_started)
            with index.connection() as db:
                stored = db.execute("SELECT i.payload FROM items i WHERE " + where + " ORDER BY i.checked_at,i.id LIMIT 1", args).fetchone()
            if not stored:
                continue
            row = json.loads(stored[0])
            if not languages.codes(row.get("language")):
                try:
                    identified = languages.identify_remote(row, cancel=cancel)
                    if identified.get("language"):
                        row = index.correct_metadata(identified, expected=row)
                        if not languages.matches(row["language"], selected_languages):
                            progressed = True
                            continue
                except (OSError, ValueError, RuntimeError, TimeoutError):
                    pass
            report = _game_check(row, cancel) if target == "games" else quick.quick_check(row, cancel=cancel)
            if cancel.is_set():
                break
            index.record(row["id"], report, source=row["source"], identity=index.identity_key(row))
            result["checked"] += 1
            result[{"verified": "available", "failed": "failed"}.get(report["status"], "unknown")] += 1
            progressed = True
        if not progressed:
            break
    for target in targets:
        where, args = _where(target, selected_languages, cycle_started)
        with index.connection() as db:
            if db.execute("SELECT 1 FROM items i WHERE " + where + " LIMIT 1", args).fetchone():
                result["pending"] = True
                break
    return result
