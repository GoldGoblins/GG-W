"""Local music tags, complete scanning and cache-only station restoration."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import media_audio_metadata as tags, media_contract as contract


def syncsafe(number):
    return bytes((number >> shift) & 127 for shift in (21, 14, 7, 0))


def id3(values, version=3, artwork=0):
    frames = []
    names = {"artist": "TPE1", "title": "TIT2", "album": "TALB", "genre": "TCON", "track": "TRCK"}
    for field, value in values.items():
        data = b"\x03" + value.encode("utf-8")
        length = syncsafe(len(data)) if version == 4 else struct.pack(">I", len(data))
        frames.append(names[field].encode() + length + b"\x00\x00" + data)
    if artwork:
        frames.insert(0, b"APIC" + struct.pack(">I", artwork) + b"\x00\x00" + b"P" * artwork)
    data = b"".join(frames)
    return b"ID3" + bytes((version, 0, 0)) + syncsafe(len(data)) + data + b"\xff\xfb" + b"\x00" * 64


def atom(name, data):
    return struct.pack(">I", 8 + len(data)) + name + data


def mp4_tags(values):
    names = {"artist": b"\xa9ART", "title": b"\xa9nam", "album": b"\xa9alb", "genre": b"\xa9gen"}
    fields = b"".join(atom(names[k], atom(b"data", b"\x00\x00\x00\x01" + b"\x00" * 4 + v.encode("utf-8"))) for k, v in values.items())
    fields += atom(b"trkn", atom(b"data", b"\x00" * 8 + struct.pack(">HHHH", 0, 7, 12, 0)))
    return atom(b"moov", atom(b"udta", atom(b"meta", b"\x00" * 4 + atom(b"ilst", fields))))


def vorbis(values):
    fields = [f"{key}={value}".encode("utf-8") for key, value in values.items()]
    vendor = b"GG fixture"
    return struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(fields)) + b"".join(struct.pack("<I", len(field)) + field for field in fields)


class AudioMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-audio-tags-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def file(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_id3_tags_override_filename_and_do_not_start_a_decoder(self):
        path = self.file("Wrong artist - Wrong title.mp3", id3(dict(artist="Björk", title="Jóga", album="Homogenic", genre="Electronic", track="2/10")))
        with patch("subprocess.run", side_effect=AssertionError("Metadata started a process")):
            metadata = tags.read_audio_metadata(path)
        self.assertEqual(metadata, dict(artist="Björk", title="Jóga", album="Homogenic", genre="Electronic", track=2))

    def test_id3_artwork_is_skipped_before_reading_text_frames(self):
        path = self.file("Plain.mp3", id3(dict(artist="Real artist", title="After artwork"), artwork=tags.MAX_TAG_BYTES + 65536))
        self.assertEqual(tags.read_audio_metadata(path)["artist"], "Real artist")
        self.assertEqual(tags.read_audio_metadata(path)["title"], "After artwork")

    def test_id3_version_four_and_version_one(self):
        path = self.file("Version four.mp3", id3(dict(artist="V4 artist", title="V4 title"), version=4))
        self.assertEqual(tags.read_audio_metadata(path)["artist"], "V4 artist")
        v1 = b"TAG" + b"Old title".ljust(30, b"\x00") + b"Old artist".ljust(30, b"\x00") + b"Old album".ljust(30, b"\x00")
        v1 += b"1998" + b"".ljust(28, b"\x00") + b"\x00\x04\x11"
        path = self.file("Version one.mp3", b"audio bytes" + v1)
        metadata = tags.read_audio_metadata(path)
        self.assertEqual((metadata["artist"], metadata["title"], metadata["track"]), ("Old artist", "Old title", 4))

    def test_m4a_finds_tail_metadata_by_seeking_past_large_audio_atom(self):
        path = self.root / "Tail.m4a"
        head = atom(b"ftyp", b"M4A " + b"\x00" * 8)
        audio_size = 16 * 1024 * 1024
        with path.open("wb") as stream:
            stream.write(head + struct.pack(">I", audio_size) + b"mdat")
            stream.seek(len(head) + audio_size)
            stream.write(mp4_tags(dict(artist="M4A artist", title="Tagged title", album="Album", genre="Jazz")))
        metadata = tags.read_audio_metadata(path)
        self.assertEqual(metadata, dict(artist="M4A artist", title="Tagged title", album="Album", genre="Jazz", track=7))

    def test_flac_and_opus_vorbis_comments(self):
        comments = vorbis(dict(ARTIST="Tagged artist", TITLE="Tagged song", ALBUM="Tagged album", GENRE="Pop", TRACKNUMBER="3"))
        flac = self.file("Test.flac", b"fLaC" + b"\x84" + len(comments).to_bytes(3, "big") + comments)
        opus = self.file("Test.opus", b"OggS" + b"\x00" * 30 + b"OpusTags" + comments)
        for path in (flac, opus):
            self.assertEqual(tags.read_audio_metadata(path), dict(artist="Tagged artist", title="Tagged song", album="Tagged album", genre="Pop", track=3))

    def test_wave_info_and_honest_filename_fallback(self):
        def chunk(name, value):
            return name + len(value).to_bytes(4, "little") + value + (b"\x00" if len(value) % 2 else b"")
        info = b"INFO" + chunk(b"IART", b"Wave artist\x00") + chunk(b"INAM", b"Wave title\x00")
        body = b"WAVE" + chunk(b"LIST", info)
        wave = self.file("Test.wav", b"RIFF" + len(body).to_bytes(4, "little") + body)
        self.assertEqual(tags.read_audio_metadata(wave)["artist"], "Wave artist")
        named = self.file("03. Filename Artist - Filename Song.mp3", b"not decoded")
        self.assertEqual(tags.read_audio_metadata(named)["artist"], "Filename Artist")
        self.assertEqual(tags.read_audio_metadata(named)["title"], "Filename Song")
        plain = self.file("Unknown_song.wma", b"not decoded")
        self.assertEqual(tags.read_audio_metadata(plain)["artist"], "Okänd artist")
        self.assertEqual(tags.read_audio_metadata(plain)["title"], "Unknown song")

    def test_invalid_tag_lengths_remain_bounded_and_fall_back(self):
        for data in (b"ID3\x03\x00\x00\x7f\x7f\x7f\x7f" + b"TPE1\xff\xff\xff\xff\x00\x00", b"fLaC\x84\xff\xff\xff"):
            path = self.file("Fallback.mp3", data)
            self.assertEqual(tags.read_audio_metadata(path)["artist"], "Okänd artist")

    def test_private_cache_reuses_tags_and_invalidates_fingerprint(self):
        path = self.file("Cached.mp3", id3(dict(artist="First artist", title="First title")))
        cache_path = self.root / "state" / "music-tags-v1.json"
        cache = tags.AudioMetadataCache(cache_path)
        cache.get(path, path.stat())
        cache.save()
        self.assertNotIn(str(self.root), cache_path.read_text(encoding="utf-8"))
        second = tags.AudioMetadataCache(cache_path)
        with patch.object(tags, "read_audio_metadata", side_effect=AssertionError("Unchanged file parsed again")):
            self.assertEqual(second.get(path, path.stat())["artist"], "First artist")
        path.write_bytes(id3(dict(artist="Changed artist", title="New title")))
        self.assertEqual(second.get(path, path.stat())["artist"], "Changed artist")

    def test_cancelled_scan_cache_keeps_unvisited_entries(self):
        a = self.file("A.mp3", id3(dict(artist="A", title="A")))
        b = self.file("B.mp3", id3(dict(artist="B", title="B")))
        cache_path = self.root / "tags.json"
        cache = tags.AudioMetadataCache(cache_path)
        for path in (a, b):
            cache.get(path, path.stat())
        cache.save()
        partial = tags.AudioMetadataCache(cache_path)
        partial.get(a, a.stat())
        partial.save(complete=False)
        self.assertEqual(len(tags.AudioMetadataCache(cache_path).previous), 2)
        complete = tags.AudioMetadataCache(cache_path)
        complete.get(a, a.stat())
        complete.save()
        self.assertEqual(len(tags.AudioMetadataCache(cache_path).previous), 1)

    def test_music_scan_has_no_old_item_or_folder_depth_cutoff_and_marks_local_artist(self):
        music = self.root / "music"
        a = self.file("music/Artist/Album/Disc/Extra/Deep/A.mp3", id3(dict(artist="Artist A", title="Song A", album="Album A", genre="Rock")))
        b = self.file("music/Artist B - Song B.mp3", b"audio file")
        self.file("music/.hidden/Hidden.mp3", b"audio file")
        self.file("music/node_modules/Hidden.mp3", b"audio file")
        self.file("music/Empty.mp3", b"")
        with patch.object(contract, "STATE_DIR", self.root / "state"), patch.object(contract, "library_roots", return_value=[music, music / "Artist"]), patch.object(contract, "MAX_ITEMS", 1), patch.object(contract, "MAX_SCAN_DEPTH", 1):
            rows = contract.music_catalog()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["source"] for row in rows}, {str(a), str(b)})
        self.assertEqual([row["artist"] for row in rows], ["Artist A", "Artist B"])
        self.assertTrue(all(row["local"] and row["source_label"] == "LOKAL" and row["media"] == "file" for row in rows))
        self.assertTrue(all(row["category"] == row["artist"] and row["audio_metadata_version"] == tags.VERSION for row in rows))
        self.assertEqual(rows[0]["genre"], "Rock")

    def test_music_scan_cancelled_before_start_reads_no_audio(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch.object(contract, "STATE_DIR", self.root / "state"), patch.object(contract, "library_roots", return_value=[self.root]), patch.object(tags, "read_audio_metadata", side_effect=AssertionError("Cancelled scan read audio")):
            self.assertEqual(contract.music_catalog(cancel=cancelled), [])

    def test_radio_cache_only_preserves_presets_and_cached_stations_without_network(self):
        payload = [dict(name="Cached station", url="https://example.invalid/cached.mp3")]
        # Reuse the production cache name by recording its normal URL once.
        with patch.object(contract, "STATE_DIR", self.root / "state"), patch.object(contract, "RADIO_BROWSER_COUNTRIES", (("SE", 80),)):
            with patch.object(contract, "_http_get", return_value=json.dumps(payload).encode()) as download:
                contract.radio_browser_stations(country="SE", limit=80)
                self.assertEqual(download.call_count, 1)
            with patch.object(contract, "_http_get", side_effect=AssertionError("Opening radio requested network")), patch.object(contract, "_cached_bytes", side_effect=AssertionError("Cache-only radio tried a refresh")):
                rows = contract.radio_catalog(refresh=False)
        self.assertEqual(len(rows), len(contract.RADIO_PRESETS) + 1)
        self.assertIn("Cached station", [row["title"] for row in rows])
        self.assertTrue(all("availability" not in row for row in rows), "Metadata pretended stations had been decoded")

    def test_radio_missing_or_invalid_cache_keeps_presets(self):
        with patch.object(contract, "STATE_DIR", self.root / "state"), patch.object(contract, "_http_get", side_effect=AssertionError("Cache-only radio requested network")):
            self.assertEqual(len(contract.radio_catalog(refresh=False)), len(contract.RADIO_PRESETS))


if __name__ == "__main__":
    unittest.main()
