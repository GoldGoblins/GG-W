"""Small, safe OSIRIS-style public intelligence collector for GG AI Desktop.

The upstream OSIRIS project is a broad web application.  This module keeps
the native desktop surface deliberately narrower: it reads a fixed allowlist
of public feeds, bounds every response, and never accepts a user supplied URL
or target.  That gives the desktop the useful observation layer without
turning a dashboard into an arbitrary network scanner.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import hashlib
import re
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


SCHEMA = "gg.ai-desktop.osiris-snapshot.v1"
SAFE_SCOPE = "PUBLIC_READ_ONLY"
CACHE_TTL_SECONDS = 90.0
MAX_RESPONSE_BYTES = 5_000_000
MAX_ROWS = 160
MAX_AIRCRAFT_CATALOG = 20_000
MAX_AIRCRAFT_RENDER = 10_000
MAX_NEWS_ROWS = 2_048
MAX_NEWS_RENDER = 1_000
MAX_CAMERA_ROWS = 100_000
MAX_CAMERA_RENDER = 2_500
MAX_STREAM_ROWS = 28
MAX_GDELT_ROWS = 5_000
MAX_GDELT_RENDER = 1_200
MAX_SATELLITES = 72
MAX_FIRE_ROWS = 120
MAX_EARTHQUAKES = 80
MAX_HISTORY = 60
# Rendering limits are separate from catalog limits.  The catalog can stay
# broad while the globe receives a small, zoom-aware set of map features.
LOD_AIRCRAFT_CLUSTER_ZOOM = 6.0
LOD_EVENT_CLUSTER_ZOOM = 6.0
LOD_CAMERA_CLUSTER_ZOOM = 8.0
HTTP_TIMEOUT_SECONDS = 5.0
USER_AGENT = "gg-ai-desktop/osiris-native/1.0"

USGS_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/"
    "2.5_day.geojson"
)
OPENSKY_URL = "https://opensky-network.org/api/states/all"
EONET_URL = (
    "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=100"
)
CELESTRAK_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=json"
)
NOAA_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
BBC_URL = "https://feeds.bbci.co.uk/news/world/rss.xml"
SVT_URL = "https://www.svt.se/rss.xml"
EKOT_URL = "https://api.sr.se/api/rss/program/83"
NEWS_FEEDS = (
    {"id": "svt", "provider": "SVT NYHETER", "language": "sv", "url": SVT_URL},
    {"id": "ekot", "provider": "SR EKOT", "language": "sv", "url": EKOT_URL},
    {"id": "bbc", "provider": "BBC WORLD", "language": "en", "url": BBC_URL},
)
_news_feed_cache: dict[str, list[dict[str, Any]]] = {}
GDELT_URL = "https://api.gdeltproject.org/api/v1/gkg_geojson?TIMESPAN=180"
OSIRIS_REPOSITORY_URL = "https://github.com/simplifaisoul/osiris"
DEFLOCK_URL = "https://deflock.org/"
TFL_CAM_URL = "https://api.tfl.gov.uk/Place/Type/JamCam"
FIN_CAM_URL = "https://weathercam.digitraffic.fi/api/v1/camera-data"
ALPR_SAMPLE_PATH = (
    Path(__file__).resolve().parents[1] / "qml/osint-map/data/alpr.geojson"
)

SOURCE_CATALOG = (
    {
        "id": "earthquakes",
        "label": "SEISMIC",
        "provider": "USGS",
        "url": USGS_URL,
    },
    {
        "id": "aircraft",
        "label": "FLIGHTS",
        "provider": "OPENSKY",
        "url": OPENSKY_URL,
    },
    {
        "id": "fires",
        "label": "FIRES",
        "provider": "NASA EONET",
        "url": EONET_URL,
    },
    {
        "id": "satellites",
        "label": "SPACE",
        "provider": "CELESTRAK",
        "url": CELESTRAK_URL,
    },
    {
        "id": "solar",
        "label": "SOLAR",
        "provider": "NOAA SWPC",
        "url": NOAA_URL,
    },
    {
        "id": "news",
        "label": "NEWS",
        "provider": "SVT / SR EKOT / BBC WORLD",
        "url": BBC_URL,
    },
    {
        "id": "gdelt",
        "label": "GLOBAL NEWS GEO",
        "provider": "GDELT",
        "url": GDELT_URL,
    },
    {
        "id": "cameras",
        "label": "CCTV",
        "provider": "TFL / DIGITRAFFIC / PUBLIC SNAPSHOTS",
        "url": TFL_CAM_URL,
    },
    {
        "id": "conflicts",
        "label": "WATCHLIST",
        "provider": "OSIRIS REFERENCE",
        "url": OSIRIS_REPOSITORY_URL,
    },
)

ALLOWED_SOURCE_URLS = frozenset(
    str(source["url"]) for source in SOURCE_CATALOG
) | frozenset({TFL_CAM_URL, FIN_CAM_URL, DEFLOCK_URL, SVT_URL, EKOT_URL})
MAP_API_HOSTS = frozenset(
    {
        "nominatim.openstreetmap.org",
        "router.project-osrm.org",
        "api.adsbdb.com",
        "api.airplanes.live",
        "api.adsb.lol",
    }
)
MAX_ROUTE_PLACES = 26
FLIGHT_CACHE_TTL_SECONDS = 600.0

# These are deliberately labelled as reference locations.  They are not a
# claim that the desktop has independently verified a live conflict status.
REFERENCE_ZONES = (
    {"id": "ukraine", "label": "UKRAINE", "lat": 49.0, "lon": 32.0, "severity": 5},
    {"id": "gaza", "label": "GAZA / LEVANT", "lat": 31.4, "lon": 34.4, "severity": 5},
    {"id": "sudan", "label": "SUDAN", "lat": 15.6, "lon": 32.5, "severity": 4},
    {"id": "myanmar", "label": "MYANMAR", "lat": 21.0, "lon": 96.0, "severity": 4},
    {"id": "drc", "label": "EASTERN DRC", "lat": -1.6, "lon": 29.2, "severity": 4},
    {"id": "yemen", "label": "YEMEN / RED SEA", "lat": 15.5, "lon": 48.5, "severity": 4},
    {"id": "syria", "label": "SYRIA", "lat": 35.0, "lon": 38.0, "severity": 3},
    {"id": "sahel", "label": "SAHEL", "lat": 14.0, "lon": 0.0, "severity": 4},
    {"id": "somalia", "label": "SOMALIA", "lat": 5.2, "lon": 46.2, "severity": 3},
    {"id": "taiwan", "label": "TAIWAN STRAIT", "lat": 23.7, "lon": 120.7, "severity": 3},
    {"id": "korean-dmz", "label": "KOREAN DMZ", "lat": 38.0, "lon": 127.0, "severity": 3},
    {"id": "south-caucasus", "label": "SOUTH CAUCASUS", "lat": 40.2, "lon": 45.0, "severity": 2},
    {"id": "lebanon", "label": "LEBANON", "lat": 33.9, "lon": 35.7, "severity": 4},
)

# Public snapshot cameras that work without a key. Runtime collectors add
# TfL JamCams and Finnish road cameras on top of this seed.
BUNDLED_CCTV: tuple[dict[str, Any], ...] = (
    {"id": "usgs-kilauea-v1", "label": "Kīlauea V1cam", "lat": 19.4069, "lon": -155.2834, "photo": "https://volcanoes.usgs.gov/vsc/captures/kilauea/kilauea_v1cam.jpg", "source": "USGS", "city": "Hawaiʻi", "country": "USA"},
    {"id": "usgs-kilauea-v2", "label": "Kīlauea V2cam", "lat": 19.4120, "lon": -155.2860, "photo": "https://volcanoes.usgs.gov/vsc/captures/kilauea/kilauea_v2cam.jpg", "source": "USGS", "city": "Hawaiʻi", "country": "USA"},
    {"id": "usgs-kilauea-hp", "label": "Halemaʻumaʻu", "lat": 19.4060, "lon": -155.2800, "photo": "https://volcanoes.usgs.gov/vsc/captures/kilauea/HPcam.jpg", "source": "USGS", "city": "Hawaiʻi", "country": "USA"},
    {"id": "usgs-maunaloa", "label": "Mauna Loa", "lat": 19.4790, "lon": -155.6080, "photo": "https://volcanoes.usgs.gov/vsc/captures/maunaloa/mkwcam.jpg", "source": "USGS", "city": "Hawaiʻi", "country": "USA"},
    {"id": "usgs-rainier", "label": "Mount Rainier", "lat": 46.8523, "lon": -121.7603, "photo": "https://volcanoes.usgs.gov/vsc/captures/rainier/muir.jpg", "source": "USGS", "city": "Washington", "country": "USA"},
    {"id": "usgs-sthelens", "label": "Mount St. Helens", "lat": 46.1914, "lon": -122.1956, "photo": "https://volcanoes.usgs.gov/vsc/captures/sthelens/loowit.jpg", "source": "USGS", "city": "Washington", "country": "USA"},
    {"id": "usgs-shasta", "label": "Mount Shasta", "lat": 41.4090, "lon": -122.1950, "photo": "https://volcanoes.usgs.gov/vsc/captures/shasta/shastacam.jpg", "source": "USGS", "city": "California", "country": "USA"},
    {"id": "nps-oldfaithful", "label": "Old Faithful", "lat": 44.4605, "lon": -110.8280, "photo": "https://www.nps.gov/webcams-yell/yellcam.jpg", "source": "NPS", "city": "Yellowstone", "country": "USA"},
    {"id": "nps-grandcanyon", "label": "Grand Canyon Yavapai", "lat": 36.0650, "lon": -112.1180, "photo": "https://www.nps.gov/webcams-grca/yavapai.jpg", "source": "NPS", "city": "Arizona", "country": "USA"},
    {"id": "nps-yosemite", "label": "Yosemite Valley", "lat": 37.7459, "lon": -119.5936, "photo": "https://www.nps.gov/webcams-yose/yose_ahwahnee.jpg", "source": "NPS", "city": "California", "country": "USA"},
    {"id": "wsdot-i5-seattle", "label": "I-5 Seattle", "lat": 47.6062, "lon": -122.3321, "photo": "https://images.wsdot.wa.gov/nw/005vc16545.jpg", "source": "WSDOT", "city": "Seattle", "country": "USA"},
    {"id": "wsdot-i90-seattle", "label": "I-90 Seattle", "lat": 47.5950, "lon": -122.3310, "photo": "https://images.wsdot.wa.gov/nw/090vc00280.jpg", "source": "WSDOT", "city": "Seattle", "country": "USA"},
    {"id": "wsdot-i5-tacoma", "label": "I-5 Tacoma", "lat": 47.2529, "lon": -122.4443, "photo": "https://images.wsdot.wa.gov/sw/005vc13222.jpg", "source": "WSDOT", "city": "Tacoma", "country": "USA"},
    {"id": "wsdot-i405-bellevue", "label": "I-405 Bellevue", "lat": 47.6101, "lon": -122.1872, "photo": "https://images.wsdot.wa.gov/nw/405vc01250.jpg", "source": "WSDOT", "city": "Bellevue", "country": "USA"},
    {"id": "wsdot-sr520", "label": "SR 520 Bridge", "lat": 47.6390, "lon": -122.2600, "photo": "https://images.wsdot.wa.gov/nw/520vc00180.jpg", "source": "WSDOT", "city": "Seattle", "country": "USA"},
    {"id": "wsdot-i5-everett", "label": "I-5 Everett", "lat": 47.9790, "lon": -122.2021, "photo": "https://images.wsdot.wa.gov/nw/005vc19450.jpg", "source": "WSDOT", "city": "Everett", "country": "USA"},
    {"id": "wsdot-i5-vancouver", "label": "I-5 Vancouver WA", "lat": 45.6387, "lon": -122.6615, "photo": "https://images.wsdot.wa.gov/sw/005vc00750.jpg", "source": "WSDOT", "city": "Vancouver", "country": "USA"},
    {"id": "wsdot-i90-spokane", "label": "I-90 Spokane", "lat": 47.6588, "lon": -117.4260, "photo": "https://images.wsdot.wa.gov/e/090vc27900.jpg", "source": "WSDOT", "city": "Spokane", "country": "USA"},
    {"id": "caltrans-baybridge", "label": "Bay Bridge", "lat": 37.7983, "lon": -122.3778, "photo": "https://cwwp2.dot.ca.gov/data/d4/cctv/image/cctvD4BayBridge.jpg", "source": "CALTRANS", "city": "San Francisco", "country": "USA"},
    {"id": "caltrans-d7-101", "label": "US-101 LA", "lat": 34.0522, "lon": -118.2437, "photo": "https://cwwp2.dot.ca.gov/data/d7/cctv/image/cctvD7us101.jpg", "source": "CALTRANS", "city": "Los Angeles", "country": "USA"},
    {"id": "nycdot-timesq", "label": "Times Square", "lat": 40.7580, "lon": -73.9855, "photo": "https://webcams.nyctmc.org/api/cameras/times-square/image", "source": "NYC DOT", "city": "New York", "country": "USA"},
    {"id": "tfl-trafalgar", "label": "Trafalgar Square", "lat": 51.5080, "lon": -0.1281, "photo": "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.07351.jpg", "source": "TFL", "city": "London", "country": "UK"},
    {"id": "tfl-oxford", "label": "Oxford Circus", "lat": 51.5154, "lon": -0.1419, "photo": "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.06690.jpg", "source": "TFL", "city": "London", "country": "UK"},
    {"id": "tfl-londonbridge", "label": "London Bridge", "lat": 51.5079, "lon": -0.0877, "photo": "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.06510.jpg", "source": "TFL", "city": "London", "country": "UK"},
    {"id": "tfl-canary", "label": "Canary Wharf", "lat": 51.5054, "lon": -0.0235, "photo": "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.08890.jpg", "source": "TFL", "city": "London", "country": "UK"},
    {"id": "tfl-heathrow", "label": "Heathrow approach", "lat": 51.4700, "lon": -0.4543, "photo": "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.04301.jpg", "source": "TFL", "city": "London", "country": "UK"},
    {"id": "tfl-camden", "label": "Camden", "lat": 51.5390, "lon": -0.1426, "photo": "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.07451.jpg", "source": "TFL", "city": "London", "country": "UK"},
    {"id": "fin-helsinki", "label": "Helsinki ring", "lat": 60.1699, "lon": 24.9384, "photo": "https://weathercam.digitraffic.fi/C0150201.jpg", "source": "DIGITRAFFIC", "city": "Helsinki", "country": "Finland"},
    {"id": "fin-tampere", "label": "Tampere", "lat": 61.4978, "lon": 23.7610, "photo": "https://weathercam.digitraffic.fi/C0850201.jpg", "source": "DIGITRAFFIC", "city": "Tampere", "country": "Finland"},
    {"id": "fin-turku", "label": "Turku", "lat": 60.4518, "lon": 22.2666, "photo": "https://weathercam.digitraffic.fi/C0350201.jpg", "source": "DIGITRAFFIC", "city": "Turku", "country": "Finland"},
    {"id": "fin-oulu", "label": "Oulu", "lat": 65.0121, "lon": 25.4651, "photo": "https://weathercam.digitraffic.fi/C1650201.jpg", "source": "DIGITRAFFIC", "city": "Oulu", "country": "Finland"},
    {"id": "fin-rovaniemi", "label": "Rovaniemi", "lat": 66.5039, "lon": 25.7294, "photo": "https://weathercam.digitraffic.fi/C1950201.jpg", "source": "DIGITRAFFIC", "city": "Rovaniemi", "country": "Finland"},
    {"id": "nl-rotterdam", "label": "Rotterdam port", "lat": 51.9225, "lon": 4.4792, "photo": "https://www.rijkswaterstaat.nl/webcams/rotterdam.jpg", "source": "RWS", "city": "Rotterdam", "country": "Netherlands"},
    {"id": "de-brandenburg", "label": "Brandenburg Gate", "lat": 52.5163, "lon": 13.3777, "photo": "https://www.berlin.de/webcams/brandenburger-tor.jpg", "source": "BERLIN", "city": "Berlin", "country": "Germany"},
    {"id": "fr-trocadero", "label": "Trocadéro", "lat": 48.8616, "lon": 2.2893, "photo": "https://www.paris.fr/webcams/trocadero.jpg", "source": "PARIS", "city": "Paris", "country": "France"},
    {"id": "it-vaticano", "label": "St Peter's Square", "lat": 41.9022, "lon": 12.4570, "photo": "https://www.vatican.va/news_services/webcam/images/square.jpg", "source": "VATICAN", "city": "Rome", "country": "Italy"},
    {"id": "jp-shibuya", "label": "Shibuya scramble", "lat": 35.6595, "lon": 139.7004, "photo": "https://www.shibuya-scramble.com/cam.jpg", "source": "SHIBUYA", "city": "Tokyo", "country": "Japan"},
    {"id": "jp-mtfuji", "label": "Mount Fuji", "lat": 35.3606, "lon": 138.7274, "photo": "https://www.live-fuji.jp/image.jpg", "source": "FUJI", "city": "Honshu", "country": "Japan"},
    {"id": "hk-harbour", "label": "Victoria Harbour", "lat": 22.2930, "lon": 114.1730, "photo": "https://tdcctv.data.one.gov.hk/K107F.JPG", "source": "HK TD", "city": "Hong Kong", "country": "Hong Kong"},
    {"id": "hk-cross", "label": "Cross Harbour Tunnel", "lat": 22.2860, "lon": 114.1820, "photo": "https://tdcctv.data.one.gov.hk/H429F.JPG", "source": "HK TD", "city": "Hong Kong", "country": "Hong Kong"},
    {"id": "tw-taipei", "label": "Taipei", "lat": 25.0330, "lon": 121.5654, "photo": "https://thb.gov.tw/cctv/taipei.jpg", "source": "THB", "city": "Taipei", "country": "Taiwan"},
    {"id": "au-sydney", "label": "Sydney Harbour", "lat": -33.8580, "lon": 151.2140, "photo": "https://www.livetraffic.com/cameras/camera_images/harbourbridge.jpg", "source": "LIVE TRAFFIC", "city": "Sydney", "country": "Australia"},
    {"id": "au-melbourne", "label": "Melbourne", "lat": -37.8136, "lon": 144.9631, "photo": "https://www.vicroads.vic.gov.au/traffic/cameras/cbd.jpg", "source": "VICROADS", "city": "Melbourne", "country": "Australia"},
    {"id": "nz-auckland", "label": "Auckland harbour", "lat": -36.8485, "lon": 174.7633, "photo": "https://www.journeys.nzta.govt.nz/assets/Traffic-Cameras/Auckland.jpg", "source": "NZTA", "city": "Auckland", "country": "New Zealand"},
    {"id": "za-cape", "label": "Cape Town", "lat": -33.9249, "lon": 18.4241, "photo": "https://www.capetown.gov.za/webcams/waterfront.jpg", "source": "CAPE TOWN", "city": "Cape Town", "country": "South Africa"},
    {"id": "br-rio", "label": "Copacabana", "lat": -22.9711, "lon": -43.1822, "photo": "https://video.rio.rj.gov.br/cameras/copacabana.jpg", "source": "RIO", "city": "Rio", "country": "Brazil"},
    {"id": "cl-santiago", "label": "Santiago", "lat": -33.4489, "lon": -70.6693, "photo": "https://www.uoct.cl/camaras/santiago.jpg", "source": "UOCT", "city": "Santiago", "country": "Chile"},
    {"id": "ca-toronto", "label": "Gardiner Toronto", "lat": 43.6390, "lon": -79.3870, "photo": "https://511on.ca/map/Cctv/toronto-gardiner.jpg", "source": "511 ON", "city": "Toronto", "country": "Canada"},
    {"id": "ca-vancouver", "label": "Lions Gate", "lat": 49.3150, "lon": -123.1380, "photo": "https://images.drivebc.ca/bchighwaycam/pub/cameras/lionsgate.jpg", "source": "DRIVEBC", "city": "Vancouver", "country": "Canada"},
    {"id": "se-slussen", "label": "Slussen", "lat": 59.3200, "lon": 18.0730, "photo": "https://www.trafikverket.se/kamera/stockholm-slussen.jpg", "source": "TRAFIKVERKET", "city": "Stockholm", "country": "Sweden"},
    {"id": "no-oslo", "label": "Oslo", "lat": 59.9139, "lon": 10.7522, "photo": "https://webkamera.atlas.vegvesen.no/public/kamera/oslo.jpg", "source": "STATENS VEGVESEN", "city": "Oslo", "country": "Norway"},
    {"id": "is-reykjavik", "label": "Reykjavík", "lat": 64.1466, "lon": -21.9426, "photo": "https://www.road.is/webcam/reykjavik.jpg", "source": "ROAD.IS", "city": "Reykjavík", "country": "Iceland"},
    {"id": "sg-marina", "label": "Marina Bay", "lat": 1.2834, "lon": 103.8607, "photo": "https://onemotoring.lta.gov.sg/images/cameras/marina.jpg", "source": "LTA", "city": "Singapore", "country": "Singapore"},
    {"id": "ae-sheikh", "label": "Sheikh Zayed Road", "lat": 25.2048, "lon": 55.2708, "photo": "https://www.rta.ae/wps/portal/cameras/sheikh-zayed.jpg", "source": "RTA", "city": "Dubai", "country": "UAE"},
    {"id": "in-mumbai", "label": "Mumbai marine drive", "lat": 18.9432, "lon": 72.8236, "photo": "https://traffic.mcgm.gov.in/cameras/marine-drive.jpg", "source": "MCGM", "city": "Mumbai", "country": "India"},
    {"id": "kr-seoul", "label": "Seoul", "lat": 37.5665, "lon": 126.9780, "photo": "https://topis.seoul.go.kr/camera/seoul.jpg", "source": "TOPIS", "city": "Seoul", "country": "South Korea"},
)

# Longest match first. Used to pin BBC headlines onto the globe.
PLACE_COORDS: tuple[tuple[str, float, float], ...] = tuple(
    sorted(
        (
            ("united states", 39.8, -98.5),
            ("washington", 38.9, -77.0),
            ("new york", 40.7, -74.0),
            ("california", 36.8, -119.4),
            ("ukraine", 49.0, 32.0),
            ("russia", 55.8, 37.6),
            ("moscow", 55.8, 37.6),
            ("gaza", 31.4, 34.4),
            ("israel", 31.5, 34.9),
            ("lebanon", 33.9, 35.7),
            ("syria", 35.0, 38.0),
            ("iran", 32.4, 53.7),
            ("iraq", 33.3, 44.4),
            ("yemen", 15.5, 48.5),
            ("sudan", 15.6, 32.5),
            ("sahel", 14.0, 0.0),
            ("somalia", 5.2, 46.2),
            ("ethiopia", 9.0, 38.7),
            ("kenya", -1.3, 36.8),
            ("nigeria", 9.1, 8.7),
            ("egypt", 26.8, 30.8),
            ("libya", 26.3, 17.2),
            ("algeria", 28.0, 2.0),
            ("morocco", 31.8, -7.1),
            ("south africa", -28.5, 24.7),
            ("congo", -2.9, 23.8),
            ("china", 35.9, 104.2),
            ("taiwan", 23.7, 120.9),
            ("japan", 36.2, 138.3),
            ("korea", 37.5, 127.0),
            ("india", 21.1, 79.0),
            ("pakistan", 30.4, 69.3),
            ("afghanistan", 33.9, 67.7),
            ("myanmar", 21.0, 96.0),
            ("australia", -25.3, 133.8),
            ("indonesia", -2.2, 118.0),
            ("philippines", 12.9, 121.8),
            ("united kingdom", 54.0, -2.0),
            ("britain", 54.0, -2.0),
            ("london", 51.5, -0.1),
            ("france", 46.2, 2.2),
            ("paris", 48.9, 2.3),
            ("germany", 51.2, 10.4),
            ("berlin", 52.5, 13.4),
            ("spain", 40.5, -3.7),
            ("italy", 42.8, 12.6),
            ("poland", 52.1, 19.4),
            ("sweden", 60.1, 18.6),
            ("sverige", 60.1, 18.6),
            ("stockholm", 59.3, 18.1),
            ("göteborg", 57.7, 12.0),
            ("malmö", 55.6, 13.0),
            ("uppsala", 59.9, 17.6),
            ("kiruna", 67.9, 20.2),
            ("ukraina", 49.0, 32.0),
            ("ryssland", 55.8, 37.6),
            ("norway", 60.5, 8.5),
            ("finland", 64.0, 26.0),
            ("turkey", 39.0, 35.2),
            ("greece", 39.1, 21.8),
            ("brazil", -14.2, -51.9),
            ("argentina", -38.4, -63.6),
            ("mexico", 23.6, -102.5),
            ("canada", 56.1, -106.3),
            ("venezuela", 6.4, -66.6),
            ("colombia", 4.6, -74.1),
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

_lock = threading.RLock()
_last_collect_at = 0.0
_last_generated_at = ""
_collections: dict[str, list[dict[str, Any]]] = {
    "aircraft": [],
    "earthquakes": [],
    "fires": [],
    "satellites": [],
    "news": [],
    "cameras": [],
    "gdelt": [],
}
_solar: dict[str, Any] = {}
_sources: dict[str, dict[str, Any]] = {
    str(source["id"]): {
        **source,
        "status": "IDLE",
        "count": 0,
        "error": "",
        "last_updated": "",
        "last_attempt_at": "",
        "last_success_at": "",
    }
    for source in SOURCE_CATALOG
}
_histories: dict[str, list[int]] = {
    "aircraft": [],
    "earthquakes": [],
    "fires": [],
    "satellites": [],
    "news": [],
    "cameras": [],
    "gdelt": [],
}
_alpr_total = 0
_flight_cache: dict[str, dict[str, Any]] = {}
_flight_cache_at: dict[str, float] = {}
_camera_index: dict[tuple[int, int], list[dict[str, Any]]] = {}
_camera_index_size = 0
_CAMERA_INDEX_CELL_DEG = 1.0
_camera_lod: dict[float, dict[tuple[int, int], dict[str, Any]]] = {}
_camera_lod_size = 0
_CAMERA_LOD_CELLS = (8.0, 3.0, 1.0)
_geo_lod: dict[str, dict[float, dict[tuple[int, int], dict[str, Any]]]] = {}
_geo_lod_size: dict[str, int] = {}
_geo_lod_unlocated: dict[str, list[dict[str, Any]]] = {}
_GEO_LOD_CELLS = (10.0, 4.0, 1.5)


def _cached_alpr_total() -> int:
    global _alpr_total
    if _alpr_total:
        return _alpr_total
    try:
        payload = json.loads(ALPR_SAMPLE_PATH.read_text(encoding="utf-8"))
        _alpr_total = len(payload.get("features") or [])
    except (OSError, TypeError, ValueError):
        _alpr_total = 0
    return _alpr_total


def _rebuild_camera_index(rows: list[dict[str, Any]]) -> None:
    """Build a coarse geographic index once per camera catalog refresh."""
    global _camera_index, _camera_index_size, _camera_lod, _camera_lod_size
    index: dict[tuple[int, int], list[dict[str, Any]]] = {}
    lod: dict[float, dict[tuple[int, int], dict[str, Any]]] = {
        cell: {} for cell in _CAMERA_LOD_CELLS
    }
    for row in rows:
        lat = _float(row.get("lat"))
        lon = _float(row.get("lon"))
        if lat is None or lon is None:
            continue
        key = (
            max(0, min(359, int((lon + 180.0) / _CAMERA_INDEX_CELL_DEG))),
            max(0, min(179, int((lat + 90.0) / _CAMERA_INDEX_CELL_DEG))),
        )
        index.setdefault(key, []).append(row)
        for cell in _CAMERA_LOD_CELLS:
            lod_key = (
                int((lon + 180.0) / cell),
                int((lat + 90.0) / cell),
            )
            bucket = lod[cell].get(lod_key)
            if bucket is None:
                lod[cell][lod_key] = {
                    "count": 1,
                    "sum_lat": lat,
                    "sum_lon": lon,
                    "first": row,
                }
            else:
                bucket["count"] += 1
                bucket["sum_lat"] += lat
                bucket["sum_lon"] += lon
    _camera_index = index
    _camera_index_size = len(rows)
    _camera_lod = lod
    _camera_lod_size = len(rows)


def _rebuild_geo_lod(kind: str, rows: list[dict[str, Any]]) -> None:
    """Pre-aggregate movable event catalogs for fast low-zoom queries."""
    levels: dict[float, dict[tuple[int, int], dict[str, Any]]] = {
        cell: {} for cell in _GEO_LOD_CELLS
    }
    unlocated: list[dict[str, Any]] = []
    for row in rows:
        lat = _float(row.get("lat"))
        lon = _float(row.get("lon"))
        if lat is None or lon is None:
            unlocated.append(row)
            continue
        for cell in _GEO_LOD_CELLS:
            key = (
                int((lon + 180.0) / cell),
                int((lat + 90.0) / cell),
            )
            bucket = levels[cell].get(key)
            if bucket is None:
                levels[cell][key] = {
                    "count": 1,
                    "sum_lat": lat,
                    "sum_lon": lon,
                    "first": row,
                }
            else:
                bucket["count"] += 1
                bucket["sum_lat"] += lat
                bucket["sum_lon"] += lon
    _geo_lod[kind] = levels
    _geo_lod_size[kind] = len(rows)
    _geo_lod_unlocated[kind] = unlocated


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _bounded_text(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _float(value: Any, fallback: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number or number in (float("inf"), float("-inf")):
        return fallback
    return number


def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _iso_from_millis(value: Any) -> str:
    stamp = _float(value)
    if stamp is None:
        return ""
    try:
        return (
            datetime.fromtimestamp(stamp / 1000.0, tz=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        return ""


def _read_public(url: str, timeout: float | None = None) -> bytes:
    """Read one allowlisted public endpoint with strict bounds."""
    if url not in ALLOWED_SOURCE_URLS:
        raise ValueError("source is not allowlisted")
    request = Request(
        url,
        headers={
            "Accept": "application/json, application/xml, text/xml",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(
            request, timeout=timeout if timeout is not None else HTTP_TIMEOUT_SECONDS
        ) as response:
            status = int(getattr(response, "status", 200) or 200)
            if status >= 400:
                raise OSError(f"HTTP {status}")
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise OSError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise OSError(str(exc.reason or "network error")) from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise OSError("response exceeded size limit")
    return body


def _read_json(url: str, timeout: float | None = None) -> Any:
    return json.loads(
        _read_public(url, timeout=timeout).decode("utf-8", errors="replace")
    )


def _map_api_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = str(parsed.hostname).lower()
    if host not in MAP_API_HOSTS:
        return False
    path = str(parsed.path or "")
    if ".." in path:
        return False
    if host == "api.adsbdb.com":
        return path.startswith("/v0/callsign/") or path.startswith("/v0/aircraft/")
    if host == "api.airplanes.live":
        return path.startswith("/v2/point/")
    if host == "api.adsb.lol":
        return path.startswith("/v2/lat/") or path.startswith("/v2/point/")
    return True


def _read_map_api(url: str, timeout: float = 8.0) -> bytes:
    if not _map_api_allowed(url):
        raise ValueError("map api host is not allowlisted")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            if status >= 400:
                raise OSError(f"HTTP {status}")
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise OSError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise OSError(str(exc.reason or "network error")) from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise OSError("response exceeded size limit")
    return body


def geocode_place(query: str, gps: dict[str, Any] | None = None) -> dict[str, Any]:
    text = _bounded_text(query, 120)
    if text.lower() == "gps" and not gps:
        raise OSError("GPS fix missing")
    if gps and (not text or text.lower() == "gps"):
        lat = _float(gps.get("lat"))
        lon = _float(gps.get("lon"))
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            raise OSError("GPS fix missing")
        stamp = _float(gps.get("timestamp"))
        if stamp is not None and (time.time() * 1000 - stamp > 120000 or stamp > time.time() * 1000 + 10000):
            raise OSError("GPS fix expired")
        return {"lat": round(lat, 5), "lon": round(lon, 5), "name": "GPS"}
    if not text:
        raise OSError("empty place")
    url = (
        "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q="
        + quote(text)
    )
    hits = json.loads(_read_map_api(url).decode("utf-8", errors="replace"))
    if not isinstance(hits, list) or not hits:
        raise OSError("place not found: " + text)
    hit = hits[0] if isinstance(hits[0], dict) else {}
    lat = _float(hit.get("lat"))
    lon = _float(hit.get("lon"))
    if lat is None or lon is None:
        raise OSError("place not found: " + text)
    return {
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "name": _bounded_text(hit.get("display_name") or text, 120),
    }


def _normalize_route_steps(route: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    cumulative = 0.0
    for leg in (route.get("legs") or [])[:MAX_ROUTE_PLACES]:
        for step in (leg.get("steps") or []):
            if len(steps) >= 2048:
                return steps
            maneuver = step.get("maneuver") or {}
            pair = maneuver.get("location") or []
            if len(pair) == 2:
                lat, lon = _float(pair[1]), _float(pair[0])
                if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180:
                    steps.append({"at_m": round(cumulative, 1), "name": _bounded_text(step.get("name"), 100),
                                  "type": _bounded_text(maneuver.get("type"), 40),
                                  "modifier": _bounded_text(maneuver.get("modifier"), 40),
                                  "exit": maneuver.get("exit"), "lat": lat, "lon": lon})
            cumulative += max(0.0, _float(step.get("distance"), 0.0) or 0.0)
    return steps


def plan_driving_route(
    places: list[str],
    gps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    names = [_bounded_text(item, 120) for item in places if _bounded_text(item, 120)]
    if len(names) < 2:
        return {"ok": False, "error": "Need at least two places.", "points": []}
    if len(names) > MAX_ROUTE_PLACES:
        names = names[:MAX_ROUTE_PLACES]
    points: list[dict[str, Any]] = []
    try:
        for index, name in enumerate(names):
            points.append(geocode_place(name, gps if index == 0 else None))
        path = ";".join(f"{point['lon']},{point['lat']}" for point in points)
        payload = json.loads(
            _read_map_api(
                "https://router.project-osrm.org/route/v1/driving/"
                + path
                + "?overview=full&geometries=geojson&steps=true",
                timeout=12.0,
            ).decode("utf-8", errors="replace")
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": _bounded_text(exc, 160),
            "points": points,
        }
    route = (payload.get("routes") or [None])[0]
    if not isinstance(route, dict) or not route.get("geometry"):
        return {"ok": False, "error": "No driving route for those places.", "points": points}
    return {
        "ok": True,
        "error": "",
        "points": points,
        "geometry": route.get("geometry"),
        "steps": _normalize_route_steps(route),
        "distance_m": _float(route.get("distance"), 0.0) or 0.0,
        "duration_s": _float(route.get("duration"), 0.0) or 0.0,
    }


def _clean_callsign(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())[:8]


def _clean_icao24(value: str) -> str:
    return "".join(
        ch for ch in str(value or "").lower() if ch in "0123456789abcdef"
    )[:6]


def _flight_key(callsign: str, icao: str) -> str:
    return f"{callsign}|{icao}"


def _airport_brief(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    iata = _bounded_text(row.get("iata_code"), 8)
    icao = _bounded_text(row.get("icao_code"), 8)
    city = _bounded_text(row.get("municipality"), 48)
    name = _bounded_text(row.get("name"), 80)
    code = iata or icao
    label = code
    if city and code:
        label = f"{code} {city}"
    elif city:
        label = city
    return {
        "iata": iata,
        "icao": icao,
        "name": name,
        "city": city,
        "label": label,
        "lat": _float(row.get("latitude")),
        "lon": _float(row.get("longitude")),
    }


def _looks_airline_callsign(callsign: str) -> bool:
    text = str(callsign or "")
    return len(text) >= 4 and text[:3].isalpha() and any(ch.isdigit() for ch in text[3:])


def cached_flight(callsign: str = "", icao: str = "") -> dict[str, Any] | None:
    key = _flight_key(_clean_callsign(callsign), _clean_icao24(icao))
    with _lock:
        stamp = _flight_cache_at.get(key)
        if stamp is None or time.monotonic() - stamp > FLIGHT_CACHE_TTL_SECONDS:
            return None
        payload = _flight_cache.get(key)
        return dict(payload) if payload else None


def lookup_flight(callsign: str = "", icao: str = "") -> dict[str, Any]:
    """Public adsbdb enrichment: origin/destination, type, optional photo."""
    cs = _clean_callsign(callsign)
    hex_id = _clean_icao24(icao)
    cached = cached_flight(cs, hex_id)
    if cached:
        return cached
    result: dict[str, Any] = {
        "ok": False,
        "callsign": cs,
        "icao24": hex_id,
        "kind": "aircraft",
    }
    if not cs and not hex_id:
        result["error"] = "Need a callsign or ICAO."
        return result
    errors: list[str] = []
    if _looks_airline_callsign(cs):
        try:
            raw = json.loads(
                _read_map_api(
                    "https://api.adsbdb.com/v0/callsign/" + quote(cs)
                ).decode("utf-8", errors="replace")
            )
            envelope = raw.get("response") if isinstance(raw, dict) else None
            flightroute = None
            if isinstance(envelope, dict):
                flightroute = envelope.get("flightroute")
                if not isinstance(flightroute, dict):
                    flightroute = envelope
            if isinstance(flightroute, dict):
                origin = _airport_brief(flightroute.get("origin"))
                dest = _airport_brief(flightroute.get("destination"))
                airline = (
                    flightroute.get("airline")
                    if isinstance(flightroute.get("airline"), dict)
                    else {}
                )
                result["origin"] = origin
                result["destination"] = dest
                result["airline"] = _bounded_text(airline.get("name"), 80)
                result["airline_icao"] = _bounded_text(airline.get("icao"), 8)
                origin_code = origin.get("iata") or origin.get("icao")
                dest_code = dest.get("iata") or dest.get("icao")
                if origin_code and dest_code:
                    result["route"] = f"{origin_code} → {dest_code}"
                result["ok"] = True
        except Exception as exc:
            errors.append(_bounded_text(exc, 160))
    if hex_id:
        try:
            raw = json.loads(
                _read_map_api(
                    "https://api.adsbdb.com/v0/aircraft/" + quote(hex_id)
                ).decode("utf-8", errors="replace")
            )
            envelope = raw.get("response") if isinstance(raw, dict) else None
            aircraft = None
            if isinstance(envelope, dict):
                aircraft = envelope.get("aircraft")
                if not isinstance(aircraft, dict):
                    aircraft = envelope
            if isinstance(aircraft, dict):
                result["type"] = _bounded_text(
                    aircraft.get("icao_type") or aircraft.get("type"), 24
                )
                result["registration"] = _bounded_text(
                    aircraft.get("registration"), 16
                )
                result["owner"] = _bounded_text(
                    aircraft.get("registered_owner"), 80
                )
                result["photo"] = _bounded_text(
                    aircraft.get("url_photo_thumbnail")
                    or aircraft.get("url_photo"),
                    300,
                )
                result["ok"] = True
        except Exception as exc:
            errors.append(_bounded_text(exc, 160))
    if result.get("ok"):
        key = _flight_key(cs, hex_id)
        with _lock:
            _flight_cache[key] = dict(result)
            _flight_cache_at[key] = time.monotonic()
    elif "error" not in result:
        result["error"] = "No public route or airframe for that flight."
    return result


def _read_xml(url: str) -> ET.Element:
    return ET.fromstring(_read_public(url))


def _normalize_earthquakes(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    features = payload.get("features", []) if isinstance(payload, dict) else []
    for feature in features[:MAX_EARTHQUAKES]:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        lon = _float(coords[0] if len(coords) > 0 else None)
        lat = _float(coords[1] if len(coords) > 1 else None)
        if lat is None or lon is None:
            continue
        magnitude = _float(props.get("mag"), 0.0)
        rows.append(
            {
                "id": _bounded_text(feature.get("id"), 80),
                "place": _bounded_text(props.get("place"), 180),
                "magnitude": round(float(magnitude or 0.0), 1),
                "depth_km": round(float(_float(coords[2], 0.0) or 0.0), 1)
                if len(coords) > 2
                else 0.0,
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "time": _iso_from_millis(props.get("time")),
                "tsunami": bool(props.get("tsunami")),
                "alert": _bounded_text(props.get("alert"), 32),
                "url": _bounded_text(props.get("url"), 300),
                "type": "earthquake",
            }
        )
    rows.sort(key=lambda row: float(row.get("magnitude") or 0), reverse=True)
    return rows


def _normalize_aircraft(
    payload: Any, cap: int = MAX_ROWS
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_states = payload.get("states") if isinstance(payload, dict) else []
    if not isinstance(raw_states, list):
        raw_states = []
    usable: list[Any] = [
        state
        for state in raw_states
        if isinstance(state, list) and len(state) >= 11
    ]
    airborne = [state for state in usable if not bool(state[8])]
    pool = airborne or usable
    cap = max(1, min(int(cap), MAX_AIRCRAFT_CATALOG))
    if len(pool) > cap:
        step = len(pool) / float(cap)
        pool = [pool[int(index * step)] for index in range(cap)]
    for state in pool:
        lon = _float(state[5])
        lat = _float(state[6])
        if lat is None or lon is None:
            continue
        callsign = _bounded_text(state[1], 24) or _bounded_text(state[0], 16)
        rows.append(
            {
                "id": _bounded_text(state[0], 24),
                "callsign": callsign,
                "country": _bounded_text(state[2], 48),
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "alt_m": round(float(_float(state[7], 0.0) or 0.0)),
                "speed_mps": round(float(_float(state[9], 0.0) or 0.0), 1),
                "heading": round(float(_float(state[10], 0.0) or 0.0)),
                "vert_rate_mps": round(
                    float(_float(state[11], 0.0) or 0.0), 1
                )
                if len(state) > 11
                else 0.0,
                "squawk": _bounded_text(
                    state[14] if len(state) > 14 else "", 8
                ),
                "on_ground": bool(state[8]),
                "last_contact": _iso_from_millis(
                    _int(state[4], 0) * 1000 if len(state) > 4 else 0
                ),
                "type": "aircraft",
            }
        )
    return rows


def _normalize_adsb_ac(payload: Any) -> list[dict[str, Any]]:
    """ADSB Exchange v2 / airplanes.live / adsb.lol aircraft list."""
    rows: list[dict[str, Any]] = []
    aircraft = []
    if isinstance(payload, dict):
        raw = payload.get("ac")
        if not isinstance(raw, list):
            raw = payload.get("aircraft")
        aircraft = raw if isinstance(raw, list) else []
    elif isinstance(payload, list):
        aircraft = payload
    for item in aircraft:
        if not isinstance(item, dict):
            continue
        lat = _float(item.get("lat"))
        lon = _float(item.get("lon"))
        if lat is None or lon is None:
            continue
        alt_ft = _float(item.get("alt_baro"))
        if alt_ft is None:
            alt_ft = _float(item.get("alt_geom"), 0.0) or 0.0
        gs_kt = _float(item.get("gs"), 0.0) or 0.0
        hex_id = _bounded_text(item.get("hex") or item.get("icao"), 24)
        callsign = _bounded_text(item.get("flight") or item.get("r") or hex_id, 24)
        rows.append(
            {
                "id": hex_id,
                "callsign": callsign.strip() or hex_id,
                "country": _bounded_text(item.get("desc") or item.get("t") or "", 48),
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "alt_m": round(float(alt_ft) * 0.3048),
                "speed_mps": round(float(gs_kt) * 0.514444, 1),
                "heading": round(float(_float(item.get("track"), 0.0) or 0.0)),
                "vert_rate_mps": round(
                    float(_float(item.get("baro_rate"), 0.0) or 0.0) * 0.00508, 1
                ),
                "squawk": _bounded_text(item.get("squawk"), 8),
                "on_ground": bool(item.get("ground") or alt_ft == 0),
                "last_contact": "",
                "type": "aircraft",
            }
        )
    return rows


def _coordinate_from_eonet(geometry: Any) -> tuple[float, float] | None:
    if not isinstance(geometry, dict):
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return None
    # Point is the normal EONET shape.  For a polygon/line, use the first
    # coordinate that looks like [longitude, latitude].
    candidates: list[Any] = [coordinates]
    while candidates:
        candidate = candidates.pop(0)
        if (
            isinstance(candidate, list)
            and len(candidate) >= 2
            and not isinstance(candidate[0], list)
        ):
            lon = _float(candidate[0])
            lat = _float(candidate[1])
            if lat is not None and lon is not None:
                return lat, lon
        elif isinstance(candidate, list):
            candidates[0:0] = candidate[:10]
    return None


def _normalize_fires(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    events = payload.get("events", []) if isinstance(payload, dict) else []
    for event in events[:MAX_FIRE_ROWS]:
        if not isinstance(event, dict):
            continue
        categories = event.get("categories") or []
        category_names = " ".join(
            _bounded_text(item.get("title") or item.get("id"), 40)
            for item in categories
            if isinstance(item, dict)
        ).lower()
        title = _bounded_text(event.get("title"), 180)
        if not any(
            token in (category_names + " " + title.lower())
            for token in ("wildfire", "wildfires", "fire", "volcano")
        ):
            continue
        geometries = event.get("geometry") or []
        geometry = geometries[-1] if geometries else {}
        coord = _coordinate_from_eonet(geometry)
        if coord is None:
            continue
        lat, lon = coord
        rows.append(
            {
                "id": _bounded_text(event.get("id"), 80),
                "title": title,
                "category": _bounded_text(category_names, 80) or "EVENT",
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "date": _bounded_text(geometry.get("date"), 40)
                if isinstance(geometry, dict)
                else "",
                "url": _bounded_text(event.get("link"), 300),
                "type": "fire",
            }
        )
    return rows


def _normalize_satellites(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    values = payload if isinstance(payload, list) else []
    for satellite in values[:MAX_SATELLITES]:
        if not isinstance(satellite, dict):
            continue
        name = _bounded_text(satellite.get("OBJECT_NAME"), 80)
        if not name:
            continue
        rows.append(
            {
                "id": _bounded_text(satellite.get("NORAD_CAT_ID"), 24),
                "name": name,
                "norad": _int(satellite.get("NORAD_CAT_ID"), 0),
                "inclination": round(
                    float(_float(satellite.get("INCLINATION"), 0.0) or 0.0), 1
                ),
                "mean_motion": round(
                    float(_float(satellite.get("MEAN_MOTION"), 0.0) or 0.0), 2
                ),
                "type": "satellite",
            }
        )
    return rows


def _local_name(tag: Any) -> str:
    value = str(tag or "")
    return value.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, name: str) -> str:
    wanted = name.lower()
    for child in list(node):
        if _local_name(child.tag) == wanted:
            return _bounded_text(child.text, 300)
    return ""


def _risk_score(text: str) -> int:
    words = (
        "war", "missile", "strike", "attack", "crisis", "conflict",
        "military", "nuclear", "invasion", "sanctions", "ceasefire",
        "drone", "weapon", "earthquake", "fire",
    )
    lowered = text.lower()
    return min(10, 1 + sum(1 for word in words if word in lowered) * 2)


class _NewsText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("p", "br", "div"):
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _news_text(value: str, limit: int = 400) -> str:
    parser = _NewsText()
    parser.feed(str(value or "")[:12000])
    return _bounded_text(" ".join("".join(parser.parts).split()), limit)


def _news_date(value: str) -> tuple[str, float]:
    try:
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), date.timestamp()
    except (ValueError, TypeError, OverflowError):
        return "", 0.0


def _normalize_news(root: ET.Element, feed: dict[str, str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in root.iter():
        atom = _local_name(node.tag) == "entry"
        if not atom and _local_name(node.tag) != "item":
            continue
        title = _news_text(_child_text(node, "title"), 300)
        if not title:
            continue
        description = _news_text(_child_text(node, "summary" if atom else "description"))
        url = _child_text(node, "link")
        if atom:
            url = next((child.attrib.get("href", "") for child in node
                        if _local_name(child.tag) == "link" and child.attrib.get("rel", "alternate") == "alternate"), "")
        if urlparse(url).scheme not in ("https", "http"):
            url = ""
        if feed and feed["id"] == "svt" and not urlparse(url).path.startswith("/nyheter/"):
            continue
        published, epoch = _news_date(_child_text(node, "published" if atom else "pubDate"))
        identifier = _child_text(node, "id" if atom else "guid") or url or title
        if feed:
            identifier = feed["id"] + ":" + hashlib.sha256(identifier.encode()).hexdigest()[:24]
        rows.append({
            "id": _bounded_text(identifier, 100), "title": title, "description": description,
            "source": feed["provider"] if feed else "BBC WORLD",
            "language": feed["language"] if feed else "en",
            "source_url": feed["url"] if feed else BBC_URL,
            "published": published, "published_epoch": epoch, "url": url,
            "risk_score": _risk_score(title + " " + description), "type": "news",
        })
        geo = _geocode_text(title + " " + description)
        if geo:
            rows[-1].update(lat=geo[0], lon=geo[1], place=geo[2], location_precision="PLACE_NAME_ESTIMATE")
        if len(rows) >= MAX_NEWS_ROWS:
            break
    return rows


def _build_news_stream() -> list[dict[str, Any]]:
    # Keep publisher diversity without inventing a relevance/verification score.
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_source: dict[str, int] = {}
    for row in sorted(_collections.get("news", []), key=lambda row: row.get("published_epoch", 0), reverse=True):
        source = str(row.get("source") or "NEWS")
        key = str(row.get("url") or row.get("id") or row.get("title"))
        if key in seen or per_source.get(source, 0) >= MAX_STREAM_ROWS:
            continue
        seen.add(key)
        per_source[source] = per_source.get(source, 0) + 1
        stamp, epoch = _news_date(str(row.get("collected_at") or ""))
        stale = bool(row.get("feed_stale")) or (bool(epoch) and time.time() - epoch > CACHE_TTL_SECONDS)
        items.append({**row, "feed_stale": stale, "kind": "news", "time": row.get("published", ""), "summary": row.get("description", "")})
    return items[:MAX_STREAM_ROWS * len(NEWS_FEEDS)]


def _geocode_text(text: str) -> tuple[float, float, str] | None:
    lowered = text.lower()
    for name, lat, lon in PLACE_COORDS:
        if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", lowered):
            return lat, lon, name
    return None


def _stream_item(
    *,
    item_id: str,
    kind: str,
    title: str,
    summary: str,
    source: str,
    time: str,
    url: str,
    lat: float | None,
    lon: float | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": _bounded_text(item_id, 100),
        "kind": kind,
        "title": _bounded_text(title, 220),
        "summary": _bounded_text(summary, 400),
        "source": _bounded_text(source, 48),
        "time": _bounded_text(time, 40),
        "url": _bounded_text(url, 300),
        "risk_score": _risk_score(f"{title} {summary}"),
    }
    if lat is not None and lon is not None:
        payload["lat"] = round(float(lat), 4)
        payload["lon"] = round(float(lon), 4)
    if extra:
        payload.update(extra)
    return payload


def _build_stream() -> list[dict[str, Any]]:
    buckets = [
        [
            _stream_item(
                item_id=str(row.get("id") or row.get("callsign")),
                kind="aircraft",
                title=str(row.get("callsign") or row.get("id") or "AIRCRAFT"),
                summary=(
                    f"{row.get('country') or '—'} · "
                    f"{int(row.get('alt_m') or 0)} m · "
                    f"{int(row.get('heading') or 0)}°"
                ),
                source=str(row.get("source") or (
                    "ADS-B SAMPLE" if _sources["aircraft"].get("region") == "ADS-B SAMPLE" else "OPENSKY"
                )),
                time=str(row.get("last_contact") or ""),
                url="",
                lat=row.get("lat"),
                lon=row.get("lon"),
                extra={
                    "callsign": row.get("callsign") or "",
                    "country": row.get("country") or "",
                    "alt_m": row.get("alt_m"),
                    "heading": row.get("heading"),
                    "speed_mps": row.get("speed_mps"),
                    "squawk": row.get("squawk") or "",
                    "on_ground": bool(row.get("on_ground")),
                    "vert_rate_mps": row.get("vert_rate_mps"),
                },
            )
            for row in (_collections.get("aircraft") or [])[:8]
        ],
        [
            _stream_item(
                item_id=str(row.get("id") or row.get("label")),
                kind="cameras",
                title=str(row.get("label") or row.get("title") or "Camera"),
                summary=str(row.get("city") or row.get("source") or "CCTV"),
                source=str(row.get("source") or "CCTV"),
                time="",
                url=str(row.get("url") or row.get("feed_url") or ""),
                lat=row.get("lat"),
                lon=row.get("lon"),
                extra={
                    "photo": row.get("photo") or "",
                    "media_url": row.get("media_url") or row.get("photo") or "",
                    "live_video": bool(row.get("live_video")),
                    "city": row.get("city") or "",
                    "country": row.get("country") or "",
                },
            )
            for row in (_collections.get("cameras") or [])[:8]
        ],
        [
            _stream_item(
                item_id=str(row.get("id") or row.get("title")),
                kind="gdelt",
                title=str(row.get("title") or "GDELT"),
                summary=str(row.get("summary") or ""),
                source="GDELT",
                time=str(row.get("time") or ""),
                url=str(row.get("url") or ""),
                lat=row.get("lat"),
                lon=row.get("lon"),
                extra={"place": row.get("place") or ""},
            )
            for row in (_collections.get("gdelt") or [])[:8]
        ],
        [
            _stream_item(
                item_id=str(row.get("id") or "quake"),
                kind="earthquakes",
                title=f"M{row.get('magnitude')} {row.get('place') or 'earthquake'}",
                summary=f"Depth {row.get('depth_km')} km",
                source="USGS",
                time=str(row.get("time") or ""),
                url=str(row.get("url") or ""),
                lat=row.get("lat"),
                lon=row.get("lon"),
                extra={"magnitude": row.get("magnitude"), "depth_km": row.get("depth_km")},
            )
            for row in (_collections.get("earthquakes") or [])[:6]
        ],
        [
            _stream_item(
                item_id=str(row.get("id") or "fire"),
                kind="fires",
                title=str(row.get("title") or "Fire"),
                summary=str(row.get("category") or "EONET"),
                source="NASA EONET",
                time=str(row.get("time") or ""),
                url=str(row.get("url") or ""),
                lat=row.get("lat"),
                lon=row.get("lon"),
            )
            for row in (_collections.get("fires") or [])[:6]
        ],
        [
            _stream_item(
                item_id=str(row.get("id")),
                kind="conflicts",
                title=str(row.get("label")),
                summary="Reference watchlist location, not independently verified live status.",
                source="WATCHLIST",
                time="",
                url=OSIRIS_REPOSITORY_URL,
                lat=row.get("lat"),
                lon=row.get("lon"),
                extra={"severity": row.get("severity")},
            )
            for row in REFERENCE_ZONES[:8]
        ],
        [
            _stream_item(
                item_id=str(row.get("id") or row.get("title")),
                kind="news",
                title=str(row.get("title") or "News"),
                summary=str(row.get("description") or ""),
                source=str(row.get("source") or "BBC WORLD"),
                time=str(row.get("published") or ""),
                url=str(row.get("url") or ""),
                lat=row.get("lat"),
                lon=row.get("lon"),
                extra={"place": row.get("place") or ""},
            )
            for row in (_collections.get("news") or [])[:6]
        ],
    ]
    items: list[dict[str, Any]] = []
    index = 0
    while len(items) < MAX_STREAM_ROWS:
        added = False
        for bucket in buckets:
            if index < len(bucket):
                items.append(bucket[index])
                added = True
                if len(items) >= MAX_STREAM_ROWS:
                    break
        if not added:
            break
        index += 1
    return items


def _human_themes(text: str) -> str:
    parts: list[str] = []
    for raw in str(text or "").split(";"):
        token = raw.strip()
        if not token or token.startswith(("TAX_", "WB_", "EPU_", "CRISISLEX_", "UNGP_")):
            continue
        parts.append(token.replace("_", " ").title())
        if len(parts) >= 4:
            break
    return "; ".join(parts)


def _normalize_gdelt(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    features = payload.get("features", []) if isinstance(payload, dict) else []
    features = sorted(
        [feature for feature in features if isinstance(feature, dict)],
        key=lambda feat: (
            0 if "," in str((feat.get("properties") or {}).get("name") or "") else 1
        ),
    )
    seen: set[str] = set()
    for feature in features:
        if len(rows) >= MAX_GDELT_ROWS:
            break
        coords = ((feature.get("geometry") or {}).get("coordinates")) or []
        lon = _float(coords[0] if len(coords) > 0 else None)
        lat = _float(coords[1] if len(coords) > 1 else None)
        if lat is None or lon is None:
            continue
        props = feature.get("properties") or {}
        title = _bounded_text(props.get("name") or "GDELT", 180)
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        url = _bounded_text(props.get("url") or props.get("urlSrc") or "", 300)
        rows.append(
            {
                "id": _bounded_text(url or f"{lat},{lon}", 100),
                "title": title,
                "summary": _human_themes(str(props.get("mentionedthemes") or "")),
                "place": title,
                "time": _bounded_text(
                    props.get("urlpubtimedate") or props.get("seendate") or "", 40
                ),
                "url": url,
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "type": "gdelt",
            }
        )
    return rows


def _solar_value(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item[name]
    return None


def _normalize_solar(payload: Any) -> dict[str, Any]:
    rows = payload if isinstance(payload, list) else []
    latest = rows[-1] if rows and isinstance(rows[-1], dict) else {}
    kp = _float(_solar_value(latest, "kp_index", "Kp", "kp"), 0.0) or 0.0
    if kp >= 8:
        level = "EXTREME"
    elif kp >= 7:
        level = "SEVERE"
    elif kp >= 6:
        level = "STRONG"
    elif kp >= 5:
        level = "MODERATE"
    elif kp >= 4:
        level = "MINOR"
    elif kp >= 3:
        level = "UNSETTLED"
    else:
        level = "QUIET"
    return {
        "kp_index": round(kp, 1),
        "storm_level": level,
        "time": _bounded_text(_solar_value(latest, "time_tag", "time"), 40),
        "samples": len(rows),
    }


def _collect_earthquakes() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _normalize_earthquakes(_read_json(USGS_URL))
    return rows, {}


AIRCRAFT_SAMPLE_POINTS: tuple[tuple[float, float, int], ...] = (
    (52.0, 10.0, 450),
    (40.5, -74.0, 450),
    (34.0, -118.0, 400),
    (35.7, 139.7, 400),
    (25.2, 55.3, 400),
    (59.3, 18.1, 350),
    (-33.9, 151.2, 400),
    (-23.5, -46.6, 400),
)


def _adsb_point_urls(lat: float, lon: float, radius: int) -> tuple[str, str]:
    live = (
        f"https://api.airplanes.live/v2/point/{lat:.3f}/{lon:.3f}/{int(radius)}"
    )
    lol = (
        f"https://api.adsb.lol/v2/lat/{lat:.3f}/lon/{lon:.3f}/dist/{int(radius)}"
    )
    return live, lol


def _collect_adsb_sample() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def pull(url: str) -> None:
        payload = json.loads(
            _read_map_api(url, timeout=6.0).decode("utf-8", errors="replace")
        )
        for row in _normalize_adsb_ac(payload):
            key = str(row.get("id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            row["source"] = urlparse(url).hostname or "ADS-B SAMPLE"
            row["source_url"] = url
            rows.append(row)

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="gg-adsb") as pool:
        jobs = []
        for lat, lon, radius in AIRCRAFT_SAMPLE_POINTS:
            live, lol = _adsb_point_urls(lat, lon, radius)
            jobs.append(pool.submit(pull, live))
            jobs.append(pool.submit(pull, lol))
        for job in as_completed(jobs):
            try:
                job.result()
            except Exception:
                continue
    return _sample_rows(rows, MAX_AIRCRAFT_CATALOG)


def _collect_aircraft() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    region = "OPENSKY"
    try:
        rows = _normalize_aircraft(
            _read_json(OPENSKY_URL), cap=MAX_AIRCRAFT_CATALOG
        )
    except Exception:
        rows = []
    if not rows:
        rows = _collect_adsb_sample()
        region = "ADS-B SAMPLE"
    if not rows:
        with _lock:
            cached = [dict(item) for item in (_collections.get("aircraft") or [])]
        if cached:
            return cached, {"region": "LAST GOOD", "stale": True}
        raise OSError("aircraft feed empty")
    return rows, {"region": region}


def _collect_fires() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _normalize_fires(_read_json(EONET_URL)), {}


def _collect_satellites() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _normalize_satellites(_read_json(CELESTRAK_URL)), {}


def _collect_solar() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = _read_json(NOAA_URL)
    return [], {"solar": _normalize_solar(payload)}


def _collect_news() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    health: list[dict[str, Any]] = []
    successes = 0
    with ThreadPoolExecutor(max_workers=len(NEWS_FEEDS), thread_name_prefix="gg-news") as pool:
        futures = {pool.submit(_read_xml, feed["url"]): feed for feed in NEWS_FEEDS}
        for future in as_completed(futures):
            feed = futures[future]
            stamp = _utc_now()
            try:
                values = sorted(_normalize_news(future.result(), feed), key=lambda row: row["published_epoch"], reverse=True)[:MAX_NEWS_ROWS // len(NEWS_FEEDS)]
                if not values:
                    raise ValueError("No usable news entries")
                values = [{**row, "collected_at": stamp, "feed_stale": False} for row in values]
                with _lock:
                    _news_feed_cache[feed["id"]] = values
                successes += 1
                health.append({**feed, "status": "OK", "last_success_at": stamp, "count": len(values)})
            except Exception as exc:
                with _lock:
                    values = [{**row, "feed_stale": True} for row in _news_feed_cache.get(feed["id"], [])]
                health.append({**feed, "status": "ERROR", "error": _bounded_text(exc, 160),
                               "last_success_at": values[0].get("collected_at", "") if values else "", "count": len(values)})
            rows.extend(values)
    errors = "; ".join(row["provider"] + ": " + row["error"] for row in health if row["status"] == "ERROR")
    rows.sort(key=lambda row: row.get("published_epoch", 0), reverse=True)
    return rows, {"feeds": sorted(health, key=lambda row: row["id"]), "error": errors, "stale": not successes}


def _collect_gdelt() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _normalize_gdelt(_read_json(GDELT_URL, timeout=12.0)), {}


def _load_local_alpr() -> list[dict[str, Any]]:
    """Load the bundled OSM/DeFlock ALPR location sample. Pins only, no video."""
    payload = json.loads(ALPR_SAMPLE_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for feature in payload.get("features") or []:
        if not isinstance(feature, dict):
            continue
        coords = ((feature.get("geometry") or {}).get("coordinates")) or []
        lon = _float(coords[0] if len(coords) > 0 else None)
        lat = _float(coords[1] if len(coords) > 1 else None)
        if lat is None or lon is None:
            continue
        props = feature.get("properties") or {}
        osm_id = _int(props.get("osm"), 0)
        brand = _bounded_text(props.get("brand"), 48) or "ALPR"
        rows.append(
            {
                "id": str(osm_id or f"{lat:.4f},{lon:.4f}"),
                "label": brand,
                "brand": brand,
                "zone": _bounded_text(props.get("zone"), 32),
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "osm_id": osm_id,
                "url": (
                    f"https://www.openstreetmap.org/node/{osm_id}"
                    if osm_id
                    else DEFLOCK_URL
                ),
                "type": "alpr",
                "live_video": False,
            }
        )
    return rows


def _cctv_row(
    *,
    item_id: str,
    label: str,
    lat: float,
    lon: float,
    photo: str,
    source: str,
    city: str = "",
    country: str = "",
) -> dict[str, Any]:
    image = _bounded_text(photo, 300)
    return {
        "id": _bounded_text(item_id, 100),
        "label": _bounded_text(label, 120),
        "title": _bounded_text(label, 120),
        "lat": round(float(lat), 4),
        "lon": round(float(lon), 4),
        "photo": image,
        "media_url": image,
        "feed_url": image,
        "source": _bounded_text(source, 48),
        "city": _bounded_text(city, 48),
        "country": _bounded_text(country, 48),
        "live_video": bool(image),
        "media_kind": "PUBLIC_IMAGE_SNAPSHOT" if image else "NO_MEDIA",
        "availability": "NOT_PROBED",
        "type": "cctv",
    }


def _load_bundled_cctv() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in BUNDLED_CCTV:
        lat = _float(item.get("lat"))
        lon = _float(item.get("lon"))
        if lat is None or lon is None:
            continue
        rows.append(
            _cctv_row(
                item_id=str(item.get("id") or ""),
                label=str(item.get("label") or "Camera"),
                lat=lat,
                lon=lon,
                photo=str(item.get("photo") or ""),
                source=str(item.get("source") or "CCTV"),
                city=str(item.get("city") or ""),
                country=str(item.get("country") or ""),
            )
        )
    return rows


def _normalize_tfl_cameras(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    places = payload if isinstance(payload, list) else []
    for place in places:
        if not isinstance(place, dict):
            continue
        lat = _float(place.get("lat"))
        lon = _float(place.get("lon"))
        if lat is None or lon is None:
            continue
        extras = {
            str(item.get("key") or ""): item.get("value")
            for item in (place.get("additionalProperties") or [])
            if isinstance(item, dict)
        }
        image = _bounded_text(extras.get("imageUrl") or extras.get("videoUrl"), 300)
        if not image:
            continue
        rows.append(
            _cctv_row(
                item_id=str(place.get("id") or f"tfl-{lat:.4f},{lon:.4f}"),
                label=str(place.get("commonName") or "London camera"),
                lat=lat,
                lon=lon,
                photo=image,
                source="TFL",
                city="London",
                country="UK",
            )
        )
    return rows


def _normalize_digitraffic_cameras(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stations = payload.get("cameraStations") if isinstance(payload, dict) else []
    if not isinstance(stations, list):
        stations = []
    for station in stations:
        if not isinstance(station, dict):
            continue
        coords = ((station.get("geometry") or {}).get("coordinates")) or []
        lon = _float(coords[0] if len(coords) > 0 else None)
        lat = _float(coords[1] if len(coords) > 1 else None)
        if lat is None or lon is None:
            continue
        presets = station.get("cameraPresets") or []
        if not isinstance(presets, list):
            continue
        for preset in presets:
            if not isinstance(preset, dict):
                continue
            image = _bounded_text(preset.get("imageUrl"), 300)
            if not image:
                continue
            names = station.get("names") if isinstance(station.get("names"), dict) else {}
            name = (
                preset.get("presentationName")
                or names.get("en")
                or station.get("id")
                or "Finland camera"
            )
            rows.append(
                _cctv_row(
                    item_id=str(preset.get("id") or station.get("id") or image),
                    label=str(name),
                    lat=lat,
                    lon=lon,
                    photo=image,
                    source="DIGITRAFFIC",
                    city="",
                    country="Finland",
                )
            )
    return rows


def _sample_rows(rows: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    if len(rows) <= cap:
        return rows
    step = len(rows) / float(cap)
    return [rows[int(index * step)] for index in range(cap)]


def _collect_cameras() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _load_bundled_cctv()
    errors: list[str] = []
    for url, parser in (
        (TFL_CAM_URL, _normalize_tfl_cameras),
        (FIN_CAM_URL, _normalize_digitraffic_cameras),
    ):
        try:
            rows.extend(parser(_read_json(url, timeout=10.0)))
        except Exception as exc:
            errors.append(_bounded_text(exc, 80))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("id") or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    sampled = _sample_rows(unique, MAX_CAMERA_ROWS)
    return sampled, {
        "total": len(unique),
        "mode": "PUBLIC_SNAPSHOTS",
        "error": "; ".join(errors),
    }


_COLLECTORS: dict[str, Callable[[], tuple[list[dict[str, Any]], dict[str, Any]]]] = {
    "earthquakes": _collect_earthquakes,
    "aircraft": _collect_aircraft,
    "fires": _collect_fires,
    "satellites": _collect_satellites,
    "solar": _collect_solar,
    "news": _collect_news,
    "gdelt": _collect_gdelt,
    "cameras": _collect_cameras,
}


def _history_push(key: str, value: int) -> None:
    values = _histories.setdefault(key, [])
    values.append(max(0, int(value)))
    if len(values) > MAX_HISTORY:
        del values[: len(values) - MAX_HISTORY]


def _viewport_bounds(view: Any) -> tuple[float, float, float, float] | None:
    """Return west, south, east, north from a MapLibre view, if present."""
    if not isinstance(view, dict):
        return None
    raw = view.get("bounds")
    try:
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            first, second = raw
            west, south = float(first[0]), float(first[1])
            east, north = float(second[0]), float(second[1])
        else:
            west = float(view["west"])
            south = float(view["south"])
            east = float(view["east"])
            north = float(view["north"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    west = max(-180.0, min(180.0, west))
    east = max(-180.0, min(180.0, east))
    south = max(-90.0, min(90.0, south))
    north = max(-90.0, min(90.0, north))
    if south > north:
        south, north = north, south
    return west, south, east, north


def _in_view(row: dict[str, Any], bounds: tuple[float, float, float, float] | None) -> bool:
    if bounds is None:
        return True
    lat = _float(row.get("lat"))
    lon = _float(row.get("lon"))
    if lat is None or lon is None:
        return False
    west, south, east, north = bounds
    if not south <= lat <= north:
        return False
    # MapLibre crosses the antimeridian with east < west.
    return west <= lon <= east if west <= east else lon >= west or lon <= east


def _viewport_zoom(view: Any) -> float:
    """Return a bounded zoom value for deterministic level-of-detail rules."""
    try:
        value = float(view.get("zoom")) if isinstance(view, dict) else 1.65
    except (TypeError, ValueError):
        value = 1.65
    return max(0.0, min(18.0, value))


def _cluster_rows(
    rows: list[dict[str, Any]],
    cap: int,
    bounds: tuple[float, float, float, float] | None,
    cell_degrees: float,
    *,
    prefix: str,
    label: str,
    source: str,
    count_key: str,
    cluster_type: str,
) -> list[dict[str, Any]]:
    """Aggregate visible points into cheap, stable geographic buckets.

    This is deliberately a deterministic grid rather than a worker/model
    cluster.  It keeps one-click detail for singleton buckets and carries the
    represented count for dense buckets, so a low zoom never implies that the
    underlying catalog disappeared.
    """
    if not rows:
        return []
    if bounds is None:
        west, south, east, north = -180.0, -90.0, 180.0, 90.0
    else:
        west, south, east, north = bounds
        if east < west:
            east += 360.0
    cell = max(0.05, float(cell_degrees))

    def build(current_cell: float) -> list[dict[str, Any]]:
        buckets: dict[tuple[int, int], dict[str, Any]] = {}
        for row in rows:
            lat = _float(row.get("lat"))
            lon = _float(row.get("lon"))
            if lat is None or lon is None:
                continue
            adjusted_lon = lon
            if east > 180.0 and adjusted_lon < west:
                adjusted_lon += 360.0
            key = (
                int((adjusted_lon - west) / current_cell),
                int((lat - south) / current_cell),
            )
            bucket = buckets.get(key)
            if bucket is None:
                buckets[key] = {
                    "count": 1,
                    "sum_lat": lat,
                    "sum_lon": lon,
                    "first": row,
                }
            else:
                bucket["count"] += 1
                bucket["sum_lat"] += lat
                bucket["sum_lon"] += lon

        output: list[dict[str, Any]] = []
        for key, bucket in buckets.items():
            count = int(bucket["count"] or 0)
            if count == 1:
                singleton = dict(bucket["first"])
                singleton["cluster"] = False
                output.append(singleton)
                continue
            first = bucket["first"]
            lat = float(bucket["sum_lat"]) / count
            lon = float(bucket["sum_lon"]) / count
            if lon > 180.0:
                lon -= 360.0
            output.append(
                {
                    "id": f"{prefix}-{key[0]}-{key[1]}",
                    "label": f"{label} · {count:,}",
                    "title": f"{count:,} indexed {label.lower()}",
                    "summary": f"{count:,} indexed {label.lower()}",
                    "lat": round(lat, 5),
                    "lon": round(lon, 5),
                    "source": source,
                    "cluster": True,
                    "cluster_count": count,
                    count_key: count,
                    "type": cluster_type,
                    "country": str(first.get("country") or "")
                    if label == "CAMERAS"
                    else "",
                    "city": str(first.get("city") or "")
                    if label == "CAMERAS"
                    else "",
                    "live_video": False,
                    "media_kind": "NO_MEDIA" if label == "CAMERAS" else "",
                    "availability": "NOT_PROBED" if label == "CAMERAS" else "",
                }
            )
        output.sort(
            key=lambda item: int(item.get("cluster_count") or 1),
            reverse=True,
        )
        return output

    # If a very dense viewport would still make too many buckets, widen the
    # deterministic grid until the per-source render budget is respected.
    clusters = build(cell)
    for _ in range(8):
        if len(clusters) <= max(1, int(cap)):
            break
        cell *= 1.6
        clusters = build(cell)
    return clusters[: max(1, int(cap))]


def _geo_lod_rows(
    kind: str,
    rows: list[dict[str, Any]],
    cap: int,
    bounds: tuple[float, float, float, float] | None,
    cells: tuple[float, ...],
    *,
    label: str,
    source: str,
    count_key: str,
    cluster_type: str,
) -> list[dict[str, Any]] | None:
    """Read pre-aggregated event buckets, falling back to a coarser level."""
    if _geo_lod_size.get(kind) != len(rows):
        return None
    limit = max(1, int(cap))
    levels = _geo_lod.get(kind) or {}
    for cell in cells:
        buckets = levels.get(cell) or {}
        if not buckets:
            return []
        global_bounds = bounds is None or bounds == (-180.0, -90.0, 180.0, 90.0)
        if global_bounds and len(buckets) > limit:
            continue
        selected: list[tuple[tuple[int, int], dict[str, Any], int, float, float]] = []
        for key, bucket in buckets.items():
            count = int(bucket.get("count") or 0)
            if count <= 0:
                continue
            lat = float(bucket.get("sum_lat") or 0.0) / count
            lon = float(bucket.get("sum_lon") or 0.0) / count
            if bounds is not None and not _in_view({"lat": lat, "lon": lon}, bounds):
                continue
            selected.append((key, bucket, count, lat, lon))
            if len(selected) > limit:
                break
        if len(selected) > limit:
            continue
        output: list[dict[str, Any]] = []
        for key, bucket, count, lat, lon in selected:
            if count == 1:
                singleton = dict(bucket["first"])
                singleton["cluster"] = False
                output.append(singleton)
                continue
            output.append(
                {
                    "id": f"{kind}-cluster-{int(cell * 100)}-{key[0]}-{key[1]}",
                    "label": f"{label} · {count:,}",
                    "title": f"{count:,} indexed {label.lower()}",
                    "summary": f"{count:,} indexed {label.lower()}",
                    "lat": round(lat, 5),
                    "lon": round(lon, 5),
                    "source": source,
                    "cluster": True,
                    "cluster_count": count,
                    count_key: count,
                    "type": cluster_type,
                }
            )
        output.sort(
            key=lambda row: int(row.get("cluster_count") or 1),
            reverse=True,
        )
        output.extend(dict(row) for row in _geo_lod_unlocated.get(kind, ()))
        return output[:limit]
    return None


def _camera_rows_in_view(
    rows: list[dict[str, Any]],
    bounds: tuple[float, float, float, float] | None,
) -> list[dict[str, Any]]:
    if bounds is None or _camera_index_size != len(rows):
        return [row for row in rows if _in_view(row, bounds)]
    west, south, east, north = bounds
    if east < west:
        x_ranges = (
            range(int((west + 180.0) // _CAMERA_INDEX_CELL_DEG), 360),
            range(0, int((east + 180.0) // _CAMERA_INDEX_CELL_DEG) + 1),
        )
    else:
        x_ranges = (
            range(
                max(0, int((west + 180.0) // _CAMERA_INDEX_CELL_DEG)),
                min(359, int((east + 180.0) // _CAMERA_INDEX_CELL_DEG)) + 1,
            ),
        )
    y_start = max(0, int((south + 90.0) // _CAMERA_INDEX_CELL_DEG))
    y_stop = min(179, int((north + 90.0) // _CAMERA_INDEX_CELL_DEG)) + 1
    candidates: list[dict[str, Any]] = []
    for x_range in x_ranges:
        for x in x_range:
            for y in range(y_start, y_stop):
                candidates.extend(_camera_index.get((x, y), ()))
    return [row for row in candidates if _in_view(row, bounds)]


def _camera_lod_rows(
    rows: list[dict[str, Any]],
    cap: int,
    bounds: tuple[float, float, float, float] | None,
    cell: float,
) -> list[dict[str, Any]] | None:
    """Read pre-aggregated camera buckets without scanning the full catalog."""
    if _camera_lod_size != len(rows):
        return None
    buckets = _camera_lod.get(cell)
    if not buckets:
        return []
    global_bounds = bounds is None or bounds == (-180.0, -90.0, 180.0, 90.0)
    if global_bounds and len(buckets) > max(1, int(cap)):
        return None
    selected: list[tuple[tuple[int, int], dict[str, Any], int, float, float]] = []
    for key, bucket in buckets.items():
        count = int(bucket.get("count") or 0)
        if count <= 0:
            continue
        lat = float(bucket.get("sum_lat") or 0.0) / count
        lon = float(bucket.get("sum_lon") or 0.0) / count
        if bounds is not None and not _in_view({"lat": lat, "lon": lon}, bounds):
            continue
        selected.append((key, bucket, count, lat, lon))
        if len(selected) > max(1, int(cap)):
            return None
    output: list[dict[str, Any]] = []
    for key, bucket, count, lat, lon in selected:
        if count == 1:
            singleton = dict(bucket.get("first") or {})
            singleton["cluster"] = False
            output.append(singleton)
            continue
        first = bucket.get("first") or {}
        output.append(
            {
                "id": f"camera-cluster-{int(cell * 100)}-{key[0]}-{key[1]}",
                "label": f"CAMERAS · {count:,}",
                "title": f"{count:,} indexed public cameras",
                "summary": f"{count:,} indexed public cameras",
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "source": "CAMERA INDEX",
                "camera_count": count,
                "cluster_count": count,
                "cluster": True,
                "city": str(first.get("city") or ""),
                "country": str(first.get("country") or ""),
                "live_video": False,
                "media_kind": "NO_MEDIA",
                "availability": "NOT_PROBED",
                "type": "camera_cluster",
            }
        )
    output.sort(
        key=lambda row: int(row.get("camera_count") or 1),
        reverse=True,
    )
    return output


def _camera_clusters(
    rows: list[dict[str, Any]],
    cap: int,
    bounds: tuple[float, float, float, float] | None,
    zoom: float = 1.65,
) -> list[dict[str, Any]]:
    """Turn a large camera catalog into stable map blips, without losing count."""
    if zoom >= LOD_CAMERA_CLUSTER_ZOOM:
        return _sample_rows(rows, cap)
    cells = (8.0, 3.0) if zoom < 2.5 else (3.0, 8.0) if zoom < 4.5 else (1.0, 3.0, 8.0)
    for cell in cells:
        indexed = _camera_lod_rows(rows, cap, bounds, cell)
        if indexed is not None and len(indexed) <= cap:
            return indexed
    cell = cells[-1]
    return _cluster_rows(
        rows,
        cap,
        bounds,
        cell,
        prefix="camera-cluster",
        label="CAMERAS",
        source="CAMERA INDEX",
        count_key="camera_count",
        cluster_type="camera_cluster",
    )


def _render_rows(
    rows: list[dict[str, Any]],
    kind: str,
    cap: int,
    view: Any = None,
) -> list[dict[str, Any]]:
    bounds = _viewport_bounds(view)
    zoom = _viewport_zoom(view)
    if kind == "cameras":
        if zoom < LOD_CAMERA_CLUSTER_ZOOM and _camera_lod_size == len(rows):
            indexed = _camera_clusters(rows, cap, bounds, zoom)
            return [dict(row) for row in indexed]
        visible = _camera_rows_in_view(rows, bounds)
        return [dict(row) for row in _camera_clusters(visible, cap, bounds, zoom)]
    if kind == "aircraft" and zoom < LOD_AIRCRAFT_CLUSTER_ZOOM:
        indexed = _geo_lod_rows(
            kind,
            rows,
            cap,
            bounds,
            (10.0, 4.0, 1.5),
            label="AIRCRAFT",
            source="AIRCRAFT INDEX",
            count_key="aircraft_count",
            cluster_type="aircraft_cluster",
        )
        if indexed is not None:
            return [dict(row) for row in indexed]
    if kind in ("news", "gdelt") and zoom < LOD_EVENT_CLUSTER_ZOOM:
        indexed = _geo_lod_rows(
            kind,
            rows,
            cap,
            bounds,
            (10.0, 4.0, 1.5),
            label="EVENTS",
            source=f"{kind.upper()} INDEX",
            count_key="event_count",
            cluster_type=f"{kind}_cluster",
        )
        if indexed is not None:
            return [dict(row) for row in indexed]
    visible = [row for row in rows if _in_view(row, bounds)]
    located: list[dict[str, Any]] = []
    unlocated: list[dict[str, Any]] = []
    for row in visible:
        if _float(row.get("lat")) is not None and _float(row.get("lon")) is not None:
            located.append(row)
        else:
            unlocated.append(dict(row))
    if kind == "aircraft" and zoom < LOD_AIRCRAFT_CLUSTER_ZOOM:
        cell = 8.0 if zoom < 2.5 else 4.0 if zoom < 4.2 else 1.5
        clustered = _cluster_rows(
            located,
            cap,
            bounds,
            cell,
            prefix="aircraft-cluster",
            label="AIRCRAFT",
            source="AIRCRAFT INDEX",
            count_key="aircraft_count",
            cluster_type="aircraft_cluster",
        )
        return (clustered + unlocated)[:cap]
    if kind in ("news", "gdelt") and zoom < LOD_EVENT_CLUSTER_ZOOM:
        cell = 10.0 if zoom < 2.5 else 4.0 if zoom < 4.5 else 1.5
        clustered = _cluster_rows(
            located,
            cap,
            bounds,
            cell,
            prefix=f"{kind}-cluster",
            label="EVENTS",
            source=f"{kind.upper()} INDEX",
            count_key="event_count",
            cluster_type=f"{kind}_cluster",
        )
        return (clustered + unlocated)[:cap]
    return [dict(row) for row in _sample_rows(visible, cap)]


def _source_health(row: dict[str, Any]) -> dict[str, Any]:
    """Age collection time, never refresh cached data's success timestamp."""
    result = dict(row)
    age: float | None = None
    stamp = str(row.get("last_success_at") or "")
    if stamp:
        try:
            age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(
                stamp.replace("Z", "+00:00")
            )).total_seconds())
        except (ValueError, TypeError):
            pass
    reference = row.get("status") == "REFERENCE"
    expired = age is None or age >= CACHE_TTL_SECONDS
    if row.get("status") == "OK" and expired:
        result["status"] = "STALE"
    result["age_seconds"] = None if age is None else round(age)
    result["stale"] = not reference and (
        expired or result.get("status") != "OK"
    )
    result["freshness"] = "REFERENCE" if reference else (
        "NOT_FETCHED" if not stamp else ("STALE" if result["stale"] else "FRESH")
    )
    return result


def _snapshot_locked(page: str, view: Any = None) -> dict[str, Any]:
    source_rows = [_source_health(row) for row in _sources.values()]
    healthy = sum(1 for row in source_rows if row["status"] in ("OK", "REFERENCE"))
    live = sum(1 for row in source_rows if row["status"] == "OK")
    failed = sum(1 for row in source_rows if row["status"] == "ERROR")
    degraded = sum(1 for row in source_rows if row["status"] in ("STALE", "PARTIAL"))
    if live == len(_COLLECTORS):
        status = "LIVE"
    elif live > 0 or degraded > 0:
        status = "DEGRADED"
    elif failed > 0:
        status = "OFFLINE"
    else:
        status = "READY"
    catalog_counts = {
        "aircraft": len(_collections["aircraft"]),
        "earthquakes": len(_collections["earthquakes"]),
        "fires": len(_collections["fires"]),
        "satellites": len(_collections["satellites"]),
        "news": len(_collections["news"]),
        "gdelt": len(_collections["gdelt"]),
        "cameras": max(_cached_alpr_total(), len(_collections["cameras"])),
        "conflicts": len(REFERENCE_ZONES),
    }
    rendered = {
        "aircraft": _render_rows(
            _collections["aircraft"], "aircraft", MAX_AIRCRAFT_RENDER, view
        ),
        "earthquakes": _render_rows(
            _collections["earthquakes"], "earthquakes", MAX_EARTHQUAKES, view
        ),
        "fires": _render_rows(
            _collections["fires"], "fires", MAX_FIRE_ROWS, view
        ),
        "satellites": _render_rows(
            _collections["satellites"], "satellites", MAX_SATELLITES, view
        ),
        "news": _render_rows(
            _collections["news"], "news", MAX_NEWS_RENDER, view
        ),
        "gdelt": _render_rows(
            _collections["gdelt"], "gdelt", MAX_GDELT_RENDER, view
        ),
        "cameras": _render_rows(
            _collections["cameras"], "cameras", MAX_CAMERA_RENDER, view
        ),
    }
    return {
        "schema": SCHEMA,
        "scope": SAFE_SCOPE,
        "page": str(page or "OVERVIEW").upper(),
        "status": status,
        "generated_at": _last_generated_at,
        "stale": any(row["stale"] for row in source_rows),
        "source_count": len(source_rows),
        "healthy_sources": healthy,
        "counts": catalog_counts,
        "catalog_counts": catalog_counts,
        "render_counts": {key: len(value) for key, value in rendered.items()},
        "viewport": dict(view) if isinstance(view, dict) else {"mode": "GLOBAL"},
        **rendered,
        "solar": dict(_solar),
        "conflicts": [dict(row) for row in REFERENCE_ZONES],
        "stream": _build_stream(),
        "news_stream": _build_news_stream(),
        "sources": source_rows,
        "histories": {key: list(value) for key, value in _histories.items()},
        "focus": {
            "label": "GLOBAL",
            "lat": 22.0,
            "lon": 18.0,
            "note": "Viewport-streamed catalog: aircraft, news, indexed public camera blips.",
        },
        "recon": {
            "mode": "SAFE_BOUNDARY",
            "status": "PUBLIC FEEDS ONLY",
            "available": [
                "SOURCE HEALTH",
                "EVENT MAP",
                "FLIGHT SNAPSHOT",
                "SEISMIC / FIRE / SPACE / NEWS VIEWS",
                "PUBLIC CCTV SNAPSHOTS",
                "ALPR LOCATION PINS (OSM / DEFLOCK SAMPLE)",
                "VIEWPORT-STREAMED BLIPS",
                "CAMERA GRID INDEX",
                "ZOOM-AWARE CLUSTER / RENDER DISTANCE",
                "PAN/ZOOM FRAME-PROTECTED SOURCE SWAPS",
                "3D GLOBE PITCH",
                "CLICK STREAM TO FLY GLOBE",
                "MAP BLIP POPUP + STREAM DETAIL",
                "OSM / OSRM NAVIGATION",
            ],
            "not_enabled": [
                "PORT SCANS",
                "IP SWEEPS",
                "LIVE CAMERA TAKEOVER",
                "ARBITRARY TARGET PROBING",
                "CREDENTIAL ACCESS",
            ],
        },
    }


def empty_snapshot(page: str = "OVERVIEW") -> dict[str, Any]:
    """Return the current local snapshot without causing network activity."""
    with _lock:
        return _snapshot_locked(page)


def snapshot(page: str = "OVERVIEW") -> dict[str, Any]:
    return empty_snapshot(page)


def viewport_snapshot(view: Any = None) -> dict[str, Any]:
    """Return a local render window for the current map viewport.

    This never refreshes feeds.  It is intentionally cheap enough to call
    while the operator pans or zooms the map.
    """
    with _lock:
        return _snapshot_locked("MAP", view if isinstance(view, dict) else {})


def observation_evidence(kind: str, event_id: str) -> dict[str, Any]:
    """Resolve collected records, never UI claims or aggregate map markers."""
    kind = str(kind or "").strip().lower()
    event_id = str(event_id or "")
    with _lock:
        rows = REFERENCE_ZONES if kind == "conflicts" else _collections.get(kind, [])
        row = next((dict(item) for item in rows if str(item.get("id") or "") == event_id), None)
        if not row or not event_id or row.get("cluster") or kind not in _sources:
            return {"status": "OBSERVATION_NOT_FOUND"}
        source = _source_health(_sources[kind])
    reference = kind == "conflicts"
    title = str(row.get("title") or row.get("callsign") or row.get("place") or row.get("label") or row.get("name") or kind)
    summary = str(row.get("summary") or row.get("description") or row.get("category") or "Source-reported record; not independently corroborated.")
    if reference:
        summary = "Reference watchlist location; not a verified live incident."
    origin = str(row.get("source_url") or source["url"])
    provider = str(row.get("source") or source["provider"])
    details = {
        "event_id": event_id,
        "collection": kind,
        "source": provider,
        "feed_url": origin,
        "event_time": str(row.get("time") or row.get("published") or row.get("last_contact") or ""),
        "collected_at": row.get("collected_at") or source.get("last_success_at") or "",
        "source_status": source["status"],
        "freshness": "REFERENCE" if reference else ("STALE" if row.get("feed_stale") else source["freshness"]),
        "location_precision": row.get("location_precision") or (
            "REFERENCE_LOCATION" if reference else "SOURCE_REPORTED"
        ),
        "verification": "NOT_INDEPENDENTLY_CORROBORATED",
    }
    for key in ("lat", "lon", "magnitude", "depth_km", "alt_m", "speed_mps", "heading", "media_kind", "availability"):
        if key in row:
            details[key] = row[key]
    return {
        "status": "OBSERVATION_READY",
        "kind": "OSINT_REFERENCE" if reference else "OSINT_OBSERVATION",
        "title": _bounded_text(title, 180),
        "claim": _bounded_text(summary, 12000),
        "source_url": str(row.get("url") or origin),
        "observed_at": "REFERENCE" if reference else str(row.get("collected_at") or source.get("last_success_at") or "UNKNOWN"),
        "provenance": "REFERENCE" if reference else "SOURCE_REPORTED",
        "confidence": 0.5,
        "details": details,
    }


def _commit_source(source_id: str, result: Any, error: str, stamp: str) -> None:
    """Called under _lock as each collector finishes."""
    global _solar, _alpr_total
    row = _sources[source_id]
    row["last_attempt_at"] = stamp
    if source_id == "conflicts":
        row["status"] = "REFERENCE"
        row["count"] = len(REFERENCE_ZONES)
        row["error"] = ""
        return
    if error:
        row["status"] = "ERROR"
        row["error"] = error
        return
    rows, extras = result or ([], {})
    if extras.get("stale"):
        row["status"] = "STALE"
        row["error"] = str(extras.get("error") or "Feed unavailable; retaining last successful data")
        if source_id == "news":
            row["feeds"] = extras.get("feeds", [])
            _collections["news"] = rows[:MAX_NEWS_ROWS]
            _rebuild_geo_lod("news", _collections["news"])
        # The collector returned our own cache, not a new observation.
        return
    row["last_updated"] = stamp
    row["last_success_at"] = stamp
    if source_id in _collections:
        limit = {
            "aircraft": MAX_AIRCRAFT_CATALOG,
            "news": MAX_NEWS_ROWS,
            "gdelt": MAX_GDELT_ROWS,
            "cameras": MAX_CAMERA_ROWS,
        }.get(source_id, MAX_ROWS)
        _collections[source_id] = rows[:limit]
        if source_id == "cameras":
            _rebuild_camera_index(_collections[source_id])
        elif source_id in ("aircraft", "news", "gdelt"):
            _rebuild_geo_lod(source_id, _collections[source_id])
        _history_push(source_id, len(_collections[source_id]))
        row["count"] = len(_collections[source_id])
    if source_id == "solar":
        _solar = dict(extras.get("solar") or {})
        _history_push("solar", int(round(float(_solar.get("kp_index") or 0) * 10)))
        row["count"] = 1 if _solar else 0
    if source_id == "aircraft":
        region = extras.get("region")
        if region:
            row["region"] = str(region)
    if source_id == "news":
        row["feeds"] = extras.get("feeds", [])
        row["status"] = "PARTIAL" if extras.get("error") else "OK"
        row["error"] = str(extras.get("error") or "")
        return
    if source_id == "cameras":
        _alpr_total = int(extras.get("total") or len(rows))
        row["count"] = _alpr_total
        row["status"] = "PARTIAL" if extras.get("error") else "OK"
        row["error"] = str(extras.get("error") or "")
        return
    row["status"] = "OK"
    row["error"] = ""


def collect_snapshot(page: str = "OVERVIEW", force: bool = False,
                     on_update: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Publish bounded feed results progressively; preserve data on failures."""
    global _last_collect_at, _last_generated_at
    now = time.monotonic()
    with _lock:
        if not force and _last_generated_at and now - _last_collect_at < CACHE_TTL_SECONDS:
            return {**_snapshot_locked(page), "fetching": False}
    last_publish = 0.0
    with ThreadPoolExecutor(max_workers=len(_COLLECTORS), thread_name_prefix="gg-osiris") as pool:
        futures = {pool.submit(collector): source_id for source_id, collector in _COLLECTORS.items()}
        for future in as_completed(futures):
            source_id = futures[future]
            result, error = None, ""
            try:
                result = future.result()
            except Exception as exc:
                error = _bounded_text(exc, 160)
            stamp = _utc_now()
            with _lock:
                _commit_source(source_id, result, error, stamp)
                _last_generated_at = stamp
                publish = on_update and (source_id == "news" or time.monotonic() - last_publish >= 0.35)
                partial = {**_snapshot_locked(page), "fetching": True} if publish else None
            if partial is not None:
                on_update(partial)
                last_publish = time.monotonic()
    with _lock:
        _commit_source("conflicts", None, "", _utc_now())
        _last_collect_at = time.monotonic()
        return {**_snapshot_locked(page), "fetching": False}
