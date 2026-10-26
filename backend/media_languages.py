"""One language policy for MEDIA labels, catalogue filters and provider imports."""
from __future__ import annotations

from functools import lru_cache
import re

from PySide6.QtCore import QLocale

DEFAULT_LANGUAGES = ("sv", "en")
PREFERENCE_KEY = "media_discovery_languages"
_NAMES = {
    "sv": "Svenska", "en": "Engelska", "no": "Norska", "nb": "Norska (bokmål)",
    "nn": "Norska (nynorska)", "da": "Danska", "fi": "Finska", "is": "Isländska",
    "de": "Tyska", "fr": "Franska", "es": "Spanska", "it": "Italienska",
    "pt": "Portugisiska", "nl": "Nederländska", "pl": "Polska", "ru": "Ryska",
    "uk": "Ukrainska", "ar": "Arabiska", "zh": "Kinesiska", "ja": "Japanska",
    "ko": "Koreanska", "hi": "Hindi", "tr": "Turkiska", "el": "Grekiska",
    "he": "Hebreiska", "fa": "Persiska", "cs": "Tjeckiska", "sk": "Slovakiska",
    "hu": "Ungerska", "ro": "Rumänska", "bg": "Bulgariska", "sr": "Serbiska",
    "hr": "Kroatiska", "bs": "Bosniska", "sl": "Slovenska", "et": "Estniska",
    "lv": "Lettiska", "lt": "Litauiska", "vi": "Vietnamesiska", "th": "Thailändska",
    "id": "Indonesiska", "ms": "Malajiska", "tl": "Tagalog", "fil": "Filippinska",
    "ta": "Tamil", "te": "Telugu", "bn": "Bengaliska", "ur": "Urdu",
    "sw": "Swahili", "af": "Afrikaans", "ca": "Katalanska", "eu": "Baskiska",
    "cy": "Walesiska", "ga": "Iriska", "sq": "Albanska", "hy": "Armeniska",
    "ka": "Georgiska", "mk": "Makedonska", "mt": "Maltesiska", "eo": "Esperanto",
}


@lru_cache(maxsize=1)
def _aliases():
    result = {name.casefold(): code for code, name in _NAMES.items()}
    for language in QLocale.Language:
        code = QLocale.languageToCode(language)
        if code:
            result[QLocale.languageToString(language).casefold()] = code
    result.update(norsk="no", svensk="sv", engelska="en", svenska="sv")
    return result


@lru_cache(maxsize=2048)
def _code(value):
    value = value.strip().casefold().replace("_", "-")
    if value in _aliases():
        return _aliases()[value]
    base = value.split("-", 1)[0]
    if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9-]+)?", value):
        return QLocale.languageToCode(QLocale.codeToLanguage(base))
    return ""


def codes(value):
    if not isinstance(value, (list, tuple, set)):
        return _string_codes(str(value or ""))
    return tuple(dict.fromkeys(code for part in list(value)[:64] for code in codes(part)))


@lru_cache(maxsize=4096)
def _string_codes(value):
    parts = re.split(r"[;,/|]", value)
    return tuple(dict.fromkeys(code for part in list(parts)[:64] for code in [_code(str(part))] if code))


def selection(value=DEFAULT_LANGUAGES):
    """None means an explicit unrestricted selection; empty means no languages."""
    if value is None or value == "all":
        return None
    return codes(value)


def matches(value, selected=DEFAULT_LANGUAGES):
    selected = selection(selected)
    return selected is None or bool(set(codes(value)).intersection(selected))


def sql_match(value, selected):
    return int(not codes(value)) if selected == "unknown" else int(matches(value, selected))


def label(value):
    known = codes(value)
    return " / ".join(_NAMES.get(code) or QLocale.languageToString(QLocale.codeToLanguage(code))
                      for code in known) or "Okänt språk"


def options(values=(), *, discovery=False):
    available = set(DEFAULT_LANGUAGES)
    for value in values:
        available.update(codes(value))
    if discovery:
        available.update(_NAMES)
    ordered = list(DEFAULT_LANGUAGES) + sorted(available - set(DEFAULT_LANGUAGES), key=lambda code: label(code).casefold())
    rows = [{"value": code, "label": label(code)} for code in ordered]
    return rows if discovery else [
        {"value": "all", "label": "Alla språk"},
        {"value": "sv; en", "label": "Svenska och engelska"},
    ] + rows + [{"value": "unknown", "label": "Okänt språk"}]


def archive_clause(selected=DEFAULT_LANGUAGES, *, include_unknown=True):
    chosen = selection(selected)
    if chosen is None:
        return ""
    if not chosen:
        raise ValueError("Välj minst ett språk för sökningen.")
    terms = []
    for code in chosen:
        language = QLocale.codeToLanguage(code)
        variants = {code, QLocale.languageToString(language),
                    QLocale.languageToCode(language, QLocale.LanguageCodeType.ISO639Part2B),
                    QLocale.languageToCode(language, QLocale.LanguageCodeType.ISO639Part2T)}
        terms.extend('language:"' + value + '"' for value in sorted(variants) if value)
    if include_unknown:
        terms.extend(["(*:* AND -language:[* TO *])", 'language:"und"', 'language:"unknown"', 'language:"undetermined"'])
    return "(" + " OR ".join(terms) + ")"


@lru_cache(maxsize=1)
def _audio_marker():
    names = {**_aliases(), **{code: code for code in _NAMES}}
    long_names = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True) if len(name) >= 3)
    all_names = long_names + "|" + "|".join(re.escape(code) for code in _NAMES if len(code) < 3)
    return names, re.compile(
        r"(?:\b(?:language|audio|språk|tal|dubbed in|på)\s*[:=–-]?\s*(" + long_names + r")\b"
        r"|\b(" + long_names + r")\s+(?:audio|dub(?:bed)?|tal)\b"
        r"|[\[(]\s*(" + all_names + r")\s*[\])])", re.IGNORECASE)


@lru_cache(maxsize=8192)
def _infer_text(text):
    text = _subtitle_marker().sub(" ", text)
    names, marker = _audio_marker()
    return tuple(dict.fromkeys(names[next(value for value in match.groups() if value).casefold()]
                               for match in marker.finditer(text)))


@lru_cache(maxsize=1)
def _subtitle_marker():
    names, _ = _audio_marker()
    alternatives = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    subtitles = r"(?:subtitles?|subs|undertexter|textad)"
    return re.compile(r"\b(?:" + alternatives + r")\s+" + subtitles + r"\b|\b" + subtitles
                      + r"(?:\s+(?:in|på))?\s+(?:" + alternatives + r")\b", re.IGNORECASE)


def classify(row, *metadata):
    """Recover missing audio language from evidence, never from title spelling.

    Subtitle labels, country and an English-looking title do not establish
    spoken language. Unresolved candidates remain available for later review.
    """
    result = dict(row)
    if codes(row.get("language")):
        result["language"] = "; ".join(codes(row["language"]))
        result.setdefault("language_evidence", "provider")
        return result
    for entry in metadata:
        if not isinstance(entry, dict):
            continue
        for field in ("audio_language", "spoken_language", "language", "languages"):
            known = codes(entry.get(field))
            if known:
                result.update(language="; ".join(known), language_evidence="source_metadata")
                return result
    # Explicit audio/dub markers can occur in titles or descriptions even when
    # the provider's structured language field is empty.
    for entry in (row, *metadata):
        if not isinstance(entry, dict):
            continue
        for field in ("title", "archive_title", "description", "subject", "name"):
            value = entry.get(field) or ""
            text = " ".join(map(str, value)) if isinstance(value, list) else str(value)
            # A subtitle claim must never be mistaken for the audio language.
            found = _infer_text(text[:8000])
            if found:
                result.update(language="; ".join(dict.fromkeys(found)), language_evidence="explicit_audio_label")
                return result
    if row.get("language") and not result.get("language_raw"):
        result["language_raw"] = str(row["language"])[:200]
    result.update(language="", language_evidence="pending")
    return result


def identify_remote(row, *, cancel=None):
    """Bounded worker-only enrichment of unresolved provider or HLS metadata."""
    result = classify(row)
    if result.get("language") or cancel and cancel.is_set():
        return result
    from backend import media_library as library
    from urllib.parse import quote, urlsplit
    identifier = str(row.get("archive_id") or "")
    if library._IDENTIFIER.fullmatch(identifier):
        payload = library._cached_json("https://archive.org/metadata/" + quote(identifier, safe=""), library._valid_metadata)
        if cancel and cancel.is_set():
            return result
        result = classify(row, payload.get("metadata") or {})
        if not result.get("language"):
            # File metadata can identify a dub absent from collection metadata.
            entries = [entry for entry in payload.get("files", [])[:library.MAX_FILES]
                       if isinstance(entry, dict) and library._file_allowed(entry)]
            inferred = [classify({}, entry) for entry in entries]
            known = tuple(dict.fromkeys(code for entry in inferred for code in codes(entry.get("language"))))
            if known:
                result.update(language="; ".join(known), language_evidence="audio_file_metadata")
    elif urlsplit(str(row.get("source") or "")).path.casefold().endswith(".m3u8"):
        from backend import media_availability as availability
        from backend.media_request import public_headers
        budget = availability._Budget(cancel=cancel, max_seconds=4, max_bytes=32768, headers=public_headers(row))
        try:
            response = budget.fetch(row["source"], count=32768, manifest=True, ranged=False)
            found = []
            for line in response["data"].decode("utf-8-sig", errors="replace").splitlines():
                if line.startswith("#EXT-X-MEDIA:"):
                    attrs = availability._attributes(line.split(":", 1)[1])
                    if attrs.get("TYPE") == "AUDIO":
                        found.extend(codes(attrs.get("LANGUAGE")))
            if found:
                result.update(language="; ".join(dict.fromkeys(found)), language_evidence="hls_audio_metadata")
        except (availability._Unknown, availability._Failed, OSError, ValueError):
            pass
    return result
