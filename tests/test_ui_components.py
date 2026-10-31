"""Unit and integration tests for Stage 8 UI modules and Streamlit pipeline wiring.

Tests:
1. CSS style and badge generators (src/ui/styles.py).
2. Plotly chart builders with populated and empty data (src/ui/charts.py).
3. Data masking helpers for reference IDs and narrations (src/ui/components.py).
4. End-to-end UI pipeline integration function (app.run_pipeline).
5. Schema validation error handling for unsupported CSVs.
6. Availability and integrity of all pre-packaged demo datasets.
"""

import os
import unittest
from datetime import date
import plotly.graph_objects as go

from src.models import (
    ConfidenceLevel,
    CadenceType,
    RowStatus,
    SchemaValidationError,
    RecurringSeries,
)
from src.ui.styles import (
    get_custom_css,
    render_confidence_badge,
    render_cadence_badge,
    render_price_hike_badge,
    render_review_badge,
    render_paused_badge,
    render_variable_badge,
    render_kpi_card_html,
)
from src.ui.charts import (
    create_monthly_burn_chart,
    create_category_donut_chart,
    create_cadence_breakdown_chart,
    create_savings_comparison_chart,
)
from src.ui.components import (
    mask_reference_id,
    mask_narration,
)
from src.ui.pipeline import (
    DEMO_FILES,
    load_file_content,
    run_pipeline,
)


class TestUIComponents(unittest.TestCase):
    """Test suite for UI components, charts, and app pipeline wiring."""

    def test_custom_css_structure(self):
        """Verifies custom CSS contains essential layout and badge classes."""
        css = get_custom_css()
        self.assertIsInstance(css, str)
        self.assertIn(".kpi-card", css)
        self.assertIn(".badge-high", css)
        self.assertIn(".badge-medium", css)
        self.assertIn(".badge-low", css)
        self.assertIn(".privacy-vault-pill", css)
        self.assertIn(".price-alert-box", css)

    def test_badge_rendering(self):
        """Verifies HTML badge generators produce correct classes and content."""
        b_high = render_confidence_badge(ConfidenceLevel.HIGH, 88.5)
        self.assertIn("badge-high", b_high)
        self.assertIn("88/100", b_high)
        self.assertIn("High Confidence", b_high)

        b_med = render_confidence_badge(ConfidenceLevel.MEDIUM, 65.0)
        self.assertIn("badge-medium", b_med)
        self.assertIn("65/100", b_med)

        b_low = render_confidence_badge(ConfidenceLevel.LOW, 35.0)
        self.assertIn("badge-low", b_low)

        b_cadence = render_cadence_badge(CadenceType.MONTHLY)
        self.assertIn("badge-cadence", b_cadence)
        self.assertIn("Monthly", b_cadence)

        b_hike = render_price_hike_badge("+₹150.00 (+30.1%)")
        self.assertIn("badge-price-hike", b_hike)
        self.assertIn("+30.1%", b_hike)

        b_review = render_review_badge()
        self.assertIn("badge-review", b_review)

        b_paused = render_paused_badge()
        self.assertIn("badge-paused", b_paused)

        b_var = render_variable_badge()
        self.assertIn("badge-variable", b_var)

    def test_kpi_card_html_generation(self):
        """Verifies KPI card HTML generation with values and deltas."""
        card_html = render_kpi_card_html(
            label="Monthly Run-Rate",
            value="₹8,756.17",
            subtext="Forward 30-day commitment",
            delta="2 Alerts",
            delta_type="alert",
        )
        self.assertIn("Monthly Run-Rate", card_html)
        self.assertIn("₹8,756.17", card_html)
        self.assertIn("Forward 30-day commitment", card_html)
        self.assertIn("kpi-card-delta-alert", card_html)
        self.assertIn("2 Alerts", card_html)

    def test_masking_functions(self):
        """Verifies reference ID and narration privacy masking."""
        # Reference ID masking
        self.assertEqual(mask_reference_id(None), "-")
        self.assertEqual(mask_reference_id(""), "-")
        self.assertEqual(mask_reference_id("NA"), "-")
        self.assertEqual(mask_reference_id("REF1"), "REF1")  # <= 6 chars stays as is
        self.assertEqual(mask_reference_id("UPI/DR/1234567890"), "UPI***7890")
        self.assertEqual(mask_reference_id("TXN987654321"), "TXN***4321")

        # Narration card / account number masking
        narration_card = "POS 4012123456781234 AMZN PRIME MUMBAI"
        masked_card = mask_narration(narration_card)
        self.assertNotIn("12345678", masked_card)
        self.assertIn("4012XXXXXXXX1234", masked_card)

        # Narration phone number masking
        narration_phone = "UPI-TRANSFER TO 9876543210 VIA GPAY"
        masked_phone = mask_narration(narration_phone)
        self.assertNotIn("9876543210", masked_phone)
        self.assertIn("987****210", masked_phone)

    def test_chart_creation_valid_data(self):
        """Verifies Plotly chart generators create valid go.Figure objects with data."""
        # 1. Monthly burn chart
        sample_timeline = {
            "2025-11": {
                "total_spend": 5000.0,
                "by_category": {"Streaming & Media": 1500.0, "Health & Fitness": 3500.0},
            },
            "2025-12": {
                "total_spend": 5200.0,
                "by_category": {"Streaming & Media": 1700.0, "Health & Fitness": 3500.0},
            },
        }
        fig_burn = create_monthly_burn_chart(sample_timeline)
        self.assertIsInstance(fig_burn, go.Figure)
        self.assertEqual(len(fig_burn.data), 2)  # Two categories

        # 2. Category donut chart
        cat_totals = {"Streaming & Media": 649.0, "Software & Cloud": 130.0}
        fig_donut = create_category_donut_chart(cat_totals)
        self.assertIsInstance(fig_donut, go.Figure)
        self.assertEqual(len(fig_donut.data), 1)

        # 3. Savings comparison chart
        fig_savings = create_savings_comparison_chart(current_annual=100000.0, potential_savings=25000.0)
        self.assertIsInstance(fig_savings, go.Figure)
        self.assertEqual(len(fig_savings.data), 1)

    def test_chart_creation_empty_data(self):
        """Verifies Plotly chart generators return None or handle empty data gracefully."""
        self.assertIsNone(create_monthly_burn_chart({}))
        self.assertIsNone(create_category_donut_chart({}))
        self.assertIsNone(create_cadence_breakdown_chart([]))
        self.assertIsNone(create_savings_comparison_chart(0.0, 0.0))
        self.assertIsNone(create_savings_comparison_chart(-100.0, 0.0))

    def test_app_pipeline_run_on_benchmark_test_dataset(self):
        """Integration test executing app.run_pipeline on the 13-case test benchmark CSV."""
        csv_path = "data/synthetic/test_transactions.csv"
        self.assertTrue(os.path.exists(csv_path), f"Demo file missing: {csv_path}")

        with open(csv_path, "r", encoding="utf-8") as f:
            csv_content = f.read()

        cleaning_result, series_list, rejections, summary = run_pipeline(
            csv_text=csv_content,
            filename_hint="test_transactions.csv",
            min_confidence=ConfidenceLevel.LOW,
            override_start_date=date(2025, 11, 1),
            override_end_date=date(2026, 10, 31),
        )

        # Ingestion & Cleaning assertions (223 parsed data transactions in test_transactions.csv)
        self.assertEqual(cleaning_result.total_rows, 223)
        self.assertGreater(cleaning_result.valid_count, 100)

        # Recurring Detection assertions (11 benchmark subscriptions)
        self.assertEqual(len(series_list), 11)
        merchants = {s.merchant_name for s in series_list}
        self.assertIn("Netflix", merchants)
        self.assertIn("Spotify", merchants)
        self.assertIn("Cult.fit", merchants)
        self.assertIn("Amazon Prime", merchants)
        self.assertIn("BESCOM Electricity", merchants)

        # Price alerts check (Netflix & Spotify hiked, BESCOM suppressed)
        hiked = [s for s in series_list if s.price_alert is not None]
        self.assertEqual(len(hiked), 2)
        hiked_merchants = {s.merchant_name for s in hiked}
        self.assertEqual(hiked_merchants, {"Netflix", "Spotify"})

        # Cancellation details attached
        for s in series_list:
            self.assertIsNotNone(s.cancellation_details)
            self.assertTrue(len(s.cancellation_details.steps) >= 3)

        # Summary check
        self.assertFalse(summary.is_period_inferred)  # Explicit dates provided
        self.assertEqual(summary.observed_period_months, 12.0)
        self.assertAlmostEqual(summary.monthly_projected_commitment, 8756.17, places=1)
        self.assertAlmostEqual(summary.annual_projected_commitment, 105074.0, places=1)
        self.assertEqual(len(summary.review_candidates), 5)

        # Rejection shield check (Swiggy, Zomato, Blinkit, Uber rejected)
        self.assertGreaterEqual(len(rejections), 4)

    def test_app_pipeline_schema_validation_error(self):
        """Verifies that uploading an invalid CSV raises SchemaValidationError with diagnostics."""
        # Case 1: Missing amount column
        invalid_missing_amt = """Date,Description,Reference,Balance
01/01/2026,Netflix,REF1,1000.00
"""
        with self.assertRaises(SchemaValidationError) as cm1:
            run_pipeline(
                csv_text=invalid_missing_amt,
                filename_hint="missing_amt.csv",
                min_confidence=ConfidenceLevel.LOW,
            )
        err1 = cm1.exception
        self.assertIn("amount", err1.message.lower())
        self.assertTrue(any("amount" in m.lower() for m in err1.missing_fields))

        # Case 2: No valid header found
        invalid_no_header = """ColumnA,ColumnB,ColumnC
Foo,Bar,Baz
1,2,3
"""
        with self.assertRaises(SchemaValidationError) as cm2:
            run_pipeline(
                csv_text=invalid_no_header,
                filename_hint="bad_statement.csv",
                min_confidence=ConfidenceLevel.LOW,
            )
        err2 = cm2.exception
        self.assertIn("header", err2.message.lower())

    def test_demo_files_exist_and_are_readable(self):
        """Verifies that all pre-packaged demo options in DEMO_FILES exist and are non-empty."""
        for label, (rel_path, default_name) in DEMO_FILES.items():
            self.assertTrue(os.path.exists(rel_path), f"File {rel_path} for '{label}' does not exist")
            content = load_file_content(rel_path)
            self.assertIsNotNone(content, f"Could not read {rel_path}")
            self.assertGreater(len(content), 50, f"File {rel_path} is too small or empty")


if __name__ == "__main__":
    unittest.main()
