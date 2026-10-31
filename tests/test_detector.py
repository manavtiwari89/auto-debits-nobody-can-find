"""Unit tests for Cadence & Recurring Detection Engine."""

import unittest
from datetime import date
from app.models import Transaction, CadenceType, ConfidenceLevel
from app.detector import RecurringDetector


class TestRecurringDetector(unittest.TestCase):

    def test_monthly_cadence_netflix(self):
        txns = [
            Transaction(date=date(2026, 1, 1), narration="UPI-NETFLIX-NETFLIX@HDFC-101", amount=649.0, is_debit=True),
            Transaction(date=date(2026, 2, 1), narration="UPI-NETFLIX-NETFLIX@HDFC-102", amount=649.0, is_debit=True),
            Transaction(date=date(2026, 3, 3), narration="UPI-NETFLIX-NETFLIX@HDFC-103", amount=649.0, is_debit=True),
            Transaction(date=date(2026, 4, 2), narration="UPI-NETFLIX-NETFLIX@HDFC-104", amount=649.0, is_debit=True),
        ]
        results = RecurringDetector.detect_recurring(txns)
        self.assertEqual(len(results), 1)
        series = results[0]
        self.assertEqual(series.merchant_name, "Netflix")
        self.assertEqual(series.cadence, CadenceType.MONTHLY)
        self.assertEqual(series.confidence, ConfidenceLevel.HIGH)
        self.assertEqual(series.expected_amount, 649.0)
        self.assertEqual(series.monthly_equivalent_amount, 649.0)
        self.assertEqual(series.annual_equivalent_amount, 649.0 * 12)
        self.assertTrue(len(series.evidence_reasons) >= 3)

    def test_annual_cadence_amazon_prime(self):
        txns = [
            Transaction(date=date(2025, 1, 15), narration="POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI", amount=1499.0, is_debit=True),
            Transaction(date=date(2026, 1, 16), narration="POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI", amount=1499.0, is_debit=True),
        ]
        results = RecurringDetector.detect_recurring(txns)
        self.assertEqual(len(results), 1)
        series = results[0]
        self.assertEqual(series.merchant_name, "Amazon Prime")
        self.assertEqual(series.cadence, CadenceType.ANNUAL)
        self.assertEqual(series.expected_amount, 1499.0)
        self.assertEqual(series.annual_equivalent_amount, 1499.0)
        self.assertAlmostEqual(series.monthly_equivalent_amount, 1499.0 / 12, places=2)

    def test_quarterly_cadence_hotstar(self):
        txns = [
            Transaction(date=date(2026, 1, 1), narration="BIL/ONL/000987/HOTSTAR/MUMBAI", amount=499.0, is_debit=True),
            Transaction(date=date(2026, 4, 2), narration="BIL/ONL/000988/HOTSTAR/MUMBAI", amount=499.0, is_debit=True),
            Transaction(date=date(2026, 7, 3), narration="BIL/ONL/000989/HOTSTAR/MUMBAI", amount=499.0, is_debit=True),
        ]
        results = RecurringDetector.detect_recurring(txns)
        self.assertEqual(len(results), 1)
        series = results[0]
        self.assertEqual(series.merchant_name, "Disney+ Hotstar")
        self.assertEqual(series.cadence, CadenceType.QUARTERLY)
        self.assertAlmostEqual(series.monthly_equivalent_amount, 499.0 / 3, places=1)

    def test_reject_rapid_food_orders_false_positives(self):
        # 3 food orders placed on consecutive days (not a recurring subscription)
        txns = [
            Transaction(date=date(2026, 3, 10), narration="UPI-SWIGGY-BANGALORE-1", amount=350.0, is_debit=True),
            Transaction(date=date(2026, 3, 11), narration="UPI-SWIGGY-BANGALORE-2", amount=420.0, is_debit=True),
            Transaction(date=date(2026, 3, 12), narration="UPI-SWIGGY-BANGALORE-3", amount=280.0, is_debit=True),
        ]
        results = RecurringDetector.detect_recurring(txns)
        # Should not be detected as recurring subscription
        self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
