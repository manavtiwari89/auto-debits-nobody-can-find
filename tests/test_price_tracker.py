"""Unit tests for Price Change & Stealth Auto-Debit Hike Detector."""

import unittest
from datetime import date
from app.models import Transaction, RecurringSeries, CadenceType, ConfidenceLevel
from app.price_tracker import PriceTracker


class TestPriceTracker(unittest.TestCase):

    def setUp(self):
        self.txns_with_hike = [
            Transaction(date=date(2026, 1, 1), narration="UPI-NETFLIX-1", amount=499.0, is_debit=True),
            Transaction(date=date(2026, 2, 1), narration="UPI-NETFLIX-2", amount=499.0, is_debit=True),
            Transaction(date=date(2026, 3, 1), narration="UPI-NETFLIX-3", amount=649.0, is_debit=True),
            Transaction(date=date(2026, 4, 1), narration="UPI-NETFLIX-4", amount=649.0, is_debit=True),
        ]
        self.series_with_hike = RecurringSeries(
            series_id="SERIES-NETFLIX-MON",
            merchant_name="Netflix",
            category="Streaming & Entertainment",
            cadence=CadenceType.MONTHLY,
            confidence=ConfidenceLevel.HIGH,
            confidence_score=0.9,
            transactions=self.txns_with_hike,
            expected_amount=649.0,
            monthly_equivalent_amount=649.0,
            annual_equivalent_amount=649.0 * 12,
            interval_mean_days=30.0,
            interval_std_days=0.5,
            evidence_reasons=[]
        )

    def test_detect_price_hike(self):
        alert = PriceTracker.evaluate_series_price_change(self.series_with_hike)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.old_amount, 499.0)
        self.assertEqual(alert.new_amount, 649.0)
        self.assertEqual(alert.effective_date, date(2026, 3, 1))
        self.assertAlmostEqual(alert.percent_change, 30.1, places=1)
        self.assertEqual(alert.formatted_difference, "+₹150.00 (+30.1%)")

    def test_constant_price_no_alert(self):
        txns_constant = [
            Transaction(date=date(2026, 1, 1), narration="UPI-SPOTIFY-1", amount=119.0, is_debit=True),
            Transaction(date=date(2026, 2, 1), narration="UPI-SPOTIFY-2", amount=119.0, is_debit=True),
            Transaction(date=date(2026, 3, 1), narration="UPI-SPOTIFY-3", amount=119.0, is_debit=True),
        ]
        series_constant = RecurringSeries(
            series_id="SERIES-SPOTIFY-MON",
            merchant_name="Spotify",
            category="Streaming & Entertainment",
            cadence=CadenceType.MONTHLY,
            confidence=ConfidenceLevel.HIGH,
            confidence_score=0.9,
            transactions=txns_constant,
            expected_amount=119.0,
            monthly_equivalent_amount=119.0,
            annual_equivalent_amount=119.0 * 12,
            interval_mean_days=30.0,
            interval_std_days=0.5,
            evidence_reasons=[]
        )
        alert = PriceTracker.evaluate_series_price_change(series_constant)
        self.assertIsNone(alert)

    def test_price_decrease_no_hike_alert(self):
        txns_decrease = [
            Transaction(date=date(2026, 1, 1), narration="UPI-PLAN-1", amount=999.0, is_debit=True),
            Transaction(date=date(2026, 2, 1), narration="UPI-PLAN-2", amount=499.0, is_debit=True),
        ]
        series_decrease = RecurringSeries(
            series_id="SERIES-PLAN-MON",
            merchant_name="Plan",
            category="Software & Cloud",
            cadence=CadenceType.MONTHLY,
            confidence=ConfidenceLevel.MEDIUM,
            confidence_score=0.6,
            transactions=txns_decrease,
            expected_amount=499.0,
            monthly_equivalent_amount=499.0,
            annual_equivalent_amount=499.0 * 12,
            interval_mean_days=31.0,
            interval_std_days=0.0,
            evidence_reasons=[]
        )
        alert = PriceTracker.evaluate_series_price_change(series_decrease)
        self.assertIsNone(alert)

    def test_attach_price_alerts(self):
        series_list = [self.series_with_hike]
        PriceTracker.attach_price_alerts(series_list)
        self.assertIsNotNone(series_list[0].price_alert)
        self.assertTrue(any("Price hike" in r for r in series_list[0].evidence_reasons))


if __name__ == "__main__":
    unittest.main()
