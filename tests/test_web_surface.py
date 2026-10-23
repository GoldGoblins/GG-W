#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    import shutil
    import tempfile
    from backend import web_surface

    saved_root = web_surface.SITE_ROOT
    web_surface.SITE_ROOT = Path(tempfile.mkdtemp(prefix="gg-site-test-")) / "site"
    try:
        return _run(web_surface)
    finally:
        web_surface.SITE_ROOT = saved_root


def _run(web_surface) -> int:
    if web_surface.PROFILE_ROOT.name != "web-profile":
        raise AssertionError("WEB cookie profile root missing")
    profile = web_surface.ensure_web_profile_root()
    if not profile.is_dir():
        raise AssertionError("WEB cookie profile directory missing")
    web_surface.ensure_site_root()
    files = web_surface.list_site_files()
    if "index.html" not in files:
        raise AssertionError("site seed index missing")
    preferred = web_surface.preferred_site_file()
    if preferred and not (web_surface.SITE_ROOT / preferred).is_file():
        raise AssertionError("preferred site file missing")
    if not web_surface.url_allowed(web_surface.default_web_url()):
        raise AssertionError("local site url rejected")
    if not web_surface.url_allowed("about:blank"):
        raise AssertionError("SITE webengine blank document rejected")
    if not web_surface.url_allowed("http://127.0.0.1:8765/"):
        raise AssertionError("SITE localhost preview rejected")
    if web_surface.url_allowed("https://example.com/"):
        raise AssertionError("open internet url accepted")
    if web_surface.url_allowed("javascript:alert(1)"):
        raise AssertionError("javascript url accepted")
    if not web_surface.url_allowed("https://goldgoblins.se/"):
        raise AssertionError("allowlisted origin rejected")
    saved = web_surface.write_site_file("snippets/header.html", "<header>ok</header>\n")
    if not saved:
        raise AssertionError("site write failed")
    if "ok" not in web_surface.read_site_file("snippets/header.html"):
        raise AssertionError("site read mismatch")
    if web_surface.write_site_file("../escape.html", "no"):
        raise AssertionError("site path escape accepted")
    if not web_surface.browse_url_allowed("https://example.com/"):
        raise AssertionError("WEB browse https rejected")
    if web_surface.browse_url_allowed("javascript:alert(1)"):
        raise AssertionError("WEB javascript accepted")
    if web_surface.browse_url_allowed(web_surface.default_web_url()):
        raise AssertionError("WEB must not open SITE file urls")
    if web_surface.normalize_browse_url("example.com") != "https://example.com":
        raise AssertionError("WEB url normalize failed")
    from backend.grok_worker_contract import resolve_workspace_surface
    from backend.chat_context_compiler import compile_chat_prompt

    surface = resolve_workspace_surface("ws.site.file.index.html")
    assert str(surface["source_path"]).startswith("site:")
    assert "Blank slate" in str(surface["body"])
    prompt = compile_chat_prompt("ändra rubriken", "@current", surface)
    assert "LASER_SITE_FILE" in prompt
    assert "Blank slate" in prompt
    assert "EDIT_OBLIGATION=PROPOSE_ONLY_NO_APPLY" in prompt
    assert "GG_EDIT_PROPOSAL=" in prompt
    import io
    import zipfile
    from pathlib import Path
    import tempfile

    scratch = Path(tempfile.mkdtemp(prefix="gg-site-import-"))
    payload = scratch / "site.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("index.html", "<h1>imported-gg</h1>\n")
        archive.writestr("../escape.html", "no\n")
        archive.writestr("snippets/hero.html", "<section>hero</section>\n")
        archive.writestr("wp-config.php", "<?php // secret\n")
    notes: list[tuple[str, int, int, str]] = []
    result = web_surface.import_site_tree(
        str(payload),
        progress=lambda phase, current, total, extra: notes.append(
            (phase, current, total, extra)
        ),
    )
    if not notes or notes[0][0] != "BACKUP":
        raise AssertionError("import made no real progress events")
    if not str(result).startswith("PASS"):
        raise AssertionError("zip import failed: " + result)
    if "skipped" not in result:
        raise AssertionError("import summary hid skipped files")
    if "imported-gg" not in web_surface.read_site_file("index.html"):
        raise AssertionError("imported index missing")
    if web_surface.read_site_file("../escape.html"):
        raise AssertionError("zip escape leaked")
    if "hero" not in web_surface.read_site_file("snippets/hero.html"):
        raise AssertionError("imported snippet missing")
    if web_surface.read_site_file("wp-config.php"):
        raise AssertionError("wp-config leaked through import")
    print("WEB_SURFACE_TEST=PASS")
    print("NETWORK_AUTHORITY=NONE")
    print("WEB=USER_BROWSE_HTTP_HTTPS")
    if web_surface.IMPORT_PROGRESS_BATCH < 1:
        raise AssertionError("import batches missing")
    argv = web_surface.preview_argv(8765)
    joined = " ".join(argv)
    if "127.0.0.1" not in joined:
        raise AssertionError("preview is not bound to localhost")
    if "0.0.0.0" in joined:
        raise AssertionError("preview bound to all interfaces")
    kind = web_surface.preview_kind()
    if kind == "STATIC" and "site_preview_server.py" not in joined:
        raise AssertionError("static preview server script missing")
    if kind == "PHP" and "php" not in joined.lower():
        raise AssertionError("PHP preview argv missing php")
    print("SITE=LOCAL_ALLOWLIST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
