"""Expose the reachable GG account chest to upstream container verbs.

GG owns a 48-cell account chest rather than the original client's 24 cells and
six purchasable bags.  Container -1 carries its real capacity; no purchased
bags, prices, access grant, persistence or account identity is invented here.
The host still checks reach, ownership and the open chest on every operation.
"""

from collections.abc import Callable, Mapping
from typing import Any

from backend.game_engine_adapter_gameplay import GameplayViews, QUALITY


MAX_BANK_SLOTS = 48
MAX_BACKPACK_SLOTS = 64


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Invalid GG bank " + label)
    return value


class BankViews:
    """Retain exact owned instances separately from template ids sent to Lua."""

    def __init__(self, identity: Callable[[str], int]) -> None:
        self.identity = identity
        self.opened = False
        self.capacity = 0
        self.bank_refs: dict[int, tuple[str, str]] = {}

    def update(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        # Clear first: malformed or closed snapshots cannot keep old sources
        # routable. Runtime.bank.accessible includes session, reach and errors.
        self.opened = False
        self.capacity = 0
        self.bank_refs = {}
        bank = snapshot.get("bank", {})
        if not isinstance(bank, Mapping):
            raise ValueError("Invalid GG bank snapshot")
        capacity = _integer(bank.get("capacity", 0), "capacity")
        if not 0 <= capacity <= MAX_BANK_SLOTS:
            raise ValueError("Invalid GG bank capacity")
        revision = _integer(bank.get("revision", 0), "revision")
        if revision < 0:
            raise ValueError("Invalid GG bank revision")
        opened = bank.get("accessible") is True and not bank.get("error")
        output = {
            "open": opened,
            "name": "GG shared chest",
            "capacity": capacity,
            "revision": revision,
            "items": [],
        }
        if not opened:
            return output
        rows = bank.get("items", [])
        if not isinstance(rows, list) or len(rows) > capacity:
            raise ValueError("Invalid GG bank items")
        refs: dict[int, tuple[str, str]] = {}
        instances: set[str] = set()
        projected: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("Invalid GG bank item")
            slot = _integer(row.get("slot_index"), "item slot") + 1
            ref = row.get("definition_id")
            instance = row.get("instance_id")
            if (not 1 <= slot <= capacity or slot in refs
                    or not isinstance(ref, str) or not ref or len(ref) > 96
                    or not isinstance(instance, str) or not instance or len(instance) > 64
                    or instance in instances or row.get("location") != "BANK"):
                raise ValueError("Invalid or ambiguous GG bank item source")
            count = _integer(row.get("quantity", 1), "item count")
            if not 1 <= count <= 999:
                raise ValueError("Invalid GG bank item count")
            stack_limit = _integer(row.get("stack_limit", count), "item stack limit")
            if not count <= stack_limit <= 999:
                raise ValueError("Invalid GG bank item stack limit")
            item = self.identity(ref)
            name = str(row.get("name", ref))[:96]
            projected.append({
                "slot": slot,
                # An original vault event distinguishes replacing an exact
                # source from changes to that source's fields. Template ids
                # alone cannot distinguish identical stacks swapping cells.
                "instance_id": instance,
                "item_id": item,
                "name": name,
                "count": count,
                "stack_limit": stack_limit,
                "quality": QUALITY.get(row.get("rarity"), 1),
                "kind": str(row.get("kind", "ITEM"))[:32],
                "link": "|Hitem:" + str(item) + ":0:0:0|h[" + name + "]|h",
                **GameplayViews.item_fields(row),
            })
            refs[slot] = (ref, instance)
            instances.add(instance)
        self.opened = True
        self.capacity = capacity
        self.bank_refs = refs
        output["items"] = projected
        return output

    def route_use(self, bag: int, slot: int, inventory_refs: Mapping[int, tuple[str, str]]) -> dict[str, Any]:
        """An open-bank right click stores the whole item in a host-chosen cell.

        The original app gives an open merchant precedence over this bank
        arm. Callers must keep that ordering before ordinary item use.
        """
        if not self.opened:
            raise ValueError("GG bank is closed or out of reach")
        bag = _integer(bag, "source bag")
        slot = _integer(slot, "source slot")
        if bag not in (-1, 0):
            raise ValueError("Unsupported GG bank container use")
        limit = self.capacity if bag == -1 else MAX_BACKPACK_SLOTS
        if not 1 <= slot <= limit:
            raise ValueError("Invalid GG bank item use slot")
        source = (self.bank_refs if bag == -1 else inventory_refs).get(slot)
        if not source or len(source) != 2 or not source[1]:
            raise ValueError("Unknown GG bank item source")
        return {"method": "gameEngineBankWithdrawAt" if bag == -1 else "gameEngineBankDepositAt",
                "args": (source[1], -1)}

    def route(self, move: Mapping[str, Any], inventory_refs: Mapping[int, tuple[str, str]]) -> dict[str, Any] | None:
        """Plan one whole-stack move; the authoritative host performs it.

        Cross-boundary occupied drops are rejected: GG's deposit/withdraw
        methods relocate a destination occupant instead of swapping it with
        the original source, so advertising the original swap would mislead
        Lua. Within-bank swaps use the existing atomic stash move.
        Splits, equipped sources and containers other than -1/0 are not mapped.
        """
        if not self.opened:
            raise ValueError("GG bank is closed or out of reach")
        if move.get("count") is not None:
            raise ValueError("GG bank split stacks are not implemented")
        src_bag = _integer(move.get("src_bag"), "source bag")
        dst_bag = _integer(move.get("dst_bag"), "destination bag")
        src_slot = _integer(move.get("src_slot"), "source slot")
        dst_slot = _integer(move.get("dst_slot"), "destination slot")
        if src_bag not in (-1, 0) or dst_bag not in (-1, 0) or -1 not in (src_bag, dst_bag):
            raise ValueError("Unsupported GG bank container move")
        src_limit = self.capacity if src_bag == -1 else MAX_BACKPACK_SLOTS
        dst_limit = self.capacity if dst_bag == -1 else MAX_BACKPACK_SLOTS
        if not 1 <= src_slot <= src_limit or not 1 <= dst_slot <= dst_limit:
            raise ValueError("Invalid GG bank move slot")
        sources = self.bank_refs if src_bag == -1 else inventory_refs
        source = sources.get(src_slot)
        if not source or len(source) != 2 or not source[1]:
            raise ValueError("Unknown GG bank item source")
        destinations = self.bank_refs if dst_bag == -1 else inventory_refs
        if src_bag != dst_bag and dst_slot in destinations:
            raise ValueError("GG bank cross-container swaps are not implemented")
        if src_bag == dst_bag and src_slot == dst_slot:
            return None
        method = ("gameEngineBankDepositAt" if src_bag == 0 else
                  "gameEngineBankWithdrawAt" if dst_bag == 0 else
                  "gameEngineBankMove")
        return {"method": method, "args": (source[1], dst_slot - 1)}
