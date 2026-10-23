"""Keep terminal text, cursor cells and the scrollbar within the chat pane."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from backend.terminal_grid import TerminalGrid


class _PaintRecorder:
    def __init__(self):
        self.runs = []
        self.font = None

    def hasClipping(self):
        return False

    def setFont(self, font):
        self.font = font

    def fillRect(self, *args):
        pass

    def setPen(self, *args):
        pass

    def drawText(self, rect, flags, text):
        self.runs.append((rect, text, QFontMetricsF(self.font).horizontalAdvance(text)))


class TerminalGridLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.name == "nt":
            fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
            for name in ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"):
                QFontDatabase.addApplicationFont(str(fonts / name))
            QFont.insertSubstitution("monospace", "Consolas")

    @staticmethod
    def stop_grid(host, grid):
        # Keep the Qt parent alive until its worker has stopped.
        grid._stop_worker()
        grid.setParentItem(None)

    def make_grid(self, *, right_inset=0):
        host = QQuickItem()
        host.setProperty("terminalRightInset", right_inset)
        host.setWidth(495.5)
        host.setHeight(750.5)
        grid = TerminalGrid(host)
        self.addCleanup(self.stop_grid, host, grid)
        # Fractional spacing exercises the Windows/DPI failure on every platform.
        for font in (grid._font, grid._font_bold, grid._font_italic, grid._font_both):
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.25)
        grid._measure()
        grid._refit()
        self.app.processEvents()
        return host, grid

    def test_styled_text_runs_fit_their_cells(self):
        host, grid = self.make_grid()
        grid.feed_text("\x1b[?25l" + "M" * 20 + "\x1b[1m" + "M" * 20)
        painter = _PaintRecorder()
        grid.paint(painter)
        runs = [(rect, text, width) for rect, text, width in painter.runs if text.strip()]
        self.assertEqual(len(runs), 2)
        for rect, text, width in runs:
            self.assertGreaterEqual(rect.width() + 1e-6, width)
            self.assertLessEqual(rect.right(), host.width())
        self.assertAlmostEqual(runs[1][0].left(), runs[0][2])

    def test_text_wraps_at_the_visible_edge_after_resizes(self):
        host, grid = self.make_grid(right_inset=9)
        sizes = []
        grid.resized.connect(lambda cols, rows: sizes.append((cols, rows)))
        for width in (420.25, 800.75, 470.5):
            with self.subTest(width=width):
                host.setWidth(width)
                self.app.processEvents()
                self.assertEqual(sizes[-1], (grid._last_cols, grid._last_rows))
                self.assertLessEqual(grid._last_cols * grid._cell_w, grid.width())
                self.assertLessEqual(grid._last_rows * grid._cell_h, grid.height())
                grid.reset_terminal()
                line = "M" * (grid._last_cols - 1) + "X"
                grid.feed_text(line + "Y")
                self.assertEqual("".join(cell[0] for cell in grid.vt().buf[0]), line)
                self.assertEqual(grid.vt().buf[1][0][0], "Y")

    def test_scrollbar_does_not_cover_text(self):
        host, grid = self.make_grid(right_inset=9)
        for width in (495.5, 780.25):
            host.setWidth(width)
            self.app.processEvents()
            self.assertEqual(grid.width(), width - 9)
            self.assertLessEqual(grid._last_cols * grid._cell_w, width - 9)
        host, grid = self.make_grid()
        self.assertEqual(grid.width(), host.width())


if __name__ == "__main__":
    unittest.main()
