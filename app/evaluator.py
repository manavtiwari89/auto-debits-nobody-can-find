"""Evaluation Benchmark for The Auto Debits Nobody Can Find.

Evaluates recurring debit detection precision, recall, F1 score,
and price-hike alert accuracy against ground-truth synthetic statements.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
from app.parser import BankStatementParser
from app.normalizer import NarrationNormalizer
from app.detector import RecurringDetector
from app.price_tracker import PriceTracker
from app.demo_data import generate_hdfc_statement, GROUND_TRUTH_RECURRING


@dataclass
class EvaluationReport:
    """Comprehensive evaluation metrics report."""
    total_ground_truth: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    price_hike_tp: int
    price_hike_fp: int
    price_hike_fn: int
    price_hike_accuracy: float
    detected_merchants: List[str]
    missed_merchants: List[str]
    spurious_merchants: List[str]

    def summary(self) -> str:
        return (
            f"=== Model Evaluation Benchmark Report ===\n"
            f"Ground Truth Subscriptions : {self.total_ground_truth}\n"
            f"True Positives (TP)        : {self.true_positives}\n"
            f"False Positives (FP)       : {self.false_positives}\n"
            f"False Negatives (FN)       : {self.false_negatives}\n"
            f"Precision                  : {self.precision * 100:.1f}%\n"
            f"Recall                     : {self.recall * 100:.1f}%\n"
            f"F1 Score                   : {self.f1_score * 100:.1f}%\n"
            f"Price Hike Accuracy        : {self.price_hike_accuracy * 100:.1f}%\n"
            f"Detected Subscriptions     : {', '.join(self.detected_merchants)}\n"
            f"Missed Subscriptions       : {', '.join(self.missed_merchants) or 'None'}\n"
            f"False Positive Alerts      : {', '.join(self.spurious_merchants) or 'None'}\n"
            f"=========================================="
        )


class BenchmarkEvaluator:
    """Runs evaluation benchmark against synthetic statement."""

    @classmethod
    def evaluate_statement(
        cls, csv_content: str, ground_truth: Dict[str, Dict[str, Any]]
    ) -> EvaluationReport:
        """Runs pipeline and measures classification performance."""
        # 1. Parse CSV
        txns = BankStatementParser.parse_csv_content(csv_content, "Benchmark")

        # 2. Enrich transactions
        for t in txns:
            NarrationNormalizer.enrich_transaction(t)

        # 3. Detect recurring
        series_list = RecurringDetector.detect_recurring(txns)

        # 4. Price tracker
        PriceTracker.attach_price_alerts(series_list)

        detected_map = {s.merchant_name: s for s in series_list}

        tp = 0
        fn = 0
        fp = 0
        detected_names: List[str] = []
        missed_names: List[str] = []
        spurious_names: List[str] = []

        # Check ground truth
        for gt_name, gt_meta in ground_truth.items():
            if gt_name in detected_map:
                tp += 1
                detected_names.append(gt_name)
            else:
                fn += 1
                missed_names.append(gt_name)

        # Check spurious detections (FP)
        for det_name in detected_map.keys():
            if det_name not in ground_truth:
                fp += 1
                spurious_names.append(det_name)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        # Evaluate price hikes
        price_hike_tp = 0
        price_hike_fp = 0
        price_hike_fn = 0

        for gt_name, gt_meta in ground_truth.items():
            expected_hike = gt_meta.get("has_price_hike", False)
            if gt_name in detected_map:
                actual_hike = detected_map[gt_name].price_alert is not None
                if expected_hike and actual_hike:
                    price_hike_tp += 1
                elif expected_hike and not actual_hike:
                    price_hike_fn += 1
                elif not expected_hike and actual_hike:
                    price_hike_fp += 1

        total_hike_checks = len(ground_truth)
        hike_correct = sum(
            1 for gt_name, gt_meta in ground_truth.items()
            if gt_name in detected_map and (detected_map[gt_name].price_alert is not None) == gt_meta.get("has_price_hike", False)
        )
        price_hike_accuracy = hike_correct / total_hike_checks if total_hike_checks > 0 else 1.0

        return EvaluationReport(
            total_ground_truth=len(ground_truth),
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1_score=round(f1, 4),
            price_hike_tp=price_hike_tp,
            price_hike_fp=price_hike_fp,
            price_hike_fn=price_hike_fn,
            price_hike_accuracy=round(price_hike_accuracy, 4),
            detected_merchants=detected_names,
            missed_merchants=missed_names,
            spurious_merchants=spurious_names
        )


def main():
    csv_content, _ = generate_hdfc_statement()
    report = BenchmarkEvaluator.evaluate_statement(csv_content, GROUND_TRUTH_RECURRING)
    print(report.summary())


if __name__ == "__main__":
    main()
