"""Unit tests for CostEstimator & Recurring Totals."""

import unittest
from datetime import date
from app.models import RecurringSeries, CadenceType, ConfidenceLevel, PriceAlert
from app.totals import CostEstimator


class TestCostEstimator(unittest.TestCase):

    def setUp(self):
        self.series1 = RecurringSeries(
            series_id="S1",
            merchant_name="Netflix",
            category="Streaming & Entertainment",
            cadence=CadenceType.MONTHLY,
            confidence=ConfidenceLevel.HIGH,
            confidence_score=0.9,
            transactions=[],
            expected_amount=649.0,
            monthly_equivalent_amount=649.0,
            annual_equivalent_amount=649.0 * 12,
            interval_mean_days=30.0,
            interval_std_days=0.5,
            evidence_reasons=[],
            price_alert=PriceAlert(
                merchant_name="Netflix", old_amount=499.0, new_amount=649.0,
                percent_change=30.1, effective_date=date(2026, 3, 1), details=""
            )
        )
        self.series2 = RecurringSeries(
            series_id="S2",
            merchant_name="Amazon Prime",
            category="Streaming & Entertainment",
            cadence=CadenceType.ANNUAL,
            confidence=ConfidenceLevel.HIGH,
            confidence_score=0.85,
            transactions=[],
            expected_amount=1499.0,
            monthly_equivalent_amount=124.92,
            annual_equivalent_amount=1499.0,
            interval_mean_days=365.0,
            interval_std_days=1.0,
            evidence_reasons=[]
        )
        self.series3 = RecurringSeries(
            series_id="S3",
            merchant_name="JioFiber",
            category="Utilities & Telecom",
            cadence=CadenceType.MONTHLY,
            confidence=ConfidenceLevel.MEDIUM,
            confidence_score=0.6,
            transactions=[],
            expected_amount=1179.0,
            monthly_equivalent_amount=1179.0,
            annual_equivalent_amount=1179.0 * 12,
            interval_mean_days=30.0,
            interval_std_days=2.0,
            evidence_reasons=[]
        )

    def test_calculate_summary(self):
        summary = CostEstimator.calculate_summary([self.series1, self.series2, self.series3])
        self.assertEqual(summary.active_subscriptions_count, 3)
        self.assertAlmostEqual(summary.total_monthly_recurring, 649.0 + 124.92 + 1179.0, places=2)
        self.assertAlmostEqual(summary.total_annual_recurring, (649.0 * 12) + 1499.0 + (1179.0 * 12), places=2)
        self.assertEqual(summary.price_hike_count, 1)
        self.assertEqual(summary.high_confidence_count, 2)
        self.assertEqual(summary.medium_confidence_count, 1)
        self.assertEqual(summary.low_confidence_count, 0)
        self.assertIn("Streaming & Entertainment", summary.category_breakdown)
        self.assertIn("Utilities & Telecom", summary.category_breakdown)

    def test_filter_by_high_confidence(self):
        summary = CostEstimator.calculate_summary(
            [self.series1, self.series2, self.series3],
            min_confidence=ConfidenceLevel.HIGH
        )
        self.assertEqual(summary.active_subscriptions_count, 2)
        self.assertEqual(summary.high_confidence_count, 2)
        self.assertEqual(summary.medium_confidence_count, 0)


if __name__ == "__main__":
    unittest.main()
