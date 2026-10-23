from __future__ import annotations

from typing import Any

from backend import marketplace_contract


def _ok() -> dict[str, Any]:
    payload = marketplace_contract.status_payload()
    payload["error"] = ""
    return payload


def _fail(exc: Exception) -> dict[str, Any]:
    payload = marketplace_contract.status_payload()
    payload["error"] = str(exc)
    return payload


def status_payload() -> dict[str, Any]:
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
