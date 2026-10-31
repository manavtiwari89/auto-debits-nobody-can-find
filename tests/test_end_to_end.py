"""Stage 9 End-to-End Regression Test Suite for The Auto Debits Nobody Can Find.

Exercises the authoritative src/ pipeline from end to end:
1. StatementIngestor (src/ingestion.py) - delimiter, bank headers, preamble
2. StatementCleaner (src/cleaning.py) - dates, amounts, Dr/Cr, dupes, refunds, row status
3. MerchantMatcher (src/merchants.py) - 4-tier cascade, VPA cleaning, flags
4. RecurringDetector (src/detection.py) - cadence, CV, paused/resumed, repeat shield, 0-100 score
5. PriceHikeTracker (src/price_changes.py) - >=2% hikes, persistence, variable-bill suppression
6. CancellationRegistry (src/cancellation.py) - verified vs unverified, AutoPay steps, anti-hallucination
7. CostEstimator & SavingsSimulator (src/insights.py) - burn vs commitment, review savings

Validates ground-truth metrics on both:
- data/synthetic/test_transactions.csv vs data/synthetic/ground_truth.json
- data/synthetic/stress_transactions.csv vs data/synthetic/ground_truth_stress.json

Maintains strict row preservation, in-memory privacy, verified vs unverified cancellation segregation,
and explicit non-agency and synthetic benchmark disclaimers.
"""

from __future__ import annotations
import os
import json
import unittest
from datetime import date
from typing import Dict, Any, List

from src.ingestion import StatementIngestor
from src.cleaning import StatementCleaner
from src.merchants import MerchantMatcher
from src.detection import RecurringDetector
from src.price_changes import PriceHikeTracker
from src.cancellation import CancellationRegistry
from src.insights import CostEstimator, SavingsSimulator, POTENTIAL_SAVINGS_DISCLAIMER
from src.models import (
    RowStatus,
    MatchMethod,
    CadenceType,
    ConfidenceLevel,
    CleaningResult,
    RecurringSeries,
    RejectionRecord,
    InsightsSummary,
)
from src.ui.pipeline import run_pipeline, DEMO_FILES, load_file_content
from src.ui.components import mask_reference_id, mask_narration
from scripts.evaluate import ModelEvaluator


class TestEndToEndCleanBenchmark(unittest.TestCase):
    """End-to-end regression on data/synthetic/test_transactions.csv."""

    @classmethod
    def setUpClass(cls):
        cls.workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.csv_path = os.path.join(cls.workspace_root, "data", "synthetic", "test_transactions.csv")
        cls.gt_path = os.path.join(cls.workspace_root, "data", "synthetic", "ground_truth.json")

        with open(cls.csv_path, "r", encoding="utf-8") as f:
            cls.csv_text = f.read()

        with open(cls.gt_path, "r", encoding="utf-8") as f:
            cls.gt_data = json.load(f)

        # Execute full authoritative pipeline
        cls.ingested = StatementIngestor.ingest_csv_text(cls.csv_text, filename_hint="test_transactions.csv")
        cls.cleaned = StatementCleaner.clean_statement(cls.ingested)
        MerchantMatcher.enrich_transactions(cls.cleaned.transactions)
        cls.series_list, cls.rejections = RecurringDetector.detect(cls.cleaned.transactions)
        PriceHikeTracker.attach_price_alerts(cls.series_list)
        CancellationRegistry.attach_cancellation_details(cls.series_list)
        cls.insights = CostEstimator.calculate_summary(cls.series_list)

        cls.series_by_name = {s.merchant_name: s for s in cls.series_list}
        cls.rejections_by_name = {r.merchant_name: r for r in cls.rejections}

    def test_ingestion_and_cleaning_row_preservation(self):
        """Verify delimiter detection, preamble skipping, and zero silent drops."""
        self.assertEqual(self.ingested.bank_name, "HDFC Bank")
        self.assertEqual(self.ingested.delimiter, ",")
        self.assertEqual(self.ingested.header_row_index, 6)

        # Zero silent drops invariant
        self.assertEqual(self.cleaned.total_rows, 223)
        self.assertEqual(len(self.cleaned.transactions), 223)

        # Duplicates and refunds
        self.assertEqual(self.cleaned.duplicate_count, 1)
        self.assertEqual(self.cleaned.refund_count, 1)
        self.assertEqual(len(self.cleaned.valid_debits), 208)

        # Verify duplicate debit row
        dup_row = next(t for t in self.cleaned.transactions if t.row_status == RowStatus.DUPLICATE)
        self.assertEqual(dup_row.reference_id, "DUPREF02")
        self.assertEqual(dup_row.refund_linked_id, "DUPREF01")

        # Verify refund row
        refund_row = next(t for t in self.cleaned.transactions if t.row_status == RowStatus.REFUND)
        self.assertEqual(refund_row.reference_id, "SHOPREFUND899")
        self.assertEqual(refund_row.refund_linked_id, "SHOPDEBIT899")
        self.assertFalse(refund_row.is_debit)

    def test_recurring_detection_precision_recall_and_cadence(self):
        """Verify 100% precision, 100% recall, and 100% cadence accuracy against ground truth."""
        gt_recurring = self.gt_data["recurring_series"]
        self.assertEqual(len(gt_recurring), 11)

        # Check true positives: all 11 ground truth series detected
        for gt in gt_recurring:
            m_name = gt["merchant"]
            self.assertIn(m_name, self.series_by_name, f"Expected subscription '{m_name}' not detected.")
            det = self.series_by_name[m_name]

            # Cadence match
            self.assertEqual(
                det.cadence.value.lower(),
                gt["cadence"].lower(),
                f"Cadence mismatch for {m_name}: expected {gt['cadence']}, got {det.cadence.value}"
            )

            # Amount match
            self.assertAlmostEqual(
                det.latest_amount,
                gt["expected_amount"],
                places=1,
                msg=f"Amount mismatch for {m_name}: expected {gt['expected_amount']}, got {det.latest_amount}"
            )

        # Zero false positives: no extra detected series
        self.assertEqual(len(self.series_list), 11)

    def test_paused_resumed_cadence_cultfit_regression(self):
        """Verify Cult.fit 60-day pause maintains Monthly cadence and tags review candidate."""
        cult = self.series_by_name["Cult.fit"]
        self.assertEqual(cult.cadence, CadenceType.MONTHLY)
        self.assertTrue(cult.is_paused_resumed)
        self.assertTrue(cult.is_review_candidate)
        self.assertTrue(any("Paused" in note or "pause" in note.lower() for note in cult.evidence.notes))
        # Ensure gap penalty was applied in score breakdown
        penalties = [p.name for p in cult.confidence_breakdown.penalties]
        self.assertTrue(any("Pause" in p or "gap" in p.lower() for p in penalties))

    def test_ordinary_repeat_rejections(self):
        """Verify discretionary spends (Swiggy, Zomato, Blinkit, Uber) are rejected with audits."""
        ordinary_repeats = self.gt_data["ordinary_repeats_to_reject"]
        self.assertEqual(len(ordinary_repeats), 4)

        for name in ordinary_repeats:
            self.assertNotIn(name, self.series_by_name, f"Ordinary repeat '{name}' falsely detected as recurring.")
            self.assertIn(name, self.rejections_by_name, f"Ordinary repeat '{name}' must have a RejectionRecord.")
            rec = self.rejections_by_name[name]
            self.assertGreater(rec.transaction_count, 0)
            self.assertTrue(len(rec.rejection_reasons) > 0)
            self.assertTrue(
                any("Discretionary" in r or "Rapid" in r or "Fluctuating" in r for r in rec.rejection_reasons),
                f"Expected clear explanation for {name}, got {rec.rejection_reasons}"
            )

    def test_price_hike_detection_and_variable_bill_suppression(self):
        """Verify Netflix & Spotify price hikes alerted, BESCOM variable bills suppressed."""
        # Netflix: ₹499 -> ₹649 (+30.1%)
        netflix = self.series_by_name["Netflix"]
        self.assertIsNotNone(netflix.price_alert)
        self.assertEqual(netflix.price_alert.old_amount, 499.0)
        self.assertEqual(netflix.price_alert.new_amount, 649.0)
        self.assertAlmostEqual(netflix.price_alert.change_percent, 30.1, places=1)
        self.assertTrue(netflix.price_alert.is_confirmed)
        self.assertGreaterEqual(netflix.price_alert.persistence_cycles, 2)

        # Spotify: ₹119 -> ₹129 (+8.4%)
        spotify = self.series_by_name["Spotify"]
        self.assertIsNotNone(spotify.price_alert)
        self.assertEqual(spotify.price_alert.old_amount, 119.0)
        self.assertEqual(spotify.price_alert.new_amount, 129.0)
        self.assertAlmostEqual(spotify.price_alert.change_percent, 8.4, places=1)
        self.assertTrue(spotify.price_alert.is_confirmed)

        # BESCOM: Fluctuating variable utility bills must NOT trigger price alert
        bescom = self.series_by_name["BESCOM Electricity"]
        self.assertTrue(bescom.is_variable_bill)
        self.assertIsNone(bescom.price_alert, "BESCOM Electricity variable bill must suppress price hike alert.")

        # Other 8 subscriptions have constant prices and must have NO price alert
        for name in ["Google One", "JioFiber", "Disney+ Hotstar", "Swiggy One", "Amazon Prime", "Microsoft 365", "Cult.fit", "Fitness First Gym"]:
            s = self.series_by_name[name]
            self.assertIsNone(s.price_alert, f"Subscription {name} should not have a price alert.")

    def test_verified_vs_unverified_cancellation_guidance(self):
        """Verify strict anti-hallucination segregation of verified vs unverified cancellation."""
        verified_merchants = ["Netflix", "Spotify", "Amazon Prime", "Disney+ Hotstar", "Google One", "Microsoft 365"]
        for vm in verified_merchants:
            s = self.series_by_name[vm]
            self.assertIsNotNone(s.cancellation_details)
            self.assertTrue(s.cancellation_details.is_verified, f"{vm} must be verified.")
            self.assertTrue(s.cancellation_details.source_url.startswith("https://"))
            self.assertNotEqual(s.cancellation_details.last_verified, "Unverified")
            self.assertGreaterEqual(len(s.cancellation_details.steps), 3)

        unverified_merchants = ["Cult.fit", "Swiggy One", "Fitness First Gym"]
        for uvm in unverified_merchants:
            s = self.series_by_name[uvm]
            self.assertIsNotNone(s.cancellation_details)
            self.assertFalse(s.cancellation_details.is_verified, f"{uvm} must be unverified.")
            self.assertEqual(s.cancellation_details.source_url, "", f"{uvm} source_url must be empty.")
            self.assertEqual(s.cancellation_details.last_verified, "Unverified")
            # Strict anti-hallucination check: ensure no specific identifiers or guarantees
            joined = " ".join(s.cancellation_details.steps + s.cancellation_details.mandate_guidance)
            self.assertNotIn("guarantee", joined.lower())
            self.assertNotIn("Bundl", joined)
            self.assertNotIn("Curefit", joined)

    def test_financial_insights_burn_vs_commitment(self):
        """Verify cost estimation, run-rate normalization, and potential savings simulation."""
        self.assertEqual(self.insights.detected_series_count, 11)
        self.assertEqual(self.insights.price_alerts_count, 2)
        self.assertAlmostEqual(self.insights.monthly_projected_commitment, 8756.17, places=1)
        self.assertAlmostEqual(self.insights.annual_projected_commitment, 105074.0, places=1)
        self.assertAlmostEqual(self.insights.total_actual_spend, 105442.0, places=1)
        self.assertGreater(self.insights.monthly_actual_burn, 0.0)

        # Review candidates must include Cult.fit (paused), Microsoft 365 (annual), Amazon Prime (annual), Netflix (hike), Spotify (hike)
        cand_names = {s.merchant_name for s in self.insights.review_candidates}
        self.assertTrue({"Cult.fit", "Microsoft 365", "Amazon Prime", "Netflix", "Spotify"}.issubset(cand_names))

        # Savings simulation
        sim = SavingsSimulator.simulate_savings(self.series_list, selected_merchants=["Netflix", "Spotify"])
        self.assertEqual(sim.discontinued_series_count, 2)
        self.assertEqual(sim.retained_series_count, 9)
        self.assertAlmostEqual(sim.potential_monthly_savings, 649.0 + 129.0, places=1)
        self.assertAlmostEqual(sim.potential_annual_savings, (649.0 + 129.0) * 12, places=1)
        self.assertEqual(sim.disclaimer, POTENTIAL_SAVINGS_DISCLAIMER)


class TestEndToEndStressBenchmark(unittest.TestCase):
    """End-to-end regression on data/synthetic/stress_transactions.csv."""

    @classmethod
    def setUpClass(cls):
        cls.workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.csv_path = os.path.join(cls.workspace_root, "data", "synthetic", "stress_transactions.csv")
        cls.gt_path = os.path.join(cls.workspace_root, "data", "synthetic", "ground_truth_stress.json")

        with open(cls.csv_path, "r", encoding="utf-8") as f:
            cls.csv_text = f.read()

        with open(cls.gt_path, "r", encoding="utf-8") as f:
            cls.gt_data = json.load(f)

        cls.ingested = StatementIngestor.ingest_csv_text(cls.csv_text, filename_hint="stress_transactions.csv")
        cls.cleaned = StatementCleaner.clean_statement(cls.ingested)
        MerchantMatcher.enrich_transactions(cls.cleaned.transactions)
        cls.series_list, cls.rejections = RecurringDetector.detect(cls.cleaned.transactions)
        PriceHikeTracker.attach_price_alerts(cls.series_list)
        CancellationRegistry.attach_cancellation_details(cls.series_list)
        cls.insights = CostEstimator.calculate_summary(cls.series_list)

        cls.series_by_name = {s.merchant_name: s for s in cls.series_list}
        cls.rejections_by_name = {r.merchant_name: r for r in cls.rejections}

    def test_stress_ingestion_and_cleaning(self):
        """Verify DD-MM-YYYY dates and noise handling without dropping rows."""
        self.assertEqual(self.cleaned.total_rows, 179)
        self.assertEqual(len(self.cleaned.transactions), 179)
        self.assertGreaterEqual(len(self.cleaned.valid_debits), 160)

    def test_stress_merchant_fuzzy_matching_and_unknown_fallback(self):
        """Verify fuzzy typo resilience and Tier 4 unknown merchant handling."""
        # Tier 4 unknown merchant: Fitness First Gym
        self.assertIn("Fitness First Gym", self.series_by_name)
        gym = self.series_by_name["Fitness First Gym"]
        self.assertEqual(gym.cadence, CadenceType.MONTHLY)
        self.assertFalse(gym.is_merchant_verified)
        self.assertEqual(gym.confidence_level, ConfidenceLevel.MEDIUM)
        self.assertLessEqual(gym.confidence_score, 74.0)
        self.assertFalse(gym.cancellation_details.is_verified)
        self.assertEqual(gym.cancellation_details.source_url, "")

    def test_stress_ground_truth_accuracy(self):
        """Verify 11/11 subscriptions detected with 100% cadence accuracy under stress."""
        gt_recurring = self.gt_data["recurring_series"]
        self.assertEqual(len(gt_recurring), 11)

        for gt in gt_recurring:
            m_name = gt["merchant"]
            self.assertIn(m_name, self.series_by_name, f"Expected {m_name} in detected series.")
            det = self.series_by_name[m_name]
            self.assertEqual(
                det.cadence.value.lower(),
                gt["cadence"].lower(),
                f"Cadence mismatch on stress dataset for {m_name}: expected {gt['cadence']}, got {det.cadence.value}"
            )

        self.assertEqual(len(self.series_list), 11)

    def test_stress_ordinary_repeat_rejection(self):
        """Verify Swiggy, Zomato, Zepto, and Uber are rejected under heavy noise."""
        for rep in ["Swiggy", "Zomato", "Zepto", "Uber"]:
            self.assertNotIn(rep, self.series_by_name)
            self.assertIn(rep, self.rejections_by_name)

    def test_stress_price_hike_behavior(self):
        """Verify only Netflix price hike is alerted in stress dataset (Spotify is constant ₹119)."""
        # Netflix: hiked
        netflix = self.series_by_name["Netflix"]
        self.assertIsNotNone(netflix.price_alert)
        self.assertEqual(netflix.price_alert.old_amount, 499.0)
        self.assertEqual(netflix.price_alert.new_amount, 649.0)

        # Spotify: constant in stress dataset
        spotify = self.series_by_name["Spotify"]
        self.assertIsNone(spotify.price_alert)

        # BESCOM: suppressed
        bescom = self.series_by_name["BESCOM Electricity"]
        self.assertIsNone(bescom.price_alert)


class TestEndToEndSampleBankStatements(unittest.TestCase):
    """End-to-end execution across all demo and pre-packaged sample statements."""

    def test_all_demo_files_execute_successfully(self):
        """Verify run_pipeline executes with 0 exceptions on all demo statements."""
        for label, (rel_path, hint) in DEMO_FILES.items():
            content = load_file_content(rel_path)
            self.assertIsNotNone(content, f"Failed to load demo file: {rel_path}")
            cleaning, series, rejections, summary = run_pipeline(content, filename_hint=hint)

            self.assertIsInstance(cleaning, CleaningResult)
            self.assertGreater(cleaning.total_rows, 0)
            self.assertIsInstance(series, list)
            self.assertIsInstance(rejections, list)
            self.assertIsInstance(summary, InsightsSummary)
            self.assertGreaterEqual(summary.detected_series_count, 0)

    def test_masking_utility_preserves_privacy(self):
        """Verify sensitive account and reference ID masking."""
        self.assertEqual(mask_reference_id("TXN_NETFLIX_20251102"), "TXN***1102")
        self.assertEqual(mask_reference_id("UPI/DR/1234567890"), "UPI***7890")
        masked = mask_narration("POS 4012888899991234 AMZN PRIME 9876543210")
        self.assertNotIn("4012888899991234", masked)
        self.assertIn("4012XXXXXXXX1234", masked)
        self.assertNotIn("9876543210", masked)
        self.assertIn("987****210", masked)


class TestEndToEndBenchmarkEvaluatorCLI(unittest.TestCase):
    """Verifies scripts/evaluate.py benchmark evaluation on both src and legacy engines."""

    def test_evaluator_src_engine_on_clean_dataset(self):
        """Verify ModelEvaluator on test dataset achieves 100% precision, recall, and cadence."""
        csv_path = os.path.join("data", "synthetic", "test_transactions.csv")
        gt_path = os.path.join("data", "synthetic", "ground_truth.json")

        report = ModelEvaluator.evaluate(csv_path, gt_path, verbose=False, engine="src")

        self.assertEqual(report["engine"], "src")
        self.assertEqual(report["true_positives"], 11)
        self.assertEqual(report["false_positives"], 0)
        self.assertEqual(report["false_negatives"], 0)
        self.assertEqual(report["precision"], 1.0)
        self.assertEqual(report["recall"], 1.0)
        self.assertEqual(report["f1_score"], 1.0)
        self.assertEqual(report["cadence_accuracy"], 1.0)
        self.assertEqual(report["ordinary_repeat_fp_rate"], 0.0)
        self.assertEqual(report["rejected_ordinary_repeats"], 4)
        self.assertEqual(report["price_hike_tp"], 2)
        self.assertEqual(report["price_hike_fp"], 0)
        self.assertEqual(report["price_hike_precision"], 1.0)
        self.assertEqual(report["price_hike_recall"], 1.0)

    def test_evaluator_src_engine_on_stress_dataset(self):
        """Verify ModelEvaluator on stress dataset achieves 100% precision, recall, and cadence."""
        csv_path = os.path.join("data", "synthetic", "stress_transactions.csv")
        gt_path = os.path.join("data", "synthetic", "ground_truth_stress.json")

        report = ModelEvaluator.evaluate(csv_path, gt_path, verbose=False, engine="src")

        self.assertEqual(report["engine"], "src")
        self.assertEqual(report["true_positives"], 11)
        self.assertEqual(report["false_positives"], 0)
        self.assertEqual(report["false_negatives"], 0)
        self.assertEqual(report["precision"], 1.0)
        self.assertEqual(report["recall"], 1.0)
        self.assertEqual(report["cadence_accuracy"], 1.0)
        self.assertEqual(report["ordinary_repeat_fp_rate"], 0.0)
        self.assertEqual(report["price_hike_tp"], 1)
        self.assertEqual(report["price_hike_fp"], 0)
        self.assertEqual(report["price_hike_precision"], 1.0)

    def test_evaluator_legacy_engine_remains_available(self):
        """Verify explicit legacy engine produces expected historical baseline metrics."""
        csv_path = os.path.join("data", "synthetic", "test_transactions.csv")
        gt_path = os.path.join("data", "synthetic", "ground_truth.json")

        report = ModelEvaluator.evaluate(csv_path, gt_path, verbose=False, engine="legacy")

        self.assertEqual(report["engine"], "legacy")
        self.assertEqual(report["true_positives"], 11)
        # In legacy baseline: Cult.fit was Irregular -> 90.9% cadence
        self.assertEqual(report["cadence_accuracy"], 0.9091)
        # In legacy baseline: BESCOM was flagged as false hike -> 66.7% precision
        self.assertEqual(report["price_hike_precision"], 0.6667)


if __name__ == "__main__":
    unittest.main()
