"""Unit tests for Benchmark Evaluation Framework."""

import unittest
from app.evaluator import BenchmarkEvaluator
from app.demo_data import generate_hdfc_statement, GROUND_TRUTH_RECURRING


class TestBenchmarkEvaluation(unittest.TestCase):

    def test_benchmark_performance_metrics(self):
        csv_content, _ = generate_hdfc_statement()
        report = BenchmarkEvaluator.evaluate_statement(csv_content, GROUND_TRUTH_RECURRING)
        
        # Verify precision, recall, and F1 meet high production-grade thresholds
        self.assertGreaterEqual(report.precision, 0.95)
        self.assertGreaterEqual(report.recall, 0.95)
        self.assertGreaterEqual(report.f1_score, 0.95)
        self.assertEqual(report.false_positives, 0)
        self.assertEqual(report.false_negatives, 0)
        
        # Verify price hike detection on Netflix
        self.assertEqual(report.price_hike_tp, 1)
        self.assertEqual(report.price_hike_fp, 0)
        self.assertGreaterEqual(report.price_hike_accuracy, 0.95)


if __name__ == "__main__":
    unittest.main()
