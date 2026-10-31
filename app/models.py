"""Data models for The Auto Debits Nobody Can Find."""

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


@dataclass
class Transaction:
    """Represents a single parsed transaction from a bank statement."""
    date: date
    narration: str
    amount: float
    is_debit: bool = True
    reference_id: Optional[str] = None
    balance: Optional[float] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    cleaned_narration: Optional[str] = None
    normalized_merchant: Optional[str] = None
    has_mandate_indicator: bool = False
    source_bank: Optional[str] = None

    def __post_init__(self):
        if self.amount < 0:
            self.amount = abs(self.amount)


@dataclass
class PriceAlert:
    """Alert triggered when a recurring merchant increases price over time."""
    merchant_name: str
    old_amount: float
    new_amount: float
    percent_change: float
    effective_date: date
    details: str

    @property
    def formatted_difference(self) -> str:
        diff = self.new_amount - self.old_amount
        return f"+₹{diff:,.2f} ({self.percent_change:+.1f}%)"


@dataclass
class CancellationGuide:
    """Verifiable cancellation pathway for a subscription or mandate."""
    merchant_name: str
    portal_name: str
    direct_url: Optional[str]
    is_verified_source: bool
    source_domain: Optional[str]
    last_verified: str
    steps: List[str]
    npci_autopay_revocable: bool = True
    guidance_source_explanation: str = ""


@dataclass
class RecurringSeries:
    """A detected series of recurring payments for a specific merchant."""
    series_id: str
    merchant_name: str
    category: str
    cadence: CadenceType
    confidence: ConfidenceLevel
    confidence_score: float
    transactions: List[Transaction]
    expected_amount: float
    monthly_equivalent_amount: float
    annual_equivalent_amount: float
    interval_mean_days: float
    interval_std_days: float
    evidence_reasons: List[str]
    price_alert: Optional[PriceAlert] = None
    cancellation_info: Optional[CancellationGuide] = None

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)

    @property
    def first_date(self) -> Optional[date]:
        return self.transactions[0].date if self.transactions else None

    @property
    def latest_date(self) -> Optional[date]:
        return self.transactions[-1].date if self.transactions else None


@dataclass
class CostSummary:
    """Aggregate recurring costs and run-rate projections."""
    total_monthly_recurring: float
    total_annual_recurring: float
    active_subscriptions_count: int
    category_breakdown: Dict[str, float]
    price_hike_count: int
    potential_annual_savings: float
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
