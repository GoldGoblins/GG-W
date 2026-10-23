"""Bounded standalone paper worker. No keys, signing, orders or service install."""
from pathlib import Path
import argparse
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import crypto_market, crypto_paper


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", choices=sorted(crypto_paper.PAIRS), required=True)
    parser.add_argument("--cycles", type=int, default=1, help="Finite number of checks (1–1000).")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--enable-all", action="store_true", help="Explicitly enable all six PAPER accounts for this pair.")
    args = parser.parse_args(argv)
    if not 1 <= args.cycles <= 1000 or not 60 <= args.poll_seconds <= 3600:
        parser.error("cycles must be 1–1000; poll-seconds must be 60–3600")
    if args.enable_all:
        crypto_paper.set_all(args.pair, True)
    for index in range(args.cycles):
        error = None
        try:
            if crypto_paper.due(args.pair):
                crypto_paper.advance(args.pair, crypto_market.recent_frames(args.pair))
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)[:160]
            crypto_paper.data_error(args.pair, error)
        summary = crypto_paper.snapshot(args.pair)
        print(json.dumps({"mode":"PAPER_ONLY", "pair":args.pair, "error":error,
            "accounts":[{key:row[key] for key in ("book","status","tokens","quote","pnl_quote","processed_ts")} for row in summary["accounts"]]}, ensure_ascii=False), flush=True)
        if index + 1 < args.cycles:
            time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
