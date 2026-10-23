"""Regression tests for collection freshness and source-bound evidence handoff."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import osint_contract as osint, research_desk
from backend.osint_host import OsintHost


class OsintResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.enterContext(patch.object(research_desk, "ROOT", Path(self.directory.name)))
        self.enterContext(patch.object(osint, "_sources", copy.deepcopy(osint._sources)))
        self.enterContext(patch.object(osint, "_collections", {key: [] for key in osint._collections}))
        self.enterContext(patch.object(osint, "_histories", {key: [] for key in osint._histories}))
        self.enterContext(patch.object(osint, "_last_collect_at", 0.0))
        self.enterContext(patch.object(osint, "_last_generated_at", ""))
        self.enterContext(patch.object(osint, "_solar", {}))
        self.enterContext(patch.object(osint, "_rebuild_camera_index"))
        self.enterContext(patch.object(osint, "_rebuild_geo_lod"))
        self.enterContext(patch.object(osint, "_cached_alpr_total", return_value=0))
        self.enterContext(patch.object(osint, "_render_rows", side_effect=lambda rows, *args: rows))
        self.enterContext(patch.object(osint, "_read_public", side_effect=AssertionError("unexpected network")))

    def collect(self, rows: list[dict], extras: dict | None = None) -> dict:
        with patch.object(osint, "_COLLECTORS", {"aircraft": lambda: (rows, extras or {})}):
            return osint.collect_snapshot(force=True)

    def seed(self, kind: str = "aircraft") -> dict:
        row = {"id": "sample", "callsign": "GG123", "lat": 59.3, "lon": 18.1,
               "alt_m": 9000, "heading": 120, "source": "api.adsb.lol",
               "source_url": "https://api.adsb.lol/v2/lat/59.300/lon/18.100/dist/350"}
        osint._collections[kind] = [row]
        osint._sources[kind].update(status="OK", last_success_at=osint._utc_now())
        return row

    def test_failed_attempt_preserves_success_and_records_age(self) -> None:
        self.collect([{"id": "sample"}])
        success = osint._sources["aircraft"]["last_success_at"]
        with patch.object(osint, "_utc_now", return_value="2099-01-01T00:00:00Z"), patch.object(
            osint, "_COLLECTORS", {"aircraft": lambda: (_ for _ in ()).throw(OSError("offline"))}
        ):
            snapshot = osint.collect_snapshot(force=True)
        row = osint._sources["aircraft"]
        self.assertEqual(row["last_success_at"], success)
        self.assertEqual(row["last_updated"], success)
        self.assertEqual(row["last_attempt_at"], "2099-01-01T00:00:00Z")
        self.assertEqual(row["status"], "ERROR")
        self.assertEqual(osint._collections["aircraft"], [{"id": "sample"}])
        self.assertTrue(snapshot["stale"])

    def test_cached_aircraft_is_not_a_new_success_or_history_sample(self) -> None:
        self.collect([{"id": "sample"}])
        success = osint._sources["aircraft"]["last_success_at"]
        self.collect([{"id": "sample"}], {"stale": True, "region": "LAST GOOD"})
        self.assertEqual(osint._sources["aircraft"]["status"], "STALE")
        self.assertEqual(osint._sources["aircraft"]["last_success_at"], success)
        self.assertEqual(osint._histories["aircraft"], [1])

    def test_success_expires_without_another_network_request(self) -> None:
        self.seed()
        old = (datetime.now(timezone.utc) - timedelta(seconds=osint.CACHE_TTL_SECONDS + 10)).isoformat()
        osint._sources["aircraft"]["last_success_at"] = old
        snapshot = osint.snapshot()
        source = next(row for row in snapshot["sources"] if row["id"] == "aircraft")
        self.assertEqual(source["status"], "STALE")
        self.assertGreaterEqual(source["age_seconds"], osint.CACHE_TTL_SECONDS)
        self.assertTrue(snapshot["stale"])
        self.assertEqual(osint._sources["aircraft"]["status"], "OK")

    def test_partial_camera_collection_is_visible(self) -> None:
        with patch.object(osint, "_COLLECTORS", {
            "cameras": lambda: ([{"id": "bundled"}], {"error": "TfL unavailable", "total": 1})
        }):
            osint.collect_snapshot(force=True)
        self.assertEqual(osint._sources["cameras"]["status"], "PARTIAL")
        self.assertIn("TfL", osint._sources["cameras"]["error"])

    def test_evidence_resolves_backend_record_and_is_idempotent(self) -> None:
        row = self.seed()
        host = OsintHost()
        self.addCleanup(host.shutdown)
        for _ in range(2):
            result = json.loads(host.recordEvidence("aircraft", "sample"))
            self.assertEqual(result, {"status": "EVIDENCE_RECORDED"})
        cards = research_desk.snapshot()["evidence"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["provenance"], "SOURCE_REPORTED")
        self.assertEqual(cards[0]["source_url"], row["source_url"])
        details = json.loads(cards[0]["details_json"])
        self.assertEqual(details["source"], "api.adsb.lol")
        self.assertEqual(details["alt_m"], "9000")
        self.assertEqual(details["verification"], "NOT_INDEPENDENTLY_CORROBORATED")

    def test_adsb_collector_keeps_actual_endpoint_on_each_record(self) -> None:
        def response(url: str, **kwargs) -> bytes:
            identifier = "aabb01" if "airplanes.live" in url else "aabb02"
            return json.dumps({"ac": [{"hex": identifier, "lat": 59.3, "lon": 18.1}]}).encode()

        with patch.object(osint, "AIRCRAFT_SAMPLE_POINTS", [(59.3, 18.1, 350)]), patch.object(
            osint, "_read_map_api", side_effect=response
        ):
            rows = osint._collect_adsb_sample()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["source"] for row in rows}, {"api.airplanes.live", "api.adsb.lol"})
        for row in rows:
            self.assertEqual(row["source"], urlparse(row["source_url"]).hostname)

    def test_unknown_or_cluster_selection_does_not_write(self) -> None:
        self.seed()
        osint._collections["aircraft"].append({"id": "cluster", "cluster": True})
        host = OsintHost()
        self.addCleanup(host.shutdown)
        for kind, event in (("aircraft", "missing"), ("aircraft", "cluster"), ("forged", "sample")):
            self.assertEqual(json.loads(host.recordEvidence(kind, event))["status"], "OBSERVATION_NOT_FOUND")
        self.assertEqual(research_desk.snapshot()["evidence"], [])

    def test_references_and_estimated_locations_keep_provenance(self) -> None:
        reference = osint.observation_evidence("conflicts", osint.REFERENCE_ZONES[0]["id"])
        self.assertEqual(reference["provenance"], "REFERENCE")
        self.assertEqual(reference["details"]["location_precision"], "REFERENCE_LOCATION")
        osint._collections["news"] = osint._normalize_news(ET.fromstring(
            '<rss><channel><item><guid>sample</guid><title>London event</title>'
            '<description>Reported in a public news feed</description></item></channel></rss>'
        ))
        news = osint.observation_evidence("news", "sample")
        self.assertEqual(news["details"]["location_precision"], "PLACE_NAME_ESTIMATE")

    def test_research_snapshot_exposes_ingested_sources(self) -> None:
        research_desk.ingest_source({"title": "NSA assessment", "content": "Source-backed findings"})
        self.assertEqual(research_desk.snapshot()["sources"][0]["title"], "NSA assessment")


if __name__ == "__main__":
    unittest.main()
