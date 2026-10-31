"""Configuration and thresholds for The Auto Debits Nobody Can Find.

Single source of truth for detection rules, interval tolerances,
confidence score weights, price change criteria, and categorization.
"""

from __future__ import annotations
from typing import Dict, Tuple

# ============================================================================
# Cadence Interval Definitions (Days)
# ============================================================================
# (nominal_days, min_days, max_days, max_acceptable_std_dev)
CADENCE_SPECS: Dict[str, Tuple[float, float, float, float]] = {
    "weekly": (7.0, 5.0, 9.0, 2.5),
    "biweekly": (14.0, 11.0, 17.0, 3.5),
    "monthly": (30.0, 25.0, 35.0, 6.0),
    "quarterly": (91.0, 80.0, 102.0, 10.0),
    "semiannual": (182.0, 165.0, 200.0, 14.0),
    "annual": (365.0, 350.0, 380.0, 18.0),
}

# Maximum allowed Coefficient of Variation (std_dev / mean) for regular interval
MAX_REGULAR_CV: float = 0.35
LOOSE_REGULAR_CV: float = 0.50

# Minimum occurrences required to detect recurring series
MIN_OCCURRENCES_WEEKLY_MONTHLY: int = 3
MIN_OCCURRENCES_QUARTERLY_ANNUAL_KNOWN: int = 2

# Maximum day-of-month deviation considered "anchored" (e.g. 5th of every month ± 3 days)
DAY_OF_MONTH_TOLERANCE_DAYS: int = 4

# Minimum percentage of debits at the modal amount to be considered stable
AMOUNT_MODAL_RATIO_THRESHOLD: float = 0.70
AMOUNT_VARIANCE_TOLERANCE_PERCENT: float = 5.0

# ============================================================================
# Confidence Score Weights (Additive 0–100 Scale)
# ============================================================================
# Maximum possible component points: 25 + 30 + 20 + 15 + 10 = 100
WEIGHT_OCCURRENCES_MAX: int = 25
WEIGHT_INTERVAL_REGULARITY_MAX: int = 30
WEIGHT_AMOUNT_STABILITY_MAX: int = 20
WEIGHT_MERCHANT_QUALITY_MAX: int = 15
WEIGHT_DAY_OF_MONTH_MAX: int = 10

# Confidence Classification Thresholds
CONFIDENCE_HIGH_THRESHOLD: int = 75
CONFIDENCE_MEDIUM_THRESHOLD: int = 50

# Penalties
PENALTY_UNKNOWN_MERCHANT: int = -15
PENALTY_FEW_OBSERVATIONS: int = -10
PENALTY_RETAIL_CATEGORY: int = -20
PENALTY_GAP_PAUSED: int = -10

# Cap confidence for unknown merchants
UNKNOWN_MERCHANT_MAX_CONFIDENCE_LEVEL: str = "Medium"

# ============================================================================
# Price Change Detection Settings
# ============================================================================
PRICE_HIKE_MIN_PERCENT: float = 2.0
PRICE_HIKE_MIN_BASELINE_CYCLES: int = 2
PRICE_HIKE_CONFIRMED_CYCLES: int = 2

# ============================================================================
# Narration Cleaning & Banking Mandate Keywords
# ============================================================================
MANDATE_KEYWORDS: Tuple[str, ...] = (
    "SI",
    "STANDING INSTRUCTION",
    "ACH",
    "NACH",
    "AUTOPAY",
    "AUTO-DEBIT",
    "MANDATE",
    "E-MANDATE",
    "ENACH",
    "ECS",
    "P2M",
    "RECURRING",
)

UPI_DOMAINS: Tuple[str, ...] = (
    "@hdfcbank",
    "@icici",
    "@oksbi",
    "@okaxis",
    "@okicici",
    "@paytm",
    "@ybl",
    "@ibl",
    "@axl",
    "@apl",
    "@barodampay",
    "@kotak",
    "@upi",
)

# Categories
CATEGORY_STREAMING: str = "Streaming & Media"
CATEGORY_SOFTWARE: str = "Software & Cloud"
CATEGORY_DELIVERY: str = "Delivery & Food"
CATEGORY_HEALTH: str = "Health & Fitness"
CATEGORY_TELECOM: str = "Telecom & Broadband"
CATEGORY_UTILITIES: str = "Utilities & Bills"
CATEGORY_RETAIL: str = "Discretionary Retail & Dining"
CATEGORY_OTHER: str = "Other Recurring"
