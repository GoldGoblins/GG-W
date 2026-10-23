#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend.mini_vt import MiniVt, rgb_of

    screen = MiniVt(4, 10)
    screen.feed("hello")
    if "hello" not in screen.display():
        raise AssertionError("vt put failed")
    screen.feed("\x1b[2J\x1b[HABC")
    shown = screen.display()
    if "hello" in shown:
        raise AssertionError("vt clear did not replace the screen")
    if not shown.startswith("ABC"):
        raise AssertionError("vt home write failed: " + repr(shown))

    screen.feed("\x1b[31mX")
    cell = screen.buf[screen.r][screen.c - 1]
    if cell[0] != "X":
        raise AssertionError("sgr glyph lost")
    if cell[1] != 1:
        raise AssertionError("sgr red fg missing: " + repr(cell))
    red = rgb_of(cell[1], True)
    if red[0] < 200 or red[1] > 20:
        raise AssertionError("red palette wrong: " + repr(red))

    screen.feed("\x1b[2J\x1b[H\x1b[?1049hALT\x1b[?1049l")
    if "ALT" in screen.display():
        raise AssertionError("alt screen leaked into primary")

    screen.feed("\x1b[6n")
    if not screen.out or "R" not in screen.out[-1]:
        raise AssertionError("cursor report missing")

    screen.feed("\x1b[?1000h\x1b[?1006h")
    report = screen.mouse_report(2, 3, 0, True)
    if report != "\x1b[<0;3;4M":
        raise AssertionError("sgr mouse report wrong: " + repr(report))

    legacy = MiniVt(4, 10)
    legacy.feed("\x1b[?1000h")
    report = legacy.mouse_report(2, 3, 64, True)
    if report != "\x1b[M`#$":
        raise AssertionError("legacy mouse report wrong: " + repr(report))
    release = legacy.mouse_report(2, 3, 0, False)
    if release != "\x1b[M##$":
        raise AssertionError("legacy mouse release wrong: " + repr(release))

    screen = MiniVt(4, 10)
    screen.feed("1234567890abcdef")
    body = screen.display()
    if "abcdef" not in body:
        raise AssertionError("wrap/scroll lost tail: " + repr(body))

    inline = MiniVt(3, 12)
    inline.feed("one\ntwo\nthree\nfour\n")
    if not inline.history:
        raise AssertionError("inline VT did not retain scrollback")
    if "one" not in inline.plain_text():
        raise AssertionError("plain_text lost scrollback: " + repr(inline.plain_text()))

    region = MiniVt(5, 20)
    region.feed("\x1b[1;4r\x1b[Hone\r\ntwo\r\nthree\r\nfour\r\nfive")
    history_text = "\n".join(
        "".join(cell[0] for cell in row).rstrip()
        for row in region.history
    )
    if not region.history or "one" not in history_text:
        raise AssertionError("top-anchored scroll region did not retain scrollback")

    print("MINI_VT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
