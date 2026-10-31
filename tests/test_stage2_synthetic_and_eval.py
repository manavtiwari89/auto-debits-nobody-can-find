"""Unit tests for Stage 2: Seeded Synthetic Generator and Ground-Truth Evaluation."""

import os
import json
import unittest
from scripts.generate_synthetic import SyntheticDataGenerator
from scripts.evaluate import ModelEvaluator


class TestStage2SyntheticAndEvaluation(unittest.TestCase):
    """Test suite specifically verifying Stage 2 deliverables."""

    def test_generator_deterministic_reproducibility(self):
        """Verify that identical seeds produce 100% byte-identical datasets."""
        gen1 = SyntheticDataGenerator(seed=42)
        gen2 = SyntheticDataGenerator(seed=42)

        demo1 = gen1.generate_demo_dataset()
        demo2 = gen2.generate_demo_dataset()
        self.assertEqual(demo1, demo2, "Demo dataset must be byte-identical for identical seeds")

        test1, gt1 = gen1.generate_test_dataset()
        test2, gt2 = gen2.generate_test_dataset()
        self.assertEqual(test1, test2, "Test dataset must be byte-identical for identical seeds")
        self.assertEqual(gt1, gt2, "Ground truth JSON must be identical for identical seeds")

        stress1, sgt1 = gen1.generate_stress_dataset()
        stress2, sgt2 = gen2.generate_stress_dataset()
        self.assertEqual(stress1, stress2, "Stress dataset must be byte-identical for identical seeds")
        self.assertEqual(sgt1, sgt2, "Stress ground truth must be identical for identical seeds")

    def test_generator_different_seeds_produce_different_data(self):
        """Verify that different seeds produce different statements."""
        gen_a = SyntheticDataGenerator(seed=42)
        gen_b = SyntheticDataGenerator(seed=999)

        demo_a = gen_a.generate_demo_dataset()
        demo_b = gen_b.generate_demo_dataset()
        self.assertNotEqual(demo_a, demo_b, "Different seeds must produce different noise sequences")

    def test_ground_truth_schema_completeness(self):
        """Verify that ground truth JSON files contain required benchmark keys."""
        gt_path = os.path.join("data", "synthetic", "ground_truth.json")
        self.assertTrue(os.path.exists(gt_path), "data/synthetic/ground_truth.json must exist")

        with open(gt_path, "r", encoding="utf-8") as f:
            gt = json.load(f)

        self.assertIn("recurring_series", gt)
        self.assertIn("ordinary_repeats_to_reject", gt)
        self.assertGreaterEqual(len(gt["recurring_series"]), 10)
        self.assertGreaterEqual(len(gt["ordinary_repeats_to_reject"]), 4)

    def test_model_evaluation_on_test_dataset(self):
        """Verify evaluation metrics on test_transactions.csv."""
        csv_path = os.path.join("data", "synthetic", "test_transactions.csv")
        gt_path = os.path.join("data", "synthetic", "ground_truth.json")

        results = ModelEvaluator.evaluate(csv_path, gt_path, verbose=False)

        # Baseline detector should detect all ground truth subscriptions
        self.assertEqual(results["true_positives"], 11)
        self.assertEqual(results["false_negatives"], 0)
        self.assertEqual(results["false_positives"], 0)
        self.assertEqual(results["precision"], 1.0)
        self.assertEqual(results["recall"], 1.0)
        self.assertEqual(results["f1_score"], 1.0)

        # Ordinary repeats must be completely rejected (0.0% FP rate)
        self.assertEqual(results["ordinary_repeat_fp_rate"], 0.0)
        self.assertEqual(results["rejected_ordinary_repeats"], 4)

    def test_model_evaluation_on_stress_dataset(self):
        """Verify evaluation metrics on stress_transactions.csv using matching ground truth."""
        csv_path = os.path.join("data", "synthetic", "stress_transactions.csv")
        gt_path = os.path.join("data", "synthetic", "ground_truth_stress.json")

        results = ModelEvaluator.evaluate(csv_path, gt_path, verbose=False)

        self.assertEqual(results["false_positives"], 0)
        self.assertEqual(results["ordinary_repeat_fp_rate"], 0.0)
        self.assertGreaterEqual(results["precision"], 0.90)


if __name__ == "__main__":
    unittest.main()
