"""Map an explicitly opened GG vendor's physical offers to GgEngine Lua.

An offer is one real owned instance, including its entire stack. It is one
purchase bundle, rather than synthetic unlimited stock. The authoritative
GgEngine host's guarded merchant methods still check the current session,
proximity, owner, funds and stock when a planned transaction executes; this
module grants none of those. Existing DOS vendor methods are separate.
"""

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any


MAX_VENDOR_ROWS = 16
MAX_VENDORS = 8
MAX_BACKPACK_SLOTS = 64
MAX_COPPER = (1 << 32) - 1
MAX_BUNDLE_REQUEST_BYTES = 8192
_BUNDLE_FIELDS = frozenset({"instance_id", "definition_id", "quantity", "total_price", "revision", "bundle_fingerprint"})
_TRANSIENT_ITEM_FIELDS = frozenset({
    "instance_id", "location", "owner_id", "container_id", "slot_index",
    "position", "visual_phase", "visual", "origin", "seed", "roll",
    "base_item_id", "roll_table_id",
})


def _bundle_fingerprint(item: Mapping[str, Any]) -> str:
    """Compare the actual offered item, excluding identity and world animation.

    Gear, enchantments, condition, firearm state and authored appearances remain
    in the comparison. Two physical stacks with different properties cannot be
    silently purchased as interchangeable bundles.
    """
    encoded = json.dumps({key: value for key, value in item.items()
                          if key not in _TRANSIENT_ITEM_FIELDS},
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded) > 16384:
        raise ValueError("GG merchant item description capacity exceeded")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Invalid GG merchant " + label)
    return value


def _identity(value: Any, limit: int, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError("Invalid GG merchant " + label)
    return value


def _copper(gold: Any) -> int:
    gold = _integer(gold, "quote")
    copper = gold * 10000
    if not 0 < copper <= MAX_COPPER:
        raise ValueError("GG merchant quote cannot be represented in copper")
    return copper


def _bundle_requests(value: Any) -> list[dict[str, Any]]:
    """Bound and copy a shown offer plan before consulting mutable stock."""
    try:
        encoded = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_BUNDLE_REQUEST_BYTES:
            raise ValueError("VENDOR_BUNDLE_REQUEST_CAPACITY")

        def unique_fields(pairs):
            result = {}
            for key, field in pairs:
                if key in result:
                    raise ValueError("VENDOR_BUNDLE_REQUEST_INVALID")
                result[key] = field
            return result

        rows = json.loads(encoded, object_pairs_hook=unique_fields)
    except (TypeError, UnicodeError, OverflowError, json.JSONDecodeError) as exc:
        raise ValueError("VENDOR_BUNDLE_REQUEST_INVALID") from exc
    if not isinstance(rows, list) or not 2 <= len(rows) <= MAX_VENDOR_ROWS:
        raise ValueError("VENDOR_BUNDLE_COUNT_INVALID")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _BUNDLE_FIELDS:
            raise ValueError("VENDOR_BUNDLE_REQUEST_INVALID")
        instance = _identity(row["instance_id"], 64, "bundle instance")
        _identity(row["definition_id"], 96, "bundle definition")
        if instance in seen:
            raise ValueError("VENDOR_BUNDLE_INSTANCE_DUPLICATE")
        seen.add(instance)
        quantity = _integer(row["quantity"], "bundle quantity")
        price = _integer(row["total_price"], "bundle price")
        revision = _integer(row["revision"], "bundle revision")
        if not 1 <= quantity <= 999 or not 1 <= price <= 2_000_000_000 or not 0 <= revision < 2**63:
            raise ValueError("VENDOR_BUNDLE_REQUEST_INVALID")
        fingerprint = row["bundle_fingerprint"]
        if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in fingerprint)):
            raise ValueError("VENDOR_BUNDLE_REQUEST_INVALID")
    return rows


class MerchantBundlesMixin:
    """Commit one finite purchase plan through the canonical durable barter."""

    def merchant_buy_bundles(self, vendor_id: str, requests: Any) -> dict[str, Any]:
        with self._lock:
            return self._vendor_durable_locked(
                lambda: self._merchant_buy_bundles_locked(vendor_id, requests))

    def _merchant_buy_bundles_locked(self, vendor_id: str, requests: Any) -> dict[str, Any]:
        from backend import game_engine_economy as economy, game_engine_items as items

        rows = _bundle_requests(requests)
        vendor_id = _identity(vendor_id, 96, "bundle vendor")
        session = self._merchant_view_locked()
        if not session.get("open") or session.get("vendor_id") != vendor_id:
            raise ValueError("MERCHANT_SESSION_REQUIRED")
        valid, target = self._vendor_target_locked(vendor_id)
        if not valid:
            raise ValueError(str(target.get("error", "MERCHANT_SESSION_REQUIRED")))
        account = self._economy_state.get("vendors", {}).get(vendor_id)
        wallet = self._economy_state.get("wallet")
        if not isinstance(account, dict) or not isinstance(wallet, dict):
            raise ValueError("VENDOR_ACCOUNT_MISSING")
        revision = account.get("revision", 0)
        if any(row["revision"] != revision for row in rows):
            raise ValueError("VENDOR_BUNDLE_REVISION_CHANGED")

        # Only the bounded published stock is eligible. A caller cannot select
        # hidden physical stock or replace a consumed shown row with a new one.
        snapshot = self.snapshot_locked()
        vendor = next((entry for entry in snapshot.get("economy", {}).get("vendors", [])
                       if entry.get("id") == vendor_id), None)
        if not isinstance(vendor, dict):
            raise ValueError("VENDOR_ACCOUNT_MISSING")
        current_offers = {offer["instance_id"]: offer
                          for offer in vendor.get("offers", {}).get("buy", [])}
        first = rows[0]
        for row in rows:
            if any(row[key] != first[key] for key in _BUNDLE_FIELDS - {"instance_id"}):
                raise ValueError("VENDOR_BUNDLES_NOT_IDENTICAL")
            offer = current_offers.get(row["instance_id"])
            instance = self._item_instances.get(row["instance_id"])
            if (not isinstance(offer, dict) or not isinstance(instance, dict)
                    or instance.get("owner_id") != target["npc_id"]
                    or instance.get("location") != "POCKET"):
                raise ValueError("VENDOR_STOCK_INSTANCE_INVALID")
            if any(offer.get(key) != row[key] for key in ("definition_id", "quantity", "total_price")):
                raise ValueError("VENDOR_BUNDLE_OFFER_CHANGED")
            if _bundle_fingerprint(offer["item"]) != row["bundle_fingerprint"]:
                raise ValueError("VENDOR_BUNDLE_OFFER_CHANGED")
            if self._item_binding_locked(instance):
                raise ValueError("ITEM_PENDING_CONFIRMATION")
            if instance.get("bound_to") and instance["bound_to"] != str(self._persistence_key):
                raise ValueError("ITEM_BOUND_TO_ANOTHER_CHARACTER")

        quantity = first["quantity"]
        total_price = first["total_price"] * len(rows)
        if total_price > economy.MAX_CURRENCY:
            raise ValueError("VENDOR_BUNDLE_PRICE_CAPACITY")
        if int(wallet.get("gold", 0)) < total_price:
            raise ValueError("VENDOR_PLAYER_GOLD_INSUFFICIENT")
        if int(account.get("gold", 0)) > economy.MAX_CURRENCY - total_price:
            raise ValueError("VENDOR_GOLD_CAPACITY")
        slots = sum(1 for instance in self._item_instances.values()
                    if instance.get("owner_id") == "player" and instance.get("location") == "INVENTORY")
        if slots + len(rows) > items.MAX_INVENTORY_SLOTS:
            raise ValueError("VENDOR_PLAYER_INVENTORY_FULL")
        person = self._individual_state.get("individuals", {}).get(target["npc_id"], {})
        if person.get("inventory", []).count(first["definition_id"]) < len(rows):
            raise ValueError("VENDOR_STOCK_REFERENCE_MISSING")

        # The client supplies expectations, never a price authority. Compute
        # the initial canonical quote once, then retain it for this whole batch
        # while normal demand/stock accounting advances per physical bundle.
        stock = self._vendor_stock_count_locked(target["vendor"], first["definition_id"])
        quote = economy.dynamic_prices(target["vendor"], account, first["definition_id"], stock)
        if not quote or quote["buy"] * quantity != first["total_price"]:
            raise ValueError("VENDOR_BUNDLE_OFFER_CHANGED")
        result = None
        for row in rows:
            result = self._vendor_transition_locked("BUY", vendor_id, row["instance_id"],
                                                    quote_override=quote)
            if result.get("error"):
                return result
        result["economy_result"] = {
            **copy.deepcopy(result["economy_result"]), "bundle_count": len(rows),
            "instance_ids": [row["instance_id"] for row in rows],
            "quantity": quantity * len(rows), "total_price": total_price, "atomic": True,
        }
        return result


class MerchantViews:
    def __init__(self, identity: Callable[[str], int]) -> None:
        self.identity = identity
        self.opened = False
        self.vendor_id = ""
        self.buy_refs: dict[int, tuple[str, str]] = {}
        self.sell_refs: dict[str, str] = {}
        self.entry_refs={};self.buyback_refs={}
        self.bundle_refs: dict[int, tuple[tuple[str, str, int, int, int, str], ...]] = {}

    def update(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        # Clear before reading so malformed, closed or distant snapshots
        # cannot leave references from an earlier session routable.
        self.opened = False
        self.vendor_id = ""
        self.buy_refs = {}
        self.sell_refs = {}
        self.entry_refs={};self.buyback_refs={}
        self.bundle_refs = {}
        output = {"open": False, "vendor_id": "", "name": "", "revision": 0, "items": []}
        session = snapshot.get("merchant", {})
        if not isinstance(session, Mapping):
            raise ValueError("Invalid GG merchant session")
        if session.get("open") is not True or session.get("error"):
            return output
        vendor_id = _identity(session.get("vendor_id"), 96, "vendor id")
        economy = snapshot.get("economy", {})
        vendors = economy.get("vendors", []) if isinstance(economy, Mapping) else None
        if not isinstance(vendors, list) or len(vendors) > MAX_VENDORS:
            raise ValueError("Invalid GG merchant vendor list")
        matches = [row for row in vendors if isinstance(row, Mapping) and row.get("id") == vendor_id]
        if len(matches) != 1:
            raise ValueError("Unknown or ambiguous GG merchant session vendor")
        vendor = matches[0]
        presence = vendor.get("presence", {})
        if not isinstance(presence, Mapping) or presence.get("available") is not True:
            return output
        npc_id = _identity(vendor.get("npc_id"), 64, "vendor owner")
        revision = _integer(vendor.get("revision", 0), "revision")
        if revision < 0:
            raise ValueError("Invalid GG merchant revision")
        offers = vendor.get("offers", {})
        if not isinstance(offers, Mapping):
            raise ValueError("Invalid GG merchant offers")
        buy = offers.get("buy", [])
        sell = offers.get("sell", [])
        if (not isinstance(buy, list) or not isinstance(sell, list)
                or len(buy) > MAX_VENDOR_ROWS or len(sell) > MAX_VENDOR_ROWS):
            raise ValueError("GG merchant offer capacity exceeded")
        buy_refs: dict[int, tuple[str, str]] = {}
        sell_refs: dict[str, str] = {}
        seen_buy: set[str] = set()
        projected: list[dict[str, Any]] = []
        seen_definitions=set()
        bundle_rows: dict[int, tuple[str, str, int, int, int, str]] = {}
        for action, rows in (("BUY", buy), ("SELL", sell)):
            for index, offer in enumerate(rows, 1):
                if not isinstance(offer, Mapping) or offer.get("action") != action or offer.get("currency") != "GOLD":
                    raise ValueError("Invalid GG merchant offer")
                ref = _identity(offer.get("definition_id"), 96, "item definition")
                instance = _identity(offer.get("instance_id"), 64, "item instance")
                item = offer.get("item")
                quantity = _integer(offer.get("quantity"), "bundle quantity")
                if not 1 <= quantity <= 999:
                    raise ValueError("Invalid GG merchant bundle quantity")
                if (not isinstance(item, Mapping) or item.get("definition_id") != ref
                        or item.get("instance_id") != instance or item.get("quantity") != quantity
                        or item.get("location") != ("POCKET" if action == "BUY" else "INVENTORY")
                        or item.get("owner_id") != (npc_id if action == "BUY" else "player")):
                    raise ValueError("Invalid GG merchant offer ownership or instance")
                price = _copper(offer.get("total_price"))
                if action == "SELL":
                    if instance in sell_refs:
                        raise ValueError("Ambiguous GG merchant sell instance")
                    sell_refs[instance] = ref
                    continue
                if instance in seen_buy:
                    raise ValueError("Ambiguous GG merchant buy instance")
                seen_buy.add(instance)
                item_id = self.identity(ref)
                if ref in seen_definitions:item_id=self.identity('merchant:'+vendor_id+':'+instance)
                seen_definitions.add(ref)
                if item_id in self.entry_refs:raise ValueError('Ambiguous GG merchant entry')
                self.entry_refs[item_id]=(ref,instance)
                name = str(item.get("name", ref))[:96]
                stack_limit = _integer(item.get("stack_limit", quantity), "stack limit")
                if not quantity <= stack_limit <= 999:
                    raise ValueError("Invalid GG merchant stack limit")
                projected.append({
                    "name": name,
                    "texture": item.get("icon"),
                    "price": price,
                    "quantity": quantity,
                    "num_available": 1,
                    "item_id": item_id,
                    "link": "|Hitem:" + str(item_id) + ":0:0:0|h[" + name + "]|h",
                    "max_stack": stack_limit,
                    'quality':{'POOR':0,'COMMON':1,'UNCOMMON':2,'RARE':3,'EPIC':4}.get(item.get('rarity'),1),
                    'kind':item.get('kind','ITEM'),
                })
                buy_refs[index] = (ref, instance)
                bundle_rows[index] = (instance, ref, quantity, offer["total_price"], revision,
                                      _bundle_fingerprint(item))
        bundle_refs = {}
        for index, source in bundle_rows.items():
            matching = tuple(offer for other, offer in bundle_rows.items()
                             if other != index and offer[1:] == source[1:])
            bundle_refs[index] = (source, *matching)
            projected[index - 1]["num_available"] = len(bundle_refs[index])
        output.update(open=True, vendor_id=vendor_id,
                      name=str(session.get("name") or vendor.get("name", vendor_id))[:96],
                      revision=revision, items=projected)
        buybacks=[]
        for index,row in enumerate(session.get('buybacks',[])[:12],1):
            item=row['item'];ref=_identity(item.get('definition_id'),96,'buyback definition');instance=_identity(item.get('instance_id'),64,'buyback instance')
            if item.get('owner_id')!=npc_id or item.get('location')!='POCKET':raise ValueError('Invalid GG buyback ownership')
            self.buyback_refs[index]=instance
            buybacks.append({'name':str(item.get('name',ref))[:96],'texture':item.get('icon'),'price':_copper(row['price']),'quantity':int(item['quantity']),'item_id':self.identity(ref),'max_stack':int(item.get('stack_limit',1))})
        costs=session.get('repair_items',{});repair_bags=[];repair_equipped=[]
        from backend.game_engine_adapter_gameplay import EQUIPMENT_SLOTS
        for key,rows in (('inventory',snapshot.get('items',{}).get('inventory',[])),('equipment',snapshot.get('items',{}).get('equipment',[]))):
            for fallback,item in enumerate(rows[:64]):
                price=costs.get(item.get('instance_id'),0)
                if not price:continue
                if key=='inventory':repair_bags.append([0,int(item.get('slot_index',fallback))+1,_copper(price)])
                elif item.get('equipped_slot') in EQUIPMENT_SLOTS:repair_equipped.append([EQUIPMENT_SLOTS[item['equipped_slot']],_copper(price)])
        cost=session.get('repair_gold',0)
        output.update(buybacks=buybacks,can_repair=session.get('can_repair') is True,repair_cost=_copper(cost) if cost else 0,repair_bags=repair_bags,repair_equipped=repair_equipped)
        self.vendor_id = vendor_id
        self.buy_refs = buy_refs
        self.sell_refs = sell_refs
        self.bundle_refs = bundle_refs
        self.opened = True
        return output

    def route_buy_slot(self,bag,slot,entry):
        bag=_integer(bag,'destination bag');slot=_integer(slot,'destination slot');entry=_integer(entry,'entry')
        source=self.entry_refs.get(entry)
        if not self.opened or source is None:raise ValueError('Unknown GG merchant physical offer')
        if bag!=0 or not 1<=slot<=MAX_BACKPACK_SLOTS:raise ValueError('Unsupported GG merchant destination')
        return {'method':'gameEngineMerchantBuyAt','args':(self.vendor_id,source[1],slot-1)}

    def route_buyback(self,row):
        source=self.buyback_refs.get(_integer(row,'buyback row'))
        if not self.opened or source is None:raise ValueError('Unknown GG merchant buyback')
        return {'method':'gameEngineMerchantBuyback','args':(self.vendor_id,source)}

    def route_repair(self,instance=''):
        if not self.opened:raise ValueError('GG merchant is closed or unavailable')
        return {'method':'gameEngineMerchantRepair','args':(self.vendor_id,instance)}

    def route_buy(self, row: int, quantity: int = 1) -> dict[str, Any]:
        if not self.opened:
            raise ValueError("GG merchant is closed or unavailable")
        row = _integer(row, "buy row")
        quantity = _integer(quantity, "purchase count")
        if not 1 <= quantity <= MAX_VENDOR_ROWS:
            raise ValueError("Invalid GG merchant purchase count")
        source = self.buy_refs.get(row)
        if source is None:
            raise ValueError("Unknown GG merchant buy row")
        if quantity > 1:
            offers = self.bundle_refs.get(row, ())
            if len(offers) < quantity:
                raise ValueError("GG merchant has insufficient identical physical bundles")
            records = [dict(zip(("instance_id", "definition_id", "quantity", "total_price",
                                 "revision", "bundle_fingerprint"), offer))
                       for offer in offers[:quantity]]
            payload = json.dumps(records, separators=(",", ":"), allow_nan=False)
            if len(payload) > MAX_BUNDLE_REQUEST_BYTES:
                raise ValueError("GG merchant bundle request capacity exceeded")
            return {"method": "gameEngineMerchantBuyBundles", "args": (self.vendor_id, payload)}
        return {"method": "gameEngineMerchantBuy", "args": (self.vendor_id, source[1])}

    def route_sell(self, bag: int, slot: int, inventory_refs: Mapping[int, tuple[str, str]], quantity: int = 0) -> dict[str, Any]:
        if not self.opened:
            raise ValueError("GG merchant is closed or unavailable")
        bag = _integer(bag, "sell bag")
        slot = _integer(slot, "sell slot")
        quantity = _integer(quantity, "sell quantity")
        if not 0 <= quantity <= 999:
            raise ValueError("Invalid GG merchant sell quantity")
        if bag != 0 or not 1 <= slot <= MAX_BACKPACK_SLOTS:
            raise ValueError("Unsupported GG merchant sell container")
        source = inventory_refs.get(slot)
        if not source or len(source) != 2 or self.sell_refs.get(source[1]) != source[0]:
            raise ValueError("GG merchant has no current sell offer for this exact inventory item")
        return ({"method": "gameEngineMerchantSellCount", "args": (self.vendor_id, source[1], quantity)}
                if quantity else {"method": "gameEngineMerchantSell", "args": (self.vendor_id, source[1])})
