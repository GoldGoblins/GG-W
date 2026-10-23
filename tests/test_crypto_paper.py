"""Regression checks for strategy continuation, closed bars and paper accounting."""
import copy
import json
import math
import os
from pathlib import Path
import time
import tempfile
import unittest
from unittest.mock import patch
from backend import crypto_backtest as bt, crypto_bots as bots, crypto_paper as paper, crypto_market as market
from backend import crypto_hybrid as hybrid, crypto_host as host, crypto_contract as contract

BASE = 1700002800

def _paper_tick_in_child(raw, now, state_dir):
    contract.STATE_DIR = Path(state_dir)
    paper.advance("SOLUSDT", {"1h": raw}, now=now)

def frame(n=160, pair="SOLUSDT", interval="1h"):
    step = bt.BAR_SECONDS[interval]
    prices = [100 + 18 * math.sin(i/9) + 2 * math.sin(i/2) for i in range(n)]
    return dict(times=[BASE+i*step for i in range(n)], opens=prices[:], closes=prices,
                highs=[p*1.015 for p in prices], lows=[p*.985 for p in prices], volumes=[1000]*n,
                symbol=pair, source="offline-fixture", closed_only=True)

def prefix(raw, n):
    return {**raw, **{k:raw[k][:n] for k in ("times","opens","closes","highs","lows","volumes")}}

class Paper(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="gg-paper-test-")
        self.addCleanup(directory.cleanup)
        state = patch.object(contract, "STATE_DIR", Path(directory.name))
        state.start()
        self.addCleanup(state.stop)
        for pair in sorted(paper.PAIRS):
            for book in bots.BOOKS:
                paper.reset(pair,book["id"])

    def test_all_six_resume_without_reseeding_and_match_batch(self):
        raw=frame(165); raw["evaluation_start"]=95
        for book in bots.BOOKS:
            bid=book["id"]
            expected=bots.run_backtest({"1h":raw},book_id=bid,persist=False)
            checkpoint=None; result=None
            for n in range(96,166):
                result=bots.run_step({"1h":prefix(raw,n)},book_id=bid,continuation=checkpoint)
                # Real serialization boundary, just like an app restart.
                checkpoint=json.loads(json.dumps(result["continuation"],allow_nan=False))
            with self.subTest(book=bid):
                self.assertAlmostEqual(result["inventory_tokens"],expected["inventory_tokens"],places=7)
                self.assertAlmostEqual(result["quote_balance"],expected["quote_balance"],places=5)

    def test_restart_and_duplicate_bar_are_idempotent_and_pair_separated(self):
        raw=frame(96); now=raw["times"][-1]+3600
        paper.set_all("SOLUSDT",True)
        first=paper.advance("SOLUSDT",{"1h":raw},now=now)
        persisted=paper._path("SOLUSDT").read_bytes()
        second=paper.advance("SOLUSDT",{"1h":raw},now=now)
        self.assertEqual(first,second)
        self.assertEqual(persisted,paper._path("SOLUSDT").read_bytes())
        self.assertTrue(all(r["status"]=="RUNNING" for r in second["accounts"]))
        self.assertTrue(all(r["equity_quote"]==200 for r in paper.snapshot("KASUSDT")["accounts"]))
        self.assertFalse(paper.due("SOLUSDT",now))

    def test_pause_skips_historical_orders_and_restarts_at_latest(self):
        raw=frame(120)
        paper.set_enabled("SOLUSDT","dca",True)
        paper.advance("SOLUSDT",{"1h":prefix(raw,96)},now=raw["times"][95]+3600)
        paper.set_enabled("SOLUSDT","dca",False)
        paper.set_enabled("SOLUSDT","dca",True)
        paper.advance("SOLUSDT",{"1h":raw},now=raw["times"][-1]+3600)
        account=paper._load("SOLUSDT")["accounts"]["dca"]
        self.assertEqual(account["processed_ts"],raw["times"][-1])
        self.assertEqual(account.get("recovery_bars",0),0)

    def test_stale_wrong_pair_and_missing_bar_never_trade(self):
        raw=frame(96); now=raw["times"][-1]+3600
        paper.set_enabled("SOLUSDT","dca",True)
        with self.assertRaisesRegex(ValueError,"STALE"):
            paper.advance("SOLUSDT",{"1h":raw},now=now+10800)
        with self.assertRaisesRegex(ValueError,"DATA_PAIR"):
            paper.advance("SOLUSDT",{"1h":frame(96,"KASUSDT")},now=now)
        paper.advance("SOLUSDT",{"1h":raw},now=now)
        shifted=frame(96)
        shifted["times"]=[t+100*3600 for t in shifted["times"]]
        result=paper.advance("SOLUSDT",{"1h":shifted},now=shifted["times"][-1]+3600)
        row=next(r for r in result["accounts"] if r["book"]=="dca")
        self.assertEqual(row["status"],"GAP")
        with self.assertRaisesRegex(ValueError,"RESET_REQUIRED"):
            paper.set_enabled("SOLUSDT","dca",True)

    def test_auxiliary_token_pair_cannot_leak_into_another_market(self):
        with self.assertRaisesRegex(ValueError,"DATA_PAIR_MIX"):
            bt.prepare({"1h":frame(96),"15m":frame(400,"KASUSDT","15m")})

    def test_loss_stop_liquidates_inventory_and_requires_reset(self):
        raw=frame(97); now=raw["times"][95]+3600
        paper.set_enabled("SOLUSDT","dca",True)
        paper.advance("SOLUSDT",{"1h":prefix(raw,96)},now=now)
        raw["closes"][-1]=raw["opens"][-1]=50
        raw["highs"][-1]=51; raw["lows"][-1]=49
        result=paper.advance("SOLUSDT",{"1h":raw},now=now+3600)
        row=next(r for r in result["accounts"] if r["book"]=="dca")
        self.assertEqual(row["status"],"RISK_HALT")
        self.assertEqual(row["tokens"],0)
        self.assertGreater(row["quote"],0)
        self.assertFalse(row["enabled"])
        paper.set_enabled("SOLUSDT","dca",False)
        paper.set_all("SOLUSDT",False)
        paper.set_all("SOLUSDT",True)
        halted=next(r for r in paper.snapshot("SOLUSDT")["accounts"] if r["book"]=="dca")
        self.assertEqual(halted["status"],"RISK_HALT")
        self.assertEqual(halted["tokens"],0)
        self.assertFalse(halted["enabled"])
        with self.assertRaisesRegex(ValueError,"RESET_REQUIRED"):
            paper.set_enabled("SOLUSDT","dca",True)

    def test_one_book_failure_does_not_stop_other_books(self):
        raw=frame(96); native=bots.run_step
        def fail(frames,book_id,continuation):
            if book_id=="dca": raise AttributeError("regression fixture")
            return native(frames,book_id=book_id,continuation=continuation)
        paper.set_all("SOLUSDT",True)
        with patch.object(bots,"run_step",side_effect=fail):
            result=paper.advance("SOLUSDT",{"1h":raw},now=raw["times"][-1]+3600)
        self.assertEqual(sum(r["status"]=="RUNNING" for r in result["accounts"]),5)
        self.assertEqual(next(r for r in result["accounts"] if r["book"]=="dca")["status"],"ERROR")

    def test_data_error_recovers_and_snapshot_marks_current_price(self):
        raw=frame(120)
        paper.set_enabled("SOLUSDT","dca",True)
        paper.advance("SOLUSDT",{"1h":prefix(raw,96)},now=raw["times"][95]+3600)
        paper.data_error("SOLUSDT","public feed unavailable")
        result=paper.advance("SOLUSDT",{"1h":raw},now=raw["times"][-1]+3600)
        row=next(r for r in result["accounts"] if r["book"]=="dca")
        self.assertIsNone(row["error"])
        self.assertEqual(row["status"],"RUNNING")
        self.assertAlmostEqual(row["equity_quote"],row["tokens"]*result["price"]+row["quote"])

    def test_snapshot_never_waits_for_strategy_inference(self):
        import threading
        held=threading.Event(); release=threading.Event()
        def writer():
            with paper._transaction():
                held.set(); release.wait(2)
        thread=threading.Thread(target=writer); thread.start(); held.wait(2)
        try:
            start=time.monotonic(); paper.snapshot("SOLUSDT")
            self.assertLess(time.monotonic()-start,.2)
        finally:
            release.set(); thread.join(2)

    def test_two_processes_cannot_duplicate_a_closed_bar(self):
        import multiprocessing
        raw=frame(96); now=raw["times"][-1]+3600
        paper.set_enabled("SOLUSDT","gg",True)
        ctx=multiprocessing.get_context("spawn" if os.name == "nt" else "fork")
        workers=[ctx.Process(target=_paper_tick_in_child, args=(raw, now, str(contract.STATE_DIR))) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers:
            worker.join(10)
            if worker.is_alive(): worker.terminate(); worker.join()
            self.assertEqual(worker.exitcode,0)
        before=paper.snapshot("SOLUSDT")
        paper.advance("SOLUSDT",{"1h":raw},now=now)
        self.assertEqual(before,paper.snapshot("SOLUSDT"))
        self.assertEqual(len({json.dumps(e, sort_keys=True) for e in before["events"]}),len(before["events"]))

    def test_forward_fills_respect_market_price_and_costs(self):
        from backend import crypto_trader as trader
        for flag in (True,False):
            amount,venue=trader._paper_fill(100_000_000,0,250_000_000,flag,True)
            self.assertEqual(amount,398_600_000)
            proceeds,_=trader._paper_fill(0,amount,250_000_000,flag,False)
            self.assertEqual(proceeds,99_301_225)
            self.assertIn("paper",venue)

    def test_public_gate_base_volume_and_closed_bar_filter(self):
        stamp=BASE
        rows=[[str(stamp),"9000","100","102","99","101","90","true"],
              [str(stamp+3600),"9000","100","102","99","101","90","false"]]
        result=market.parse(rows,"KASUSDT","1h",now=stamp+7200)
        self.assertEqual(result["volumes"],[90.0])
        self.assertEqual(result["opens"],[101.0])
        self.assertEqual(result["times"],[stamp])

    def test_gap_stop_uses_traded_price_and_forecast_schedule_is_causal(self):
        executor=hybrid.PaperPositionExecutor(0,BASE,100,hybrid.HybridConfig(stop_loss_bps=500))
        hit=executor.check(1,85,79,84,80)
        self.assertEqual(hit[1],80)
        cfg=hybrid.HybridConfig()
        earlier=hybrid._forecast_indices(80,200,cfg)
        later=hybrid._forecast_indices(80,1000,cfg)
        self.assertEqual(earlier,{i for i in later if i<200})

    def test_auxiliary_candles_use_primary_close_and_preserve_open_alignment(self):
        raw=frame(4005); fast=frame(16020,interval="15m")
        out=bt.prepare({"1h":raw,"15m":fast})
        self.assertEqual(len(out["1h"]["opens"]),4000)
        self.assertEqual(out["1h"]["opens"][0],raw["opens"][5])
        self.assertEqual(out["15m"]["times"][-1]+900,out["1h"]["times"][-1]+3600)

if __name__=="__main__": unittest.main(argv=[__file__],verbosity=2)
