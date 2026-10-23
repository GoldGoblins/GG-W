#!/usr/bin/env python3
"""Pack/unpack T-lines. Lexicon is the only token list."""
from __future__ import annotations

import sys
from pathlib import Path

LEX = Path(__file__).with_name("lexicon.txt")


def load_lex() -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in LEX.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or "\t" not in line:
            continue
        tok, meaning = line.split("\t", 1)
        out[tok.strip()] = meaning.strip()
    return out


def encode(text: str, lex: dict[str, str]) -> str:
    low = text.lower()
    hits: list[str] = []
    for tok in lex:
        if tok in ("T", "TS", "Y", "R", "A=0"):
            continue
        key = tok.lower()
        if key in low or lex[tok].split("—")[0].strip().lower() in low:
            if tok not in hits:
                hits.append(tok)
    if not hits:
        return "T // M:TS Y A=0 // N:unknown // R:look // D:names // H:T // R:look"
    now = " ".join(hits[:6])
    round_t = " ".join(hits[:2])
    nxt = " ".join(hits[2:4]) or "look"
    return f"T // M:TS Y A=0 // N:{now} // R:{round_t} // D:look // H:T // R:{nxt}"


def decode(line: str, lex: dict[str, str]) -> str:
    parts = [p.strip() for p in line.split("//")]
    rows: list[str] = []
    for part in parts:
        words = part.split()
        for w in words:
            key = w[:-1] if w.endswith(":") else w
            if key in lex:
                rows.append(f"{w}  {lex[key]}")
            else:
                rows.append(f"{w}")
    return "\n".join(rows)


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: pack.py encode|decode <text>", file=sys.stderr)
        return 2
    lex = load_lex()
    cmd = sys.argv[1]
    text = " ".join(sys.argv[2:])
    if cmd == "encode":
        print(encode(text, lex))
        return 0
    if cmd == "decode":
        print(decode(text, lex))
        return 0
    print("usage: pack.py encode|decode <text>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
