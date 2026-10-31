"""End-to-End Pipeline Integration Test for src/ Modules.

Exercises the intended HackFront Stage 3–6 architecture:
StatementIngestor (src/ingestion.py)
  -> StatementCleaner (src/cleaning.py)
    -> MerchantMatcher (src/merchants.py)
      -> RecurringDetector (src/detection.py)
        -> PriceHikeTracker (src/price_changes.py)
          -> CancellationRegistry (src/cancellation.py)

Tests ingestion, date/amount sanitization, debit/credit resolution,
duplicate detection, refund/reversal linking, row status preservation,
4-tier merchant normalization, cadence classification with paused/resumed
gap tolerance, transparent confidence breakdown, ordinary repeat rejection,
persistent price-change detection with variable-bill suppression,
and human-verified cancellation guidance with anti-hallucination guarantees.
"""

import os
import json
import unittest
from datetime import date
from src.ingestion import StatementIngestor
from src.cleaning import StatementCleaner
from src.merchants import MerchantMatcher
from src.detection import RecurringDetector
from src.price_changes import PriceHikeTracker
from src.cancellation import CancellationRegistry
from src.insights import CostEstimator, SavingsSimulator, POTENTIAL_SAVINGS_DISCLAIMER
from src.models import RowStatus, MatchMethod, CadenceType, ConfidenceLevel


class TestSrcPipeline(unittest.TestCase):
    """E2E test suite for the authoritative src/ pipeline."""

    def test_full_pipeline_hdfc_statement_with_preamble(self):
        """Tests ingestion, cleaning, and merchant normalization on HDFC-style statement."""
        csv_content = """HDFC BANK LIMITED - ACCOUNT STATEMENT
Account Number: SYNTHETIC-ACCOUNT
Branch: INDIRANAGAR BANGALORE

Date,Narration,Chq/Ref No,Withdrawal Amt.,Deposit Amt.,Closing Balance
01/11/2025,SALARY CREDIT FROM INFOSYS,SAL001,,140000.00,140000.00
02/11/2025,UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/HDFC/AUTOPAY,TXN001,649.00,,139351.00
05/11/2025,ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567,TXN002,129.00,,139222.00
10/11/2025,BIL/ONL/000987654/HOTSTAR/MUMBAI,TXN003,499.00,,138723.00
12/11/2025,POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI,TXN004,1499.00,,137224.00
15/11/2025,UPI-GOOGLE*STORAGE-GOOGLE@ICICI-887766,TXN005,130.00,,137094.00
18/11/2025,UPI/P2M/BUNDL TECH SWIGGY ONE MEMBERSHIP/AUTOPAY,TXN006,299.00,,136795.00
20/11/2025,BIL/ONL/BESCOM BANGALORE ELECTRICITY AUTOPAY,TXN007,1620.00,,135175.00
22/11/2025,UPI-SWIGGY-ORDER-BANGALORE,TXN008,349.00,,134826.00
22/11/2025,UPI-SWIGGY-ORDER-BANGALORE,TXN009,349.00,,134477.00
25/11/2025,UPI-UBER-TRIP-BANGALORE,UBER01,420.00,,134057.00
26/11/2025,UPI/REV/UBER INDIA/REFUND420,REF01,,420.00,134477.00
28/11/2025,The Netflix Cafe,CAFE01,250.00,,134227.00
29/11/2025,Amazon Tea Stall,TEA01,40.00,,134187.00
30/11/2025,ACH D- SPOTFY PREMUM-8877,TXN010,129.00,,134058.00
"""
        # Step 1: Ingestion
        ingested = StatementIngestor.ingest_csv_text(csv_content, filename_hint="HDFC_Statement.csv")
        self.assertEqual(ingested.bank_name, "HDFC Bank")
        self.assertEqual(ingested.header_row_index, 3)
        self.assertEqual(len(ingested.raw_rows), 15)

        # Step 2: Cleaning & Status Tagging
        cleaning_result = StatementCleaner.clean_statement(ingested)
        self.assertEqual(cleaning_result.total_rows, 15)
        self.assertEqual(cleaning_result.duplicate_count, 1)  # TXN009 is duplicate
        self.assertEqual(cleaning_result.refund_count, 1)     # REF01 is refund of UBER01

        # Check refund linking
        refund_txn = next(t for t in cleaning_result.transactions if t.reference_id == "REF01")
        self.assertEqual(refund_txn.row_status, RowStatus.REFUND)
        self.assertEqual(refund_txn.refund_linked_id, "UBER01")
        self.assertFalse(refund_txn.is_debit)

        # Check duplicate debit tagging
        dup_txn = next(t for t in cleaning_result.transactions if t.reference_id == "TXN009")
        self.assertEqual(dup_txn.row_status, RowStatus.DUPLICATE)
        self.assertEqual(dup_txn.refund_linked_id, "TXN008")

        # Step 3: Merchant Normalization Cascade
        MerchantMatcher.enrich_transactions(cleaning_result.transactions)

        by_ref = {t.reference_id: t for t in cleaning_result.transactions}

        # Netflix subscription: Tier 2 Regex match
        t_netflix = by_ref["TXN001"]
        self.assertEqual(t_netflix.normalized_merchant, "Netflix")
        self.assertEqual(t_netflix.merchant_match.method, MatchMethod.RULE_REGEX)
        self.assertEqual(t_netflix.merchant_match.match_confidence, 0.95)
        self.assertTrue(t_netflix.has_mandate_indicator)

        # Spotify: Tier 2 Regex match
        t_spotify = by_ref["TXN002"]
        self.assertEqual(t_spotify.normalized_merchant, "Spotify")
        self.assertEqual(t_spotify.merchant_match.method, MatchMethod.RULE_REGEX)

        # Amazon Prime: Tier 2 Regex match with card mask
        t_prime = by_ref["TXN004"]
        self.assertEqual(t_prime.normalized_merchant, "Amazon Prime")
        self.assertEqual(t_prime.merchant_match.method, MatchMethod.RULE_REGEX)

        # Swiggy One membership: Tier 2 Regex match
        t_swiggy_one = by_ref["TXN006"]
        self.assertEqual(t_swiggy_one.normalized_merchant, "Swiggy One")
        self.assertFalse(t_swiggy_one.merchant_match.is_retail)

        # BESCOM Electricity: Variable bill flag
        t_bescom = by_ref["TXN007"]
        self.assertEqual(t_bescom.normalized_merchant, "BESCOM Electricity")
        self.assertTrue(t_bescom.merchant_match.is_variable_bill)

        # Swiggy food order: Retail flag
        t_swiggy = by_ref["TXN008"]
        self.assertEqual(t_swiggy.normalized_merchant, "Swiggy")
        self.assertTrue(t_swiggy.merchant_match.is_retail)

        # Fuzzy typo match: 'SPOTFY PREMUM'
        t_fuzzy = by_ref["TXN010"]
        self.assertEqual(t_fuzzy.normalized_merchant, "Spotify")
        self.assertEqual(t_fuzzy.merchant_match.method, MatchMethod.FUZZY)
        self.assertGreaterEqual(t_fuzzy.merchant_match.match_confidence, 0.60)

        # Regression: 'The Netflix Cafe' must NOT match Netflix
        t_cafe = by_ref["CAFE01"]
        self.assertEqual(t_cafe.normalized_merchant, "The Netflix Cafe")
        self.assertEqual(t_cafe.merchant_match.method, MatchMethod.UNKNOWN)
        self.assertLessEqual(t_cafe.merchant_match.match_confidence, 0.40)
        self.assertNotEqual(t_cafe.normalized_merchant, "Netflix")

        # Regression: 'Amazon Tea Stall' must NOT match Amazon Prime
        t_tea = by_ref["TEA01"]
        self.assertEqual(t_tea.normalized_merchant, "Amazon Tea Stall")
        self.assertEqual(t_tea.merchant_match.method, MatchMethod.UNKNOWN)
        self.assertNotEqual(t_tea.normalized_merchant, "Amazon Prime")

    def test_full_pipeline_single_column_signed_statement(self):
        """Tests ingestion, cleaning, and merchant normalization on single Amount column statement."""
        csv_content = """Date,Narration,Ref,Amount
01/11/2025,NETFLIX.COM,REF1,-649.00
02/11/2025,SALARY DEPOSIT,REF2,140000.00
05/11/2025,SPOTIFY PREMIUM,REF3,129.00 Dr
10/11/2025,CASHBACK PROMO,REF4,50.00 Cr
12/11/2025,DISNEY HOTSTAR,REF5,(499.00)
15/11/2025,UPI/REV/NETFLIX/REFUND,REF6,+649.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_content)
        cleaning_result = StatementCleaner.clean_statement(ingested)
        MerchantMatcher.enrich_transactions(cleaning_result.transactions)

        self.assertEqual(cleaning_result.total_rows, 6)
        by_ref = {t.reference_id: t for t in cleaning_result.transactions}

        # -649.00 is debit
        self.assertTrue(by_ref["REF1"].is_debit)
        self.assertEqual(by_ref["REF1"].amount, 649.0)
        self.assertEqual(by_ref["REF1"].normalized_merchant, "Netflix")

        # 140000.00 is positive credit, not debit
        self.assertFalse(by_ref["REF2"].is_debit)
        self.assertEqual(by_ref["REF2"].amount, 140000.0)

        # 129.00 Dr is debit
        self.assertTrue(by_ref["REF3"].is_debit)
        self.assertEqual(by_ref["REF3"].normalized_merchant, "Spotify")

        # 50.00 Cr is credit
        self.assertFalse(by_ref["REF4"].is_debit)

        # (499.00) is debit
        self.assertTrue(by_ref["REF5"].is_debit)
        self.assertEqual(by_ref["REF5"].amount, 499.0)
        self.assertEqual(by_ref["REF5"].normalized_merchant, "Disney+ Hotstar")

        # +649.00 is refund linked to REF1
        t_refund = by_ref["REF6"]
        self.assertFalse(t_refund.is_debit)
        self.assertEqual(t_refund.row_status, RowStatus.REFUND)
        self.assertEqual(t_refund.refund_linked_id, "REF1")

    def test_full_pipeline_uncertain_direction_statement(self):
        """Tests that unsigned amounts without direction signals preserve uncertainty."""
        csv_content = """Date,Particulars,Ref,Amount
01/11/2025,MISCELLANEOUS PAYMENT,TX1,1000.00
02/11/2025,VENDOR TRANSFER,TX2,2500.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_content)
        cleaning_result = StatementCleaner.clean_statement(ingested)

        self.assertEqual(cleaning_result.total_rows, 2)
        self.assertEqual(cleaning_result.uncertain_count, 2)
        self.assertEqual(len(cleaning_result.valid_debits), 0)

        for t in cleaning_result.transactions:
            self.assertEqual(t.row_status, RowStatus.UNCERTAIN)
            self.assertIsNone(t.is_debit)

    def test_full_pipeline_ingestion_cleaning_merchant_detection_e2e(self):
        """
        Comprehensive E2E test exercising the complete src/ pipeline:
        Ingestion -> Cleaning -> Merchant Normalization -> Recurring Detection.
        Verifies:
        - Detection of Monthly, Quarterly, and Annual series.
        - Cult.fit paused/resumed gap tolerance (Monthly cadence with pause evidence).
        - BESCOM Electricity variable bill recognition.
        - Exclusion of refunds, duplicates, and salary deposits.
        - Rejection of ordinary repeat spends (Swiggy orders) into rejection records.
        """
        csv_data = """HDFC BANK STATEMENT
Customer: Aarav Sharma

Date,Narration,Ref,Withdrawal Amt.,Deposit Amt.
01/11/2025,SALARY FROM INFOSYS,SAL01,,140000.00
02/11/2025,UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY,NET01,649.00,
02/12/2025,UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY,NET02,649.00,
02/01/2026,UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY,NET03,649.00,
02/02/2026,UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY,NET04,649.00,
02/02/2026,UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY,NET04_DUP,649.00,
05/11/2025,BIL/ONL/000987654/HOTSTAR/MUMBAI,HOT01,499.00,
06/02/2026,BIL/ONL/000987655/HOTSTAR/MUMBAI,HOT02,499.00,
08/05/2026,BIL/ONL/000987656/HOTSTAR/MUMBAI,HOT03,499.00,
15/11/2025,SI - CULTFIT HEALTHCARE - 9982,CULT01,1750.00,
15/12/2025,SI - CULTFIT HEALTHCARE - 9982,CULT02,1750.00,
15/01/2026,SI - CULTFIT HEALTHCARE - 9982,CULT03,1750.00,
15/04/2026,SI - CULTFIT HEALTHCARE - 9982,CULT04,1750.00,
15/05/2026,SI - CULTFIT HEALTHCARE - 9982,CULT05,1750.00,
15/06/2026,SI - CULTFIT HEALTHCARE - 9982,CULT06,1750.00,
20/11/2025,POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI,AMZ01,1499.00,
21/11/2026,POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI,AMZ02,1499.00,
25/11/2025,BIL/ONL/BESCOM BANGALORE ELECTRICITY AUTOPAY,BES01,1420.00,
25/12/2025,BIL/ONL/BESCOM BANGALORE ELECTRICITY AUTOPAY,BES02,1680.00,
25/01/2026,BIL/ONL/BESCOM BANGALORE ELECTRICITY AUTOPAY,BES03,1390.00,
25/02/2026,BIL/ONL/BESCOM BANGALORE ELECTRICITY AUTOPAY,BES04,1720.00,
26/11/2025,UPI-SWIGGY-ORDER-001,SWG01,320.00,
28/11/2025,UPI-SWIGGY-ORDER-002,SWG02,450.00,
01/12/2025,UPI-SWIGGY-ORDER-003,SWG03,280.00,
04/12/2025,UPI-SWIGGY-ORDER-004,SWG04,510.00,
10/12/2025,UPI-SWIGGY-ORDER-005,SWG05,190.00,
12/12/2025,UPI-UBER-TRIP-BANGALORE,UBR01,400.00,
13/12/2025,UPI/REV/UBER/REFUND400,UBR_REF,,400.00
"""
        # Step 1: Ingestion
        ingested = StatementIngestor.ingest_csv_text(csv_data, filename_hint="HDFC_Aarav.csv")
        self.assertEqual(ingested.bank_name, "HDFC Bank")

        # Step 2: Cleaning
        cleaned = StatementCleaner.clean_statement(ingested)
        self.assertEqual(cleaned.duplicate_count, 1)  # NET04_DUP
        self.assertEqual(cleaned.refund_count, 1)     # UBR_REF

        # Step 3: Merchant Normalization
        MerchantMatcher.enrich_transactions(cleaned.transactions)

        # Step 4: Recurring Detection
        series_list, rejections = RecurringDetector.detect(cleaned.transactions)

        series_by_name = {s.merchant_name: s for s in series_list}

        # 1. Netflix: Monthly, 4 valid debits, duplicate excluded
        self.assertIn("Netflix", series_by_name)
        s_netflix = series_by_name["Netflix"]
        self.assertEqual(s_netflix.cadence, CadenceType.MONTHLY)
        self.assertEqual(s_netflix.cycle_count, 4)
        self.assertNotIn("NET04_DUP", [t.reference_id for t in s_netflix.transactions])

        # 2. Disney+ Hotstar: Quarterly
        self.assertIn("Disney+ Hotstar", series_by_name)
        s_hotstar = series_by_name["Disney+ Hotstar"]
        self.assertEqual(s_hotstar.cadence, CadenceType.QUARTERLY)

        # 3. Amazon Prime: Annual
        self.assertIn("Amazon Prime", series_by_name)
        s_prime = series_by_name["Amazon Prime"]
        self.assertEqual(s_prime.cadence, CadenceType.ANNUAL)

        # 4. Cult.fit: Monthly with paused/resumed gap
        self.assertIn("Cult.fit", series_by_name)
        s_cult = series_by_name["Cult.fit"]
        self.assertEqual(s_cult.cadence, CadenceType.MONTHLY)
        self.assertTrue(s_cult.is_paused_resumed)

        # 5. BESCOM Electricity: Monthly variable bill
        self.assertIn("BESCOM Electricity", series_by_name)
        s_bescom = series_by_name["BESCOM Electricity"]
        self.assertEqual(s_bescom.cadence, CadenceType.MONTHLY)

        # 6. Swiggy food orders: Rejected into rejection records
        self.assertNotIn("Swiggy", series_by_name)
        swiggy_rejection = next((r for r in rejections if r.merchant_name == "Swiggy"), None)
        self.assertIsNotNone(swiggy_rejection)
        self.assertTrue(any("Discretionary" in r or "Rapid" in r for r in swiggy_rejection.rejection_reasons))

        # 7. Salary credits & Uber refund: Not in recurring series
        self.assertNotIn("Infosys", series_by_name)
        self.assertNotIn("Uber", series_by_name)

    def test_full_pipeline_on_synthetic_test_dataset(self):
        """
        Executes the pure src/ pipeline on the full synthetic test_transactions.csv
        and verifies all target subscriptions and ordinary-repeat rejections.
        """
        csv_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "synthetic", "test_transactions.csv"
        )
        with open(csv_path, "r", encoding="utf-8") as f:
            csv_text = f.read()

        ingested = StatementIngestor.ingest_csv_text(csv_text, filename_hint="test_transactions.csv")
        cleaned = StatementCleaner.clean_statement(ingested)
        MerchantMatcher.enrich_transactions(cleaned.transactions)
        series_list, rejections = RecurringDetector.detect(cleaned.transactions)

        # Assert cadence for all 11 recurring series against ground truth in src/ pipeline
        gt_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "synthetic", "ground_truth.json"
        )
        with open(gt_path, "r", encoding="utf-8") as f:
            gt_data = json.load(f)

        gt_series_map = {item["merchant"]: item["cadence"] for item in gt_data["recurring_series"]}
        self.assertEqual(len(gt_series_map), 11)

        series_by_merchant = {s.merchant_name: s for s in series_list}
        for merchant, expected_cadence_str in gt_series_map.items():
            self.assertIn(merchant, series_by_merchant, f"Expected subscription {merchant} was not detected.")
            actual_cadence = series_by_merchant[merchant].cadence.value
            self.assertEqual(
                actual_cadence,
                expected_cadence_str,
                f"Cadence mismatch for {merchant} in src/ pipeline: expected {expected_cadence_str}, got {actual_cadence}"
            )

        # Cult.fit must be Monthly and tagged paused/resumed
        cult = next(s for s in series_list if s.merchant_name == "Cult.fit")
        self.assertEqual(cult.cadence, CadenceType.MONTHLY)
        self.assertTrue(cult.is_paused_resumed)

        # Ordinary repeats must all be rejected
        detected_names = set(series_by_merchant.keys())
        rej_names = {r.merchant_name for r in rejections}
        for ordinary in ["Swiggy", "Zomato", "Blinkit", "Uber"]:
            self.assertNotIn(ordinary, detected_names, f"Ordinary repeat {ordinary} should not be detected as subscription.")
            self.assertIn(ordinary, rej_names, f"Ordinary repeat {ordinary} should have a RejectionRecord.")

        # Step 5: Price Hike Tracking (Stage 6)
        PriceHikeTracker.attach_price_alerts(series_list)

        # Check price hikes against ground truth (Netflix & Spotify hiked, BESCOM suppressed)
        gt_hike_map = {item["merchant"]: item.get("has_price_hike", False) for item in gt_data["recurring_series"]}
        for merchant, expected_hike in gt_hike_map.items():
            s = series_by_merchant[merchant]
            has_hike = (s.price_alert is not None)
            self.assertEqual(
                has_hike,
                expected_hike,
                f"Price hike status mismatch for {merchant}: expected {expected_hike}, got {has_hike}"
            )

        # Detailed hike verification on Netflix
        s_netflix = series_by_merchant["Netflix"]
        self.assertIsNotNone(s_netflix.price_alert)
        self.assertEqual(s_netflix.price_alert.old_amount, 499.0)
        self.assertEqual(s_netflix.price_alert.new_amount, 649.0)
        self.assertAlmostEqual(s_netflix.price_alert.change_percent, 30.1, places=1)
        self.assertTrue(s_netflix.price_alert.is_confirmed)

        # Detailed hike verification on Spotify
        s_spotify = series_by_merchant["Spotify"]
        self.assertIsNotNone(s_spotify.price_alert)
        self.assertEqual(s_spotify.price_alert.old_amount, 119.0)
        self.assertEqual(s_spotify.price_alert.new_amount, 129.0)
        self.assertAlmostEqual(s_spotify.price_alert.change_percent, 8.4, places=1)

        # BESCOM Electricity: Variable bill must have price hike suppressed
        s_bescom = series_by_merchant["BESCOM Electricity"]
        self.assertIsNone(s_bescom.price_alert)

        # Step 6: Cancellation Guidance (Stage 6)
        CancellationRegistry.attach_cancellation_details(series_list)

        # Verified merchants with audited first-party support URLs & verification dates
        verified_merchants = ["Netflix", "Spotify", "Amazon Prime", "Disney+ Hotstar", "Google One", "Microsoft 365"]
        for vm in verified_merchants:
            s = series_by_merchant[vm]
            self.assertIsNotNone(s.cancellation_details)
            self.assertTrue(s.cancellation_details.is_verified, f"Expected {vm} to be verified")
            self.assertTrue(s.cancellation_details.source_url.startswith("https://"))
            self.assertNotEqual(s.cancellation_details.last_verified, "Unverified")
            self.assertTrue(len(s.cancellation_details.steps) >= 3)
            self.assertTrue(len(s.cancellation_details.mandate_guidance) >= 2)

        # Unverified merchants (Cult.fit, Swiggy One, Fitness First Gym, etc.)
        # must strictly use safe generic fallback with empty URL and no unverified identifiers
        unverified_merchants = ["Cult.fit", "Swiggy One", "Fitness First Gym"]
        for uvm in unverified_merchants:
            s = series_by_merchant[uvm]
            self.assertIsNotNone(s.cancellation_details)
            self.assertFalse(s.cancellation_details.is_verified, f"Expected {uvm} to be unverified")
            self.assertEqual(s.cancellation_details.source_url, "")
            self.assertEqual(s.cancellation_details.last_verified, "Unverified")
            self.assertEqual(
                s.cancellation_details.settings_location,
                "Merchant Official App/Web > Profile > Settings > Subscriptions"
            )
            self.assertTrue(len(s.cancellation_details.steps) >= 3)
            # Ensure no specific identifiers or guarantees leaked
            all_text = " ".join(s.cancellation_details.steps + s.cancellation_details.mandate_guidance)
            self.assertNotIn("guarantee", all_text.lower())
            self.assertNotIn("Bundl", all_text)
            self.assertNotIn("Curefit", all_text)

        # Step 7: Financial Insights (Stage 7)
        insights = CostEstimator.calculate_summary(series_list)
        self.assertEqual(insights.detected_series_count, 11)
        self.assertEqual(insights.price_alerts_count, 2)  # Netflix & Spotify
        self.assertAlmostEqual(insights.monthly_projected_commitment, 8756.17, places=1)
        self.assertAlmostEqual(insights.annual_projected_commitment, 105074.0, places=1)
        self.assertAlmostEqual(insights.total_actual_spend, 105442.0, places=1)
        self.assertGreater(insights.monthly_actual_burn, 0.0)
        self.assertIn("Streaming & Media", insights.category_totals)
        self.assertIn("Software & Cloud", insights.category_totals)
        self.assertIn("Utilities & Bills", insights.category_totals)
        self.assertIn("Health & Fitness", insights.category_totals)

        # Review candidates must include Cult.fit, Microsoft 365, Amazon Prime, Netflix, Spotify
        cand_names = {s.merchant_name for s in insights.review_candidates}
        self.assertIn("Cult.fit", cand_names)
        self.assertIn("Microsoft 365", cand_names)
        self.assertIn("Amazon Prime", cand_names)
        self.assertIn("Netflix", cand_names)
        self.assertIn("Spotify", cand_names)
        self.assertGreater(insights.total_review_annual_savings, 0.0)
        self.assertGreater(insights.total_review_monthly_savings, 0.0)

        # Savings simulation
        sim_result = SavingsSimulator.simulate_savings(series_list, selected_merchants=["Netflix", "Spotify"])
        self.assertEqual(sim_result.discontinued_series_count, 2)
        self.assertEqual(sim_result.retained_series_count, 9)
        self.assertAlmostEqual(sim_result.potential_monthly_savings, 649.0 + 129.0, places=1)
        self.assertAlmostEqual(sim_result.potential_annual_savings, 7788.0 + 1548.0, places=1)
        self.assertEqual(sim_result.disclaimer, POTENTIAL_SAVINGS_DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
