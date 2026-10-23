"""Exercise the original uBO engine with real WebView2, video, and persistence."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class VendorArchiveTests(unittest.TestCase):
    def test_archive_rejects_windows_and_parent_path_escapes(self):
        from tools.install_web_filter import unpack
        for name in ("../escape.txt", "/escape.txt", "C:/escape.txt", "..\\escape.txt", "file.txt:stream"):
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="gg-filter-archive-") as directory:
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w") as zipped:
                    zipped.writestr(name, "outside")
                with self.assertRaises(ValueError):
                    unpack(archive.getvalue(), Path(directory) / "inside")
                self.assertFalse((Path(directory) / "escape.txt").exists())

    def test_archive_rejects_links(self):
        from tools.install_web_filter import unpack
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            entry = zipfile.ZipInfo("link")
            entry.external_attr = 0o120777 << 16
            zipped.writestr(entry, "../outside")
        with tempfile.TemporaryDirectory(prefix="gg-filter-link-") as directory:
            with self.assertRaises(ValueError):
                unpack(archive.getvalue(), Path(directory))


@unittest.skipUnless(os.name == "nt", "Windows WebView2 integration")
class WebContentBlockerTests(unittest.TestCase):
    def test_real_filtering_video_site_switch_and_restart(self):
        from backend.platform_process import run_bounded
        from backend.windows_webview import available, extension_directory, LIBRARY_PATH
        if not available():
            self.skipTest("Run the approved WEB filter installer first")
        with tempfile.TemporaryDirectory(prefix="gg-ubo-test-", ignore_cleanup_errors=True) as temporary:
            base = Path(temporary)
            environment = {
                "GG_DESKTOP_STATE_ROOT": str(base / "state"),
                "GG_DESKTOP_DATA_ROOT": str(base / "data"),
                "WEBVIEW2_USER_DATA_FOLDER": str(base / "state/webview2-profile"),
                "GG_WEBVIEW_LIBRARY": str(LIBRARY_PATH),
                "GG_WEB_BLOCKER_PATH": str(extension_directory()),
                "GG_WEB_FILTER_FIXTURE": temporary,
                "QT_QPA_PLATFORM": "windows", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
            }
            for mode in ("--filter-probe", "--restart-probe"):
                code, out, err, reason = run_bounded(
                    [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()), mode],
                    cwd=ROOT, env=environment, timeout=55, max_output_bytes=64 * 1024)
                details = (out + b"\n" + err).decode("utf-8", "replace")
                self.assertEqual(reason, "NONE", details)
                self.assertEqual(code, 0, details)
                self.assertIn("WEB_FILTER_TEST=PASS", details)


def filter_probe(restart=False):
    import http.server
    import subprocess
    import threading
    import time
    from urllib.parse import urlparse
    from backend.platform_support import find_executable
    from backend.native_webview import initialize_native_webview

    fixture = Path(os.environ["GG_WEB_FILTER_FIXTURE"])
    video = fixture / "clip.mp4"
    if not video.exists():
        ffmpeg = find_executable("ffmpeg")
        assert ffmpeg, "FFmpeg is required for the video regression"
        result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", "testsrc2=size=160x90:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "3", "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-movflags", "frag_keyframe+empty_moov+default_base_moof", str(video)],
            capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    media = video.read_bytes()
    requests = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            requests.append(path)
            if path == "/clip.mp4":
                body, mime = media, "video/mp4"
            elif path == "/ads/cbr.js":
                body, mime = b"window.ggAdExecuted=true;", "text/javascript"
            elif path == "/essential.js":
                body, mime = b"window.ggEssentialReady=true;", "text/javascript"
            else:
                body, mime = (b'<!doctype html><title>GG uBlock video fixture</title>'
                    b'<style>body{background:#181818;color:white;font:16px monospace}video{width:85%}</style>'
                    b'<div id="target" class="pk-page-ready"><div id="sales-banner">ADVERTISEMENT</div></div>'
                    b'<video id="v" src="/clip.mp4" autoplay muted loop controls></video>'
                    b'<script src="/essential.js"></script><script src="/ads/cbr.js"></script>'
                    b'<script>window.ggAdSignal=true;</script><p>Original content remains visible.</p>'), "text/html"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    initialize_native_webview()
    from PySide6.QtCore import QUrl
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtWidgets import QApplication
    from backend.windows_webview import WindowsFilteredWebView, extension_url_allowed

    app = QApplication([])
    window = QQuickWindow()
    window.setTitle("GG · uBlock Origin verification")
    window.setWidth(800)
    window.setHeight(560)
    item = WindowsFilteredWebView(window.contentItem())
    item.setWidth(800)
    item.setHeight(560)
    item.url = QUrl(f"http://127.0.0.1:{server.server_port}/player")
    window.show()

    def wait(condition, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.003)
            assert not item.blockerError, item.blockerError
            if condition():
                return
        raise AssertionError("Browser condition timed out")

    def devtools(method, parameters):
        result = []
        item.devtools(method, parameters, result.append)
        wait(lambda: bool(result))
        assert isinstance(result[0], dict), result
        assert "exceptionDetails" not in result[0], result[0]
        return result[0]

    def evaluate(expression, *, gesture=False):
        return devtools("Runtime.evaluate", {"expression": expression, "returnByValue": True,
            "awaitPromise": True, "userGesture": gesture})["result"].get("value")

    def background(expression):
        result = []
        item._background(expression, result.append)
        wait(lambda: bool(result))
        return result[0]

    def playing():
        return evaluate("Boolean(document.querySelector('video')&&v.videoWidth===160&&v.currentTime>0.15&&v.getVideoPlaybackQuality().totalVideoFrames>1)")

    try:
        wait(lambda: item.blockerReady, 30)
        wait(playing)
        if restart:
            wait(lambda: not item.blockerEnabled)
            assert evaluate("window.ggAdExecuted===true&&window.ggEssentialReady===true")
            print("WEB_FILTER_TEST=PASS restart_and_site_preference", flush=True)
            return

        assert item.blockerEnabled
        assert "/ads/cbr.js" not in requests, requests
        assert evaluate("window.ggEssentialReady===true&&!window.ggAdExecuted")
        wait(lambda: evaluate("getComputedStyle(document.getElementById('sales-banner')).display==='none'"))
        # This uses uBO's own scriptlet engine and an in-memory test-only rule.
        assert background("await u.addInMemoryFilter('127.0.0.1##+js(set-constant, ggAdSignal, false)')") is True
        item.reload()
        wait(lambda: evaluate("window.ggAdSignal===false"))
        wait(playing)

        item.toggleBlocker()
        wait(lambda: not item.blockerEnabled and "/ads/cbr.js" in requests)
        wait(playing)
        assert evaluate("window.ggAdExecuted===true&&window.ggEssentialReady===true")
        assert evaluate("getComputedStyle(document.getElementById('sales-banner')).display!=='none'")
        count = requests.count("/ads/cbr.js")
        item.toggleBlocker()
        wait(lambda: item.blockerEnabled and evaluate("window.ggAdSignal===false&&!window.ggAdExecuted"))
        wait(playing)
        assert requests.count("/ads/cbr.js") == count
        # Native video fullscreen and return must preserve decoded playback.
        evaluate("v.requestFullscreen().then(()=>true)", gesture=True)
        assert evaluate("document.fullscreenElement===v")
        evaluate("document.exitFullscreen().then(()=>true)", gesture=True)
        wait(playing)

        settings = []
        item.newWindowRequested.connect(settings.append)
        item.openBlockerSettings()
        assert settings and extension_url_allowed(settings[0])
        assert not extension_url_allowed("chrome-extension://" + "a" * 32 + "/dashboard.html")
        # Leave this site disabled, and verify the preference in a new process.
        item.toggleBlocker()
        wait(lambda: not item.blockerEnabled)
        assert background("u.getNetFilteringSwitch(" + json.dumps(item.url.toString()) + ")") is False
        print("WEB_FILTER_TEST=PASS network cosmetic scriptlet video fullscreen site_switch settings", flush=True)
    finally:
        item.close()
        window.close()
        app.processEvents()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    if "--filter-probe" in sys.argv or "--restart-probe" in sys.argv:
        filter_probe("--restart-probe" in sys.argv)
    else:
        unittest.main()
