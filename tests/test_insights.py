"""Unit and integration tests for Financial Insights and Savings Simulator (Stage 7).

Tests:
1. Actual recurring spend from observed transactions, separated from estimated monthly
   and annual commitment.
2. Monthly and category-level breakdowns using existing recurring series and merchant metadata.
3. Review-candidate savings estimates, clearly labeled as potential savings rather than
   guaranteed savings (without labeling payments as 'forgotten' or claiming unconditional cancellation).
4. Handling for weekly, monthly, quarterly, and annual cadences, missing/insufficient history,
   paused/resumed series, and variable utility bills.
5. Strict exclusion of duplicates, refunds, reversals, invalid rows, and uncertain debits.
6. Savings simulation with custom merchant selections and edge cases.
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
    ScoreFactor,
    Evidence,
    PriceAlert,
    RowStatus,
    MatchMethod,
    InsightsSummary,
    SavingsSimulationResult,
    SeriesFinancialDetail,
)
from src.insights import (
    CostEstimator,
    SavingsSimulator,
    POTENTIAL_SAVINGS_DISCLAIMER,
)


def _make_dummy_evidence(cadence: CadenceType, is_paused: bool = False) -> Evidence:
    return Evidence(
        intervals_days=[30, 30],
        mean_interval_days=30.0,
        std_interval_days=0.5,
        cv_interval=0.02,
        day_of_month_list=[5, 5, 5],
        day_of_month_variance=0.0,
        modal_amount=500.0,
        modal_amount_ratio=1.0,
        has_mandate_keywords=True,
        notes=["Regular monthly schedule."],
        is_paused_resumed=is_paused,
    )


def _make_dummy_breakdown(score: float, level: ConfidenceLevel) -> ConfidenceBreakdown:
    return ConfidenceBreakdown(
        total_score=score,
        level=level,
        factors=[ScoreFactor(name="Regularity", points_awarded=30.0, max_points=30.0, rationale="Regular")],
    )


class TestFinancialInsights(unittest.TestCase):
    """Test suite for CostEstimator and SavingsSimulator."""

    def test_empty_series_list_returns_zeroed_summary(self):
        """Empty input returns clean zeroed InsightsSummary with disclaimer and no exceptions."""
        summary = CostEstimator.calculate_summary([])
        self.assertEqual(summary.monthly_actual_burn, 0.0)
        self.assertEqual(summary.monthly_projected_commitment, 0.0)
        self.assertEqual(summary.annual_projected_commitment, 0.0)
        self.assertEqual(summary.total_actual_spend, 0.0)
        self.assertEqual(summary.detected_series_count, 0)
        self.assertEqual(summary.price_alerts_count, 0)
        self.assertEqual(summary.category_totals, {})
        self.assertEqual(summary.merchant_annual_burn, {})
        self.assertEqual(summary.review_candidates, [])
        self.assertEqual(summary.total_review_annual_savings, 0.0)
        self.assertEqual(summary.total_review_monthly_savings, 0.0)
        self.assertEqual(summary.monthly_breakdown, {})
        self.assertEqual(summary.observed_period_months, 0.0)
        self.assertIsNone(summary.observed_start_date)
        self.assertIsNone(summary.observed_end_date)
        self.assertEqual(summary.savings_disclaimer, POTENTIAL_SAVINGS_DISCLAIMER)

    def test_actual_spend_vs_projected_commitment_distinction(self):
        """
        Verifies that actual historical spend is clearly separated from forward commitments.
        Netflix raised price from ₹499 to ₹649 in month 5:
        - 4 payments of ₹499 = ₹1,996
        - 8 payments of ₹649 = ₹5,192
        - Total actual spend = ₹7,188 (observed cash outflow over 12 months = ₹599/mo burn)
        - Projected monthly commitment = ₹649/mo (latest price)
        - Projected annual commitment = ₹7,788/yr (latest price * 12)
        """
        txns: List[CleanedTransaction] = []
        for m in range(1, 5):
            txns.append(
                CleanedTransaction(
                    date=date(2025, 10 + m if m <= 2 else m - 2, 5),
                    narration="NETFLIX",
                    amount=499.0,
                    is_debit=True,
                    row_status=RowStatus.VALID,
                    reference_id=f"NFX_{m}",
                )
            )
        for m in range(5, 13):
            txns.append(
                CleanedTransaction(
                    date=date(2026, m - 2 if m <= 12 else 11, 5),
                    narration="NETFLIX",
                    amount=649.0,
                    is_debit=True,
                    row_status=RowStatus.VALID,
                    reference_id=f"NFX_{m}",
                )
            )

        netflix_series = RecurringSeries(
            merchant_name="Netflix",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=95.0,
            confidence_breakdown=_make_dummy_breakdown(95.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=txns,
            latest_amount=649.0,
            monthly_equivalent=649.0,
            annual_equivalent=7788.0,
            price_alert=PriceAlert(
                merchant_name="Netflix",
                old_amount=499.0,
                new_amount=649.0,
                change_percent=30.06,
                effective_date=date(2026, 3, 5),
                is_confirmed=True,
                baseline_cycles=4,
                persistence_cycles=8,
                evidence_note="Price increased from ₹499 to ₹649.",
            ),
        )

        summary = CostEstimator.calculate_summary([netflix_series], statement_months=12.0)

        # Actual spend metrics
        expected_actual_total = 4 * 499.0 + 8 * 649.0  # 1996 + 5192 = 7188.0
        self.assertEqual(summary.total_actual_spend, expected_actual_total)
        self.assertEqual(summary.monthly_actual_burn, round(expected_actual_total / 12.0, 2))  # 599.0

        # Forward commitment run-rate (based on latest amount)
        self.assertEqual(summary.monthly_projected_commitment, 649.0)
        self.assertEqual(summary.annual_projected_commitment, 7788.0)

        # Distinction holds: burn (599.0) != commitment (649.0)
        self.assertNotEqual(summary.monthly_actual_burn, summary.monthly_projected_commitment)
        self.assertEqual(summary.price_alerts_count, 1)

    def test_various_cadences_and_run_rates(self):
        """Verifies run-rate formulas for weekly, biweekly, monthly, quarterly, semi-annual, and annual cadences."""
        # Weekly: ₹200/wk -> ₹866.67/mo, ₹10,400/yr
        m_wk, a_wk = CostEstimator.calculate_run_rate(CadenceType.WEEKLY, 200.0)
        self.assertAlmostEqual(m_wk, 866.67, places=2)
        self.assertEqual(a_wk, 10400.0)

        # Bi-weekly: ₹500/biwk -> ₹1,083.33/mo, ₹13,000/yr
        m_bi, a_bi = CostEstimator.calculate_run_rate(CadenceType.BIWEEKLY, 500.0)
        self.assertAlmostEqual(m_bi, 1083.33, places=2)
        self.assertEqual(a_bi, 13000.0)

        # Monthly: ₹499/mo -> ₹499/mo, ₹5,988/yr
        m_mo, a_mo = CostEstimator.calculate_run_rate(CadenceType.MONTHLY, 499.0)
        self.assertEqual(m_mo, 499.0)
        self.assertEqual(a_mo, 5988.0)

        # Quarterly: ₹499/qtr -> ₹166.33/mo, ₹1,996/yr
        m_qt, a_qt = CostEstimator.calculate_run_rate(CadenceType.QUARTERLY, 499.0)
        self.assertAlmostEqual(m_qt, 166.33, places=2)
        self.assertEqual(a_qt, 1996.0)

        # Semi-annual: ₹1,200/half-yr -> ₹200/mo, ₹2,400/yr
        m_sa, a_sa = CostEstimator.calculate_run_rate(CadenceType.SEMI_ANNUAL, 1200.0)
        self.assertEqual(m_sa, 200.0)
        self.assertEqual(a_sa, 2400.0)

        # Annual: ₹1,499/yr -> ₹124.92/mo, ₹1,499/yr
        m_an, a_an = CostEstimator.calculate_run_rate(CadenceType.ANNUAL, 1499.0)
        self.assertAlmostEqual(m_an, 124.92, places=2)
        self.assertEqual(a_an, 1499.0)

    def test_category_breakdowns_and_distributions(self):
        """Verifies category aggregation for monthly commitments, annual commitments, and actual spends."""
        s1 = RecurringSeries(
            merchant_name="Netflix",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=90.0,
            confidence_breakdown=_make_dummy_breakdown(90.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[
                CleanedTransaction(date=date(2026, 1, 1), narration="NFX", amount=649.0, is_debit=True, row_status=RowStatus.VALID),
                CleanedTransaction(date=date(2026, 2, 1), narration="NFX", amount=649.0, is_debit=True, row_status=RowStatus.VALID),
            ],
            latest_amount=649.0,
            monthly_equivalent=649.0,
            annual_equivalent=7788.0,
        )
        s2 = RecurringSeries(
            merchant_name="Spotify",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=85.0,
            confidence_breakdown=_make_dummy_breakdown(85.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[
                CleanedTransaction(date=date(2026, 1, 5), narration="SPOT", amount=129.0, is_debit=True, row_status=RowStatus.VALID),
                CleanedTransaction(date=date(2026, 2, 5), narration="SPOT", amount=129.0, is_debit=True, row_status=RowStatus.VALID),
            ],
            latest_amount=129.0,
            monthly_equivalent=129.0,
            annual_equivalent=1548.0,
        )
        s3 = RecurringSeries(
            merchant_name="Google One",
            category="Software & Cloud",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=88.0,
            confidence_breakdown=_make_dummy_breakdown(88.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[
                CleanedTransaction(date=date(2026, 1, 8), narration="G1", amount=130.0, is_debit=True, row_status=RowStatus.VALID),
                CleanedTransaction(date=date(2026, 2, 8), narration="G1", amount=130.0, is_debit=True, row_status=RowStatus.VALID),
            ],
            latest_amount=130.0,
            monthly_equivalent=130.0,
            annual_equivalent=1560.0,
        )

        summary = CostEstimator.calculate_summary([s1, s2, s3], statement_months=2.0)

        # Monthly commitments per category
        self.assertEqual(summary.category_totals["Streaming & Media"], 649.0 + 129.0)  # 778.0
        self.assertEqual(summary.category_totals["Software & Cloud"], 130.0)

        # Annual commitments per category
        self.assertEqual(summary.category_annual_commitments["Streaming & Media"], 7788.0 + 1548.0)  # 9336.0
        self.assertEqual(summary.category_annual_commitments["Software & Cloud"], 1560.0)

        # Actual spend per category
        self.assertEqual(summary.category_actual_spend["Streaming & Media"], (649.0 + 129.0) * 2)  # 1556.0
        self.assertEqual(summary.category_actual_spend["Software & Cloud"], 130.0 * 2)  # 260.0

    def test_monthly_timeline_breakdown(self):
        """Verifies that transactions are correctly grouped by year-month with merchant and category details."""
        t1 = CleanedTransaction(date=date(2026, 1, 5), narration="NFX", amount=649.0, is_debit=True, row_status=RowStatus.VALID)
        t2 = CleanedTransaction(date=date(2026, 1, 10), narration="JIO", amount=1179.0, is_debit=True, row_status=RowStatus.VALID)
        t3 = CleanedTransaction(date=date(2026, 2, 5), narration="NFX", amount=649.0, is_debit=True, row_status=RowStatus.VALID)
        t4 = CleanedTransaction(date=date(2026, 2, 10), narration="JIO", amount=1179.0, is_debit=True, row_status=RowStatus.VALID)

        s_nfx = RecurringSeries(
            merchant_name="Netflix",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=90.0,
            confidence_breakdown=_make_dummy_breakdown(90.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[t1, t3],
            latest_amount=649.0,
            monthly_equivalent=649.0,
            annual_equivalent=7788.0,
        )
        s_jio = RecurringSeries(
            merchant_name="JioFiber",
            category="Telecom & Broadband",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=90.0,
            confidence_breakdown=_make_dummy_breakdown(90.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[t2, t4],
            latest_amount=1179.0,
            monthly_equivalent=1179.0,
            annual_equivalent=14148.0,
        )

        timeline = CostEstimator.calculate_monthly_timeline([s_nfx, s_jio])
        self.assertIn("2026-01", timeline)
        self.assertIn("2026-02", timeline)

        jan = timeline["2026-01"]
        self.assertEqual(jan["total_spend"], 649.0 + 1179.0)
        self.assertEqual(jan["transaction_count"], 2)
        self.assertEqual(jan["by_category"]["Streaming & Media"], 649.0)
        self.assertEqual(jan["by_category"]["Telecom & Broadband"], 1179.0)
        self.assertEqual(jan["by_merchant"]["Netflix"], 649.0)
        self.assertEqual(jan["by_merchant"]["JioFiber"], 1179.0)

    def test_paused_resumed_series_cultfit(self):
        """
        Tests handling of paused/resumed series (e.g. Cult.fit paused for 2 months):
        - 10 debits of ₹1,750 over a 12-month period = ₹17,500 total actual spend.
        - Actual monthly burn = ₹17,500 / 12 = ₹1,458.33/mo.
        - Projected monthly commitment = ₹1,750.00/mo (active commitment).
        - Flagged as review candidate with paused/resumed explanation.
        """
        cult_txns: List[CleanedTransaction] = []
        # Months 1-3 active, months 4-5 paused, months 6-12 active (10 total debits)
        active_months = [1, 2, 3, 6, 7, 8, 9, 10, 11, 12]
        for m in active_months:
            cult_txns.append(
                CleanedTransaction(
                    date=date(2026, m, 15),
                    narration="SI CULTFIT",
                    amount=1750.0,
                    is_debit=True,
                    row_status=RowStatus.VALID,
                    reference_id=f"CULT_{m}",
                )
            )

        cult_series = RecurringSeries(
            merchant_name="Cult.fit",
            category="Health & Fitness",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.MEDIUM,
            confidence_score=68.0,
            confidence_breakdown=_make_dummy_breakdown(68.0, ConfidenceLevel.MEDIUM),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY, is_paused=True),
            transactions=cult_txns,
            latest_amount=1750.0,
            monthly_equivalent=1750.0,
            annual_equivalent=21000.0,
            is_paused_resumed=True,
            is_review_candidate=True,
            review_reasons=["Paused/resumed pattern detected: check if still desired."],
        )

        summary = CostEstimator.calculate_summary([cult_series], statement_months=12.0)
        self.assertEqual(summary.total_actual_spend, 17500.0)
        self.assertEqual(summary.monthly_actual_burn, round(17500.0 / 12.0, 2))  # 1458.33
        self.assertEqual(summary.monthly_projected_commitment, 1750.0)
        self.assertEqual(summary.annual_projected_commitment, 21000.0)

        # Cult.fit must be identified in review candidates
        candidate_names = [s.merchant_name for s in summary.review_candidates]
        self.assertIn("Cult.fit", candidate_names)
        cult_cand = next(s for s in summary.review_candidates if s.merchant_name == "Cult.fit")
        self.assertTrue(any("Paused/resumed" in r for r in cult_cand.review_reasons))

    def test_variable_bills_bescom(self):
        """
        Tests handling of variable utility bills (e.g. BESCOM electricity):
        - Amounts vary monthly (₹1,420, ₹1,680, ₹1,390, ₹1,720). Total = ₹6,210.
        - Cycle statistics (mean, min, max) are correctly captured in SeriesFinancialDetail.
        - Essential variable utility bills are NOT added as discretionary review candidates.
        """
        amounts = [1420.0, 1680.0, 1390.0, 1720.0]
        bescom_txns = [
            CleanedTransaction(
                date=date(2026, i + 1, 20),
                narration="BESCOM ELECTRICITY",
                amount=amt,
                is_debit=True,
                row_status=RowStatus.VALID,
                reference_id=f"BES_{i}",
            )
            for i, amt in enumerate(amounts)
        ]

        bescom_series = RecurringSeries(
            merchant_name="BESCOM Electricity",
            category="Utilities & Bills",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=85.0,
            confidence_breakdown=_make_dummy_breakdown(85.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=bescom_txns,
            latest_amount=1720.0,
            monthly_equivalent=1720.0,
            annual_equivalent=20640.0,
            is_variable_bill=True,
            is_review_candidate=False,
        )

        summary = CostEstimator.calculate_summary([bescom_series], statement_months=4.0)
        self.assertEqual(summary.total_actual_spend, sum(amounts))  # 6210.0
        self.assertEqual(summary.monthly_actual_burn, round(6210.0 / 4.0, 2))  # 1552.50

        # BESCOM should NOT be in review candidates
        self.assertEqual(len(summary.review_candidates), 0)

        # Check granular financial details
        details = CostEstimator.calculate_series_details([bescom_series])
        self.assertEqual(len(details), 1)
        d = details[0]
        self.assertEqual(d.merchant_name, "BESCOM Electricity")
        self.assertEqual(d.min_cycle_amount, 1390.0)
        self.assertEqual(d.max_cycle_amount, 1720.0)
        self.assertEqual(d.average_cycle_amount, 1552.5)
        self.assertTrue(d.is_variable_bill)
        self.assertIn("Variable bill", d.evidence_summary)

    def test_strict_exclusion_of_non_valid_and_uncertain_debits(self):
        """
        Verifies that refunds, reversals, duplicates, malformed rows, and uncertain debits
        are strictly excluded from actual spend, and no double-counting occurs.
        """
        valid_t1 = CleanedTransaction(
            date=date(2026, 1, 1), narration="SUB1", amount=500.0, is_debit=True, row_status=RowStatus.VALID, reference_id="V1"
        )
        valid_t2 = CleanedTransaction(
            date=date(2026, 2, 1), narration="SUB1", amount=500.0, is_debit=True, row_status=RowStatus.VALID, reference_id="V2"
        )
        duplicate_t = CleanedTransaction(
            date=date(2026, 2, 1), narration="SUB1", amount=500.0, is_debit=True, row_status=RowStatus.DUPLICATE, reference_id="DUP1"
        )
        refund_t = CleanedTransaction(
            date=date(2026, 2, 2), narration="REFUND", amount=500.0, is_debit=False, row_status=RowStatus.REFUND, reference_id="REF1"
        )
        uncertain_t = CleanedTransaction(
            date=date(2026, 2, 3), narration="UNCERTAIN", amount=500.0, is_debit=None, row_status=RowStatus.UNCERTAIN, reference_id="UNC1"
        )
        invalid_t = CleanedTransaction(
            date=date(2026, 2, 4), narration="INVALID", amount=500.0, is_debit=True, row_status=RowStatus.INVALID, reference_id="INV1"
        )

        s = RecurringSeries(
            merchant_name="Test Sub",
            category="Software & Cloud",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=80.0,
            confidence_breakdown=_make_dummy_breakdown(80.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            # Series contains mix of valid and non-valid transactions
            transactions=[valid_t1, valid_t2, duplicate_t, refund_t, uncertain_t, invalid_t],
            latest_amount=500.0,
            monthly_equivalent=500.0,
            annual_equivalent=6000.0,
        )

        summary = CostEstimator.calculate_summary([s], statement_months=2.0)
        # Only valid_t1 (500) and valid_t2 (500) should be counted = 1,000.0
        self.assertEqual(summary.total_actual_spend, 1000.0)
        self.assertEqual(summary.monthly_actual_burn, 500.0)

    def test_review_candidate_identification_and_disclaimer(self):
        """
        Verifies review candidate criteria:
        1. Annual commitments (high impact renewal).
        2. Paused/resumed series.
        3. Price hikes.
        4. Disclaimer is always attached and clearly labels savings as potential, not guaranteed.
        5. The word 'forgotten' is never used.
        """
        s_annual = RecurringSeries(
            merchant_name="Amazon Prime",
            category="Streaming & Media",
            cadence=CadenceType.ANNUAL,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=90.0,
            confidence_breakdown=_make_dummy_breakdown(90.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.ANNUAL),
            transactions=[],
            latest_amount=1499.0,
            monthly_equivalent=124.92,
            annual_equivalent=1499.0,
            is_review_candidate=True,
            review_reasons=["Annual commitment: high-impact renewal candidate."],
        )
        s_hike = RecurringSeries(
            merchant_name="Spotify",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=88.0,
            confidence_breakdown=_make_dummy_breakdown(88.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[],
            latest_amount=129.0,
            monthly_equivalent=129.0,
            annual_equivalent=1548.0,
            price_alert=PriceAlert(
                merchant_name="Spotify",
                old_amount=119.0,
                new_amount=129.0,
                change_percent=8.4,
                effective_date=date(2026, 4, 1),
                is_confirmed=True,
                baseline_cycles=4,
                persistence_cycles=4,
                evidence_note="Price increased from ₹119 to ₹129.",
            ),
        )

        candidates = SavingsSimulator.identify_review_candidates([s_annual, s_hike])
        cand_names = [c.merchant_name for c in candidates]
        self.assertIn("Amazon Prime", cand_names)
        self.assertIn("Spotify", cand_names)

        # Build candidate records and verify disclaimer
        records = SavingsSimulator.build_candidate_details(candidates)
        self.assertEqual(len(records), 2)
        for r in records:
            self.assertEqual(r.disclaimer, POTENTIAL_SAVINGS_DISCLAIMER)
            # Ensure "forgotten" is never used and savings are labeled as potential / not guaranteed
            all_text = (r.evidence + " " + " ".join(r.review_reasons) + " " + r.disclaimer).lower()
            self.assertNotIn("forgotten", all_text)
            self.assertIn("not guaranteed", all_text)
            self.assertIn("potential savings", all_text)
            # Ensure no claims that payment "can be cancelled" without qualification
            self.assertNotIn("can be cancelled", all_text)

    def test_savings_simulator_custom_merchants(self):
        """Verifies simulation of potential savings when user selects specific merchants or accepts defaults."""
        s1 = RecurringSeries(
            merchant_name="Netflix",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=90.0,
            confidence_breakdown=_make_dummy_breakdown(90.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[],
            latest_amount=649.0,
            monthly_equivalent=649.0,
            annual_equivalent=7788.0,
            is_review_candidate=True,
            review_reasons=["Discretionary review."],
        )
        s2 = RecurringSeries(
            merchant_name="Spotify",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=85.0,
            confidence_breakdown=_make_dummy_breakdown(85.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[],
            latest_amount=129.0,
            monthly_equivalent=129.0,
            annual_equivalent=1548.0,
            is_review_candidate=True,
            review_reasons=["Discretionary review."],
        )
        s3 = RecurringSeries(
            merchant_name="JioFiber",
            category="Telecom & Broadband",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=90.0,
            confidence_breakdown=_make_dummy_breakdown(90.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[],
            latest_amount=1179.0,
            monthly_equivalent=1179.0,
            annual_equivalent=14148.0,
            is_review_candidate=False,
        )

        all_series = [s1, s2, s3]
        total_monthly = 649.0 + 129.0 + 1179.0  # 1957.0
        total_annual = 7788.0 + 1548.0 + 14148.0  # 23484.0

        # Scenario A: User selects Netflix only
        sim_netflix = SavingsSimulator.simulate_savings(all_series, selected_merchants=["Netflix"])
        self.assertEqual(sim_netflix.selected_merchants, ["Netflix"])
        self.assertEqual(sim_netflix.potential_monthly_savings, 649.0)
        self.assertEqual(sim_netflix.potential_annual_savings, 7788.0)
        self.assertEqual(sim_netflix.remaining_monthly_commitment, total_monthly - 649.0)
        self.assertEqual(sim_netflix.remaining_annual_commitment, total_annual - 7788.0)
        self.assertEqual(sim_netflix.discontinued_series_count, 1)
        self.assertEqual(sim_netflix.retained_series_count, 2)
        self.assertIn("Streaming & Media", sim_netflix.savings_by_category)

        # Scenario B: Default simulation (all review candidates = Netflix & Spotify)
        sim_default = SavingsSimulator.simulate_savings(all_series, selected_merchants=None)
        self.assertEqual(set(sim_default.selected_merchants), {"Netflix", "Spotify"})
        self.assertEqual(sim_default.potential_monthly_savings, 649.0 + 129.0)  # 778.0
        self.assertEqual(sim_default.potential_annual_savings, 7788.0 + 1548.0)  # 9336.0
        self.assertEqual(sim_default.remaining_monthly_commitment, 1179.0)
        self.assertEqual(sim_default.remaining_annual_commitment, 14148.0)

        # Scenario C: Empty list of selected merchants
        sim_empty = SavingsSimulator.simulate_savings(all_series, selected_merchants=[])
        self.assertEqual(sim_empty.potential_monthly_savings, 0.0)
        self.assertEqual(sim_empty.potential_annual_savings, 0.0)
        self.assertEqual(sim_empty.remaining_monthly_commitment, total_monthly)
        self.assertEqual(sim_empty.discontinued_series_count, 0)
        self.assertEqual(sim_empty.retained_series_count, 3)

        # Scenario D: Non-existent merchant names are ignored gracefully
        sim_unknown = SavingsSimulator.simulate_savings(all_series, selected_merchants=["NonExistentCo"])
        self.assertEqual(sim_unknown.potential_monthly_savings, 0.0)
        self.assertEqual(sim_unknown.discontinued_series_count, 0)

    def test_confidence_filtering(self):
        """Verifies filtering by HIGH, MEDIUM, and LOW confidence levels."""
        s_high = RecurringSeries(
            merchant_name="Netflix",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=85.0,
            confidence_breakdown=_make_dummy_breakdown(85.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[],
            latest_amount=649.0,
            monthly_equivalent=649.0,
            annual_equivalent=7788.0,
        )
        s_med = RecurringSeries(
            merchant_name="Gym",
            category="Health & Fitness",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.MEDIUM,
            confidence_score=60.0,
            confidence_breakdown=_make_dummy_breakdown(60.0, ConfidenceLevel.MEDIUM),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[],
            latest_amount=1500.0,
            monthly_equivalent=1500.0,
            annual_equivalent=18000.0,
        )
        s_low = RecurringSeries(
            merchant_name="Unknown Vendor",
            category="General / Other",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.LOW,
            confidence_score=40.0,
            confidence_breakdown=_make_dummy_breakdown(40.0, ConfidenceLevel.LOW),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[],
            latest_amount=300.0,
            monthly_equivalent=300.0,
            annual_equivalent=3600.0,
        )

        all_series = [s_high, s_med, s_low]

        # Filter HIGH only
        sum_high = CostEstimator.calculate_summary(all_series, min_confidence=ConfidenceLevel.HIGH)
        self.assertEqual(sum_high.detected_series_count, 1)
        self.assertEqual(sum_high.monthly_projected_commitment, 649.0)

        # Filter MEDIUM (HIGH + MEDIUM)
        sum_med = CostEstimator.calculate_summary(all_series, min_confidence=ConfidenceLevel.MEDIUM)
        self.assertEqual(sum_med.detected_series_count, 2)
        self.assertEqual(sum_med.monthly_projected_commitment, 649.0 + 1500.0)

        # Filter LOW (ALL)
        sum_low = CostEstimator.calculate_summary(all_series, min_confidence=ConfidenceLevel.LOW)
        self.assertEqual(sum_low.detected_series_count, 3)
        self.assertEqual(sum_low.monthly_projected_commitment, 649.0 + 1500.0 + 300.0)

    def test_edge_cases_and_missing_inputs(self):
        """Verifies graceful handling of single-day transactions, missing dates, and zero division guards."""
        # Single transaction on a single date
        t_single = CleanedTransaction(
            date=date(2026, 5, 10), narration="SINGLE", amount=250.0, is_debit=True, row_status=RowStatus.VALID
        )
        s_single = RecurringSeries(
            merchant_name="Single",
            category="General / Other",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.LOW,
            confidence_score=35.0,
            confidence_breakdown=_make_dummy_breakdown(35.0, ConfidenceLevel.LOW),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[t_single],
            latest_amount=250.0,
            monthly_equivalent=250.0,
            annual_equivalent=3000.0,
        )

        summary = CostEstimator.calculate_summary([s_single])
        self.assertEqual(summary.total_actual_spend, 250.0)
        self.assertEqual(summary.observed_period_months, 1.0)
        self.assertEqual(summary.monthly_actual_burn, 250.0)

        # Negative amount passed to run-rate formula is sanitized
        m_neg, a_neg = CostEstimator.calculate_run_rate(CadenceType.MONTHLY, -500.0)
        self.assertEqual(m_neg, 500.0)
        self.assertEqual(a_neg, 6000.0)

    def test_statement_period_extending_beyond_recurring_transactions(self):
        """
        Verifies that when explicit statement start and end dates are provided,
        monthly_actual_burn is calculated over the full confirmed statement period,
        rather than only over the dates of detected recurring transactions.
        Also verifies the documented fallback behavior when dates are omitted.
        """
        # Recurring gym subscription active for only 3 months: March, April, May 2025
        # Total spend = ₹3,000 (3 payments of ₹1,000)
        t_mar = CleanedTransaction(date=date(2025, 3, 10), narration="FITNESS GYM", amount=1000.0, is_debit=True, row_status=RowStatus.VALID, reference_id="GYM01")
        t_apr = CleanedTransaction(date=date(2025, 4, 10), narration="FITNESS GYM", amount=1000.0, is_debit=True, row_status=RowStatus.VALID, reference_id="GYM02")
        t_may = CleanedTransaction(date=date(2025, 5, 10), narration="FITNESS GYM", amount=1000.0, is_debit=True, row_status=RowStatus.VALID, reference_id="GYM03")

        gym_series = RecurringSeries(
            merchant_name="Fitness Gym",
            category="Health & Fitness",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=85.0,
            confidence_breakdown=_make_dummy_breakdown(85.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[t_mar, t_apr, t_may],
            latest_amount=1000.0,
            monthly_equivalent=1000.0,
            annual_equivalent=12000.0,
        )

        # Case A: Caller provides full 12-month statement period (1 Jan 2025 to 31 Dec 2025)
        stmt_start = date(2025, 1, 1)
        stmt_end = date(2025, 12, 31)
        summary_explicit = CostEstimator.calculate_summary(
            [gym_series],
            statement_start_date=stmt_start,
            statement_end_date=stmt_end,
        )

        self.assertFalse(summary_explicit.is_period_inferred)
        self.assertEqual(summary_explicit.observed_period_months, 12.0)
        self.assertEqual(summary_explicit.total_actual_spend, 3000.0)
        # Burn calculated over 12 months: ₹3,000 / 12 = ₹250.00/mo
        self.assertEqual(summary_explicit.monthly_actual_burn, 250.00)
        self.assertIn("explicit statement period", summary_explicit.period_notes)
        # Timeline must span all 12 calendar months from 2025-01 to 2025-12
        self.assertEqual(len(summary_explicit.monthly_breakdown), 12)
        self.assertEqual(summary_explicit.monthly_breakdown["2025-01"]["total_spend"], 0.0)
        self.assertEqual(summary_explicit.monthly_breakdown["2025-03"]["total_spend"], 1000.0)
        self.assertEqual(summary_explicit.monthly_breakdown["2025-12"]["total_spend"], 0.0)

        # Case B: Fallback behavior when statement boundaries are omitted
        summary_fallback = CostEstimator.calculate_summary([gym_series])
        self.assertTrue(summary_fallback.is_period_inferred)
        # Inferred from March to May = 3 calendar months
        self.assertEqual(summary_fallback.observed_period_months, 3.0)
        self.assertEqual(summary_fallback.monthly_actual_burn, 1000.00)
        self.assertIn("Inferred fallback period", summary_fallback.period_notes)
        self.assertIn("Full statement period was not provided", summary_fallback.period_notes)
        # Timeline contains only the active months in fallback mode
        self.assertEqual(len(summary_fallback.monthly_breakdown), 3)

    def test_stable_deduplication_separate_objects_with_same_reference(self):
        """
        Verifies that separate Python objects representing the same underlying debit
        (same non-empty bank reference ID) are not double-counted.
        """
        t1 = CleanedTransaction(
            date=date(2026, 2, 1), narration="UPI/NETFLIX", amount=649.0, is_debit=True, row_status=RowStatus.VALID, reference_id="REF_NFX_001"
        )
        t2 = CleanedTransaction(
            date=date(2026, 2, 1), narration="UPI/NETFLIX", amount=649.0, is_debit=True, row_status=RowStatus.VALID, reference_id="REF_NFX_001"
        )
        self.assertIsNot(t1, t2)  # Separate Python objects

        # Verify key generation
        k1 = CostEstimator.get_transaction_dedup_key(t1)
        k2 = CostEstimator.get_transaction_dedup_key(t2)
        self.assertEqual(k1, k2)
        self.assertEqual(k1, ("ref", "REF_NFX_001"))

        s = RecurringSeries(
            merchant_name="Netflix",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=90.0,
            confidence_breakdown=_make_dummy_breakdown(90.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[t1, t2],
            latest_amount=649.0,
            monthly_equivalent=649.0,
            annual_equivalent=7788.0,
        )

        summary = CostEstimator.calculate_summary([s], statement_months=1.0)
        # Must be counted only once
        self.assertEqual(summary.total_actual_spend, 649.0)
        self.assertEqual(summary.monthly_actual_burn, 649.0)
        self.assertEqual(summary.monthly_breakdown["2026-02"]["transaction_count"], 1)

    def test_legitimate_separate_transactions_same_date_and_amount_distinct_references(self):
        """
        Verifies that two legitimate separate transactions on the same date with the same amount
        but distinct bank reference IDs are preserved and not merged.
        """
        t_netflix = CleanedTransaction(
            date=date(2026, 3, 15), narration="NETFLIX SUB", amount=499.0, is_debit=True, row_status=RowStatus.VALID, reference_id="REF_NFX_MAR"
        )
        t_hotstar = CleanedTransaction(
            date=date(2026, 3, 15), narration="HOTSTAR SUB", amount=499.0, is_debit=True, row_status=RowStatus.VALID, reference_id="REF_HOT_MAR"
        )
        self.assertNotEqual(t_netflix.reference_id, t_hotstar.reference_id)

        s_nfx = RecurringSeries(
            merchant_name="Netflix",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=90.0,
            confidence_breakdown=_make_dummy_breakdown(90.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[t_netflix],
            latest_amount=499.0,
            monthly_equivalent=499.0,
            annual_equivalent=5988.0,
        )
        s_hot = RecurringSeries(
            merchant_name="Disney+ Hotstar",
            category="Streaming & Media",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.HIGH,
            confidence_score=90.0,
            confidence_breakdown=_make_dummy_breakdown(90.0, ConfidenceLevel.HIGH),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[t_hotstar],
            latest_amount=499.0,
            monthly_equivalent=499.0,
            annual_equivalent=5988.0,
        )

        summary = CostEstimator.calculate_summary([s_nfx, s_hot], statement_months=1.0)
        # Both ₹499 transactions must be counted separately = ₹998.0
        self.assertEqual(summary.total_actual_spend, 998.0)
        self.assertEqual(summary.monthly_actual_burn, 998.0)
        feb_entry = summary.monthly_breakdown["2026-03"]
        self.assertEqual(feb_entry["total_spend"], 998.0)
        self.assertEqual(feb_entry["transaction_count"], 2)

    def test_stable_deduplication_without_reference_id_same_fields_vs_different_narration(self):
        """
        Verifies field-based deduplication when reference_id is missing or empty:
        - Separate objects with identical date, amount, narration are deduplicated.
        - Transactions with different narrations on the same date and amount are kept distinct.
        """
        # Identical field debits without reference ID
        t_dup1 = CleanedTransaction(
            date=date(2026, 4, 1), narration="LOCAL FITNESS", amount=300.0, is_debit=True, row_status=RowStatus.VALID, reference_id=""
        )
        t_dup2 = CleanedTransaction(
            date=date(2026, 4, 1), narration="LOCAL FITNESS", amount=300.0, is_debit=True, row_status=RowStatus.VALID, reference_id=None
        )
        # Distinct debit on the same date and amount with different narration
        t_diff = CleanedTransaction(
            date=date(2026, 4, 1), narration="CLOUD HOSTING", amount=300.0, is_debit=True, row_status=RowStatus.VALID, reference_id=None
        )

        k_dup1 = CostEstimator.get_transaction_dedup_key(t_dup1)
        k_dup2 = CostEstimator.get_transaction_dedup_key(t_dup2)
        k_diff = CostEstimator.get_transaction_dedup_key(t_diff)

        self.assertEqual(k_dup1, k_dup2)  # Same fields key
        self.assertNotEqual(k_dup1, k_diff)  # Different narration differentiates them

        s1 = RecurringSeries(
            merchant_name="Local Fitness",
            category="Health & Fitness",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.LOW,
            confidence_score=40.0,
            confidence_breakdown=_make_dummy_breakdown(40.0, ConfidenceLevel.LOW),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[t_dup1, t_dup2],
            latest_amount=300.0,
            monthly_equivalent=300.0,
            annual_equivalent=3600.0,
        )
        s2 = RecurringSeries(
            merchant_name="Cloud Hosting",
            category="Software & Cloud",
            cadence=CadenceType.MONTHLY,
            confidence_level=ConfidenceLevel.LOW,
            confidence_score=40.0,
            confidence_breakdown=_make_dummy_breakdown(40.0, ConfidenceLevel.LOW),
            evidence=_make_dummy_evidence(CadenceType.MONTHLY),
            transactions=[t_diff],
            latest_amount=300.0,
            monthly_equivalent=300.0,
            annual_equivalent=3600.0,
        )

        summary = CostEstimator.calculate_summary([s1, s2], statement_months=1.0)
        # t_dup1 and t_dup2 are deduplicated to ₹300; t_diff is ₹300. Total = ₹600.
        self.assertEqual(summary.total_actual_spend, 600.0)
        self.assertEqual(summary.monthly_breakdown["2026-04"]["transaction_count"], 2)


if __name__ == "__main__":
    unittest.main()
