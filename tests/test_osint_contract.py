#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import osint_contract

    assert osint_contract.SAFE_SCOPE == "PUBLIC_READ_ONLY"
    assert len(osint_contract.SOURCE_CATALOG) == 9
    assert all(
        source["url"] in osint_contract.ALLOWED_SOURCE_URLS
        for source in osint_contract.SOURCE_CATALOG
    )
    try:
        osint_contract._read_public("https://example.invalid/not-allowlisted")
    except ValueError:
        pass
    else:
        raise AssertionError("arbitrary OSINT URL was accepted")
    try:
        osint_contract._read_map_api("https://example.invalid/route")
    except ValueError:
        pass
    else:
        raise AssertionError("arbitrary map API host was accepted")
    empty_route = osint_contract.plan_driving_route(["gothenburg"])
    assert empty_route["ok"] is False

    earthquakes = osint_contract._normalize_earthquakes(
        {
            "features": [
                {
                    "id": "test-quake",
                    "geometry": {"coordinates": [18.1, 59.3, 12.5]},
                    "properties": {
                        "mag": 4.2,
                        "place": "Test region",
                        "time": 1788897600000,
                        "tsunami": 0,
                    },
                }
            ]
        }
    )
    assert earthquakes[0]["magnitude"] == 4.2
    assert earthquakes[0]["lat"] == 59.3
    assert earthquakes[0]["lon"] == 18.1

    sampled = osint_contract._normalize_aircraft(
        {
            "states": [
                [
                    f"icao{index:03d}",
                    f"CS{index:03d}",
                    "Sweden",
                    None,
                    1_700_000_000,
                    18.0 + index,
                    59.0,
                    9000,
                    False,
                    200.0,
                    90.0,
                ]
                for index in range(400)
            ]
        }
    )
    assert len(sampled) == osint_contract.MAX_ROWS
    assert sampled[0]["heading"] == 90
    assert sampled[0]["on_ground"] is False
    adsb = osint_contract._normalize_adsb_ac(
        {
            "ac": [
                {
                    "hex": "abc123",
                    "flight": "SAS123",
                    "lat": 59.3,
                    "lon": 18.1,
                    "alt_baro": 35000,
                    "gs": 420,
                    "track": 270,
                    "squawk": "1234",
                }
            ]
        }
    )
    assert adsb[0]["callsign"] == "SAS123"
    assert adsb[0]["heading"] == 270
    assert adsb[0]["alt_m"] == round(35000 * 0.3048)
    assert osint_contract._normalize_aircraft({"states": None}) == []
    lod_rows = [
        {
            "id": f"lod-{index}",
            "lat": 45.0 + (index % 40) * 0.4,
            "lon": -10.0 + (index % 80) * 0.5,
            "heading": 90,
            "on_ground": False,
        }
        for index in range(2400)
    ]
    low_zoom = osint_contract._render_rows(
        lod_rows,
        "aircraft",
        osint_contract.MAX_AIRCRAFT_RENDER,
        {"zoom": 2.2, "bounds": [[-180, -90], [180, 90]]},
    )
    assert len(low_zoom) < len(lod_rows)
    assert sum(
        int(row.get("aircraft_count") or 1) if row.get("cluster") else 1
        for row in low_zoom
    ) == len(lod_rows)
    osint_contract._rebuild_geo_lod("aircraft", lod_rows)
    indexed_low_zoom = osint_contract._render_rows(
        lod_rows,
        "aircraft",
        osint_contract.MAX_AIRCRAFT_RENDER,
        {"zoom": 2.2, "bounds": [[-180, -90], [180, 90]]},
    )
    assert len(indexed_low_zoom) < len(lod_rows)
    assert sum(
        int(row.get("aircraft_count") or 1) if row.get("cluster") else 1
        for row in indexed_low_zoom
    ) == len(lod_rows)
    high_zoom = osint_contract._render_rows(
        lod_rows,
        "aircraft",
        osint_contract.MAX_AIRCRAFT_RENDER,
        {"zoom": 8.0, "bounds": [[-15, 40], [30, 65]]},
    )
    assert len(high_zoom) == len(lod_rows)
    assert not any(row.get("cluster") for row in high_zoom)
    assert osint_contract._map_api_allowed(
        "https://api.airplanes.live/v2/point/52.000/10.000/450"
    )
    assert osint_contract._map_api_allowed(
        "https://api.adsb.lol/v2/lat/59.300/lon/18.100/dist/350"
    )
    assert not osint_contract._map_api_allowed(
        "https://api.airplanes.live/v2/all"
    )

    fires = osint_contract._normalize_fires(
        {
            "events": [
                {
                    "id": "eonet-test",
                    "title": "Test wildfire",
                    "categories": [{"id": "wildfires", "title": "Wildfires"}],
                    "geometry": [
                        {
                            "date": "2026-09-08T12:00:00Z",
                            "coordinates": [17.9, 59.4],
                        }
                    ],
                    "link": "https://example.invalid/event",
                }
            ]
        }
    )
    assert fires[0]["type"] == "fire"
    assert fires[0]["lon"] == 17.9

    satellites = osint_contract._normalize_satellites(
        [
            {
                "OBJECT_NAME": "ISS (ZARYA)",
                "NORAD_CAT_ID": 25544,
                "INCLINATION": 51.6,
                "MEAN_MOTION": 15.5,
            }
        ]
    )
    assert satellites[0]["norad"] == 25544
    assert satellites[0]["name"] == "ISS (ZARYA)"

    news_root = osint_contract.ET.fromstring(
        "<rss><channel><item><title>Test world event</title>"
        "<description>Short report</description><link>https://example.invalid</link>"
        "<pubDate>today</pubDate></item></channel></rss>"
    )
    news = osint_contract._normalize_news(news_root)
    assert news[0]["source"] == "BBC WORLD"
    assert news[0]["title"] == "Test world event"

    pinned = osint_contract._normalize_news(
        osint_contract.ET.fromstring(
            "<rss><channel><item><title>Strike reported near Ukraine border</title>"
            "<description>Field report</description><link>https://example.invalid/u</link>"
            "<pubDate>today</pubDate></item></channel></rss>"
        )
    )
    assert pinned[0]["lat"] == 49.0
    assert pinned[0]["lon"] == 32.0

    solar = osint_contract._normalize_solar(
        [{"time_tag": "2026-09-08T12:00:00Z", "kp_index": 4.3}]
    )
    assert solar["kp_index"] == 4.3
    assert solar["storm_level"] == "MINOR"

    empty = osint_contract.empty_snapshot("MAP")
    assert empty["schema"] == osint_contract.SCHEMA
    assert empty["scope"] == "PUBLIC_READ_ONLY"
    assert empty["page"] == "MAP"
    assert len(empty["conflicts"]) == 13
    assert empty["recon"]["mode"] == "SAFE_BOUNDARY"
    assert "PORT SCANS" in empty["recon"]["not_enabled"]
    assert "LIVE CAMERA TAKEOVER" in empty["recon"]["not_enabled"]
    assert empty["counts"]["cameras"] >= 100
    assert empty["stream"]
    assert any(item.get("lat") is not None for item in empty["stream"])
    gdelt = osint_contract._normalize_gdelt(
        {
            "features": [
                {
                    "geometry": {"coordinates": [32.0, 49.0]},
                    "properties": {
                        "name": "Kyiv",
                        "url": "https://example.invalid/g",
                        "urlpubtimedate": "2026-09-09",
                    },
                }
            ]
        }
    )
    assert gdelt[0]["lat"] == 49.0
    assert gdelt[0]["title"] == "Kyiv"
    alpr = osint_contract._load_local_alpr()
    assert alpr[0]["live_video"] is False
    assert alpr[0]["lat"] is not None
    bundled = osint_contract._load_bundled_cctv()
    assert len(bundled) > 20
    assert bundled[0]["live_video"] is True
    assert str(bundled[0]["photo"]).startswith("https://")
    assert osint_contract.TFL_CAM_URL.startswith("https://api.tfl.gov.uk/")
    tfl_rows = osint_contract._normalize_tfl_cameras(
        [{
            "id": "tfl-test",
            "commonName": "Test Cam",
            "lat": 51.5,
            "lon": -0.12,
            "additionalProperties": [
                {"key": "imageUrl", "value": "https://example.invalid/cam.jpg"},
            ],
        }]
    )
    assert tfl_rows[0]["live_video"] is True
    assert tfl_rows[0]["photo"].endswith("cam.jpg")

    qml = (PROJECT / "qml/components/OsintSurface.qml").read_text(
        encoding="utf-8"
    )
    globe = (PROJECT / "qml/components/OsintGlobe.qml").read_text(
        encoding="utf-8"
    )
    workspace = (PROJECT / "qml/components/WorkspaceSurface.qml").read_text(
        encoding="utf-8"
    )
    settings = (
        PROJECT / "qml/components/SettingsWorkspaceModule.qml"
    ).read_text(encoding="utf-8")
    for marker in (
        'objectName: "workspaceOsintPane"',
        'text: "PUBLIC READ-ONLY RECON"',
        'leftLegend: "EVENT MAP"',
        'leftLegend: "SOURCE HEALTH"',
        'leftLegend: "RECON BOUNDARY"',
        "osintSnapshot",
        "osintRefresh",
    ):
        assert marker in qml or marker in workspace, marker
    assert 'objectName: "workspaceOsintPane"' in workspace
    assert 'active: !root.settingsOpen && root.hostKind === "OSINT"' in workspace
    assert 'objectName: "workspaceKindOSINT"' in workspace
    assert workspace.index('text: "TMOG"') < workspace.index('text: "OSINT"')
    assert workspace.index('text: "OSINT"') < workspace.index('text: "MEDIA"')
    assert '"OSINT"' in settings
    assert 'text: "OSINT"' in qml
    assert "color: root.ledgerGold" in qml
    assert "user-supplied target" in qml.lower()
    html = (PROJECT / "qml/osint-map/index.html").read_text(encoding="utf-8")
    script = (PROJECT / "qml/osint-map/map.js").read_text(encoding="utf-8")
    countries = PROJECT / "qml/osint-map/data/countries.geojson"
    alpr_path = PROJECT / "qml/osint-map/data/alpr.geojson"
    vendor = PROJECT / "qml/osint-map/vendor/maplibre-gl.js"
    assert countries.is_file() and countries.stat().st_size > 50_000
    assert alpr_path.is_file() and alpr_path.stat().st_size > 20_000
    assert vendor.is_file() and vendor.stat().st_size > 200_000
    assert osint_contract.OPENSKY_URL == "https://opensky-network.org/api/states/all"
    assert '"type":"FeatureCollection"' in countries.read_text(encoding="utf-8")[:80]
    for marker in (
        "import QtWebEngine",
        'objectName: "osintGlobe"',
        "WebEngineView",
        "setOsintPoints",
        'url: Qt.resolvedUrl("../osint-map/index.html")',
        "webGLEnabled: true",
        "function focusPoint",
        "function showPopup",
        "takeOsintPick",
        "lastPickSeq",
    ):
        assert marker in globe, marker
    for marker in (
        "tiles.openfreemap.org/styles/dark",
        "data/countries.geojson",
        "data/alpr.geojson",
        "window.setOsintPoints",
        "window.focusOsintPoint",
        "window.showOsintPopup",
        "window.takeOsintPick",
        "window.setOsintRoute",
        "gg-pop",
        "gg-pop-legend",
        "window.setOsintProjection",
        "attributionControl: false",
        "router.project-osrm.org",
        "source: 'waypoints'",
        "setRouteData(route.geometry, points)",
        "nominatim.openstreetmap.org",
        "setProjection",
        "LineString",
        "conflict-label",
        "minzoom: 4",
        "TRACKS_MIN_ZOOM",
        "cluster_count",
        "event-clusters",
        "window.osintMapReady",
        "pixelRatio: 1",
        "minzoom: 5",
        "catalogCounts",
        "BLIPS",
    ):
        assert marker in script, marker
    assert "['case'," not in script
    assert "filter: ['==', ['get', 'cluster'], true]" in script
    assert "function syncMapReady" in globe
    assert "tiles.openfreemap.org" in html
    assert "nominatim.openstreetmap.org" in html
    assert 'id="nav"' in html
    assert "osintSharedPane" in qml
    assert "function commitNavPlace" in qml
    assert "function moveNavPlace" in qml
    assert 'color: root.navMode ? "#1a1a1a" : "#181818"' in qml
    assert "TYPE A PLACE + ENTER" in qml
    assert "function applyRoute" in globe
    assert "osintPlanRoute" in qml
    assert "function selectEvent" in qml
    assert "osintLoadUi" in qml
    assert "osintLookupFlight" in qml
    assert "eventFacts" in qml
    assert "lastViewportKey" in qml
    assert "renderedPointCount" in qml
    empty_lookup = osint_contract.lookup_flight("", "")
    assert empty_lookup["ok"] is False
    assert osint_contract._map_api_allowed(
        "https://api.adsbdb.com/v0/callsign/SAS123"
    )
    assert osint_contract._map_api_allowed(
        "https://api.adsbdb.com/v0/aircraft/abc123"
    )
    assert not osint_contract._map_api_allowed(
        "https://api.adsbdb.com/v0/stats"
    )
    assert not osint_contract._map_api_allowed(
        "https://example.invalid/v0/callsign/SAS123"
    )
    osint_contract._collections["aircraft"] = [{
        "id": "abc123",
        "callsign": "CES570",
        "country": "Mexico",
        "lat": 25.4,
        "lon": -101.0,
        "alt_m": 9000,
        "heading": 90,
        "speed_mps": 200.0,
        "on_ground": False,
        "squawk": "1234",
        "last_contact": "",
    }]
    stream = osint_contract._build_stream()
    osint_contract._collections["aircraft"] = []
    assert any(
        row.get("kind") == "aircraft" and row.get("title") == "CES570"
        for row in stream
    )
    gdelt_dup = osint_contract._normalize_gdelt(
        {
            "features": [
                {
                    "geometry": {"coordinates": [32.0, 49.0]},
                    "properties": {"name": "Kyiv", "url": "https://example.invalid/a", "mentionedthemes": ";WAR;TAX_ETHNICITY_X;"},
                },
                {
                    "geometry": {"coordinates": [32.1, 49.1]},
                    "properties": {"name": "Kyiv", "url": "https://example.invalid/b", "mentionedthemes": ";WAR;"},
                },
            ]
        }
    )
    assert len(gdelt_dup) == 1
    assert "TAX_" not in gdelt_dup[0]["summary"]
    assert "vendor/maplibre-gl.js" in html
    main_py = (PROJECT / "main.py").read_text(encoding="utf-8")
    assert "QTWEBENGINE_CHROMIUM_FLAGS" in main_py
    assert "--disable-gpu" not in main_py
    assert "--enable-webgl" in main_py

    from PySide6.QtCore import QObject, QUrl, Slot, QMetaObject, qInstallMessageHandler
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
    from PySide6.QtGui import QGuiApplication
    from backend.osint_host import OsintHost

    app = QGuiApplication.instance() or QGuiApplication([])
    host = OsintHost()
    payload = json.loads(host.snapshot("SOURCES"))
    assert payload["page"] == "SOURCES"
    assert payload["schema"] == osint_contract.SCHEMA
    host.saveUi(json.dumps({
        "navPlaces": ["Gothenburg", "Oslo"],
        "navMode": True,
        "page": "MAP",
    }))
    ui = json.loads(host.loadUi())
    assert ui["navPlaces"] == ["Gothenburg", "Oslo"]
    assert ui["navMode"] is True
    assert ui["page"] == "MAP"
    host.shutdown()
    app.processEvents()

    fixture = osint_contract.empty_snapshot("OVERVIEW")
    fixture["counts"] = {
        "aircraft": 1,
        "earthquakes": 1,
        "fires": 1,
        "satellites": 1,
        "news": 1,
        "conflicts": 1,
    }
    fixture["aircraft"] = [{
        "id": "abc123", "callsign": "GGTEST", "country": "Sweden",
        "lat": 59.3, "lon": 18.1, "alt_m": 9000,
        "heading": 240, "speed_mps": 220.0, "on_ground": False,
    }]
    fixture["earthquakes"] = [{
        "id": "quake", "place": "Test region", "magnitude": 3.2,
        "depth_km": 10, "lat": 59.3, "lon": 18.1,
        "time": "2026-09-08T12:00:00Z", "url": "https://example.invalid/q",
    }]
    fixture["fires"] = [{
        "id": "fire", "title": "Test fire", "category": "WILDFIRE",
        "lat": 59.4, "lon": 17.9, "url": "https://example.invalid/f",
    }]
    fixture["satellites"] = [{
        "id": "25544", "name": "ISS", "norad": 25544,
        "inclination": 51.6,
    }]
    fixture["news"] = [{
        "id": "news", "title": "Test world event", "source": "BBC WORLD",
        "published": "today", "url": "https://example.invalid/n",
        "risk_score": 2,
    }]
    fixture["conflicts"] = [
        {"id": "test-zone", "label": "TEST ZONE", "lat": 59.0,
         "lon": 18.0, "severity": 2}
    ]

    fixture["news_stream"] = [
        {"id": "svt", "title": "Svenska nyheter", "kind": "news", "source": "SVT NYHETER", "language": "sv"},
        {"id": "ekot", "title": "Ekot nyheter", "kind": "news", "source": "SR EKOT", "language": "sv"},
        {"id": "bbc", "title": "World news", "kind": "news", "source": "BBC WORLD", "language": "en"},
    ]

    class FakeSurfaceHost(QObject):
        def __init__(self):
            super().__init__()
            self.refreshes = 0
            self.recorded = []
            self.nearby_transitions = []

        @Slot(bool)
        def osintSetNearbyActive(self, enabled: bool) -> None:
            self.nearby_transitions.append(enabled)

        @Slot(result=str)
        def osintNearbySnapshot(self) -> str:
            return json.dumps({"status": "SYSTEM_CACHE", "rows": [], "sources": []})

        @Slot(str, str, result=str)
        def osintRecordEvidence(self, kind: str, event_id: str) -> str:
            self.recorded.append((kind, event_id))
            return json.dumps({"status": "EVIDENCE_RECORDED"})

        @Slot(str, result=str)
        def researchCommand(self, raw: str = "{}") -> str:
            return json.dumps({"status": "READY", "tasks": [], "sources": [], "evidence": []})

        @Slot(str, result=str)
        def osintSnapshot(self, page: str = "OVERVIEW") -> str:
            payload = dict(fixture)
            payload["page"] = str(page or "OVERVIEW").upper()
            return json.dumps(payload)

        @Slot(str, result=bool)
        def osintRefresh(self, page: str = "OVERVIEW") -> bool:
            self.refreshes += 1
            return False

        @Slot(str)
        def osintCopy(self, value: str) -> None:
            return None

        @Slot(str, result=str)
        def osintPlanRoute(self, spec_json: str = "{}") -> str:
            return json.dumps({"ok": False, "error": "test-skip", "points": []})

        @Slot(str)
        def osintSaveUi(self, raw: str = "{}") -> None:
            return None

        @Slot(result=str)
        def osintLoadUi(self) -> str:
            return "{}"

        @Slot(str, str, result=str)
        def osintLookupFlight(self, callsign: str = "", icao: str = "") -> str:
            return "{}"

    engine = QQmlApplicationEngine()
    component = QQmlComponent(
        engine,
        QUrl.fromLocalFile(str(PROJECT / "qml/components/OsintSurface.qml")),
    )
    assert not component.errors(), [error.toString() for error in component.errors()]
    surface = component.create()
    assert surface is not None
    fake = FakeSurfaceHost()
    assert surface.setProperty("surfaceHost", fake)
    assert surface.setProperty("width", 1100)
    assert surface.setProperty("height", 720)
    assert surface.setProperty("payload", fixture)
    assert surface.setProperty("visible", True)
    messages: list[str] = []
    qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(str(message))
    )
    app.processEvents()
    news_list = surface.findChild(QObject, "overviewNewsList")
    assert news_list is not None and news_list.property("count") == 3
    surface.setProperty("streamMode", "SVENSKA")
    app.processEvents()
    assert news_list.property("count") == 2
    surface.setProperty("streamMode", "SIGNALS")
    app.processEvents()
    assert news_list.property("count") == len(fixture["stream"])
    surface.setProperty("streamMode", "NEWS")
    assert surface.findChild(QObject, "osintMapPage") is not None
    assert surface.findChild(QObject, "osintSourcesPage") is not None
    globe = surface.findChild(QObject, "osintGlobe")
    assert globe is not None
    assert int(globe.property("pointCount")) == 4
    globe.setProperty("mapReady", True)
    globe.setProperty("savedView", {"zoom": 2})
    surface.setProperty("nearbyEnabled", True)
    app.processEvents()
    assert not surface.property("nearbyActive"), "nearby activated while zoomed out"
    globe.setProperty("savedView", {"zoom": 15.5})
    app.processEvents()
    assert surface.property("nearbyActive"), "nearby failed to activate at close zoom"
    globe.setProperty("savedView", {"zoom": 2})
    app.processEvents()
    assert not surface.property("nearbyActive"), "nearby failed to pause after zoom-out"
    assert True in fake.nearby_transitions and False in fake.nearby_transitions
    globe.setProperty("mapReady", False)
    assert surface.setProperty("page", "MAP")
    app.processEvents()
    assert str(surface.property("page")) == "MAP"
    refreshes = fake.refreshes
    requests = []
    surface.researchRequested.connect(requests.append)
    assert surface.setProperty("selectedEvent", {"kind": "earthquakes", "id": "quake"})
    assert QMetaObject.invokeMethod(surface, "saveEvidence")
    app.processEvents()
    assert fake.recorded == [("earthquakes", "quake")]
    assert requests == ["EVIDENCE"], "OSINT did not hand off to shared Research"
    assert str(surface.property("page")) == "MAP"
    assert surface.findChild(QObject, "osintResearchPage") is None
    assert surface.findChild(QObject, "osintQipPage") is None
    assert surface.findChild(QObject, "workspaceResearchPane") is None
    assert surface.findChild(QObject, "workspaceQipPane") is None
    assert fake.refreshes == refreshes, "saving evidence refreshed public feeds"
    bad_messages = [
        message for message in messages
        if any(token in message for token in (
            "ReferenceError", "TypeError", "Cannot assign", "Unable to assign",
        ))
    ]
    assert not bad_messages, bad_messages
    qInstallMessageHandler(None)
    surface.deleteLater()
    app.processEvents()
    print("OSINT_CONTRACT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
