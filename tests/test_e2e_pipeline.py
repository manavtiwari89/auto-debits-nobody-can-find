"""End-to-End Pipeline Integration Test.

Tests the complete flow from raw Indian bank statement CSV to
detected subscriptions, price hikes, run-rates, and verified cancellation guidance.
"""

import unittest
from app.parser import BankStatementParser
from app.normalizer import NarrationNormalizer
from app.detector import RecurringDetector
from app.price_tracker import PriceTracker
from app.cancellation import CancellationRegistry
from app.totals import CostEstimator
from app.demo_data import generate_hdfc_statement, generate_sbi_statement, generate_icici_statement


class TestE2EPipeline(unittest.TestCase):

    def test_full_pipeline_hdfc(self):
        csv_content, _ = generate_hdfc_statement()

        # Step 1: Parse
        txns = BankStatementParser.parse_csv_content(csv_content, "HDFC_Statement")
        self.assertGreater(len(txns), 40)

        # Step 2: Enrich
        for t in txns:
            NarrationNormalizer.enrich_transaction(t)
            self.assertIsNotNone(t.normalized_merchant)

        # Step 3: Detect recurring
        series_list = RecurringDetector.detect_recurring(txns)
        self.assertGreaterEqual(len(series_list), 6)

        # Step 4: Price tracker
        PriceTracker.attach_price_alerts(series_list)
        netflix_series = next((s for s in series_list if s.merchant_name == "Netflix"), None)
        self.assertIsNotNone(netflix_series)
        self.assertIsNotNone(netflix_series.price_alert)
        self.assertEqual(netflix_series.price_alert.old_amount, 499.0)
        self.assertEqual(netflix_series.price_alert.new_amount, 649.0)

        # Step 5: Cancellation guidance
        CancellationRegistry.attach_cancellation_guides(series_list)
        for s in series_list:
            self.assertIsNotNone(s.cancellation_info)
            if s.cancellation_info.is_verified_source:
                self.assertIsNotNone(s.cancellation_info.direct_url)
                self.assertTrue(s.cancellation_info.direct_url.startswith("https://"))

        # Step 6: Cost summary
        summary = CostEstimator.calculate_summary(series_list)
        self.assertGreater(summary.total_monthly_recurring, 4000.0)
        self.assertGreater(summary.total_annual_recurring, 48000.0)
        self.assertGreaterEqual(summary.price_hike_count, 1)

    def test_full_pipeline_sbi(self):
        csv_content = generate_sbi_statement()
        txns = BankStatementParser.parse_csv_content(csv_content, "SBI_Statement")
        for t in txns:
            NarrationNormalizer.enrich_transaction(t)
        series_list = RecurringDetector.detect_recurring(txns)
        self.assertGreaterEqual(len(series_list), 2)
        names = [s.merchant_name for s in series_list]
        self.assertIn("Netflix", names)
        self.assertIn("Spotify", names)

    def test_full_pipeline_icici(self):
        csv_content = generate_icici_statement()
        txns = BankStatementParser.parse_csv_content(csv_content, "ICICI_Statement")
        for t in txns:
            NarrationNormalizer.enrich_transaction(t)
        series_list = RecurringDetector.detect_recurring(txns)
        self.assertGreaterEqual(len(series_list), 2)
        names = [s.merchant_name for s in series_list]
        self.assertIn("Cult.fit", names)
        self.assertIn("Google One", names)


if __name__ == "__main__":
    unittest.main()
