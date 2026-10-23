"""Verify bounded indexing against the real corpus and save concise evidence.

Writes only the workflow catalog and a new report under project docs. Original
assets are read and checked by before/after stamps. Finite explicit collections
and batches; no automatic world activation or source conversion.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
from backend import game_workflow_common as common, game_workflow_collections as collections
from backend import game_workflow_scout as scout, game_engine_assets as assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.store:
        common.ROOT = Path(args.store).resolve()
    output = Path(args.output).resolve()
    if not output.is_relative_to((PROJECT / "docs").resolve()) or output.exists():
        raise ValueError("SELECT_NEW_PROJECT_DOCS_REPORT")
    root = assets.ASSET_ROOT
    _, before = collections.manifest(str(root))
    plan = collections.plan(str(root))
    began, results, batches = time.monotonic(), [], 0
    for collection in plan["collections"]:
        parameters = {key: collection[key] for key in ("recursive", "partition", "partitions")}
        result = collections.batch(collection["path"], "GG local library", batch_files=128, **parameters)
        batches += 1
        for _ in range(scout.MAX_CATALOG):
            if result["status"] != "STAGED":
                break
            result = collections.batch(collection["path"], "GG local library", cursor=result["cursor"], batch_files=128, **parameters)
            batches += 1
        if result["status"] != "INDEXED":
            raise ValueError("COLLECTION_DID_NOT_COMPLETE")
        results.append({"collection": collection, "result": result})
        print(f"COLLECTION_DONE {collection['relative']}: {result['indexed']} indexed / {result['invalid']} invalid / {result['oversize_files']} oversized", flush=True)
    db = scout._db()
    try:
        rows = list(db.execute("SELECT * FROM assets WHERE game='GG local library'"))
        formats = Counter(r["format"] for r in rows)
        coverage = Counter(r["coverage"] for r in rows)
        unresolved = [r["relative"] for r in rows if json.loads(r["observation"]).get("dependency_status") == "INCOMPLETE"]
        invalid = [{"path": str(Path(r["root"]) / r["relative"]), "reason": json.loads(r["observation"])["limits"]}
                   for r in rows if r["coverage"] == "INVALID"]
        variant = next(r for r in rows if r["relative"] == "gg-crew-briarstride-articulated-v1.glb")
    finally:
        db.close()
    relations = scout.relations(variant["key"])
    rig_owners = [{"path": r["path"], "catalog_owners": r["catalog_owners"]} for r in relations["resources"] if "/rig-" in r["path"] or "/animations-" in r["path"]]
    _, after = collections.manifest(str(root))
    if before != after:
        raise ValueError("SOURCE_CORPUS_CHANGED_DURING_VERIFICATION")
    report = {"schema": "gg.local-asset-improvement-verification.v1", "status": "VERIFIED",
              "source_files": len(before), "source_stamps_unchanged": True, "catalog_store": str(common.ROOT),
              "collections": results, "batches": batches, "indexed": sum(r["result"]["indexed"] for r in results),
              "oversized": sum(r["result"]["oversize_files"] for r in results),
              "formats": dict(formats), "coverage": dict(coverage), "invalid_assets": invalid,
              "incomplete_dependencies": unresolved, "shared_character_resources": rig_owners,
              "elapsed_s": round(time.monotonic() - began, 3),
              "limits": ["Source stamps and catalog hashes checked; opaque files are indexed by identity, not decoded.",
                         "Incomplete dependencies and unsupported/malformed exports are reported separately from successful metadata coverage."]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "source_files", "indexed", "oversized", "batches", "formats", "coverage", "elapsed_s")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
