"""Offline-first MMO and persistence seams for the GAME ENGINE preview."""

from __future__ import annotations

import json
import os
from backend.platform_support import file_locks as fcntl
from backend.platform_files import secure_open
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA = "gg.game-engine.mmo.v1"
PERSISTENCE_SCHEMA = "gg.game-engine.persistence.memory.v1"
STASH_SCHEMA = "gg.game-engine.account-stash.v1"
MAX_STASH_SLOTS = 48
DEFAULT_STASH_PATH = (
    Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    / "goldgoblins" / "gg-ai-desktop" / "game" / "account-stash.json"
)


class LocalAccountStashStore:
    """Atomic, local account stash shared by character runtimes on this computer."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_STASH_PATH
        self.lock_path = self.path.with_suffix(".lock")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema": STASH_SCHEMA, "accounts": {}}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != STASH_SCHEMA:
            raise ValueError("ACCOUNT_STASH_FORMAT_INVALID")
        if not isinstance(value.get("accounts"), dict):
            raise ValueError("ACCOUNT_STASH_ACCOUNTS_INVALID")
        return value

    def _write(self, state: dict[str, Any]) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".account-stash-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(state, output, ensure_ascii=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _place_items(items: list[dict[str, Any]]) -> None:
        """Give legacy and newly stored items stable, unique chest cells."""
        used: set[int] = set()
        pending: list[dict[str, Any]] = []
        for row in items:
            try:
                index = int(row.get("slot_index", -1))
            except (TypeError, ValueError):
                index = -1
            if 0 <= index < MAX_STASH_SLOTS and index not in used:
                row["slot_index"] = index
                used.add(index)
            else:
                pending.append(row)
        free = (index for index in range(MAX_STASH_SLOTS) if index not in used)
        for row in pending:
            row["slot_index"] = next(free)

    def _operate(self, account_id: str, operation: str, item: Any = None) -> dict[str, Any]:
        account = str(account_id or "local-account")[:64]
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_descriptor = secure_open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(lock_descriptor, "r+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            state = self._read()
            accounts = state["accounts"]
            row = accounts.get(account, {"revision": 0, "items": []})
            if not isinstance(row, dict) or not isinstance(row.get("items"), list):
                raise ValueError("ACCOUNT_STASH_ITEMS_INVALID")
            items = row["items"]
            if len(items) > MAX_STASH_SLOTS:
                raise ValueError("ACCOUNT_STASH_CAPACITY_INVALID")
            if any(not isinstance(value, dict) for value in items):
                raise ValueError("ACCOUNT_STASH_ITEM_INVALID")
            self._place_items(items)
            result_item = None
            error = ""
            if operation == "deposit":
                incoming, requested_slot = item
                if len(items) >= MAX_STASH_SLOTS:
                    error = "ACCOUNT_STASH_FULL"
                elif not isinstance(incoming, dict) or not incoming.get("definition_id"):
                    error = "ACCOUNT_STASH_ITEM_INVALID"
                else:
                    result_item = deepcopy(incoming)
                    result_item["instance_id"] = "stash-" + uuid.uuid4().hex
                    result_item["location"] = "BANK"
                    result_item["owner_id"] = account
                    result_item["container_id"] = ""
                    result_item["equipped_slot"] = ""
                    occupied = {int(value["slot_index"]) for value in items}
                    free_slot = next(index for index in range(MAX_STASH_SLOTS) if index not in occupied)
                    if isinstance(requested_slot, int) and 0 <= requested_slot < MAX_STASH_SLOTS:
                        for value in items:
                            if int(value["slot_index"]) == requested_slot:
                                value["slot_index"] = free_slot
                                break
                        result_item["slot_index"] = requested_slot
                    else:
                        result_item["slot_index"] = free_slot
                    items.append(result_item)
            elif operation == "withdraw":
                wanted = str(item or "")
                index = next(
                    (i for i, value in enumerate(items)
                     if isinstance(value, dict) and value.get("instance_id") == wanted),
                    -1,
                )
                if index < 0:
                    error = "ACCOUNT_STASH_ITEM_MISSING"
                else:
                    result_item = items.pop(index)
            elif operation == "move":
                wanted, requested_slot = item
                selected = next((value for value in items if value.get("instance_id") == wanted), None)
                if selected is None:
                    error = "ACCOUNT_STASH_ITEM_MISSING"
                elif not isinstance(requested_slot, int) or not 0 <= requested_slot < MAX_STASH_SLOTS:
                    error = "ACCOUNT_STASH_SLOT_INVALID"
                else:
                    previous_slot = int(selected["slot_index"])
                    for value in items:
                        if value is not selected and int(value["slot_index"]) == requested_slot:
                            value["slot_index"] = previous_slot
                            break
                    selected["slot_index"] = requested_slot
                    result_item = selected
            elif operation != "read":
                raise ValueError("ACCOUNT_STASH_OPERATION_INVALID")
            if operation != "read" and not error:
                row["revision"] = max(0, int(row.get("revision", 0))) + 1
                row["items"] = items
                accounts[account] = row
                self._write(state)
            result = {
                "revision": max(0, int(row.get("revision", 0))),
                "items": deepcopy(items),
                "item": deepcopy(result_item),
            }
            if error:
                result["error"] = error
            return result

    def load(self, account_id: str) -> dict[str, Any]:
        return self._operate(account_id, "read")

    def deposit(self, account_id: str, item: dict[str, Any], slot_index: int = -1) -> dict[str, Any]:
        return self._operate(account_id, "deposit", (item, slot_index))

    def withdraw(self, account_id: str, instance_id: str) -> dict[str, Any]:
        return self._operate(account_id, "withdraw", instance_id)

    def move(self, account_id: str, instance_id: str, slot_index: int) -> dict[str, Any]:
        return self._operate(account_id, "move", (instance_id, slot_index))


class MemoryStateStore:
    """A deterministic persistence seam with no filesystem or account access."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._revision = 0

    def save(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._revision += 1
        safe_key = str(key or "local-player")[:96]
        self._rows[safe_key] = deepcopy(payload)
        encoded = json.dumps(self._rows[safe_key], separators=(",", ":"))
        return {
            "schema": PERSISTENCE_SCHEMA,
            "key": safe_key,
            "revision": self._revision,
            "bytes": len(encoded.encode("utf-8")),
            "mode": "MEMORY_ONLY",
        }

    def load(self, key: str) -> dict[str, Any] | None:
        return deepcopy(self._rows.get(str(key or "local-player")[:96]))

    def clear(self) -> None:
        self._rows.clear()
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision


def build_network_view(
    world_view: dict[str, Any],
    *,
    sequence: int,
    active_entities: int,
    snapshot_hz: int = 20,
    persistence_revision: int = 0,
    persistence_mode: str = "MEMORY_ONLY",
) -> dict[str, Any]:
    cells = world_view.get("streaming", {}).get("loaded_cells", [])
    local_files = persistence_mode == "LOCAL_FILE"
    return {
        "schema": SCHEMA,
        "mode": "LOCAL_SINGLE_PLAYER" if local_files else "LOCAL_LOOPBACK",
        "transport": "IN_PROCESS" if local_files else "NOT_CONNECTED",
        "authoritative_server": False,
        "simulation_authority": "LOCAL_RUNTIME",
        "prediction": "CLIENT_FIXED_STEP_LOCAL",
        "snapshot_hz": max(1, min(60, int(snapshot_hz))),
        "sequence": max(0, int(sequence)),
        "interest": {
            "policy": "CELL_INTEREST_WITH_ENTITY_CAP",
            "cell_count": len(cells) if isinstance(cells, list) else 0,
            "entity_cap": 128,
            "active_entities": max(0, int(active_entities)),
        },
        "replication": {
            "fields": ["position", "velocity", "movement_mode", "ability_events", "loot_events"],
            "compression": "QUANTIZED_CELL_RELATIVE_OPTIONAL",
            "reconciliation": "SEQUENCE_NUMBER_SEAM",
        },
        "persistence": {
            "schema": PERSISTENCE_SCHEMA,
            "mode": "LOCAL_FILE" if local_files else "MEMORY_ONLY",
            "revision": max(0, int(persistence_revision)),
            "filesystem": "CONNECTED" if local_files else "NOT_CONNECTED",
            "accounts": "LOCAL_CHARACTERS" if local_files else "NOT_CONNECTED",
        },
        "estimated_bytes": 96 + min(max(0, int(active_entities)), 128) * 12,
        "interest_entities": min(max(0, int(active_entities)), 128),
    }


def persistent_payload(
    *,
    player: dict[str, Any],
    movement_mode: str,
    inventory: dict[str, int],
    loot_items: list[dict[str, Any]],
    progression: dict[str, Any],
    editor_document: dict[str, Any],
    terrain_overrides: dict[str, Any] | None = None,
    keybindings: dict[str, Any] | None = None,
    addons: dict[str, Any] | None = None,
    item_instances: list[dict[str, Any]] | None = None,
    profession_state: dict[str, Any] | None = None,
    npc_individuals: dict[str, Any] | None = None,
    event_journal: dict[str, Any] | None = None,
    trade_state: dict[str, Any] | None = None,
    economy_state: dict[str, Any] | None = None,
    combat_state: dict[str, Any] | None = None,
    quest_state: dict[str, Any] | None = None,
    faction_state: dict[str, Any] | None = None,
    dialogue_state: dict[str, Any] | None = None,
    social_state: dict[str, Any] | None = None,
    living_world_state: dict[str, Any] | None = None,
    world_event_state: dict[str, Any] | None = None,
    content_state: dict[str, Any] | None = None,
    simulation_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": PERSISTENCE_SCHEMA,
        "version": 1,
        "player": deepcopy(player),
        "movement_mode": str(movement_mode),
        "inventory": deepcopy(inventory),
        "loot_items": deepcopy(loot_items[-64:]),
        "progression": deepcopy(progression),
        "editor": deepcopy(editor_document),
        "terrain_overrides": deepcopy(terrain_overrides or {}),
        "keybindings": deepcopy(keybindings or {}),
        "addons": deepcopy(addons or {}),
        "item_instances": deepcopy((item_instances or [])[-96:]),
        "profession_state": deepcopy(profession_state or {}),
        "npc_individuals": deepcopy(npc_individuals or {}),
        "event_journal": deepcopy(event_journal or {}),
        "trade_state": deepcopy(trade_state or {}),
        "economy_state": deepcopy(economy_state or {}),
        "combat_state": deepcopy(combat_state or {}),
        "quest_state": deepcopy(quest_state or {}),
        "faction_state": deepcopy(faction_state or {}),
        "dialogue_state": deepcopy(dialogue_state or {}),
        "social_state": deepcopy(social_state or {}),
        "living_world_state": deepcopy(living_world_state or {}),
        "world_event_state": deepcopy(world_event_state or {}),
        "content_state": deepcopy(content_state or {}),
        "simulation": deepcopy(simulation_state or {}),
    }
