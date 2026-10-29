from __future__ import annotations

from typing import Any

from backend import marketplace_contract
_draft_media = None


def _ok() -> dict[str, Any]:
    payload = marketplace_contract.status_payload()
    payload["error"] = ""
    payload['draft_media'] = _draft_media
    from backend import marketplace_discovery
    payload['public_catalog'] = marketplace_discovery.snapshot()
    return payload


def _fail(exc: Exception) -> dict[str, Any]:
    payload = marketplace_contract.status_payload()
    payload["error"] = str(exc)
    return payload


def status_payload() -> dict[str, Any]:
    return _ok()


def discover(raw: str) -> dict[str, Any]:
    from backend import marketplace_discovery
    try:marketplace_discovery.action(raw);return _ok()
    except ValueError as exc:return _fail(exc)


def import_image(source: str) -> dict[str, Any]:
    global _draft_media
    from backend import marketplace_media
    _draft_media = marketplace_media.import_image(source, marketplace_contract.ensure_state_dir())
    return _ok()


def list_item(raw: str) -> dict[str, Any]:
    try:
        marketplace_contract.list_item(raw)
        return _ok()
    except ValueError as exc:
        return _fail(exc)


def delist_item(listing_id: str) -> dict[str, Any]:
    try:
        marketplace_contract.delist_item(listing_id)
        return _ok()
    except ValueError as exc:
        return _fail(exc)


def paper_buy(listing_id: str) -> dict[str, Any]:
    try:
        marketplace_contract.paper_buy(listing_id)
        return _ok()
    except ValueError as exc:
        return _fail(exc)


def select_listing(listing_id: str) -> dict[str, Any]:
    marketplace_contract.select_listing(listing_id)
    return _ok()


def set_filter(category: str) -> dict[str, Any]:
    marketplace_contract.set_filter(category)
    return _ok()


def list_element(symbol: str) -> dict[str, Any]:
    try:
        marketplace_contract.list_element(symbol)
        return _ok()
    except ValueError as exc:
        return _fail(exc)


def rebirth_item(raw: str) -> dict[str, Any]:
    try:
        marketplace_contract.rebirth_item(raw)
        return _ok()
    except ValueError as exc:
        return _fail(exc)
