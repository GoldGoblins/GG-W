"""Visible monetary values preserve exact wallet decimal strings."""
from pathlib import Path
import unittest


class ExactWalletPresentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtQml import QJSEngine
        cls.application=QApplication.instance() or QApplication([])
        cls.engine=QJSEngine()
        source=Path(__file__).resolve().parents[1]/'qml/components/MarketFormat.js'
        result=cls.engine.evaluate(source.read_text(encoding='utf-8'))
        if result.isError():raise AssertionError(result.toString())

    def test_large_wallet_balance_and_cents_are_never_rounded_through_float(self):
        self.assertEqual(self.engine.evaluate("exactQuantity('18446744073709551615.000000001')").toString(),
                         '18 446 744 073 709 551 615.000000001')
        self.assertEqual(self.engine.evaluate("exactMoney('9007199254740993.17')").toString(),
                         '$9 007 199 254 740 993.17')

    def test_subcent_values_and_zero_remain_distinct_from_missing(self):
        for raw,expected in (("'0.000000001'",'$0.000000001'),("'0'",'$0.00'),("'1248.0'",'$1 248.00'),('null','—'),('undefined','—'),("'not-a-quote'",'—')):
            with self.subTest(raw=raw):self.assertEqual(self.engine.evaluate('exactMoney('+raw+')').toString(),expected)

    def test_portfolio_sort_can_distinguish_cents_beyond_float_precision(self):
        for a,b,expected in (('9007199254740993.17','9007199254740993.16',1),('0.000000001','0.000000002',-1),('001.20','1.2',0),('100','99.99',1)):
            with self.subTest(a=a,b=b):self.assertEqual(self.engine.evaluate("compareExact('"+a+"','"+b+"')").toInt(),expected)


if __name__=='__main__':unittest.main()
