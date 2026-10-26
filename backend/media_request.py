"""Public playback hints published by a source catalogue, never credentials."""
from __future__ import annotations

from urllib.parse import urlsplit

DEFAULT_USER_AGENT = "GG-AI-Desktop-Media/1.0"


def public_headers(row=None):
    row = row if isinstance(row, dict) else {}
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    user_agent = str(row.get("user_agent") or "")
    referrer = str(row.get("referrer") or "")
    if user_agent:
        if len(user_agent) > 512 or any(ord(char) < 32 or ord(char) > 126 for char in user_agent):
            raise ValueError("MEDIA_PUBLIC_HEADERS_INVALID")
        headers["User-Agent"] = user_agent
    if referrer:
        parsed = urlsplit(referrer)
        if (len(referrer) > 2048 or any(ord(char) < 33 or ord(char) > 126 for char in referrer)
                or parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password):
            raise ValueError("MEDIA_PUBLIC_HEADERS_INVALID")
        headers["Referer"] = referrer
    return headers


def requires_headers(row):
    return bool(row and (row.get("referrer") or row.get("user_agent")))
