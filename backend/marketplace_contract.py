from __future__ import annotations

from backend.application_paths import STATE_ROOT

import json
import math
import time
from pathlib import Path
from typing import Any

from backend.crypto_contract import (
    format_sol,
    load_network,
    load_wallet,
    short_pubkey,
    validate_pubkey,
    write_state_json,
)
from backend.domain_merkle import (
    MerkleChild,
    build_domain_root,
    digest_json,
    leaf,
    subtree,
)


SCHEMA = "gg.ai-desktop.marketplace-status.v2"
LISTING_SCHEMA = "gg.ai-desktop.marketplace-listing.v2"
LEDGER_SCHEMA = "gg.ai-desktop.marketplace-ledger.v2"
STATE_DIR = Path(str(STATE_ROOT / 'marketplace'))
CATALOG_NAME = "catalog.json"
LEDGER_NAME = "ledger.jsonl"
PREFS_NAME = "prefs.json"
MERKLE_NAME = "merkle.json"
MAX_LISTINGS = 2000
MAX_TITLE = 96
MAX_DESCRIPTION = 480
MAX_LEDGER = 400
DOMAIN = "MARKETPLACE"
SCOPE = "solana.catalog"
CATEGORIES = (
    "MATERIAL",
    "ITEM",
    "ART",
    "COLLECTIBLE",
    "DOCUMENT",
    "TOOL",
    "COMPONENT",
    "SERVICE",
)
KINDS = (
    "ELEMENT",
    "SUBSTANCE",
    "OBJECT",
    "SERVICE",
)
ELEMENTS = (
    ("H", "Hydrogen"),
    ("C", "Carbon"),
    ("N", "Nitrogen"),
    ("O", "Oxygen"),
    ("Na", "Sodium"),
    ("Mg", "Magnesium"),
    ("Al", "Aluminium"),
    ("Si", "Silicon"),
    ("P", "Phosphorus"),
    ("S", "Sulfur"),
    ("Ti", "Titanium"),
    ("Cr", "Chromium"),
    ("Fe", "Iron"),
    ("Ni", "Nickel"),
    ("Cu", "Copper"),
    ("Zn", "Zinc"),
    ("Ag", "Silver"),
    ("Sn", "Tin"),
    ("Au", "Gold"),
    ("Pb", "Lead"),
)
ELEMENT_SYMBOLS = frozenset(symbol for symbol, _name in ELEMENTS)
MATERIALS = (
    "GOLD",
    "SILVER",
    "COPPER",
    "WOOD",
    "STONE",
    "FABRIC",
    "METAL",
    "DIGITAL",
    "MIXED",
    "UNKNOWN",
) + tuple(sorted(ELEMENT_SYMBOLS))
MAX_COMPOSITION = 24
MAX_LIVES = 12
MAX_MASS = 1_000_000_000.0
STATUSES = ("DRAFT", "LISTED", "DELISTED", "SOLD")
FILTERS = ("ALL",) + CATEGORIES + KINDS
SOL_LAMPORTS = 1_000_000_000
MAX_PRICE_SOL = 1_000_000


def ensure_state_dir() -> Path:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return STATE_DIR


def catalog_path() -> Path:
    return ensure_state_dir() / CATALOG_NAME


def ledger_path() -> Path:
    return ensure_state_dir() / LEDGER_NAME


def prefs_path() -> Path:
    return ensure_state_dir() / PREFS_NAME


def merkle_path() -> Path:
    return ensure_state_dir() / MERKLE_NAME


def parse_sol_price(raw: str | int | float | None) -> int:
    if isinstance(raw, bool) or isinstance(raw, float) and not math.isfinite(raw):
        raise ValueError("MARKETPLACE_PRICE")
    if isinstance(raw, int):
        if raw < 0 or raw > MAX_PRICE_SOL * SOL_LAMPORTS:
            raise ValueError("MARKETPLACE_PRICE")
        return raw
    if isinstance(raw, float):
        if raw < 0 or raw > MAX_PRICE_SOL:
            raise ValueError("MARKETPLACE_PRICE")
        return int(round(raw * SOL_LAMPORTS))
    text = str(raw or "0").strip()
    if not text:
        return 0
    if text.startswith("-"):
        raise ValueError("MARKETPLACE_PRICE")
    if "." in text:
        whole, frac = text.split(".", 1)
        if not whole:
            whole = "0"
        if len(frac) > 9:
            raise ValueError("MARKETPLACE_PRICE_PRECISION")
        frac = (frac + "000000000")[:9]
        if not whole.isdigit() or not frac.isdigit():
            raise ValueError("MARKETPLACE_PRICE")
        lamports = int(whole) * SOL_LAMPORTS + int(frac)
    else:
        if not text.isdigit():
            raise ValueError("MARKETPLACE_PRICE")
        lamports = int(text) * SOL_LAMPORTS
    if lamports > MAX_PRICE_SOL * SOL_LAMPORTS:
        raise ValueError("MARKETPLACE_PRICE")
    return lamports


def _clip(value: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > maximum:
        return text[:maximum]
    return text


def _norm_composition(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw[:MAX_COMPOSITION]:
        if not isinstance(item, dict):
            continue
        part_id = str(item.get("id") or "")[:80]
        symbol = str(item.get("symbol") or item.get("material") or "").strip()
        title = _clip(str(item.get("title") or symbol or part_id), MAX_TITLE)
        kind = str(item.get("kind") or "ELEMENT").strip().upper()
        if kind not in KINDS:
            kind = "ELEMENT"
        try:
            mass = float(item.get("mass_g") or 0)
        except (TypeError, ValueError):
            mass = 0.0
        if not math.isfinite(mass) or mass < 0 or mass > MAX_MASS:
            mass = 0.0
        rows.append(
            {
                "id": part_id,
                "kind": kind,
                "symbol": symbol[:8],
                "title": title,
                "mass_g": round(mass, 4),
            }
        )
    return rows


def _norm_lives(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw[:MAX_LIVES]:
        listing_id = str(item if not isinstance(item, dict) else item.get("id") or "")
        listing_id = listing_id.strip()[:80]
        if not listing_id or listing_id in seen:
            continue
        seen.add(listing_id)
        out.append(listing_id)
    return out


def infer_kind(category: str, material: str) -> str:
    if material in ELEMENT_SYMBOLS or category == "MATERIAL":
        if material in ELEMENT_SYMBOLS:
            return "ELEMENT"
        return "SUBSTANCE"
    return "OBJECT"


def identity_payload(row: dict[str, Any]) -> dict[str, Any]:
    result = {
        "schema": LISTING_SCHEMA,
        "title": str(row.get("title") or ""),
        "kind": str(row.get("kind") or ""),
        "category": str(row.get("category") or ""),
        "material": str(row.get("material") or ""),
        "description": str(row.get("description") or ""),
        "maker": str(row.get("maker") or ""),
        "origin": str(row.get("origin") or ""),
        "mass_g": float(row.get("mass_g") or 0),
        "composition": _norm_composition(row.get("composition")),
        "previous_lives": _norm_lives(row.get("previous_lives")),
        "mint": str(row.get("mint") or ""),
        "price_lamports": int(row.get("price_lamports") or 0),
        "listed_at": int(row.get("listed_at") or 0),
    }
    if row.get('settlement'):
        result['settlement'] = row['settlement']
    for key in ('image_id','collection_name','nft_binding'):
        if row.get(key):result[key]=row[key]
    if row.get('identity_version')==3:
        result['identity_version']=3
        # Generated paper references must not change the object's identity
        # after minting. Legacy rows retain their original hash interpretation.
        if str(result['mint']).startswith('paper:'):result['mint']=''
    return result


def state_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = identity_payload(row)
    payload["id"] = str(row.get("id") or "")
    payload["owner"] = str(row.get("owner") or "")
    payload["status"] = str(row.get("status") or "")
    payload["network"] = str(row.get("network") or "testnet")
    payload["mode"] = str(row.get("mode") or "TESTNET")
    payload["identity_sha256"] = str(row.get("identity_sha256") or "")
    payload["lifecycle"] = list(row.get("lifecycle") or [])[-40:]
    if row.get('transaction_receipt'):payload['transaction_receipt']=row['transaction_receipt']
    return payload


def hash_identity(row: dict[str, Any]) -> str:
    return digest_json(identity_payload(row))


def hash_state(row: dict[str, Any]) -> str:
    return digest_json(state_payload(row))


def empty_merkle_leaf() -> MerkleChild:
    return leaf(
        "catalog/empty",
        digest_json({"schema": SCHEMA, "listings": []}),
    )


def catalog_merkle(
    listings: list[dict[str, Any]],
    persist: bool = False,
) -> dict[str, Any]:
    grouped: dict[str, list[MerkleChild]] = {}
    for row in listings:
        listing_id = str(row.get("id") or "")
        state_sha = str(row.get("state_sha256") or "")
        category = str(row.get("category") or "")
        if not listing_id or not state_sha or category not in CATEGORIES:
            continue
        grouped.setdefault(category, []).append(
            leaf("listing/" + listing_id, state_sha)
        )
    children: list[MerkleChild] = []
    category_roots: dict[str, str] = {}
    for category in CATEGORIES:
        rows = grouped.get(category)
        if not rows:
            continue
        cat_root = build_domain_root(
            DOMAIN,
            SCOPE + "/" + category,
            tuple(rows),
        )
        category_roots[category] = cat_root.root_sha256()
        children.append(subtree("category/" + category, cat_root))
    if not children:
        children = [empty_merkle_leaf()]
    root = build_domain_root(DOMAIN, SCOPE, tuple(children))
    payload = {
        "schema": "gg.domain-merkle-root.v1",
        "domain": DOMAIN,
        "scope": SCOPE,
        "root_sha256": root.root_sha256(),
        "category_roots": category_roots,
        "listing_count": sum(len(rows) for rows in grouped.values()),
    }
    if persist:
        path = merkle_path()
        write_state_json(path, payload)
    return payload


def listing_proof(
    listings: list[dict[str, Any]],
    listing_id: str,
    merkle: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    wanted = str(listing_id or "").strip()
    row = next((item for item in listings if item.get("id") == wanted), None)
    if row is None:
        return None
    tree = merkle or catalog_merkle(listings)
    category = str(row.get("category") or "")
    return {
        "listing_id": wanted,
        "identity_sha256": str(row.get("identity_sha256") or ""),
        "state_sha256": str(row.get("state_sha256") or ""),
        "category": category,
        "category_root": str((tree.get("category_roots") or {}).get(category) or ""),
        "catalog_root": str(tree.get("root_sha256") or ""),
        "leaf_namespace": "listing/" + wanted,
        "mint": str(row.get("mint") or ""),
        "network": str(row.get("network") or "testnet"),
        "mode": str(row.get("mode") or "TESTNET"),
    }


def load_catalog() -> list[dict[str, Any]]:
    path = catalog_path()
    if not path.is_file():
        return []
    try:
        with path.open('rb') as stream: raw=stream.read(16*1024*1024+1)
        if len(raw)>16*1024*1024:raise ValueError('MARKETPLACE_CATALOG_TOO_LARGE')
        def invalid_constant(value):raise ValueError('MARKETPLACE_CATALOG_CORRUPT')
        payload = json.loads(raw,parse_constant=invalid_constant)
    except (OSError, json.JSONDecodeError, UnicodeError):
        raise ValueError('MARKETPLACE_CATALOG_CORRUPT') from None
    rows = payload.get("listings") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError('MARKETPLACE_CATALOG_CORRUPT')
    if len(rows)>MAX_LISTINGS or any(not isinstance(row,dict) or not row.get('id') for row in rows) or len({row['id'] for row in rows})!=len(rows):
        raise ValueError('MARKETPLACE_CATALOG_CORRUPT')
    for row in rows:
        version=row.get('identity_version')
        if version is not None and (type(version) is not int or version not in {2,3}):
            raise ValueError('MARKETPLACE_RECEIPT_INTEGRITY')
        identity_matches=row.get('identity_sha256')==hash_identity(row)
        if version in {None,2} and not identity_matches:
            # Legacy paper rows hashed their seed before assigning the generated
            # mint. Verify that exact construction as well as the final state;
            # a missing version never exempts a row from integrity checks.
            identity=str(row.get('identity_sha256') or '')
            if identity and row.get('mint')=='paper:'+identity[:32]:
                identity_matches=identity==hash_identity(dict(row,mint=''))
        if not identity_matches or row.get('state_sha256')!=hash_state(row):
            raise ValueError('MARKETPLACE_RECEIPT_INTEGRITY')
    out: list[dict[str, Any]] = []
    for item in rows[:MAX_LISTINGS]:
        if isinstance(item, dict) and item.get("id"):
            out.append(item)
    return out


def save_catalog(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = listings[:MAX_LISTINGS]
    merkle = catalog_merkle(rows, persist=True)
    payload = {
        "schema": SCHEMA,
        "listings": rows,
        "merkle_root": merkle.get("root_sha256") or "",
    }
    path = catalog_path()
    write_state_json(path, payload)
    return rows


def load_prefs() -> dict[str, Any]:
    path = prefs_path()
    if not path.is_file():
        return {"filter": "ALL", "selected": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {"filter": "ALL", "selected": ""}
    if not isinstance(payload, dict):
        return {"filter": "ALL", "selected": ""}
    filt = str(payload.get("filter") or "ALL").strip().upper()
    if filt not in FILTERS:
        filt = "ALL"
    return {
        "filter": filt,
        "selected": str(payload.get("selected") or "")[:80],
    }


def save_prefs(filter_name: str = "", selected: str = "") -> dict[str, Any]:
    current = load_prefs()
    filt = str(filter_name or current.get("filter") or "ALL").strip().upper()
    if filt not in FILTERS:
        filt = "ALL"
    selected_id = str(selected if selected != "" else current.get("selected") or "")[:80]
    payload = {"filter": filt, "selected": selected_id}
    path = prefs_path()
    write_state_json(path, payload)
    return payload


def read_ledger() -> list[dict[str, Any]]:
    path = ledger_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows[-MAX_LEDGER:]


def append_ledger(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["schema"] = LEDGER_SCHEMA
    payload["ts"] = int(payload.get("ts") or time.time())
    path = ledger_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    path.chmod(0o600)
    return payload


def parse_listing(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw or ""))
        except json.JSONDecodeError as exc:
            raise ValueError("MARKETPLACE_JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("MARKETPLACE_JSON")
    title = _clip(str(payload.get("title") or ""), MAX_TITLE)
    if not title:
        raise ValueError("MARKETPLACE_TITLE")
    category = str(payload.get("category") or "").strip().upper()
    if category not in CATEGORIES:
        raise ValueError("MARKETPLACE_CATEGORY")
    raw_mat = str(payload.get("material") or "UNKNOWN").strip()
    symbol_by_up = {symbol.upper(): symbol for symbol in ELEMENT_SYMBOLS}
    if raw_mat.upper() in symbol_by_up:
        material = symbol_by_up[raw_mat.upper()]
    else:
        material = raw_mat.upper()
    if material not in MATERIALS:
        raise ValueError("MARKETPLACE_MATERIAL")
    description = _clip(str(payload.get("description") or ""), MAX_DESCRIPTION)
    maker = _clip(str(payload.get("maker") or ""), 80)
    origin = _clip(str(payload.get("origin") or ""), 80)
    try:
        mass_g = float(payload.get("mass_g") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("MARKETPLACE_MASS") from exc
    if not math.isfinite(mass_g) or mass_g < 0 or mass_g > MAX_MASS:
        raise ValueError("MARKETPLACE_MASS")
    kind = str(payload.get("kind") or "").strip().upper()
    if not kind:
        kind = infer_kind(category, material)
    if kind not in KINDS:
        raise ValueError("MARKETPLACE_KIND")
    if kind=='SERVICE' and mass_g!=0:raise ValueError('MARKETPLACE_SERVICE_HAS_NO_MASS')
    if kind == "ELEMENT" and material not in ELEMENT_SYMBOLS:
        if material in {"GOLD"}:
            material = "Au"
        elif material in {"SILVER"}:
            material = "Ag"
        elif material in {"COPPER"}:
            material = "Cu"
        else:
            kind = "SUBSTANCE"
    composition = _norm_composition(payload.get("composition"))
    previous_lives = _norm_lives(payload.get("previous_lives"))
    mint_raw = str(payload.get("mint") or "").strip()
    mint = validate_pubkey(mint_raw) if mint_raw else ""
    settlement = None
    if payload.get('settlement_asset_id'):
        from backend import omni_assets
        omni_assets.bootstrap()
        asset = omni_assets.asset(str(payload['settlement_asset_id']))
        if asset['metadata'] == 'DECIMALS_UNKNOWN':
            raise ValueError('MARKETPLACE_ASSET_DECIMALS_UNKNOWN')
        settlement = {'asset_id': asset['id'], 'symbol': asset['symbol'], 'decimals': asset['decimals'],
                      'price_atomic': str(omni_assets.amount_atomic(payload.get('price', '0'), asset['decimals']))}
    price = 0 if settlement else parse_sol_price(
        payload.get("price_lamports", payload.get("price_sol"))
    )
    result = {
        "title": title,
        "kind": kind,
        "category": category,
        "material": material,
        "description": description,
        "maker": maker,
        "origin": origin,
        "mass_g": round(mass_g, 4),
        "composition": composition,
        "previous_lives": previous_lives,
        "mint": mint,
        "price_lamports": price,
    }
    if settlement:
        result['settlement'] = settlement
    if payload.get('image_id'):
        from backend.marketplace_media import image_url
        if not image_url(payload['image_id'],STATE_DIR):raise ValueError('MARKETPLACE_IMAGE_NOT_IMPORTED')
        result['image_id']=payload['image_id']
    if payload.get('collection_name'):result['collection_name']=_clip(str(payload['collection_name']),80)
    if payload.get('nft_binding'):
        from backend import marketplace_protocols
        binding=payload['nft_binding']
        if mint or not isinstance(binding,dict) or set(binding)!={'chain_id','standard','collection','token_id'}:raise ValueError('MARKETPLACE_NFT_BINDING')
        reference=marketplace_protocols.identity(binding['chain_id'],binding['standard'],binding['collection'],binding['token_id'])
        result['nft_binding']=dict(reference,verification='DECLARED_REFERENCE_NOT_OWNERSHIP_PROOF')
    return result


def decorate_listing(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["kind"] = str(out.get("kind") or infer_kind(
        str(out.get("category") or ""),
        str(out.get("material") or ""),
    ))
    out["composition"] = _norm_composition(out.get("composition"))
    out["previous_lives"] = _norm_lives(out.get("previous_lives"))
    out["price_sol"] = format_sol(int(out.get("price_lamports") or 0))
    from backend.marketplace_media import image_url
    out['image_url']=image_url(out.get('image_id',''),STATE_DIR)
    out['visual_reference']='USER_SELECTED_IMAGE' if out['image_url'] else 'NO_IMAGE'
    out['provenance_state']='USER_DECLARED_NOT_INDEPENDENTLY_VERIFIED'
    out['receipt_protocol']='GG-721_LOCAL_PAPER'
    if out.get('settlement'):
        from backend.omni_assets import format_atomic
        settlement = out['settlement']
        out['price_label'] = format_atomic(int(settlement['price_atomic']), settlement['decimals'])+' '+settlement['symbol']
        out['settlement_asset_id'] = settlement['asset_id']
    else:
        out['price_label'] = out['price_sol']+' SOL'
        out['settlement_asset_id'] = ''
    out["owner_short"] = short_pubkey(str(out.get("owner") or ""))
    mint = str(out.get("mint") or "")
    out["mint_short"] = short_pubkey(mint) or (mint[:12] if mint else "UNBOUND")
    out["identity_short"] = str(out.get("identity_sha256") or "")[:12]
    out["state_short"] = str(out.get("state_sha256") or "")[:12]
    out["receipt"] = "paper:" + str(out.get("identity_sha256") or "")[:32]
    out["part_count"] = len(out["composition"])
    out["life_count"] = len(out["previous_lives"])
    return out


def category_rows(
    listings: list[dict[str, Any]],
    merkle: dict[str, Any],
) -> list[dict[str, Any]]:
    counts = {name: 0 for name in CATEGORIES}
    for row in listings:
        category = str(row.get("category") or "")
        if category in counts:
            counts[category] += 1
    roots = merkle.get("category_roots") or {}
    return [
        {
            "id": name,
            "label": name,
            "count": counts[name],
            "root_sha256": str(roots.get(name) or ""),
            "root_short": str(roots.get(name) or "")[:12],
        }
        for name in CATEGORIES
    ]


def list_item(raw: str | dict[str, Any]) -> dict[str, Any]:
    parsed = parse_listing(raw)
    wallet = load_wallet()
    owner = str(wallet.get("pubkey") or "")
    chain = load_network()
    if parsed.get('settlement'):
        owner = 'paper:seller'
        chain = parsed['settlement']['asset_id'].split('/')[0]
    listed_at = int(time.time())
    seed = {
        **parsed,
        "identity_version": 3,
        "listed_at": listed_at,
    }
    identity = hash_identity(seed)
    listing_id = "lst-" + identity[:16]
    catalog = load_catalog()
    if any(row.get("id") == listing_id for row in catalog):
        raise ValueError("MARKETPLACE_DUPLICATE")
    if len(catalog) >= MAX_LISTINGS:
        raise ValueError("MARKETPLACE_FULL")
    paper_mint = parsed.get("mint") or ("paper:" + identity[:32])
    row = {
        **seed,
        "id": listing_id,
        "mint": paper_mint,
        "owner": owner,
        "status": "LISTED",
        "network": chain,
        "mode": "TESTNET",
        "identity_sha256": identity,
        "state_sha256": "",
        "lifecycle": [
            {
                "kind": "MINTED",
                "ts": listed_at,
                "note": "paper receipt",
            }
        ],
    }
    row["state_sha256"] = hash_state(row)
    catalog.append(row)
    save_catalog(catalog)
    save_prefs(selected=listing_id)
    append_ledger(
        {
            "kind": "LIST",
            "listing_id": listing_id,
            "category": row["category"],
            "material": row["material"],
            "owner": owner,
            "identity_sha256": identity,
            "state_sha256": row["state_sha256"],
            "txid": "PAPER",
            "mode": "TESTNET",
        }
    )
    return decorate_listing(row)


def _mutate(listing_id: str, status: str, owner: str | None = None, transaction_receipt=None) -> dict[str, Any]:
    wanted = str(listing_id or "").strip()
    catalog = load_catalog()
    found: dict[str, Any] | None = None
    for row in catalog:
        if row.get("id") == wanted:
            found = row
            break
    if found is None:
        raise ValueError("MARKETPLACE_MISSING")
    if owner is not None:
        found["owner"] = owner
    found["status"] = status
    if transaction_receipt is not None:found['transaction_receipt']=transaction_receipt
    events = list(found.get("lifecycle") or [])
    events.append({"kind": status, "ts": int(time.time())})
    found["lifecycle"] = events[-40:]
    found["state_sha256"] = hash_state(found)
    save_catalog(catalog)
    save_prefs(selected=wanted)
    return decorate_listing(found)


def delist_item(listing_id: str) -> dict[str, Any]:
    catalog = load_catalog()
    wanted = str(listing_id or "").strip()
    row = next((item for item in catalog if item.get("id") == wanted), None)
    if row is None:
        raise ValueError("MARKETPLACE_MISSING")
    if str(row.get("status") or "") != "LISTED":
        raise ValueError("MARKETPLACE_STATUS")
    updated = _mutate(wanted, "DELISTED")
    append_ledger(
        {
            "kind": "DELIST",
            "listing_id": wanted,
            "category": updated.get("category"),
            "owner": updated.get("owner"),
            "identity_sha256": updated.get("identity_sha256"),
            "state_sha256": updated.get("state_sha256"),
            "txid": "PAPER",
            "mode": "TESTNET",
        }
    )
    return updated


def paper_buy(listing_id: str) -> dict[str, Any]:
    wallet = load_wallet()
    buyer = str(wallet.get("pubkey") or "")
    catalog = load_catalog()
    wanted = str(listing_id or "").strip()
    row = next((item for item in catalog if item.get("id") == wanted), None)
    if row is None:
        raise ValueError("MARKETPLACE_MISSING")
    if row.get('settlement'):
        buyer = 'paper:buyer'
    if not buyer:
        raise ValueError("MARKETPLACE_WALLET")
    if str(row.get("status") or "") != "LISTED":
        raise ValueError("MARKETPLACE_STATUS")
    seller = str(row.get("owner") or "")
    if seller and seller == buyer:
        raise ValueError("MARKETPLACE_SELF")
    identity = str(row.get("identity_sha256") or "")
    transaction={'schema':'gg.transaction-receipt.v1','object_id':wanted,'object_identity':identity,'previous_state':row.get('state_sha256',''),
                 'seller':seller,'buyer':buyer,'kind':row.get('kind','OBJECT'),'title':row.get('title',''),'recorded_at':int(time.time()),
                 'consideration':row.get('settlement') or {'asset_id':'legacy-solana-SOL','price_atomic':str(row.get('price_lamports',0)),'decimals':9,'symbol':'SOL'},
                 'settlement_state':'SIMULATED_NO_FUNDS_MOVED','delivery_state':'NOT_VERIFIED','mode':'LOCAL_PAPER'}
    receipt={'body':transaction,'digest':digest_json(transaction)}
    updated = _mutate(wanted, "SOLD", owner=buyer, transaction_receipt=receipt)
    append_ledger(
        {
            "kind": "BUY",
            "listing_id": wanted,
            "category": updated.get("category"),
            "from": seller,
            "to": buyer,
            "owner": buyer,
            "identity_sha256": identity,
            "state_sha256": updated.get("state_sha256"),
            "txid": "PAPER",
            "mode": "TESTNET",
        }
    )
    return updated


def set_filter(category: str) -> dict[str, Any]:
    return save_prefs(filter_name=category)


def list_element(symbol: str) -> dict[str, Any]:
    wanted = str(symbol or "").strip()
    name = dict(ELEMENTS).get(wanted)
    if not name:
        raise ValueError("MARKETPLACE_ELEMENT")
    catalog = load_catalog()
    for row in catalog:
        if str(row.get("kind") or "") == "ELEMENT" and str(row.get("material") or "") == wanted:
            save_prefs(selected=str(row.get("id") or ""))
            return decorate_listing(row)
    return list_item(
        {
            "title": name,
            "kind": "ELEMENT",
            "category": "MATERIAL",
            "material": wanted,
            "description": "Element receipt · " + wanted + " · " + name,
            "price_sol": "0",
        }
    )


def rebirth_item(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw or ""))
        except json.JSONDecodeError as exc:
            raise ValueError("MARKETPLACE_JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("MARKETPLACE_JSON")
    from_ids = _norm_lives(payload.get("previous_lives") or payload.get("from_ids"))
    if not from_ids:
        raise ValueError("MARKETPLACE_LIVES")
    catalog = load_catalog()
    by_id = {str(row.get("id") or ""): row for row in catalog}
    sources = [by_id[item] for item in from_ids if item in by_id]
    if len(sources) != len(from_ids):
        raise ValueError("MARKETPLACE_MISSING")
    composition: list[dict[str, Any]] = []
    for src in sources:
        parts = _norm_composition(src.get("composition"))
        if parts:
            composition.extend(parts)
        else:
            composition.append(
                {
                    "id": str(src.get("id") or ""),
                    "kind": str(src.get("kind") or "OBJECT"),
                    "symbol": str(src.get("material") or ""),
                    "title": str(src.get("title") or ""),
                    "mass_g": float(src.get("mass_g") or 0),
                }
            )
    mass = sum(float(part.get("mass_g") or 0) for part in composition)
    title = _clip(str(payload.get("title") or ""), MAX_TITLE)
    if not title:
        title = "Reborn · " + " + ".join(str(src.get("title") or "") for src in sources[:3])
    born = list_item(
        {
            "title": title,
            "kind": "OBJECT",
            "category": str(payload.get("category") or "ITEM"),
            "material": str(payload.get("material") or "MIXED"),
            "description": _clip(str(payload.get("description") or ""), MAX_DESCRIPTION)
            or "Reborn object. Materials carry previous lives.",
            "maker": str(payload.get("maker") or ""),
            "origin": str(payload.get("origin") or "rebirth"),
            "mass_g": mass,
            "composition": composition[:MAX_COMPOSITION],
            "previous_lives": from_ids,
            "price_sol": payload.get("price_sol") or "0",
        }
    )
    append_ledger(
        {
            "kind": "REBIRTH",
            "listing_id": born.get("id"),
            "from_ids": from_ids,
            "identity_sha256": born.get("identity_sha256"),
            "state_sha256": born.get("state_sha256"),
            "txid": "PAPER",
            "mode": "TESTNET",
        }
    )
    return born


def resolve_lives(
    listings: list[dict[str, Any]],
    listing: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not listing:
        return []
    by_id = {str(row.get("id") or ""): row for row in listings}
    rows: list[dict[str, Any]] = []
    for listing_id in _norm_lives(listing.get("previous_lives")):
        src = by_id.get(listing_id)
        if src is None:
            rows.append({"id": listing_id, "title": "gone", "status": "MISSING"})
            continue
        rows.append(decorate_listing(src))
    return rows


def element_rows(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    listed = {
        str(row.get("material") or ""): decorate_listing(row)
        for row in listings
        if str(row.get("kind") or "") == "ELEMENT"
    }
    out: list[dict[str, Any]] = []
    for symbol, name in ELEMENTS:
        hit = listed.get(symbol)
        out.append(
            {
                "symbol": symbol,
                "name": name,
                "listed": bool(hit),
                "listing_id": str((hit or {}).get("id") or ""),
                "receipt": str((hit or {}).get("receipt") or ""),
            }
        )
    return out


def select_listing(listing_id: str) -> dict[str, Any]:
    if not any(row.get('id')==listing_id for row in load_catalog()):raise ValueError('MARKETPLACE_REFERENCE_NOT_FOUND')
    return save_prefs(selected=listing_id)


def status_payload() -> dict[str, Any]:
    from backend import omni_assets
    omni_assets.bootstrap()
    omni_state=omni_assets.snapshot()
    wallet = load_wallet()
    chain = load_network()
    listings = load_catalog()
    prefs = load_prefs()
    filt = str(prefs.get("filter") or "ALL")
    selected_id = str(prefs.get("selected") or "")
    merkle = catalog_merkle(listings)
    visible = [
        decorate_listing(row)
        for row in listings
        if filt == "ALL"
        or str(row.get("category") or "") == filt
        or str(row.get("kind") or "") == filt
    ]
    selected = next(
        (row for row in visible if row.get("id") == selected_id),
        None,
    )
    if selected is None and selected_id:
        selected = next(
            (decorate_listing(row) for row in listings if row.get("id") == selected_id),
            None,
        )
    proof = listing_proof(listings, selected_id, merkle) if selected_id else None
    pubkey = str(wallet.get("pubkey") or "")
    legend = "MAINNET" if chain == "mainnet" else "TESTNET"
    return {
        "schema": SCHEMA,
        "legend": legend,
        "network": chain,
        "mode": "TESTNET",
        "chain": "solana",
        "settlement_assets": omni_state['assets'],
        "settlement_networks": omni_state['networks'],
        "default_settlement_asset": omni_state['selected_asset'],
        "collections": sorted({str(row.get('collection_name')) for row in listings if row.get('collection_name')}),
        "settlement_mode": "LOCAL_PAPER_RECEIPTS",
        "filter": filt,
        "filters": list(FILTERS),
        "kinds": list(KINDS),
        "categories": category_rows(listings, merkle),
        "materials": list(MATERIALS),
        "elements": element_rows(listings),
        "lives": resolve_lives(listings, selected),
        "listings": visible,
        "listing_count": len(listings),
        "visible_count": len(visible),
        "selected": selected,
        "proof": proof,
        "merkle": {
            "root_sha256": merkle.get("root_sha256") or "",
            "root_short": str(merkle.get("root_sha256") or "")[:12],
            "listing_count": merkle.get("listing_count") or 0,
            "domain": DOMAIN,
            "scope": SCOPE,
        },
        "wallet": {
            "account_count": len(omni_state['accounts']),
            "pubkey": pubkey,
            "label": wallet.get("label") or "WALLET · DISCONNECTED",
            "short": short_pubkey(pubkey),
            "connected": bool(pubkey),
            "network": chain,
        },
        "ledger": read_ledger()[-80:],
        "authority": "NONE",
        "note": "NFT is a paper receipt for a physical object or element. Mainnet trade stays locked.",
    }
