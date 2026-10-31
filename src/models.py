"""Data models for The Auto Debits Nobody Can Find.

Strongly typed dataclasses representing transactions, merchant matches,
evidence, confidence score breakdowns, recurring series, price hike alerts,
financial summaries, and cancellation guidance.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, List, Optional, Any


class CadenceType(str, Enum):
    WEEKLY = "Weekly"
    BIWEEKLY = "Bi-weekly"
    MONTHLY = "Monthly"
    QUARTERLY = "Quarterly"
    SEMI_ANNUAL = "Semi-annual"
    ANNUAL = "Annual"
    IRREGULAR = "Irregular"


class ConfidenceLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class MatchMethod(str, Enum):
    EXACT_ALIAS = "Exact Alias Match"
    RULE_REGEX = "Token & Regex Pattern"
    FUZZY = "Fuzzy String Similarity"
    UNKNOWN = "Unverified Description Cluster"


class RowStatus(str, Enum):
    VALID = "Valid"
    DUPLICATE = "Duplicate Debit"
    REFUND = "Refund / Credit"
    REVERSAL = "Reversal / Chargeback"
    INVALID = "Malformed / Unusable"
    UNCERTAIN = "Uncertain Direction"


class SchemaValidationError(ValueError):
    """Raised when an uploaded bank statement CSV fails schema requirements."""
    def __init__(self, message: str, missing_fields: Optional[List[str]] = None, detected_columns: Optional[List[str]] = None):
        super().__init__(message)
        self.message = message
        self.missing_fields = missing_fields or []
        self.detected_columns = detected_columns or []


@dataclass
class IngestedStatement:
    """Represents a raw parsed bank statement CSV prior to cleaning."""
    bank_name: str
    delimiter: str
    header_row_index: int
    columns: List[str]
    column_mapping: Dict[str, str]
    raw_rows: List[Dict[str, str]]
    metadata_lines: List[str] = field(default_factory=list)
    total_lines: int = 0


@dataclass
class CleaningResult:
    """Encapsulates the output of transaction sanitization and status tagging."""
    transactions: List[CleanedTransaction]
    total_rows: int
    valid_count: int
    duplicate_count: int
    refund_count: int
    reversal_count: int
    invalid_count: int
    uncertain_count: int = 0

    @property
    def valid_debits(self) -> List[CleanedTransaction]:
        return [t for t in self.transactions if t.row_status == RowStatus.VALID and t.is_debit is True]


@dataclass
class CleanedTransaction:
    """Represents an ingested and sanitized bank transaction."""
    date: date
    narration: str
    amount: float
    is_debit: Optional[bool] = None
    reference_id: Optional[str] = None
    balance: Optional[float] = None
    row_status: RowStatus = RowStatus.UNCERTAIN
    refund_linked_id: Optional[str] = None
    cleaned_narration: str = ""
    normalized_merchant: Optional[str] = None
    merchant_match: Optional[MerchantMatch] = None
    has_mandate_indicator: bool = False
    source_bank: Optional[str] = None
    raw_row: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.amount < 0:
            self.amount = abs(self.amount)
        # If direction is unspecified, preserve uncertainty unless row is already flagged invalid
        if self.is_debit is None:
            if self.row_status != RowStatus.INVALID:
                self.row_status = RowStatus.UNCERTAIN
        elif self.row_status == RowStatus.UNCERTAIN and self.is_debit is not None:
            # Caller intentionally specified is_debit (True or False) but omitted row_status
            self.row_status = RowStatus.VALID


@dataclass
class MerchantMatch:
    """Represents the merchant normalization result for a narration."""
    normalized_name: str
    category: str
    is_variable_bill: bool = False
    is_retail: bool = False
    method: MatchMethod = MatchMethod.UNKNOWN
    match_confidence: float = 0.0  # 0.0 to 1.0
    raw_key: str = ""


@dataclass
class ScoreFactor:
    """A single constituent factor of the 0-100 confidence score."""
    name: str
    points_awarded: float
    max_points: float
    rationale: str


@dataclass
class ConfidenceBreakdown:
    """Complete transparent additive score breakdown (0–100)."""
    total_score: float
    level: ConfidenceLevel
    factors: List[ScoreFactor] = field(default_factory=list)
    penalties: List[ScoreFactor] = field(default_factory=list)
    is_capped: bool = False
    cap_reason: Optional[str] = None


@dataclass
class Evidence:
    """Diagnostic evidence explaining why a series was classified as recurring."""
    intervals_days: List[int]
    mean_interval_days: float
    std_interval_days: float
    cv_interval: float
    day_of_month_list: List[int]
    day_of_month_variance: float
    modal_amount: float
    modal_amount_ratio: float
    has_mandate_keywords: bool
    notes: List[str] = field(default_factory=list)
    uncertainty_reasons: List[str] = field(default_factory=list)
    is_paused_resumed: bool = False


@dataclass
class PriceAlert:
    """Alert triggered when a recurring merchant increases price over time."""
    merchant_name: str
    old_amount: float
    new_amount: float
    change_percent: float
    effective_date: date
    is_confirmed: bool  # True if observed >= 2 consecutive billing cycles
    baseline_cycles: int
    persistence_cycles: int
    evidence_note: str

    @property
    def formatted_difference(self) -> str:
        diff = self.new_amount - self.old_amount
        return f"+₹{diff:,.2f} (+{self.change_percent:.1f}%)"


@dataclass
class RecurringSeries:
    """A verified or candidate recurring payment series."""
    merchant_name: str
    category: str
    cadence: CadenceType
    confidence_level: ConfidenceLevel
    confidence_score: float  # 0.0 to 100.0
    confidence_breakdown: ConfidenceBreakdown
    evidence: Evidence
    transactions: List[CleanedTransaction]
    latest_amount: float
    monthly_equivalent: float
    annual_equivalent: float
    price_alert: Optional[PriceAlert] = None
    is_merchant_verified: bool = True
    is_review_candidate: bool = False
    review_reasons: List[str] = field(default_factory=list)
    is_paused_resumed: bool = False
    is_variable_bill: bool = False
    cancellation_details: Optional[CancellationDetails] = None

    @property
    def cycle_count(self) -> int:
        return len(self.transactions)

    @property
    def expected_amount(self) -> float:
        """Alias for latest_amount for compatibility with evaluation and legacy consumers."""
        return self.latest_amount

    @property
    def confidence(self) -> ConfidenceLevel:
        """Alias for confidence_level for compatibility with evaluation and legacy consumers."""
        return self.confidence_level

    @property
    def first_date(self) -> date:
        return self.transactions[0].date if self.transactions else date.today()

    @property
    def latest_date(self) -> date:
        return self.transactions[-1].date if self.transactions else date.today()


@dataclass
class RejectionRecord:
    """Audit record for a merchant group that was rejected from recurring status."""
    group_key: str
    merchant_name: str
    transaction_count: int
    total_spend: float
    rejection_reasons: List[str]
    sample_narrations: List[str]
    mean_interval_days: Optional[float] = None
    interval_cv: Optional[float] = None


@dataclass
class InsightsSummary:
    """Aggregated financial metrics, actual spend, projected burn, and review savings."""
    monthly_actual_burn: float
    monthly_projected_commitment: float
    annual_projected_commitment: float
    detected_series_count: int
    price_alerts_count: int
    category_totals: Dict[str, float]
    merchant_annual_burn: Dict[str, float]
    review_candidates: List[RecurringSeries]
    total_review_annual_savings: float
    total_actual_spend: float = 0.0
    total_review_monthly_savings: float = 0.0
    category_annual_commitments: Dict[str, float] = field(default_factory=dict)
    category_actual_spend: Dict[str, float] = field(default_factory=dict)
    monthly_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    observed_period_months: float = 0.0
    observed_start_date: Optional[date] = None
    observed_end_date: Optional[date] = None
    savings_disclaimer: str = ""
    is_period_inferred: bool = True
    period_notes: str = ""


@dataclass
class SavingsCandidate:
    """A recurring series flagged for review with potential savings metrics."""
    merchant_name: str
    category: str
    cadence: CadenceType
    latest_amount: float
    monthly_potential_savings: float
    annual_potential_savings: float
    review_reasons: List[str] = field(default_factory=list)
    evidence: str = ""
    disclaimer: str = ""


@dataclass
class SavingsSimulationResult:
    """Result of simulating potential savings by discontinuing selected review candidates."""
    selected_merchants: List[str]
    potential_monthly_savings: float
    potential_annual_savings: float
    remaining_monthly_commitment: float
    remaining_annual_commitment: float
    retained_series_count: int
    discontinued_series_count: int
    savings_by_category: Dict[str, float] = field(default_factory=dict)
    candidate_details: List[SavingsCandidate] = field(default_factory=list)
    disclaimer: str = ""


@dataclass
class SeriesFinancialDetail:
    """Comprehensive financial metrics for a single recurring series."""
    merchant_name: str
    category: str
    cadence: CadenceType
    latest_amount: float
    monthly_commitment: float
    annual_commitment: float
    actual_total_spend: float
    observed_cycles: int
    average_cycle_amount: float
    min_cycle_amount: float
    max_cycle_amount: float
    is_variable_bill: bool
    is_paused_resumed: bool
    is_review_candidate: bool
    review_reasons: List[str] = field(default_factory=list)
    has_price_hike: bool = False
    price_hike_difference: Optional[str] = None
    evidence_summary: str = ""


@dataclass
class MonthlyBreakdownItem:
    """Monthly spend breakdown item for a calendar month."""
    year_month: str
    actual_spend: float
    transaction_count: int
    by_category: Dict[str, float] = field(default_factory=dict)
    by_merchant: Dict[str, float] = field(default_factory=dict)


@dataclass
class CancellationDetails:
    """Verified cancellation steps and UPI AutoPay revocation intelligence."""
    merchant_name: str
    category: str
    settings_location: str
    steps: List[str]
    source_url: str = ""
    last_verified: str = "Unverified"
    mandate_guidance: List[str] = field(default_factory=list)
    is_verified: bool = False
