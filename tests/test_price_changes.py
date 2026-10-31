"""Unit Tests for Stage 6 Price-Change Detection Engine (src/price_changes.py).

Verifies:
1. Detection of persistent price increases (>= 2% increase across >= 2 consecutive cycles).
2. Suppression of false price-hike alerts for variable utility/postpaid bills (e.g. BESCOM).
3. Non-alerting behavior for constant prices and price decreases.
4. Non-alerting behavior for one-cycle spikes that do not persist.
5. Non-alerting behavior for minor fluctuations (< 2%).
6. Diagnostic explanation fields: previous amount, new amount, percentage change, effective date, persistence.
"""

import unittest
from datetime import date
from typing import List

from src.models import (
    CleanedTransaction,
    RecurringSeries,
    CadenceType,
    ConfidenceLevel,
    ConfidenceBreakdown,
    Evidence,
    RowStatus,
    MerchantMatch,
    MatchMethod
)
from src.price_changes import PriceHikeTracker


def make_test_series(
    merchant_name: str,
    amounts_and_dates: List[tuple],
    is_variable_bill: bool = False
) -> RecurringSeries:
    """Helper to construct RecurringSeries for price testing."""
    txns = []
    for d, amt in amounts_and_dates:
        t = CleanedTransaction(
            date=d,
            narration=f"DEBIT FOR {merchant_name}",
            amount=amt,
            is_debit=True,
            row_status=RowStatus.VALID,
            normalized_merchant=merchant_name,
            merchant_match=MerchantMatch(
                normalized_name=merchant_name,
                category="Utilities" if is_variable_bill else "Streaming & Media",
                is_variable_bill=is_variable_bill,
                method=MatchMethod.RULE_REGEX
            )
        )
        txns.append(t)

    breakdown = ConfidenceBreakdown(total_score=90.0, level=ConfidenceLevel.HIGH)
    evidence = Evidence(
        intervals_days=[30] * (len(amounts_and_dates) - 1),
        mean_interval_days=30.0,
        std_interval_days=0.5,
        cv_interval=0.02,
        day_of_month_list=[d.day for d, _ in amounts_and_dates],
        day_of_month_variance=0.5,
        modal_amount=amounts_and_dates[-1][1],
        modal_amount_ratio=0.5,
        has_mandate_keywords=True,
        notes=[]
    )

    return RecurringSeries(
        merchant_name=merchant_name,
        category="Utilities" if is_variable_bill else "Streaming & Media",
        cadence=CadenceType.MONTHLY,
        confidence_level=ConfidenceLevel.HIGH,
        confidence_score=90.0,
        confidence_breakdown=breakdown,
        evidence=evidence,
        transactions=txns,
        latest_amount=amounts_and_dates[-1][1],
        monthly_equivalent=amounts_and_dates[-1][1],
        annual_equivalent=amounts_and_dates[-1][1] * 12.0,
        is_variable_bill=is_variable_bill
    )


class TestPriceHikeTracker(unittest.TestCase):
    """Test suite for PriceHikeTracker in src/price_changes.py."""

    def test_detect_price_hike_netflix(self):
        """Tests that a 30.1% increase (499 -> 649) persisting for 2 cycles is flagged."""
        amounts_dates = [
            (date(2026, 1, 1), 499.0),
            (date(2026, 2, 1), 499.0),
            (date(2026, 3, 1), 649.0),
            (date(2026, 4, 1), 649.0),
        ]
        series = make_test_series("Netflix", amounts_dates)
        alert = PriceHikeTracker.evaluate_series(series)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.merchant_name, "Netflix")
        self.assertEqual(alert.old_amount, 499.0)
        self.assertEqual(alert.new_amount, 649.0)
        self.assertAlmostEqual(alert.change_percent, 30.1, places=1)
        self.assertEqual(alert.effective_date, date(2026, 3, 1))
        self.assertTrue(alert.is_confirmed)
        self.assertEqual(alert.baseline_cycles, 2)
        self.assertEqual(alert.persistence_cycles, 2)
        self.assertEqual(alert.formatted_difference, "+₹150.00 (+30.1%)")
        self.assertIn("persisted for 2 consecutive billing cycles", alert.evidence_note)

    def test_detect_price_hike_spotify(self):
        """Tests that an 8.4% increase (119 -> 129) persisting across cycles is flagged."""
        amounts_dates = [
            (date(2026, 1, 5), 119.0),
            (date(2026, 2, 5), 119.0),
            (date(2026, 3, 5), 119.0),
            (date(2026, 4, 5), 129.0),
            (date(2026, 5, 5), 129.0),
            (date(2026, 6, 5), 129.0),
        ]
        series = make_test_series("Spotify", amounts_dates)
        alert = PriceHikeTracker.evaluate_series(series)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.old_amount, 119.0)
        self.assertEqual(alert.new_amount, 129.0)
        self.assertAlmostEqual(alert.change_percent, 8.4, places=1)
        self.assertEqual(alert.effective_date, date(2026, 4, 5))
        self.assertEqual(alert.persistence_cycles, 3)

    def test_suppress_price_hike_for_variable_utility_bills_bescom(self):
        """
        Regression Test: BESCOM electricity is a variable utility bill.
        Fluctuations (even when ending in higher amounts) must NOT trigger price hike alerts.
        """
        amounts_dates = [
            (date(2026, 1, 20), 1240.0),
            (date(2026, 2, 20), 1580.0),
            (date(2026, 3, 20), 1390.0),
            (date(2026, 4, 20), 1720.0),
            (date(2026, 5, 20), 1620.0),
            (date(2026, 6, 20), 1620.0),
        ]
        series = make_test_series("BESCOM Electricity", amounts_dates, is_variable_bill=True)
        alert = PriceHikeTracker.evaluate_series(series)

        self.assertIsNone(alert)  # Suppressed due to is_variable_bill=True

    def test_constant_price_no_alert(self):
        """Constant subscription amounts must not trigger any price alerts."""
        amounts_dates = [
            (date(2026, 1, 10), 130.0),
            (date(2026, 2, 10), 130.0),
            (date(2026, 3, 10), 130.0),
            (date(2026, 4, 10), 130.0),
        ]
        series = make_test_series("Google One", amounts_dates)
        alert = PriceHikeTracker.evaluate_series(series)
        self.assertIsNone(alert)

    def test_price_decrease_no_hike_alert(self):
        """Price decreases (e.g. downgrades or discounts) must not trigger price hike alerts."""
        amounts_dates = [
            (date(2026, 1, 1), 649.0),
            (date(2026, 2, 1), 649.0),
            (date(2026, 3, 1), 499.0),
            (date(2026, 4, 1), 499.0),
        ]
        series = make_test_series("Netflix Plan Downgrade", amounts_dates)
        alert = PriceHikeTracker.evaluate_series(series)
        self.assertIsNone(alert)

    def test_one_cycle_spike_does_not_persist(self):
        """
        Temporary one-cycle spikes (e.g. one-off movie rental or mid-cycle adjustment)
        that either revert or only occur on the last observed cycle must not be flagged.
        """
        # Reverted spike
        reverted_dates = [
            (date(2026, 1, 1), 499.0),
            (date(2026, 2, 1), 499.0),
            (date(2026, 3, 1), 649.0),  # Temporary spike
            (date(2026, 4, 1), 499.0),  # Reverted
        ]
        series_reverted = make_test_series("Service A", reverted_dates)
        self.assertIsNone(PriceHikeTracker.evaluate_series(series_reverted))

        # Single cycle at tail (not yet confirmed by >= 2 cycles)
        tail_spike_dates = [
            (date(2026, 1, 1), 499.0),
            (date(2026, 2, 1), 499.0),
            (date(2026, 3, 1), 499.0),
            (date(2026, 4, 1), 649.0),  # Only 1 cycle observed
        ]
        series_tail = make_test_series("Service B", tail_spike_dates)
        self.assertIsNone(PriceHikeTracker.evaluate_series(series_tail))

    def test_small_increase_below_two_percent_no_alert(self):
        """Price increases below the 2.0% threshold (e.g. minor tax rounding) must not trigger alerts."""
        amounts_dates = [
            (date(2026, 1, 1), 1000.0),
            (date(2026, 2, 1), 1000.0),
            (date(2026, 3, 1), 1010.0),  # Exactly 1.0% increase (< 2%)
            (date(2026, 4, 1), 1010.0),
        ]
        series = make_test_series("Storage Service", amounts_dates)
        self.assertIsNone(PriceHikeTracker.evaluate_series(series))

    def test_attach_price_alerts_to_series_list(self):
        """Tests that attach_price_alerts populates price_alert and appends notes to evidence."""
        series_netflix = make_test_series("Netflix", [
            (date(2026, 1, 1), 499.0),
            (date(2026, 2, 1), 499.0),
            (date(2026, 3, 1), 649.0),
            (date(2026, 4, 1), 649.0),
        ])
        series_google = make_test_series("Google One", [
            (date(2026, 1, 10), 130.0),
            (date(2026, 2, 10), 130.0),
        ])
        series_bescom = make_test_series("BESCOM Electricity", [
            (date(2026, 1, 20), 1420.0),
            (date(2026, 2, 20), 1680.0),
            (date(2026, 3, 20), 1620.0),
            (date(2026, 4, 20), 1620.0),
        ], is_variable_bill=True)

        series_list = [series_netflix, series_google, series_bescom]
        PriceHikeTracker.attach_price_alerts(series_list)

        self.assertIsNotNone(series_netflix.price_alert)
        self.assertTrue(any("Price hike detected" in n for n in series_netflix.evidence.notes))

        self.assertIsNone(series_google.price_alert)
        self.assertIsNone(series_bescom.price_alert)


if __name__ == "__main__":
    unittest.main()
