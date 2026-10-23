#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend.tmog_contract import (
        APPIMAGE_NAMES,
        SCHEMA,
        format_kib,
        pulse,
        resolve_appimage,
        snapshot,
    )
    from backend.surface_intent import parse_surface_intent

    folder = Path(tempfile.mkdtemp(prefix="gg-tmog-"))
    fake = folder / "TMOG-Task-Manager-Linux-x86_64.AppImage"
    fake.write_bytes(b"x" * 1_000_001)
    os.chmod(fake, 0o700)
    found = resolve_appimage(search_dirs=(folder,))
    if found != fake:
        raise AssertionError("allowlisted appimage missed")

    alias = folder / "not-tmog.AppImage"
    alias.write_bytes(b"x" * 1_000_001)
    os.chmod(alias, 0o700)
    if resolve_appimage(search_dirs=(folder,)) != fake:
        raise AssertionError("wrong name accepted")

    link_dir = Path(tempfile.mkdtemp(prefix="gg-tmog-link-"))
    linked = link_dir / "TMOG-Task-Manager-Linux-x86_64.AppImage"
    linked.symlink_to(fake)
    if resolve_appimage(search_dirs=(link_dir,)) is not None:
        raise AssertionError("symlink appimage accepted")

    payload = snapshot()
    if payload.get("schema") != SCHEMA:
        raise AssertionError("snapshot schema")
    json.dumps(payload, separators=(",", ":"))
    if not isinstance(payload.get("processes"), list):
        raise AssertionError("process list missing")
    if not isinstance(payload.get("pressure"), dict):
        raise AssertionError("pressure snapshot missing")
    if not isinstance(payload.get("gpus"), list):
        raise AssertionError("gpu rows missing")
    if not any(str(row.get("comm") or "") for row in payload["processes"]):
        raise AssertionError("process comm still empty after two-pass fill")
    light = snapshot("PERFORMANCE")
    if light.get("processes"):
        raise AssertionError("performance page still walks the process table")
    if light.get("connections"):
        raise AssertionError("performance page still parses tcp tables")
    if not light.get("core_hist"):
        raise AssertionError("performance dropped per-core history")
    if not light.get("cores"):
        raise AssertionError("performance dropped per-core rows")
    summary = snapshot("SUMMARY")
    if not summary.get("processes"):
        raise AssertionError("summary page dropped top processes")
    if summary.get("core_hist"):
        raise AssertionError("summary still ships per-core history")
    if summary.get("cores"):
        raise AssertionError("summary still ships per-core rows")
    flight = snapshot("FLIGHT")
    if not isinstance(flight.get("flight_history"), list):
        raise AssertionError("flight history missing")
    drivers = snapshot("DRIVERS")
    if not isinstance(drivers.get("drivers"), list):
        raise AssertionError("driver rows missing")
    if any(
        str(row.get("chip") or "").lower().startswith("nvme")
        for row in (summary.get("temps") or [])
    ):
        raise AssertionError("summary still reads slow nvme hwmon")
    if int(payload.get("process_count") or 0) < 1:
        raise AssertionError("host process count empty")
    if int(payload.get("mem_total_kb") or 0) < 1:
        raise AssertionError("meminfo missing")
    if not isinstance(payload.get("cores"), list):
        raise AssertionError("cpu cores missing")
    if not isinstance(payload.get("cpu_hist"), list):
        raise AssertionError("cpu history missing")
    if not isinstance(payload.get("gpu_busy"), (int, float)):
        raise AssertionError("snapshot gpu meter missing")
    if not isinstance(payload.get("gpu_hist"), list):
        raise AssertionError("gpu history missing")
    if not isinstance(payload.get("mounts"), list):
        raise AssertionError("mounts missing")
    for row in payload["processes"]:
        if "pid" not in row or "comm" not in row or "user" not in row:
            raise AssertionError("process row incomplete")
        if "tombstone" not in row:
            raise AssertionError("process tombstone flag missing")
        break
    if "disk_led" not in payload:
        raise AssertionError("blinkendisk missing")
    beat = pulse()
    if beat.get("schema") != SCHEMA:
        raise AssertionError("pulse schema")
    if beat.get("processes"):
        raise AssertionError("60Hz pulse still walks the process table")
    if "cpu_busy" not in beat or "mem_used_kb" not in beat:
        raise AssertionError("pulse dropped live meters")
    if "gpu_busy" not in beat:
        raise AssertionError("pulse dropped gpu busy")

    from backend import tmog_contract as tmog
    from collections import deque

    src = (PROJECT / "backend" / "tmog_contract.py").read_text(encoding="utf-8")
    if "_io_rate" not in src or "IO_WINDOW" not in src:
        raise AssertionError("tmog meters lost the io target window")
    if "def _gpu_busy" not in src:
        raise AssertionError("gpu busy sysfs probe missing")
    if "IO_ATTACK" in src or "IO_RELEASE" in src:
        raise AssertionError("tmog io still uses an exponential envelope")
    win: deque = deque()
    held = [80000, 1200]
    tmog._io_rate(win, 10.0, 1000, 200, 0.1, held)
    rx, tx = tmog._io_rate(win, 10.004, 1000, 200, 0.1, held)
    if rx != 80000 or tx != 1200:
        raise AssertionError("tiny dt zeroed the held network rate")
    win = deque()
    held = [0, 0]
    tmog._io_rate(win, 10.0, 0, 0, 0.1, held)
    rx, _tx = tmog._io_rate(win, 10.1, 10000, 0, 0.1, held)
    if abs(rx - 100000) > 1:
        raise AssertionError("io target is not bytes/window: " + str(rx))
    tmog._cpu_win.clear()
    tmog._last_cpu = [20.0]
    tmog._cpu_win.append((time.monotonic() - 0.01, [(1000, 800)]))
    held_cpu = tmog._cpu_pcts([(1000, 800)])
    if not held_cpu or abs(held_cpu[0] - 20.0) > 0.15:
        raise AssertionError("cpu % snapped between jiffies: " + str(held_cpu))
    if "GiB" not in format_kib(2_097_152) and "MiB" not in format_kib(2048):
        raise AssertionError("kib format")

    if parse_surface_intent("tmog") != "TMOG":
        raise AssertionError("bare tmog intent")
    if parse_surface_intent("öppna tmog") != "TMOG":
        raise AssertionError("open tmog intent")
    if parse_surface_intent("visa task manager") != "TMOG":
        raise AssertionError("task manager intent")

    from backend.chat_surface_host import ChatSurfaceHost

    src = (PROJECT / "backend" / "chat_surface_host.py").read_text(encoding="utf-8")
    if "tmogSnapshot" not in src or "startTmog" not in src:
        raise AssertionError("host tmog slots missing")
    if "tmogPulse" not in src:
        raise AssertionError("host tmog 60Hz pulse missing")
    if "_tmog_sampler" not in src:
        raise AssertionError("chat disk lamp would double-step the tmog pulse")
    spark_src = (PROJECT / "qml" / "components" / "TmogSpark.qml").read_text(encoding="utf-8")
    if "1 - Math.log(last - index) / logSpan" not in spark_src:
        raise AssertionError("graph x-axis does not prioritize incoming samples")
    embed_src = (PROJECT / "backend" / "tmog_embed.py").read_text(encoding="utf-8")
    if "bash -c" in embed_src or "/bin/sh" in embed_src:
        raise AssertionError("generic shell in tmog embed")
    if "QT_QPA_PLATFORM" not in embed_src:
        raise AssertionError("xcb force missing")
    if any(name not in APPIMAGE_NAMES for name in ("TMOG-Task-Manager-Linux-x86_64.AppImage",)):
        raise AssertionError("expected appimage name missing")

    host = ChatSurfaceHost()
    blob = json.loads(host.tmogSnapshot())
    if blob.get("schema") != SCHEMA:
        raise AssertionError("host snapshot schema")
    deadline = time.monotonic() + 5
    live = json.loads(host.tmogPulse())
    while live.get("pending") and time.monotonic() < deadline:
        time.sleep(0.01)
        live = json.loads(host.tmogPulse())
    if live.get("schema") != SCHEMA or "cpu_busy" not in live:
        raise AssertionError("host pulse schema")
    if host.startTmog():
        raise AssertionError("startTmog without qml root must fail closed")
    if "tmogCopy" not in src:
        raise AssertionError("host tmogCopy slot missing")
    sys_page = snapshot("SYSTEM")
    if int(sys_page.get("core_count") or 0) < 1:
        raise AssertionError("SYSTEM core_count is still 0")
    apps = snapshot("APPS")
    if not apps.get("apps"):
        raise AssertionError("APPS page still empty")
    if not isinstance(apps["apps"][0], dict) or "name" not in apps["apps"][0]:
        raise AssertionError("APPS rows are still bare strings")
    services = snapshot("SERVICES")
    if services.get("services") and not isinstance(services["services"][0], dict):
        raise AssertionError("SERVICES rows are still bare strings")
    from backend.tmog_contract import _hex_ip

    if _hex_ip("00000000000000000000000000000000") != "::":
        raise AssertionError("IPv6 any-address still dumped as hex")
    if _hex_ip("0100007F") != "127.0.0.1":
        raise AssertionError("IPv4 loopback decode")
    loop6 = _hex_ip("00000000000000000000000001000000")
    if not loop6.startswith("::"):
        raise AssertionError("IPv6 loopback lost leading :: : " + loop6)

    qml = (PROJECT / "qml" / "components" / "TmogSurface.qml").read_text(encoding="utf-8")
    if 'objectName: "workspaceTmogPane"' not in qml:
        raise AssertionError("tmog pane objectName")
    if 'objectName: "workspaceTmogHole"' not in qml:
        raise AssertionError("tmog hole missing")
    if "interval: 1000" in qml:
        raise AssertionError("tmog still snapshots every second")
    if "interval: 16" not in qml:
        raise AssertionError("tmog dropped 60Hz live meters")
    if "tmogPulse" not in qml:
        raise AssertionError("tmog UI is not driven by the 60Hz pulse")
    if "function springFollow" not in qml:
        raise AssertionError("network/disk lines lost the spring damper")
    if "property bool diskLampOn" not in qml:
        raise AssertionError("disk activity lamp missing")
    if "lamp: true" not in qml or "lampOn: root.diskLampOn" not in qml:
        raise AssertionError("disk lamp is not on the DISK frame")
    if "parent.width * Math.min(1, root.n(\"disk_led\"))" not in qml:
        raise AssertionError("disk fill bar was removed")
    card_src = (PROJECT / "qml" / "components" / "TmogCard.qml").read_text(encoding="utf-8")
    if "property bool lamp" not in card_src:
        raise AssertionError("TmogCard cannot host the disk lamp")
    if "liveNetYMax" not in qml or "liveDiskYMax" not in qml:
        raise AssertionError("io sparks still autoscale every burst to full height")
    if "Menu {" not in qml or "tmogCopy" not in qml:
        raise AssertionError("tmog right-click copy menu missing")
    if "contentHeight: procCol.height" not in qml:
        raise AssertionError("process list is not scrolling inside the frame")
    if "contentHeight: appCol.height" not in qml:
        raise AssertionError("apps list is not scrolling inside the frame")
    if "contentHeight: svcCol.height" not in qml:
        raise AssertionError("services list is not scrolling inside the frame")
    if "fitContent: true" in qml:
        raise AssertionError("list pages still grow a short frame instead of filling the pane")
    if "TmogRow" not in qml:
        raise AssertionError("list rows are still unstyled Text")
    if "TmogHistoryGraph" not in qml or "toggleProcessSort" not in qml:
        raise AssertionError("tmog history/process interactions missing")
    if "FLIGHT RECORDER" not in qml or "DRIVERS" not in qml:
        raise AssertionError("tmog pro views missing")
    card_src = (PROJECT / "qml" / "components" / "TmogCard.qml").read_text(encoding="utf-8")
    if "clip: true" not in card_src:
        raise AssertionError("TmogCard inner no longer clips overflow to the frame")
    if "core_count" not in qml:
        raise AssertionError("SYSTEM page still uses empty cores array")
    if "tmogSnapshot(root.page)" not in qml:
        raise AssertionError("tmog still dumps every page on each tick")
    if "sourceComponent: summaryPage" not in qml:
        raise AssertionError("summary page is still kept alive off-screen")
    if "sourceComponent: performancePage" not in qml:
        raise AssertionError("performance page is still kept alive off-screen")
    if "sourceComponent: listPage" not in qml:
        raise AssertionError("list pages are still kept alive off-screen")
    if 'leftLegend: "TMOG"' in qml:
        raise AssertionError("tmog pane still nests a TMOG GgFrame inside the workspace frame")
    if '"label": "CLK"' in qml:
        raise AssertionError("TMOG still renders the noisy clock graph")
    if 'leftLegend: "SYS"' not in qml or 'barKey: index === 0' not in qml:
        raise AssertionError("TMOG system meter bar was removed")
    if '"k": "GPU"' not in qml or 'root.perfKey === "GPU"' not in qml:
        raise AssertionError("TMOG performance page has no GPU view")
    for page in (
        '"SUMMARY"',
        '"PERFORMANCE"',
        '"PROCESSES"',
        '"SYSTEM"',
        '"CONNECTIONS"',
        '"DISK"',
        "TmogSpark",
        "TmogCard",
        "TmogMeter",
        "CPU OVERVIEW",
        "THERMALS",
    ):
        if page not in qml:
            raise AssertionError("tmog page missing: " + page)

    card = (PROJECT / "qml" / "components" / "TmogCard.qml").read_text(encoding="utf-8")
    if "property var tabs" not in card or "signal tabChosen" not in card:
        raise AssertionError("tmog card tabs missing")
    spark = (PROJECT / "qml" / "components" / "TmogSpark.qml").read_text(encoding="utf-8")
    if "property var marks" not in spark:
        raise AssertionError("spark marks missing")
    if "property bool fromZero: true" not in spark:
        raise AssertionError("spark fromZero default must stay true for meters")
    if "renderStrategy: Canvas.Threaded" not in spark:
        raise AssertionError("spark rasterization still blocks the GUI thread")
    if "function redraw" not in spark:
        raise AssertionError("spark still paints while hidden")
    if "antialiasing: false" in spark:
        raise AssertionError("spark lines are still aliased dots")
    if 'lineJoin = "round"' not in spark:
        raise AssertionError("spark stroke is still unjoined")
    if "quadraticCurveTo" not in spark:
        raise AssertionError("spark still draws skyscraper corners")

    host.shutdown()
    print("TMOG_CONTRACT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
