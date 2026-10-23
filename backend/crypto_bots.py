"""Switchable paper books on the CRYPTO surface.

KEEP, WATCH and PARK are editorial catalogue labels. They are not measured
performance verdicts; common backtests provide separate descriptive evidence.

GG = house swing. STOCH+RSI = werkkrew StochRSITEMA, parked.
DCA = hold SOL, harvest 80% of cycle profit at highs, buy it back at lows.
DCA+SWING = DCA bag rules with a many-oscillator swing vote for timing.
HYBRID = GG MTF vote + TimesFM forecast gate + paper barriers.
GG+ = the composed book: vol size, Front Man veto, barriers, fee-band hold.
Not a Freqtrade process. MAINNET not used.
"""
from __future__ import annotations

from typing import Any

from backend import crypto_trader, crypto_backtest

BOOKS = (
    {
        "id": "gg",
        "name": "GG",
        "source": "house swing book",
        "verdict": "KEEP",
        "why": "SOL is home. A fill must clear 80 bps, and 15% of the bag never leaves.",
    },
    {
        "id": "stoch_rsi",
        "name": "STOCH+RSI",
        "source": "werkkrew StochRSITEMA (freqtrade strategy, GG runner)",
        "verdict": "PARK",
        "why": "Original ROI 0.19503 and stop -0.02205 are fixed research parameters; independent validation is required.",
    },
    {
        "id": "dca",
        "name": "DCA",
        "source": "harvest 80% of cycle profit at highs, buy it back at lows",
        "verdict": "KEEP",
        "why": "Harvests 80% of a cycle gain and skips fee-heavy clips. Remaining SOL still carries market risk.",
    },
    {
        "id": "dca_swing",
        "name": "DCA+SWING",
        "source": "DCA harvest + swing K/D/TEMA/MACD + 20 osc vote",
        "verdict": "WATCH",
        "why": "Harvest rules plus oscillator timing. Added complexity needs separate validation.",
    },
    {
        "id": "hybrid",
        "name": "HYBRID",
        "source": "GG MTF + TimesFM + Hummingbot-style triple barrier (paper)",
        "verdict": "WATCH",
        "why": "Paper barriers with an optional local forecast. The report identifies the model or deterministic fallback.",
    },
    {
        "id": "optimal",
        "name": "GG+",
        "source": "GG band + vol size + Front Man + barriers + fee hold (paper)",
        "verdict": "KEEP",
        "why": "Vol sizes the clip, Front Man vetoes a chase, and a time exit inside the fee band is held.",
    },
)


def catalog() -> list[dict[str, str]]:
    return [{**row, "verdict_kind": "EDITORIAL · NOT PERFORMANCE PROOF"} for row in BOOKS]


def selected() -> str:
    bid = str(crypto_trader.load_state().get("book") or "gg")
    if bid not in {row["id"] for row in BOOKS}:
        return "gg"
    return bid


def set_book(book_id: str) -> str:
    bid = str(book_id or "gg")
    if bid not in {row["id"] for row in BOOKS}:
        bid = "gg"
    state = crypto_trader.load_state()
    state["book"] = bid
    crypto_trader.save_state(state)
    return bid


def _native_backtest(frames: dict[str, dict[str, Any]], bid: str) -> dict[str, Any]:
    if bid == "stoch_rsi":
        from backend import crypto_bot_stoch_rsi

        report = crypto_bot_stoch_rsi.run_backtest(frames)
    elif bid == "dca":
        from backend import crypto_bot_dca

        report = crypto_bot_dca.run_backtest(frames)
    elif bid == "dca_swing":
        from backend import crypto_bot_dca_swing

        report = crypto_bot_dca_swing.run_backtest(frames)
    elif bid == "hybrid":
        from backend import crypto_hybrid

        report = crypto_hybrid.run_backtest(frames)
    elif bid == "optimal":
        from backend import crypto_optimal

        report = crypto_optimal.run_backtest(frames)
    else:
        report = crypto_trader.run_flow_backtest(frames)
    report["book"] = bid
    return report


def run_backtest(frames: dict[str, dict[str, Any]], *, book_id: str | None = None, persist: bool = True) -> dict[str, Any]:
    bid = book_id or selected()
    if bid not in {row["id"] for row in BOOKS}:
        raise ValueError("CRYPTO_BOOK")
    prepared = crypto_backtest.prepare(frames)
    token = crypto_backtest.PERSIST.set(False)
    try:
        report = crypto_backtest.finalize(_native_backtest(prepared, bid), prepared)
    finally:
        crypto_backtest.PERSIST.reset(token)
    if persist:
        crypto_trader.save_backtest(report)
    return report


def run_step(frames: dict[str, dict[str, Any]], *, book_id: str,
             continuation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Advance a native strategy at the newest closed bar, with no wallet effects."""
    if book_id not in {row["id"] for row in BOOKS}:
        raise ValueError("CRYPTO_BOOK")
    prepared = crypto_backtest.prepare(frames)
    primary = "1h" if "1h" in prepared else next(iter(prepared))
    prepared[primary]["evaluation_start"] = len(prepared[primary]["closes"]) - 1
    tokens = [crypto_backtest.PERSIST.set(False), crypto_backtest.STREAM.set(True),
              crypto_backtest.CONTINUATION.set(continuation)]
    try:
        report = _native_backtest(prepared, book_id)
        if "continuation" not in report:
            raise ValueError("CRYPTO_CONTINUATION_MISSING")
        return {key: report[key] for key in ("continuation", "events", "inventory_tokens", "quote_balance")}
    finally:
        for variable, token in zip((crypto_backtest.PERSIST, crypto_backtest.STREAM, crypto_backtest.CONTINUATION), tokens):
            variable.reset(token)


def compare_books(frames: dict[str, dict[str, Any]], *, book_id: str | None = None) -> dict[str, Any]:
    """Same data/costs; frozen rules also run on an untouched final 20%."""
    prepared = crypto_backtest.prepare(frames)
    primary = "1h" if "1h" in prepared else next(iter(prepared))
    src = prepared[primary]
    cutoff = max(80, int(len(src["closes"]) * .8))
    holdout = {**prepared, primary: {**src, **{k: src[k][cutoff - 80:] for k in ("highs", "lows", "closes", "volumes", "times", "opens") if k in src}}}
    chosen = book_id or selected()
    if chosen not in {row["id"] for row in BOOKS}:
        raise ValueError("CRYPTO_BOOK")
    reports, rows = {}, []
    for book in BOOKS:
        bid = book["id"]
        try:
            report = run_backtest(prepared, book_id=bid, persist=False)
            final = run_backtest(holdout, book_id=bid, persist=False)
            reports[bid] = report
            rows.append({"book": bid, "name": book["name"], "state": "DONE", **report["metrics"],
                         "holdout": final["metrics"], "holdout_range": final["range"],
                         "return_token_equivalent_pct": report["return_sol_pct"],
                         "inventory_tokens": report["inventory_tokens"], "quote_balance": report["quote_balance"],
                         "holdout_return_token_equivalent_pct": final["return_sol_pct"],
                         "model": report.get("forecast_model") or report.get("timesfm_model") or "deterministic",
                         "model_note": report.get("timesfm_error") or "",
                         "holdout_benchmarks": final["benchmarks"]})
        except Exception as exc:
            # A strategy failure must not discard evidence from the other books.
            rows.append({"book": bid, "name": book["name"], "state": "ERROR", "error": type(exc).__name__ + ": " + str(exc)[:160]})
    if chosen not in reports:
        raise RuntimeError("CRYPTO_SELECTED_BACKTEST_FAILED:" + next(str(row.get("error")) for row in rows if row["book"] == chosen))
    report = reports[chosen]
    report["comparison"] = rows
    report["evaluation"] = {"selection": "FROZEN_PARAMETERS", "holdout_pct": 20, "trial_count": len(BOOKS),
                            "note": "Final period is descriptive out-of-sample evidence; no automatic winner or parameter selection."}
    crypto_trader.save_backtest(report)
    return report
