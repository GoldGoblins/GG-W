"""Explicit source diagnostics and bounded substitution within the same title."""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from backend import media_contract as contract, media_library as library, media_quick_availability as quick
from backend import media_existing_checks as existing

_REASONS = {
    "http_not_found": "Länken har tagits bort eller flyttats (404/410).",
    "access_denied": "Leverantören nekar åtkomst (401/403). Inloggning eller regionbegränsning kan vara orsaken.",
    "timeout": "Källan svarade inte inom tidsgränsen.",
    "network_error": "Källan kunde inte nås. Det kan vara ett tillfälligt nätverksfel.",
    "provider_error": "Leverantörens server rapporterar ett fel.",
    "rate_limited": "Leverantören begränsar antalet förfrågningar. Försök senare.",
    "encrypted_stream": "Strömmen kräver en krypteringsnyckel som kontrollen inte kunde använda.",
    "unrecognized_media": "Svaret kunde inte identifieras som spelbar media.",
    "local_not_found": "Filen finns inte längre på den sparade platsen.",
    "empty_playlist": "Spellistan innehåller inga tillgängliga segment.",
    "invalid_source": "Den sparade länken är ogiltig.",
    "source_changed": "Källan ändrades under kontrollen. Kör felsökningen igen för den aktuella länken.",
    "unsupported_media_file": "Filformatet stöds inte av mediaspelaren.",
    "unsupported_game_file": "Spelfilens format stöds inte för det angivna systemet.",
}


def _check_source(row, *, cancel, deadline):
    if row.get("kind") == "GAME":
        source = str(row.get("source") or "")
        parsed = urlsplit(source)
        path = quick._local_path(source) if parsed.scheme == "file" or "://" not in source else Path(unquote(parsed.path))
        system = str(row.get("system") or contract.system_for(path))
        if path.suffix.lower() not in contract.SYSTEMS.get(system, {}).get("ext", ()):
            return dict(status="failed", error="unsupported_game_file")
        # Identity/confinement is checked by the caller before any resource read.
        # ROMs need the same resource check as bulk source control, not an
        # audio/video signature or decoder.
        return existing._game_check(row, cancel)
    return quick.quick_check(row, cancel=cancel, max_seconds=max(.4, min(4, deadline - time.monotonic())))


def _diagnose_series(index, original, *, cancel, deadline):
    result = dict(running=False, title=original["title"], message="", status="unknown", alternatives_checked=0,
                  replacement_id="", action_label="Spela kontrollerat avsnitt")
    collection = original.get("collection_key") or index.series_key(original)
    with index.connection() as db:
        records = db.execute("SELECT i.payload FROM items i WHERE i.parent_key=? AND i.type='episode' "
                             "ORDER BY i.verified_until DESC,i.season,i.episode LIMIT 3", (collection,)).fetchall()
    import json
    episodes = [json.loads(record[0]) for record in records]
    if not episodes:
        descriptors = index.collection_descriptors(collection, limit=1)
        if descriptors:
            descriptor = descriptors[0]
            try:
                children = library.expand_item(descriptor)
                if cancel and cancel.is_set():
                    return dict(result, message="Kontrollen avbröts.")
                children = [dict(child, collection_key=collection, series_title=original.get("series_title") or original["title"])
                            for child in children if child.get("content_type") == "episode"]
                episodes = index.ingest_discovered(children, expected={descriptor["id"]: descriptor})[:3]
            except (OSError, ValueError, RuntimeError, TimeoutError):
                return dict(result, message="Seriens källmetadata kunde inte nås. Källan kan vara tillfälligt otillgänglig eller ha tagits bort.")
    for row in episodes:
        if time.monotonic() >= deadline or cancel and cancel.is_set():
            break
        if quick.prepare_quick_identity(row)[1].get("status") != "consistent":
            continue
        report = quick.quick_check(row, cancel=cancel, max_seconds=max(.4, min(4, deadline - time.monotonic())))
        index.record(row["id"], report, source=row["source"], identity=index.identity_key(row))
        current = index.get(row["id"])
        if not current or current.get("source") != row.get("source") or index.identity_key(current) != index.identity_key(row):
            continue
        result["alternatives_checked"] += 1
        if report["status"] == "verified":
            result.update(status="verified", replacement_id=row["id"],
                          message="Serien har ett kontrollerat tillgängligt avsnitt. Kontrollen gäller detta avsnitt; övriga avsnitt kontrolleras separat.")
            return result
    return dict(result, message="Inget tillgängligt avsnitt kunde bekräftas bland seriens kontrollerade källor. Öppna serien för att felsöka ett specifikt avsnitt.")


def diagnose(index, identifier, *, cancel=None, max_seconds=32):
    original = index.get(str(identifier))
    if original is None:
        raise ValueError("MEDIA_ITEM_UNKNOWN")
    deadline = time.monotonic() + min(32, max_seconds)
    if original.get("content_type") == "series":
        return _diagnose_series(index, original, cancel=cancel, deadline=deadline)
    result = dict(running=False, title=original["title"], message="", alternatives_checked=0,
                  replacement_id="", replacement_title="", status="unknown")
    sources = [original] + [row for row in index.group_sources(identifier) if row["id"] != original["id"]]
    seen = set()
    for position, row in enumerate(sources[:4]):
        if time.monotonic() >= deadline or cancel and cancel.is_set():
            break
        if row.get("source") in seen:
            continue
        seen.add(row.get("source"))
        try:
            if row.get("archive_id") and not row.get("archive_file"):
                resolved = library.resolve_item(row)
                row = index.ingest_discovered([resolved], expected={row["id"]: row})[0]
            identity = quick.prepare_quick_identity(row)[1]
            if identity.get("status") != "consistent":
                report = dict(status="unknown", error="identity_unconfirmed")
            else:
                report = _check_source(row, cancel=cancel, deadline=deadline)
                index.record(row["id"], report, source=row["source"], identity=index.identity_key(row))
                current = index.get(row["id"])
                if not current or current.get("source") != row.get("source") or index.identity_key(current) != index.identity_key(row):
                    report = dict(status="unknown", error="source_changed")
        except (OSError, ValueError, RuntimeError, TimeoutError):
            report = dict(status="unknown", error="network_error")
        if position == 0:
            result["status"] = report.get("status", "unknown")
            result["message"] = (("Spelfilen är tillgänglig. Kontrollen verifierar inte att spelet kan startas i emulatorn."
                if row.get("kind") == "GAME" else "Källan svarar och mediedata är tillgängliga. Om uppspelningen ändå stannar kan felet finnas i formatet eller spelaren.")
                if report.get("status") == "verified" else _REASONS.get(report.get("error"), "Kontrollen kunde inte bekräfta att källan fungerar just nu."))
        else:
            result["alternatives_checked"] += 1
        if report.get("status") == "verified":
            if position > 0:
                result.update(replacement_id=row["id"], replacement_title=row["title"])
                result["message"] += " En tillgänglig ersättningskälla hittades för samma kanal eller titel."
            break
    if not result["message"]:
        result["message"] = "Kontrollen avbröts. Försök igen."
    elif result["status"] != "verified" and not result["replacement_id"]:
        result["message"] += " Ingen tillgänglig ersättningskälla hittades bland de sparade alternativen. Utöka kan söka efter fler kanalkällor."
    return result
