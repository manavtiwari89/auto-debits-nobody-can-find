"""Unit Tests for Stage 5 Recurring Detection Engine (src/detection.py).

Verifies:
1. Cadence classification: Monthly, Quarterly, Annual, Weekly.
2. Cult.fit paused/resumed gap tolerance regression test (maintaining Monthly cadence).
3. Ordinary repeat spend protection (rejecting Swiggy/Zomato discretionary orders).
4. Insufficient history rejection (1 transaction or 2 monthly without mandate).
5. Strict filtering: excluding credits, refunds, reversals, duplicates, invalid rows, and uncertain direction.
6. Variable utility bill amount variance handling (e.g. BESCOM).
7. Transparent 0-100 additive confidence score breakdown and penalties.
"""

import unittest
from datetime import date
from typing import List

from src.models import (
    CleanedTransaction,
    RecurringSeries,
    RejectionRecord,
    CadenceType,
    ConfidenceLevel,
    RowStatus,
    MatchMethod,
    MerchantMatch
)
from src.detection import RecurringDetector
from src.config import (
    PENALTY_GAP_PAUSED,
    PENALTY_UNKNOWN_MERCHANT,
    PENALTY_RETAIL_CATEGORY
)


def make_txn(
    tx_date: date,
    narration: str,
    amount: float,
    is_debit: bool = True,
    row_status: RowStatus = RowStatus.VALID,
    normalized_merchant: str = None,
    ref: str = None,
    has_mandate: bool = False
) -> CleanedTransaction:
    """Helper to construct CleanedTransaction test instances."""
    txn = CleanedTransaction(
        date=tx_date,
        narration=narration,
        amount=amount,
        is_debit=is_debit,
        row_status=row_status,
        reference_id=ref or f"REF-{tx_date.strftime('%Y%m%d')}",
        normalized_merchant=normalized_merchant,
        has_mandate_indicator=has_mandate
    )
    return txn


class TestRecurringDetection(unittest.TestCase):
    """Test suite for RecurringDetector in src/detection.py."""

    def test_monthly_cadence_netflix(self):
        """Tests standard monthly subscription detection with high confidence."""
        txns = [
            make_txn(date(2026, 1, 2), "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY", 649.0),
            make_txn(date(2026, 2, 2), "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY", 649.0),
            make_txn(date(2026, 3, 2), "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY", 649.0),
            make_txn(date(2026, 4, 2), "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY", 649.0),
            make_txn(date(2026, 5, 2), "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY", 649.0),
        ]
        series_list, rejections = RecurringDetector.detect(txns)

        self.assertEqual(len(series_list), 1)
        self.assertEqual(len(rejections), 0)

        series = series_list[0]
        self.assertEqual(series.merchant_name, "Netflix")
        self.assertEqual(series.cadence, CadenceType.MONTHLY)
        self.assertEqual(series.confidence_level, ConfidenceLevel.HIGH)
        self.assertGreaterEqual(series.confidence_score, 75.0)
        self.assertEqual(series.latest_amount, 649.0)
        self.assertEqual(series.monthly_equivalent, 649.0)
        self.assertEqual(series.annual_equivalent, 649.0 * 12.0)
        self.assertFalse(series.is_paused_resumed)
        self.assertEqual(series.cycle_count, 5)

    def test_quarterly_cadence_disney_hotstar(self):
        """Tests quarterly recurring cadence detection."""
        txns = [
            make_txn(date(2026, 1, 5), "BIL/ONL/000987654/HOTSTAR/MUMBAI", 499.0),
            make_txn(date(2026, 4, 6), "BIL/ONL/000987655/HOTSTAR/MUMBAI", 499.0),
            make_txn(date(2026, 7, 7), "BIL/ONL/000987656/HOTSTAR/MUMBAI", 499.0),
        ]
        series_list, rejections = RecurringDetector.detect(txns)

        self.assertEqual(len(series_list), 1)
        series = series_list[0]
        self.assertEqual(series.merchant_name, "Disney+ Hotstar")
        self.assertEqual(series.cadence, CadenceType.QUARTERLY)
        self.assertAlmostEqual(series.monthly_equivalent, 499.0 / 3.0, places=2)
        self.assertEqual(series.annual_equivalent, 499.0 * 4.0)

    def test_annual_cadence_amazon_prime(self):
        """Tests annual recurring cadence detection with 2 cycles across 12 months."""
        txns = [
            make_txn(date(2025, 1, 15), "POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI", 1499.0),
            make_txn(date(2026, 1, 16), "POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI", 1499.0),
        ]
        series_list, rejections = RecurringDetector.detect(txns)

        self.assertEqual(len(series_list), 1)
        series = series_list[0]
        self.assertEqual(series.merchant_name, "Amazon Prime")
        self.assertEqual(series.cadence, CadenceType.ANNUAL)
        self.assertEqual(series.annual_equivalent, 1499.0)
        self.assertAlmostEqual(series.monthly_equivalent, 1499.0 / 12.0, places=2)
        self.assertTrue(series.is_review_candidate)
        self.assertTrue(any("Annual commitment" in r for r in series.review_reasons))

    def test_weekly_cadence(self):
        """Tests weekly recurring cadence detection."""
        txns = [
            make_txn(date(2026, 1, 7), "UPI/WEEKLY NEWSPAPER SUBSCRIPTION/AUTOPAY", 150.0),
            make_txn(date(2026, 1, 14), "UPI/WEEKLY NEWSPAPER SUBSCRIPTION/AUTOPAY", 150.0),
            make_txn(date(2026, 1, 21), "UPI/WEEKLY NEWSPAPER SUBSCRIPTION/AUTOPAY", 150.0),
            make_txn(date(2026, 1, 28), "UPI/WEEKLY NEWSPAPER SUBSCRIPTION/AUTOPAY", 150.0),
            make_txn(date(2026, 2, 4), "UPI/WEEKLY NEWSPAPER SUBSCRIPTION/AUTOPAY", 150.0),
        ]
        series_list, _ = RecurringDetector.detect(txns)

        self.assertEqual(len(series_list), 1)
        series = series_list[0]
        self.assertEqual(series.cadence, CadenceType.WEEKLY)
        self.assertAlmostEqual(series.monthly_equivalent, 150.0 * (52.0 / 12.0), places=1)
        self.assertEqual(series.annual_equivalent, 150.0 * 52.0)

    def test_paused_resumed_cadence_cultfit_regression(self):
        """
        Regression Test: Cult.fit paused/resumed pattern.
        In synthetic statements, Cult.fit is active Nov-Jan, pauses for ~90 days (Feb-Mar),
        and resumes Apr-Oct. The detector must maintain CadenceType.MONTHLY,
        tag is_paused_resumed=True, record pause details in Evidence, and apply PENALTY_GAP_PAUSED.
        """
        cult_dates = [
            date(2025, 11, 15),
            date(2025, 12, 15),
            date(2026, 1, 15),
            # Gap of 90 days (Feb, Mar missed; resumes Apr)
            date(2026, 4, 15),
            date(2026, 5, 15),
            date(2026, 6, 15),
            date(2026, 7, 15),
            date(2026, 8, 15),
            date(2026, 9, 15),
            date(2026, 10, 15),
        ]
        txns = [
            make_txn(d, "SI - CULTFIT HEALTHCARE - 9982", 1750.0)
            for d in cult_dates
        ]
        series_list, rejections = RecurringDetector.detect(txns)

        self.assertEqual(len(series_list), 1)
        series = series_list[0]

        # Must be classified as MONTHLY, NOT Irregular
        self.assertEqual(series.merchant_name, "Cult.fit")
        self.assertEqual(series.cadence, CadenceType.MONTHLY)
        self.assertTrue(series.is_paused_resumed)
        self.assertTrue(series.evidence.is_paused_resumed)

        # Evidence must document pause/resume
        self.assertTrue(any("paused/resumed" in note.lower() for note in series.evidence.notes))
        self.assertTrue(any("gap" in note.lower() for note in series.evidence.notes))

        # Check penalty application
        penalties = {p.name: p.points_awarded for p in series.confidence_breakdown.penalties}
        self.assertIn("Paused Gap Penalty", penalties)
        self.assertEqual(penalties["Paused Gap Penalty"], float(PENALTY_GAP_PAUSED))

        # Must be flagged as review candidate due to pause history
        self.assertTrue(series.is_review_candidate)
        self.assertTrue(any("Paused/resumed pattern" in r for r in series.review_reasons))

    def test_ordinary_repeat_purchases_rejected_swiggy_and_zomato(self):
        """
        Tests that ordinary repeat purchases (Swiggy, Zomato) are rejected
        with explicit RejectionRecords and reasons instead of being flagged as subscriptions.
        """
        txns = [
            make_txn(date(2026, 1, 2), "UPI-SWIGGY-ORDER-001", 349.0),
            make_txn(date(2026, 1, 5), "UPI-SWIGGY-ORDER-002", 420.0),
            make_txn(date(2026, 1, 8), "UPI-SWIGGY-ORDER-003", 280.0),
            make_txn(date(2026, 1, 14), "UPI-SWIGGY-ORDER-004", 510.0),
            make_txn(date(2026, 1, 22), "UPI-SWIGGY-ORDER-005", 199.0),
            make_txn(date(2026, 1, 3), "UPI-ZOMATO-ORDER-101", 250.0),
            make_txn(date(2026, 1, 9), "UPI-ZOMATO-ORDER-102", 680.0),
            make_txn(date(2026, 1, 18), "UPI-ZOMATO-ORDER-103", 310.0),
        ]
        series_list, rejections = RecurringDetector.detect(txns)

        # Neither Swiggy nor Zomato should be classified as a recurring subscription
        self.assertEqual(len(series_list), 0)
        self.assertEqual(len(rejections), 2)

        rej_merchants = {r.merchant_name: r for r in rejections}
        self.assertIn("Swiggy", rej_merchants)
        self.assertIn("Zomato", rej_merchants)

        # Check rejection reasons transparency
        swiggy_rej = rej_merchants["Swiggy"]
        self.assertTrue(any("Discretionary" in r or "Rapid" in r for r in swiggy_rej.rejection_reasons))
        self.assertTrue(any("Fluctuating amounts" in r or "No mandate" in r for r in swiggy_rej.rejection_reasons))

    def test_insufficient_history_rejected(self):
        """Tests that 1-off transactions or 2 monthly transactions without mandate are rejected."""
        txns = [
            # 1-off transaction
            make_txn(date(2026, 1, 15), "BIL/ONL/ZEE5 ENTERTAINMENT", 999.0),
            # 2 monthly transactions without mandate (e.g. Headspace)
            make_txn(date(2026, 8, 1), "UPI-HEADSPACE-MEDITATION-APP", 1299.0),
            make_txn(date(2026, 9, 1), "UPI-HEADSPACE-MEDITATION-APP", 1299.0),
        ]
        series_list, rejections = RecurringDetector.detect(txns)

        self.assertEqual(len(series_list), 0)
        self.assertEqual(len(rejections), 2)

        rej_merchants = {r.merchant_name: r for r in rejections}
        self.assertIn("Zee5", rej_merchants)
        self.assertTrue(any("Insufficient history: only 1 transaction" in r for r in rej_merchants["Zee5"].rejection_reasons))

        headspace_key = next((k for k in rej_merchants if "Headspace" in k), None)
        self.assertIsNotNone(headspace_key)
        self.assertTrue(any("minimum 3 billing cycles required" in r for r in rej_merchants[headspace_key].rejection_reasons))

    def test_filtering_excludes_non_valid_debits(self):
        """
        Tests strict filtering: Credits, refunds, reversals, duplicates,
        invalid rows, and uncertain direction MUST be excluded from detection.
        """
        txns = [
            # 4 valid Netflix debits
            make_txn(date(2026, 1, 1), "UPI/NETFLIX/TXN01", 649.0, is_debit=True, row_status=RowStatus.VALID),
            make_txn(date(2026, 2, 1), "UPI/NETFLIX/TXN02", 649.0, is_debit=True, row_status=RowStatus.VALID),
            make_txn(date(2026, 3, 1), "UPI/NETFLIX/TXN03", 649.0, is_debit=True, row_status=RowStatus.VALID),
            make_txn(date(2026, 4, 1), "UPI/NETFLIX/TXN04", 649.0, is_debit=True, row_status=RowStatus.VALID),

            # Excluded non-valid rows for Netflix
            make_txn(date(2026, 1, 15), "UPI/REV/NETFLIX/REFUND", 649.0, is_debit=False, row_status=RowStatus.REFUND),
            make_txn(date(2026, 2, 1), "UPI/NETFLIX/TXN02_DUP", 649.0, is_debit=True, row_status=RowStatus.DUPLICATE),
            make_txn(date(2026, 2, 15), "UPI/REV/NETFLIX/CHARGEBACK", 649.0, is_debit=False, row_status=RowStatus.REVERSAL),
            make_txn(date(2026, 3, 5), "MALFORMED NETFLIX ROW", 649.0, is_debit=None, row_status=RowStatus.INVALID),
            make_txn(date(2026, 3, 6), "UNCERTAIN NETFLIX ROW", 649.0, is_debit=None, row_status=RowStatus.UNCERTAIN),

            # Salary credit (Valid, but credit)
            make_txn(date(2026, 1, 31), "SALARY CREDIT INFOSYS", 140000.0, is_debit=False, row_status=RowStatus.VALID),
            make_txn(date(2026, 2, 28), "SALARY CREDIT INFOSYS", 140000.0, is_debit=False, row_status=RowStatus.VALID),
            make_txn(date(2026, 3, 31), "SALARY CREDIT INFOSYS", 140000.0, is_debit=False, row_status=RowStatus.VALID),
        ]
        series_list, rejections = RecurringDetector.detect(txns)

        # Only Netflix valid debits should be detected
        self.assertEqual(len(series_list), 1)
        series = series_list[0]
        self.assertEqual(series.merchant_name, "Netflix")
        self.assertEqual(series.cycle_count, 4)  # Exactly 4 valid debits
        self.assertEqual(len(series.transactions), 4)

        # Verify all series transactions are valid debits
        for t in series.transactions:
            self.assertTrue(t.is_debit)
            self.assertEqual(t.row_status, RowStatus.VALID)

        # Salary credit must NOT be detected as recurring series
        self.assertFalse(any(s.merchant_name == "Infosys" for s in series_list))

    def test_amount_variation_variable_utility_bill_bescom(self):
        """
        Tests that variable utility bills (e.g. BESCOM electricity) are correctly
        recognized as recurring Monthly debits despite fluctuating amounts.
        """
        bescom_amounts = [1240.0, 1580.0, 1390.0, 1810.0, 1420.0, 1650.0]
        txns = [
            make_txn(date(2026, i + 1, 20), "BIL/ONL/BESCOM BANGALORE ELECTRICITY AUTOPAY", amt)
            for i, amt in enumerate(bescom_amounts)
        ]
        series_list, _ = RecurringDetector.detect(txns)

        self.assertEqual(len(series_list), 1)
        series = series_list[0]
        self.assertEqual(series.merchant_name, "BESCOM Electricity")
        self.assertEqual(series.cadence, CadenceType.MONTHLY)
        self.assertEqual(series.confidence_level, ConfidenceLevel.HIGH)

        # Notes must explain variable bill tolerance
        self.assertTrue(any("Variable utility" in n for n in series.evidence.notes))

        # Factor for amount stability should reflect variable bill rationale
        amt_factor = next(f for f in series.confidence_breakdown.factors if "Amount Stability" in f.name)
        self.assertIn("Utility / variable bill", amt_factor.rationale)

    def test_confidence_breakdown_transparent_and_calibrated(self):
        """Tests that the 0-100 score breakdown is fully additive and penalty-calibrated."""
        txns = [
            make_txn(date(2026, 1, 10), "ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567", 129.0),
            make_txn(date(2026, 2, 10), "ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567", 129.0),
            make_txn(date(2026, 3, 10), "ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567", 129.0),
            make_txn(date(2026, 4, 10), "ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567", 129.0),
        ]
        series_list, _ = RecurringDetector.detect(txns)
        series = series_list[0]
        breakdown = series.confidence_breakdown

        # All 5 factors must exist
        factor_names = [f.name for f in breakdown.factors]
        self.assertIn("Occurrences & Cycle History", factor_names)
        self.assertIn("Interval Regularity", factor_names)
        self.assertIn("Amount Stability", factor_names)
        self.assertIn("Merchant Verification Quality", factor_names)
        self.assertIn("Day-of-Month / Mandate Indicator", factor_names)

        # Sum of factor points + penalty points should equal total_score (within clamp range)
        raw_sum = sum(f.points_awarded for f in breakdown.factors) + sum(p.points_awarded for p in breakdown.penalties)
        expected_score = max(5.0, min(100.0, raw_sum))
        self.assertEqual(breakdown.total_score, round(expected_score, 1))

    def test_unknown_merchant_penalty_and_capping(self):
        """Tests that unverified merchants receive PENALTY_UNKNOWN_MERCHANT and are capped at Medium."""
        txns = [
            make_txn(date(2026, 1, 10), "TRANSFER TO LOCAL CLUB", 1000.0),
            make_txn(date(2026, 2, 10), "TRANSFER TO LOCAL CLUB", 1000.0),
            make_txn(date(2026, 3, 10), "TRANSFER TO LOCAL CLUB", 1000.0),
            make_txn(date(2026, 4, 10), "TRANSFER TO LOCAL CLUB", 1000.0),
            make_txn(date(2026, 5, 10), "TRANSFER TO LOCAL CLUB", 1000.0),
            make_txn(date(2026, 6, 10), "TRANSFER TO LOCAL CLUB", 1000.0),
        ]
        series_list, _ = RecurringDetector.detect(txns)
        self.assertEqual(len(series_list), 1)
        series = series_list[0]

        self.assertFalse(series.is_merchant_verified)
        self.assertNotEqual(series.confidence_level, ConfidenceLevel.HIGH)  # Capped at Medium
        penalties = {p.name: p.points_awarded for p in series.confidence_breakdown.penalties}
        self.assertIn("Unverified Merchant Penalty", penalties)
        self.assertEqual(penalties["Unverified Merchant Penalty"], float(PENALTY_UNKNOWN_MERCHANT))


if __name__ == "__main__":
    unittest.main()
