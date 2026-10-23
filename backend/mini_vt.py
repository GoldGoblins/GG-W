from __future__ import annotations

import unicodedata

DEFAULT_FG = -1
DEFAULT_BG = -2
TRUECOLOR = 0x1000000
BOLD = 1
DIM = 2
ITALIC = 4
UNDERLINE = 8
INVERSE = 16
HIDDEN = 32
STRIKE = 64
DEFAULT_FG_RGB = (0xD8, 0xDE, 0xE9)
DEFAULT_BG_RGB = (0x16, 0x16, 0x16)


def _cube_level(n: int) -> int:
    return (0, 95, 135, 175, 215, 255)[n]


def _build_palette() -> tuple[tuple[int, int, int], ...]:
    base = (
        (0, 0, 0),
        (205, 0, 0),
        (0, 205, 0),
        (205, 205, 0),
        (0, 0, 238),
        (205, 0, 205),
        (0, 205, 205),
        (229, 229, 229),
        (127, 127, 127),
        (255, 0, 0),
        (0, 255, 0),
        (255, 255, 0),
        (92, 92, 255),
        (255, 0, 255),
        (0, 255, 255),
        (255, 255, 255),
    )
    cube = tuple(
        (_cube_level(r), _cube_level(g), _cube_level(b))
        for r in range(6)
        for g in range(6)
        for b in range(6)
    )
    gray = tuple((8 + 10 * i, 8 + 10 * i, 8 + 10 * i) for i in range(24))
    return base + cube + gray


PALETTE = _build_palette()

_DEC_GRAPHICS = {
    "`": "◆",
    "a": "▒",
    "f": "°",
    "g": "±",
    "h": "█",
    "j": "┘",
    "k": "┐",
    "l": "┌",
    "m": "└",
    "n": "┼",
    "o": "⎺",
    "p": "⎻",
    "q": "─",
    "r": "⎼",
    "s": "⎽",
    "t": "├",
    "u": "┤",
    "v": "┴",
    "w": "┬",
    "x": "│",
    "y": "≤",
    "z": "≥",
    "{": "π",
    "|": "≠",
    "}": "£",
    "~": "·",
}


def cell_width(ch: str) -> int:
    if not ch:
        return 0
    code = ord(ch)
    if code < 32 or code == 127:
        return 0
    if unicodedata.combining(ch):
        return 0
    width = unicodedata.east_asian_width(ch)
    if width in {"F", "W"}:
        return 2
    return 1


def pack_rgb(red: int, green: int, blue: int) -> int:
    return (
        TRUECOLOR
        | ((red & 255) << 16)
        | ((green & 255) << 8)
        | (blue & 255)
    )


def rgb_of(code: int, is_fg: bool = True) -> tuple[int, int, int]:
    if code == DEFAULT_FG:
        return DEFAULT_FG_RGB
    if code == DEFAULT_BG:
        return DEFAULT_BG_RGB
    if code >= TRUECOLOR:
        value = code & 0xFFFFFF
        return ((value >> 16) & 255, (value >> 8) & 255, value & 255)
    if 0 <= code <= 255:
        return PALETTE[code]
    return DEFAULT_FG_RGB if is_fg else DEFAULT_BG_RGB


class MiniVt:
    """Small VT cursor screen with bounded terminal line scrollback."""

    HISTORY_LIMIT = 2000

    def __init__(self, rows: int = 36, cols: int = 72) -> None:
        self.rows = max(2, int(rows))
        self.cols = max(4, int(cols))
        self.out: list[str] = []
        self.reset()

    def reset(self) -> None:
        self.fg = DEFAULT_FG
        self.bg = DEFAULT_BG
        self.flags = 0
        self.g0_graphics = False
        self.wrap = True
        self._pending_wrap = False
        self.buf = [self._blank_row() for _ in range(self.rows)]
        self.history: list[list[tuple[str, int, int, int]]] = []
        self.history_version = 0
        self.r = 0
        self.c = 0
        self._mode = "text"
        self._csi = ""
        self.scroll_top = 0
        self.scroll_bottom = self.rows - 1
        self.cursor_visible = True
        self.origin = False
        self.insert_mode = False
        self.app_cursor = False
        self.app_keypad = False
        self.mouse_mode = 0
        self.mouse_sgr = False
        self.bracket_paste = False
        self.alt_screen = False
        self._alt: list | None = None
        self.saved = self._cursor_state()

    def display(self) -> str:
        lines = ["".join(cell[0] for cell in row).rstrip() for row in self.buf]
        while len(lines) > 1 and lines[-1] == "":
            lines.pop()
        return "\n".join(lines) + "\n"

    def plain_text(self) -> str:
        rows = list(self.buf) if self.alt_screen else list(self.history) + list(self.buf)
        lines = ["".join(cell[0] for cell in row).rstrip() for row in rows]
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)

    def resize(self, rows: int, cols: int) -> None:
        rows = max(2, int(rows))
        cols = max(4, int(cols))
        if rows == self.rows and cols == self.cols:
            return
        old = self.buf
        self.rows = rows
        self.cols = cols
        self.scroll_top = 0
        self.scroll_bottom = rows - 1
        self.buf = [self._blank_row() for _ in range(rows)]
        copy_rows = min(rows, len(old))
        copy_cols = min(cols, len(old[0]) if old else 0)
        for y in range(copy_rows):
            self.buf[y][:copy_cols] = old[y][:copy_cols]
        self.r = min(self.r, rows - 1)
        self.c = min(self.c, cols - 1)
        self._pending_wrap = False
        self._alt = None
        self.alt_screen = False
        self.history.clear()
        self.history_version += 1

    def feed(self, data: str) -> None:
        for ch in str(data or ""):
            self._step(ch)

    def mouse_report(
        self,
        col: int,
        row: int,
        button: int,
        pressed: bool,
        motion: bool = False,
    ) -> str:
        if self.mouse_mode == 0:
            return ""
        x = max(1, min(self.cols, int(col) + 1))
        y = max(1, min(self.rows, int(row) + 1))
        code = int(button)
        if motion:
            code |= 32
        if not pressed and not motion:
            if self.mouse_sgr:
                return f"\x1b[<{code};{x};{y}m"
            # Legacy tracking uses button code 3 for release.  X10 itself
            # only reports presses, while 1000+ tracking expects the release
            # packet; emitting it is harmless for X10 and keeps ordinary
            # clicks complete for TUIs that do not use SGR.
            code = 3
        if self.mouse_sgr:
            suffix = "M" if pressed or motion else "m"
            return f"\x1b[<{code};{x};{y}{suffix}"
        # Some TUIs enable the legacy X10/UTF-8 mouse protocol instead of
        # SGR.  Returning an empty string here made wheel and click events
        # silently disappear, so the visible terminal could not scroll even
        # though it had mouse reporting enabled.  The legacy packet is
        # ESC [ M followed by button, column and row bytes (coordinates are
        # one-based and limited to the protocol's 223-cell range).
        legacy_code = 32 + code
        legacy_x = 32 + min(223, x)
        legacy_y = 32 + min(223, y)
        return "\x1b[M" + bytes((legacy_code, legacy_x, legacy_y)).decode(
            "latin1"
        )

    def cursor_report(self) -> str:
        return f"\x1b[{self.r + 1};{self.c + 1}R"

    def _blank_cell(self) -> tuple[str, int, int, int]:
        return (" ", self.fg, self.bg, 0)

    def _blank_row(self) -> list[tuple[str, int, int, int]]:
        cell = self._blank_cell()
        return [cell for _ in range(self.cols)]

    def _cursor_state(self) -> tuple:
        return (
            self.r,
            self.c,
            self.fg,
            self.bg,
            self.flags,
            self.g0_graphics,
        )

    def _save_cursor(self) -> None:
        self.saved = self._cursor_state()

    def _restore_cursor(self) -> None:
        self.r, self.c, self.fg, self.bg, self.flags, self.g0_graphics = self.saved
        self.r = min(self.rows - 1, max(0, self.r))
        self.c = min(self.cols - 1, max(0, self.c))
        self._pending_wrap = False

    def _reply(self, text: str) -> None:
        if text:
            self.out.append(text)

    def _step(self, ch: str) -> None:
        if self._mode == "osc":
            if ch == "\x07":
                self._mode = "text"
            elif ch == "\x1b":
                self._mode = "osc_st"
            return
        if self._mode == "osc_st":
            self._mode = "text" if ch == "\\" else "osc"
            return
        if self._mode == "esc":
            if ch == "[":
                self._mode = "csi"
                self._csi = ""
            elif ch == "]":
                self._mode = "osc"
            elif ch in "()":
                self._mode = "esc_one"
                self._esc_one = ch
            elif ch == "7":
                self._save_cursor()
                self._mode = "text"
            elif ch == "8":
                self._restore_cursor()
                self._mode = "text"
            elif ch == "c":
                self.reset()
            elif ch == "M":
                self._reverse_index()
                self._mode = "text"
            elif ch == "D":
                self._index()
                self._mode = "text"
            elif ch == "E":
                self._index()
                self.c = 0
                self._pending_wrap = False
                self._mode = "text"
            elif ch == "=":
                self.app_keypad = True
                self._mode = "text"
            elif ch == ">":
                self.app_keypad = False
                self._mode = "text"
            else:
                self._mode = "text"
            return
        if self._mode == "esc_one":
            if getattr(self, "_esc_one", "(") == "(":
                self.g0_graphics = ch == "0"
            self._mode = "text"
            return
        if self._mode == "csi":
            if ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ch in "@`~":
                self._csi_exec(self._csi, ch)
                self._mode = "text"
            else:
                self._csi += ch
            return
        if ch == "\x1b":
            self._mode = "esc"
            return
        self._put(ch)

    def _put(self, ch: str) -> None:
        if ch == "\n":
            self._index()
            return
        if ch == "\r":
            self.c = 0
            self._pending_wrap = False
            return
        if ch == "\b":
            self._pending_wrap = False
            self.c = max(0, self.c - 1)
            return
        if ch == "\t":
            self.c = min(self.cols - 1, (self.c // 8 + 1) * 8)
            self._pending_wrap = False
            return
        if ch == "\x07":
            return
        if ord(ch) < 32:
            return
        glyph = _DEC_GRAPHICS.get(ch, ch) if self.g0_graphics else ch
        width = cell_width(glyph)
        if width <= 0:
            return
        if self._pending_wrap and self.wrap:
            self._index()
            self.c = 0
            self._pending_wrap = False
        if self.c + width > self.cols:
            if self.wrap:
                self._index()
                self.c = 0
            else:
                self.c = self.cols - width
        if self.insert_mode and self.c + width <= self.cols:
            row = self.buf[self.r]
            self.buf[self.r] = (
                row[: self.c]
                + [self._blank_cell() for _ in range(width)]
                + row[self.c : self.cols - width]
            )
        self.buf[self.r][self.c] = (glyph, self.fg, self.bg, self.flags)
        if width == 2 and self.c + 1 < self.cols:
            self.buf[self.r][self.c + 1] = ("", self.fg, self.bg, self.flags)
        self.c += width
        if self.c >= self.cols:
            self.c = self.cols - 1
            self._pending_wrap = self.wrap

    def _nums(self, raw: str) -> list[int]:
        body = raw.lstrip("?")
        if body.startswith(">"):
            body = body[1:]
        if not body:
            return []
        out: list[int] = []
        for part in body.split(";"):
            if part.isdigit():
                out.append(int(part))
            elif part == "":
                out.append(0)
        return out

    def _erase_row(self, row: int, start: int, end: int) -> None:
        blank = self._blank_cell()
        for x in range(start, end):
            self.buf[row][x] = blank

    def _erase_screen(self) -> None:
        blank = self._blank_cell()
        for y in range(self.rows):
            self.buf[y] = [blank] * self.cols
        self._pending_wrap = False

    def _row_home(self) -> int:
        return self.scroll_top if self.origin else 0

    def _clamp_cursor(self) -> None:
        top = self._row_home()
        bottom = self.scroll_bottom if self.origin else self.rows - 1
        self.r = min(bottom, max(top, self.r))
        self.c = min(self.cols - 1, max(0, self.c))

    def _remember_scrolled_row(self, row: list[tuple[str, int, int, int]]) -> None:
        """Keep rows leaving the top-anchored viewport in terminal scrollback."""
        self.history.append(row[:])
        self.history_version += 1
        if len(self.history) > self.HISTORY_LIMIT:
            del self.history[:-self.HISTORY_LIMIT]

    def _index(self) -> None:
        self._pending_wrap = False
        if self.r == self.scroll_bottom:
            self._scroll_up(1)
            return
        if self.r < self.rows - 1:
            self.r += 1

    def _reverse_index(self) -> None:
        self._pending_wrap = False
        if self.r == self.scroll_top:
            self._scroll_down(1)
            return
        if self.r > 0:
            self.r -= 1

    def _scroll_up(self, count: int) -> None:
        count = max(1, count)
        top = self.scroll_top
        bot = self.scroll_bottom
        region = self.buf[top : bot + 1]
        for _ in range(count):
            if region:
                removed = region.pop(0)
                if top == 0 and not self.alt_screen:
                    self._remember_scrolled_row(removed)
            region.append(self._blank_row())
        self.buf[top : bot + 1] = region

    def _scroll_down(self, count: int) -> None:
        count = max(1, count)
        top = self.scroll_top
        bot = self.scroll_bottom
        region = self.buf[top : bot + 1]
        for _ in range(count):
            region.pop()
            region.insert(0, self._blank_row())
        self.buf[top : bot + 1] = region

    def _swap_alt(self, enable: bool) -> None:
        if enable and not self.alt_screen:
            self._alt = (
                [row[:] for row in self.buf],
                self.r,
                self.c,
                self.scroll_top,
                self.scroll_bottom,
                self._pending_wrap,
            )
            self._erase_screen()
            self.r = 0
            self.c = 0
            self.alt_screen = True
            return
        if not enable and self.alt_screen and self._alt is not None:
            self.buf, self.r, self.c, self.scroll_top, self.scroll_bottom, self._pending_wrap = self._alt
            if len(self.buf) != self.rows or (self.buf and len(self.buf[0]) != self.cols):
                self.resize(self.rows, self.cols)
            self._alt = None
            self.alt_screen = False

    def _sgr(self, nums: list[int]) -> None:
        if not nums:
            nums = [0]
        i = 0
        while i < len(nums):
            n = nums[i]
            if n == 0:
                self.fg = DEFAULT_FG
                self.bg = DEFAULT_BG
                self.flags = 0
            elif n == 1:
                self.flags |= BOLD
            elif n == 2:
                self.flags |= DIM
            elif n == 3:
                self.flags |= ITALIC
            elif n == 4:
                self.flags |= UNDERLINE
            elif n == 7:
                self.flags |= INVERSE
            elif n == 8:
                self.flags |= HIDDEN
            elif n == 9:
                self.flags |= STRIKE
            elif n == 21 or n == 22:
                self.flags &= ~(BOLD | DIM)
            elif n == 23:
                self.flags &= ~ITALIC
            elif n == 24:
                self.flags &= ~UNDERLINE
            elif n == 27:
                self.flags &= ~INVERSE
            elif n == 28:
                self.flags &= ~HIDDEN
            elif n == 29:
                self.flags &= ~STRIKE
            elif 30 <= n <= 37:
                self.fg = n - 30
            elif n == 39:
                self.fg = DEFAULT_FG
            elif 40 <= n <= 47:
                self.bg = n - 40
            elif n == 49:
                self.bg = DEFAULT_BG
            elif 90 <= n <= 97:
                self.fg = n - 90 + 8
            elif 100 <= n <= 107:
                self.bg = n - 100 + 8
            elif n in (38, 48):
                target_fg = n == 38
                if i + 1 < len(nums) and nums[i + 1] == 5 and i + 2 < len(nums):
                    value = nums[i + 2] & 255
                    if target_fg:
                        self.fg = value
                    else:
                        self.bg = value
                    i += 2
                elif i + 4 < len(nums) and nums[i + 1] == 2:
                    packed = pack_rgb(nums[i + 2], nums[i + 3], nums[i + 4])
                    if target_fg:
                        self.fg = packed
                    else:
                        self.bg = packed
                    i += 4
            i += 1

    def _set_mode(self, raw: str, enable: bool) -> None:
        private = raw.startswith("?")
        nums = self._nums(raw)
        if not nums:
            nums = [0]
        for n in nums:
            if private:
                if n == 1:
                    self.app_cursor = enable
                elif n == 7:
                    self.wrap = enable
                elif n == 25:
                    self.cursor_visible = enable
                elif n == 6:
                    self.origin = enable
                    self.r = self._row_home()
                    self.c = 0
                elif n in (47, 1047, 1049):
                    if n == 1049 and enable:
                        self._save_cursor()
                    self._swap_alt(enable)
                    if n == 1049 and not enable:
                        self._restore_cursor()
                elif n in (1000, 1002, 1003):
                    self.mouse_mode = n if enable else 0
                elif n == 1006:
                    self.mouse_sgr = enable
                elif n == 2004:
                    self.bracket_paste = enable
            else:
                if n == 4:
                    self.insert_mode = enable

    def _csi_exec(self, params: str, cmd: str) -> None:
        nums = self._nums(params)
        n = nums[0] if nums else 0
        m = nums[1] if len(nums) > 1 else 0
        if cmd == "m":
            self._sgr(nums)
            return
        if cmd == "h":
            self._set_mode(params, True)
            return
        if cmd == "l":
            self._set_mode(params, False)
            return
        if cmd in "Hf":
            row = (n or 1) - 1
            col = (m or 1) - 1
            if self.origin:
                row += self.scroll_top
            self.r = row
            self.c = col
            self._pending_wrap = False
            self._clamp_cursor()
            return
        if cmd == "A":
            self.r = max(self.scroll_top if self.origin else 0, self.r - (n or 1))
            self._pending_wrap = False
            return
        if cmd == "B":
            bottom = self.scroll_bottom if self.origin else self.rows - 1
            self.r = min(bottom, self.r + (n or 1))
            self._pending_wrap = False
            return
        if cmd == "C":
            self.c = min(self.cols - 1, self.c + (n or 1))
            self._pending_wrap = False
            return
        if cmd == "D":
            self.c = max(0, self.c - (n or 1))
            self._pending_wrap = False
            return
        if cmd == "G":
            self.c = min(self.cols - 1, max(0, (n or 1) - 1))
            self._pending_wrap = False
            return
        if cmd == "d":
            self.r = min(self.rows - 1, max(0, (n or 1) - 1))
            self._pending_wrap = False
            return
        if cmd == "J":
            if n in (2, 3):
                self._erase_screen()
                return
            if n == 1:
                for y in range(0, self.r):
                    self.buf[y] = self._blank_row()
                self._erase_row(self.r, 0, self.c + 1)
                return
            self._erase_row(self.r, self.c, self.cols)
            for y in range(self.r + 1, self.rows):
                self.buf[y] = self._blank_row()
            return
        if cmd == "K":
            if n == 1:
                self._erase_row(self.r, 0, self.c + 1)
            elif n == 2:
                self.buf[self.r] = self._blank_row()
            else:
                self._erase_row(self.r, self.c, self.cols)
            return
        if cmd == "s":
            self._save_cursor()
            return
        if cmd == "u":
            self._restore_cursor()
            return
        if cmd == "r":
            top = (n or 1) - 1
            bottom = (m or self.rows) - 1
            self.scroll_top = min(self.rows - 1, max(0, top))
            self.scroll_bottom = min(self.rows - 1, max(self.scroll_top, bottom))
            self.r = self._row_home()
            self.c = 0
            self._pending_wrap = False
            return
        if cmd == "S":
            self._scroll_up(n or 1)
            return
        if cmd == "T":
            self._scroll_down(n or 1)
            return
        if cmd == "L":
            count = n or 1
            top = self.r
            bot = self.scroll_bottom
            if top > bot:
                return
            region = self.buf[top : bot + 1]
            for _ in range(count):
                region.pop()
                region.insert(0, self._blank_row())
            self.buf[top : bot + 1] = region
            return
        if cmd == "M":
            count = n or 1
            top = self.r
            bot = self.scroll_bottom
            if top > bot:
                return
            region = self.buf[top : bot + 1]
            for _ in range(count):
                if region:
                    removed = region.pop(0)
                    if top == 0 and not self.alt_screen:
                        self._remember_scrolled_row(removed)
                region.append(self._blank_row())
            self.buf[top : bot + 1] = region
            return
        if cmd == "@":
            count = min(n or 1, self.cols - self.c)
            row = self.buf[self.r]
            self.buf[self.r] = (
                row[: self.c]
                + [self._blank_cell() for _ in range(count)]
                + row[self.c : self.cols - count]
            )
            return
        if cmd == "P":
            count = min(n or 1, self.cols - self.c)
            row = self.buf[self.r]
            self.buf[self.r] = (
                row[: self.c]
                + row[self.c + count :]
                + [self._blank_cell() for _ in range(count)]
            )
            return
        if cmd == "X":
            self._erase_row(self.r, self.c, min(self.cols, self.c + (n or 1)))
            return
        if cmd == "n":
            if n == 6:
                self._reply(self.cursor_report())
            elif n == 5:
                self._reply("\x1b[0n")
            return
        if cmd == "c":
            if params.startswith(">"):
                self._reply("\x1b[>0;276;0c")
            else:
                self._reply("\x1b[?1;2c")
            return
