#!/usr/bin/env python3
from __future__ import annotations

import html
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _landing(root: Path) -> bytes:
    links: list[str] = []
    for name in (
        "readme.html",
        "snippets/header.html",
        "index.php",
        "wp-login.php",
    ):
        if (root / name).is_file():
            links.append(
                "<li><a href=\"/"
                + html.escape(name)
                + "\">"
                + html.escape(name)
                + "</a></li>"
            )
    body = (
        "<!DOCTYPE html><html><head><meta charset=utf-8>"
        "<title>SITE preview</title>"
        "<style>body{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:#121212;color:#e6e6e6;"
        "margin:2rem}a{color:#c8a97e}</style></head><body>"
        "<h1>Local SITE preview</h1>"
        "<p>This is 127.0.0.1 only. PHP is not running, so WordPress pages "
        "will not look like goldgoblins.se. HTML/CSS/images will.</p>"
        "<ul>"
        + "".join(links)
        + "</ul></body></html>"
    )
    return body.encode("utf-8")


def main() -> int:
    import sys

    if len(sys.argv) != 4:
        return 2
    host = sys.argv[1]
    if host not in {"127.0.0.1", "localhost"}:
        return 2
    port = int(sys.argv[2])
    root = Path(sys.argv[3]).resolve()
    if not root.is_dir():
        return 2

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in {"/", "/index.php", "/index.html"}:
                payload = _landing(root)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            super().do_GET()

    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
