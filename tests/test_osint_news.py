"""RSS/Atom normalization, isolated feed failure and progressive publication."""
from __future__ import annotations
import copy
import json
from concurrent.futures import Future
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import osint_contract as osint
from backend.osint_host import OsintHost

RSS = '''<rss><channel><item><guid>same</guid><title>Nyheter från Stockholm</title>
<description>&lt;p&gt;Nyheter &amp;amp; fakta&lt;/p&gt;&lt;script&gt;hidden&lt;/script&gt;</description>
<link>https://www.svt.se/nyheter/inrikes/report</link><pubDate>Thu, 01 Oct 2026 10:00:00 GMT</pubDate>
</item><item><title>Sport</title><link>https://www.svt.se/sport/report</link></item></channel></rss>'''
ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>same</id><title>Ekot rapporterar</title>
<summary>&lt;p&gt;En sammanfattning&lt;/p&gt;</summary><published>2026-10-01T13:00:00+02:00</published>
<link rel="enclosure" href="https://example.invalid/audio.mp3"/>
<link href="https://www.sverigesradio.se/artikel/report"/></entry></feed>'''


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(osint, '_news_feed_cache', {}))
        self.enterContext(patch.object(osint, '_collections', {key: [] for key in osint._collections}))
        self.enterContext(patch.object(osint, '_sources', copy.deepcopy(osint._sources)))
        self.enterContext(patch.object(osint, '_histories', {key: [] for key in osint._histories}))
        self.enterContext(patch.object(osint, '_last_generated_at', ''))
        self.enterContext(patch.object(osint, '_last_collect_at', 0))
        self.enterContext(patch.object(osint, '_cached_alpr_total', return_value=0))
        self.enterContext(patch.object(osint, '_render_rows', side_effect=lambda rows, *args: rows))
        self.enterContext(patch.object(osint, '_rebuild_geo_lod'))

    def test_atom_rss_dates_source_and_plain_text(self):
        svt = osint._normalize_news(ET.fromstring(RSS), osint.NEWS_FEEDS[0])
        ekot = osint._normalize_news(ET.fromstring(ATOM), osint.NEWS_FEEDS[1])
        self.assertEqual(len(svt), 1, 'SVT sport should not enter OSINT news')
        self.assertEqual(svt[0]['description'], 'Nyheter & fakta')
        self.assertEqual(svt[0]['language'], 'sv')
        self.assertEqual(svt[0]['published'], '2026-10-01T10:00:00Z')
        self.assertEqual(ekot[0]['published'], '2026-10-01T11:00:00Z')
        self.assertEqual(ekot[0]['url'], 'https://www.sverigesradio.se/artikel/report')
        self.assertNotEqual(svt[0]['id'], ekot[0]['id'])
        self.assertEqual(svt[0]['location_precision'], 'PLACE_NAME_ESTIMATE')
        self.assertEqual(svt[0]['source_url'], osint.SVT_URL)

    def test_place_names_do_not_match_fragments_of_swedish_words(self):
        self.assertIsNone(osint._geocode_text('Firande på nationaldagen'))
        self.assertEqual(osint._geocode_text('Stockholm: ny händelse')[2], 'stockholm')

    def test_unusable_dates_and_links_are_not_invented(self):
        row = osint._normalize_news(ET.fromstring('<rss><item><title>T</title><link>javascript:alert(1)</link><pubDate>bad</pubDate></item></rss>'))[0]
        self.assertEqual(row['published'], '')
        self.assertEqual(row['published_epoch'], 0)
        self.assertEqual(row['url'], '')

    def test_one_failed_feed_preserves_its_own_cache_and_timestamp(self):
        def read(url):
            return ET.fromstring(ATOM if url == osint.EKOT_URL else RSS)
        with patch.object(osint, '_read_xml', side_effect=read), patch.object(osint, '_utc_now', return_value='2026-10-01T12:00:00Z'):
            original, _ = osint._collect_news()
        def partial(url):
            if url == osint.EKOT_URL:
                raise OSError('offline')
            return read(url)
        with patch.object(osint, '_read_xml', side_effect=partial), patch.object(osint, '_utc_now', return_value='2026-10-01T12:05:00Z'):
            rows, extras = osint._collect_news()
        ekot = next(row for row in rows if row['source'] == 'SR EKOT')
        self.assertTrue(ekot['feed_stale'])
        self.assertEqual(ekot['collected_at'], '2026-10-01T12:00:00Z')
        self.assertFalse(extras['stale'])
        osint._commit_source('news', (rows, extras), '', '2026-10-01T12:05:00Z')
        self.assertEqual(osint._sources['news']['status'], 'PARTIAL')
        evidence = osint.observation_evidence('news', ekot['id'])
        self.assertEqual(evidence['observed_at'], ekot['collected_at'])
        self.assertEqual(evidence['details']['freshness'], 'STALE')
        with patch.object(osint, '_read_xml', side_effect=OSError('offline')):
            cached = osint._collect_news()
        osint._commit_source('news', cached, '', '2026-10-01T12:06:00Z')
        self.assertEqual(osint._sources['news']['last_success_at'], '2026-10-01T12:05:00Z')
        self.assertEqual(osint._sources['news']['status'], 'STALE')
        self.assertTrue(all(row['feed_stale'] for row in cached[0]))

    def test_stream_sorts_dates_deduplicates_and_keeps_publishers(self):
        rows = [{'id': str(i), 'source': 'SVT NYHETER', 'published_epoch': 100 + i, 'url': f'https://svt.se/{i}'} for i in range(50)]
        rows += [{'id': 'ekot', 'source': 'SR EKOT', 'published_epoch': 80, 'url': 'https://sr.se/a'},
                 {'id': 'bbc', 'source': 'BBC WORLD', 'published_epoch': 70, 'url': 'https://bbc.com/a'}, dict(rows[-1])]
        osint._collections['news'] = rows
        result = osint._build_news_stream()
        self.assertEqual(len(result), osint.MAX_STREAM_ROWS + 2)
        self.assertEqual(result[0]['published_epoch'], 149)
        self.assertEqual(len({row['url'] for row in result}), len(result))
        self.assertEqual({row['source'] for row in result}, {'SVT NYHETER', 'SR EKOT', 'BBC WORLD'})

    def test_terminal_error_clears_fetching_and_ui_remembers_news_filter(self):
        host = OsintHost()
        self.addCleanup(host.shutdown)
        emitted = []
        host.updated.connect(lambda raw: emitted.append(json.loads(raw)))
        future = Future()
        future.set_exception(OSError('failed'))
        host._finished(future)
        self.assertEqual(emitted[-1]['status'], 'ERROR')
        self.assertFalse(emitted[-1]['fetching'])
        host.saveUi(json.dumps({'streamMode': 'SVENSKA'}))
        self.assertEqual(json.loads(host.loadUi())['streamMode'], 'SVENSKA')

    def test_news_publishes_before_slow_collector_finishes(self):
        release = threading.Event()
        published = threading.Event()
        slow_done = threading.Event()
        errors = []
        partials = []
        def slow():
            if not release.wait(2):
                raise TimeoutError('test release missing')
            slow_done.set()
            return [], {}
        def update(snapshot):
            partials.append(snapshot)
            if snapshot['news_stream']:
                published.set()
        def run():
            try:
                osint.collect_snapshot(force=True, on_update=update)
            except Exception as exc:
                errors.append(exc)
        with patch.object(osint, '_COLLECTORS', {'aircraft': slow, 'news': lambda: ([{'id': 'n', 'title': 'Ready'}], {})}):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(published.wait(1))
                self.assertFalse(slow_done.is_set())
                self.assertTrue(partials[-1]['fetching'])
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
