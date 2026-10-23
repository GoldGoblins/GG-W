"""Finite public-data comparison; writes results only to the requested output.

Uses temporary paper state. Parameters stay frozen; no live orders or tuning.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import crypto_bots, crypto_market, crypto_contract


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bars", type=int, default=400)
    parser.add_argument("--pair", choices=sorted(crypto_market.PAIRS), action="append")
    args = parser.parse_args(argv)
    if not 200 <= args.bars <= 1000:
        parser.error("bars must be 200–1000")
    results = []
    with tempfile.TemporaryDirectory(prefix="gg-crypto-public-research-") as tmp:
        original = crypto_contract.STATE_DIR
        crypto_contract.STATE_DIR = Path(tmp)
        try:
            for pair in args.pair or sorted(crypto_market.PAIRS):
                frames = {tf: crypto_market._request(pair, tf, limit=args.bars if tf == "1h" else 400)
                          for tf in ("1h", "4h", "1d")}
                frames["15m"] = crypto_market.history(pair, "15m", frames["1h"]["times"][0] - 80 * 900, max_pages=5)
                report = crypto_bots.compare_books(frames, book_id="gg")
                rows = []
                for row in report["comparison"]:
                    if row["state"] != "DONE":
                        rows.append(row)
                        continue
                    full = crypto_bots.run_backtest(frames, book_id=row["book"], persist=False)
                    rows.append({**row, "pnl_token_equivalent": full["pnl_sol"],
                        "return_token_equivalent_pct": full["return_sol_pct"],
                        "actual_tokens": full["inventory_tokens"], "quote_balance": full["quote_balance"],
                        "buy_hold_return_pct": full["benchmarks"]["buy_and_hold"]["return_pct"],
                        "fills": full.get("fills"), "range": full["range"]})
                results.append({"pair": pair, "data": report["data"], "cost_model": report["cost_model"], "rows": rows})
                print(pair, report["range"], flush=True)
                for row in rows:
                    print(row["book"], row["state"], "return", row.get("return_pct"),
                          "holdout", (row.get("holdout") or {}).get("return_pct"), flush=True)
        finally:
            crypto_contract.STATE_DIR = original
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"as_of": time.time(), "results": results,
        "validation": "Descriptive frozen-parameter comparison; final 20% is too short to establish a durable edge."
        }, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
