"""Bound truecolor retention without changing terminal paint RGB values."""
import unittest

from PySide6.QtGui import QImage, QPainter
from backend import terminal_grid as terminal


class TerminalColorCacheTests(unittest.TestCase):
    def setUp(self): terminal._COLOR_CACHE.clear()
    def tearDown(self): terminal._COLOR_CACHE.clear()

    def test_color_churn_is_bounded_and_recent_colors_survive(self):
        for index in range(100000):
            rgb=(index>>16,(index>>8)&255,index&255)
            self.assertEqual(terminal._color(rgb).getRgb()[:3],rgb)
        self.assertEqual(len(terminal._COLOR_CACHE),terminal.MAX_COLOR_CACHE_ENTRIES)
        terminal._COLOR_CACHE.clear()
        cold=(255,255,254); hot=(255,255,255)
        retained=terminal._color(cold); frequent=terminal._color(hot)
        for index in range(terminal.MAX_COLOR_CACHE_ENTRIES-2):
            terminal._color((index>>16,(index>>8)&255,index&255))
        self.assertIs(terminal._color(hot),frequent)
        terminal._color((254,123,45))
        self.assertNotIn(cold,terminal._COLOR_CACHE)
        self.assertIs(terminal._color(hot),frequent)
        self.assertEqual(retained.getRgb()[:3],cold)

    def test_painted_pixels_remain_exact_across_eviction(self):
        image=QImage(64,64,QImage.Format.Format_RGB32)
        painter=QPainter(image)
        try:
            for index in range(4096):
                rgb=(index>>8,index&255,(index*17)&255)
                painter.setPen(terminal._color(rgb));painter.drawPoint(index%64,index//64)
        finally:painter.end()
        for index in range(4096):
            self.assertEqual(image.pixelColor(index%64,index//64).getRgb()[:3],(index>>8,index&255,(index*17)&255))
        self.assertEqual(len(terminal._COLOR_CACHE),terminal.MAX_COLOR_CACHE_ENTRIES)


if __name__=='__main__': unittest.main()
