"""Pipeline execution and demo data loading helper for the Streamlit UI.

Stage 8 UI Module.
Wires the authoritative src/ pipeline:
StatementIngestor -> StatementCleaner -> MerchantMatcher -> RecurringDetector
-> PriceHikeTracker -> CancellationRegistry -> CostEstimator & SavingsSimulator
"""

from __future__ import annotations
import os
from datetime import date
from typing import List, Optional, Tuple, Dict, Any

from src.models import (
    ConfidenceLevel,
    RecurringSeries,
    CleaningResult,
    RejectionRecord,
    InsightsSummary,
)
from src.ingestion import StatementIngestor
from src.cleaning import StatementCleaner
from src.merchants import MerchantMatcher
from src.detection import RecurringDetector
from src.price_changes import PriceHikeTracker
from src.cancellation import CancellationRegistry
from src.insights import CostEstimator


DEMO_FILES: Dict[str, Tuple[str, str]] = {
    "12-Month Realistic Demo ('Aarav' - 168 transactions)": (
        "data/synthetic/demo_transactions.csv",
        "Aarav_12Month_Demo.csv",
    ),
    "13-Case Test Benchmark (Clean - 223 transactions, 11 Series)": (
        "data/synthetic/test_transactions.csv",
        "Benchmark_Test_Statement.csv",
    ),
    "Format Jitter & Stress Statement (High Noise - 179 transactions, 11 Series)": (
        "data/synthetic/stress_transactions.csv",
        "Stress_Test_Statement.csv",
    ),
    "HDFC Bank Sample Export": (
        "data/sample_statements/hdfc_sample_statement.csv",
        "HDFC_Sample.csv",
    ),
    "SBI Bank Sample Export": (
        "data/sample_statements/sbi_sample_statement.csv",
        "SBI_Sample.csv",
    ),
    "ICICI Bank Sample Export": (
        "data/sample_statements/icici_sample_statement.csv",
        "ICICI_Sample.csv",
    ),
}


def load_file_content(relative_path: str) -> Optional[str]:
    """Loads CSV content from local workspace path."""
    if not os.path.exists(relative_path):
        return None
    with open(relative_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def run_pipeline(
    csv_text: str,
    filename_hint: str = "statement.csv",
    min_confidence: ConfidenceLevel = ConfidenceLevel.LOW,
    override_start_date: Optional[date] = None,
    override_end_date: Optional[date] = None,
) -> Tuple[
    CleaningResult,
    List[RecurringSeries],
    List[RejectionRecord],
    InsightsSummary,
]:
    """
    Executes the authoritative src/ pipeline:
    Ingestion -> Cleaning -> Merchant Normalization -> Recurring Detection
    -> Price Hike Tracking -> Cancellation Intelligence -> Cost Estimation.
    """
    # 1. Ingest statement
    ingested = StatementIngestor.ingest_csv_text(csv_text, filename_hint=filename_hint)

    # 2. Clean and sanitize rows
    cleaning_result = StatementCleaner.clean_statement(ingested)

    # 3. 4-tier merchant normalization cascade
    MerchantMatcher.enrich_transactions(cleaning_result.transactions)

    # 4. Recurring debit detection with gap-tolerant clustering & repeat protection
    series_list, rejections = RecurringDetector.detect(cleaning_result.transactions)

    # 5. Persistent price increase detection with variable-bill suppression
    PriceHikeTracker.attach_price_alerts(series_list)

    # 6. Attach verified cancellation guidance & AutoPay mandate revocation steps
    CancellationRegistry.attach_cancellation_details(series_list)

    # 7. Financial insights: actual spend vs projected commitment & review savings
    summary = CostEstimator.calculate_summary(
        series_list,
        min_confidence=min_confidence,
        statement_start_date=override_start_date,
        statement_end_date=override_end_date,
    )

    return cleaning_result, series_list, rejections, summary
