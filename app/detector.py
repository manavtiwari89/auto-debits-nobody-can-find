"""Cadence & Recurring Payment Detection Engine.

Analyzes transaction clusters to identify recurring payments, determine cadence,
calculate confidence scores, and generate transparent evidence explanations.
"""

from __future__ import annotations
import math
import re
import statistics
from datetime import date
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from app.models import (
    Transaction,
    RecurringSeries,
    CadenceType,
    ConfidenceLevel,
    PriceAlert
)
from app.normalizer import NarrationNormalizer, MERCHANT_KNOWLEDGE_BASE


# Cadence intervals in days (min_mean, max_mean, max_acceptable_std)
CADENCE_RANGES = [
    (CadenceType.WEEKLY, 6.0, 9.0, 2.5),
    (CadenceType.BIWEEKLY, 12.0, 17.0, 3.5),
    (CadenceType.MONTHLY, 26.0, 35.0, 5.0),
    (CadenceType.QUARTERLY, 82.0, 100.0, 9.0),
    (CadenceType.SEMI_ANNUAL, 170.0, 195.0, 12.0),
    (CadenceType.ANNUAL, 350.0, 380.0, 16.0),
]


class RecurringDetector:
    """Detects recurring payment patterns in bank transactions."""

    @classmethod
    def determine_cadence(cls, intervals: List[int]) -> Tuple[CadenceType, float, float]:
        """
        Calculates mean and standard deviation of day intervals and maps to CadenceType.
        Returns (cadence_type, mean_days, std_days).
        """
        if not intervals:
            return CadenceType.IRREGULAR, 0.0, 0.0

        mean_days = statistics.mean(intervals)
        std_days = statistics.stdev(intervals) if len(intervals) > 1 else 0.0

        for cadence, min_m, max_m, max_s in CADENCE_RANGES:
            if min_m <= mean_days <= max_m and std_days <= max_s:
                return cadence, mean_days, std_days

        # Wider tolerance fallback for monthly if intervals mostly 28-31
        if 25.0 <= mean_days <= 36.0 and std_days <= 7.0:
            return CadenceType.MONTHLY, mean_days, std_days

        return CadenceType.IRREGULAR, mean_days, std_days

    @classmethod
    def calculate_monthly_annual_equivalent(
        cls, cadence: CadenceType, amount: float
    ) -> Tuple[float, float]:
        """Normalize any cadence amount into monthly and annual equivalent values."""
        if cadence == CadenceType.WEEKLY:
            monthly = amount * (52 / 12)
            annual = amount * 52
        elif cadence == CadenceType.BIWEEKLY:
            monthly = amount * (26 / 12)
            annual = amount * 26
        elif cadence == CadenceType.MONTHLY:
            monthly = amount
            annual = amount * 12
        elif cadence == CadenceType.QUARTERLY:
            monthly = amount / 3.0
            annual = amount * 4
        elif cadence == CadenceType.SEMI_ANNUAL:
            monthly = amount / 6.0
            annual = amount * 2
        elif cadence == CadenceType.ANNUAL:
            monthly = amount / 12.0
            annual = amount
        else:
            monthly = amount
            annual = amount * 12
        return round(monthly, 2), round(annual, 2)

    @classmethod
    def score_series(
        cls,
        txns: List[Transaction],
        cadence: CadenceType,
        mean_days: float,
        std_days: float,
        is_known_merchant: bool,
        amounts_match: bool,
        has_price_step: bool,
        has_mandate: bool
    ) -> Tuple[ConfidenceLevel, float, List[str]]:
        """
        Calculates confidence score (0.0 to 1.0) and generates transparent evidence reasons.
        """
        count = len(txns)
        evidence: List[str] = []
        score = 0.0

        # 1. Base score by transaction count
        if count >= 4:
            score += 0.45
            evidence.append(f"Strong history: {count} billing cycles detected.")
        elif count == 3:
            score += 0.35
            evidence.append(f"Consistent record: {count} billing cycles detected.")
        elif count == 2:
            score += 0.25
            evidence.append(f"{count} billing cycles observed.")
        else:
            score += 0.10

        # 2. Cadence evidence
        if cadence != CadenceType.IRREGULAR:
            score += 0.25
            evidence.append(
                f"Regular {cadence.value.lower()} schedule (avg interval: {mean_days:.1f} days, std dev: {std_days:.1f} days)."
            )
        else:
            score -= 0.15
            evidence.append(f"Irregular payment intervals (avg: {mean_days:.1f} days).")

        # 3. Mandate keyword evidence
        if has_mandate:
            score += 0.20
            evidence.append("Bank narration contains auto-debit / mandate markers (e.g. SI, ACH, NACH, or Autopay).")

        # 4. Amount consistency or price hike pattern
        if amounts_match:
            score += 0.15
            evidence.append(f"Identical billing amount: ₹{txns[-1].amount:,.2f} across cycles.")
        elif has_price_step:
            score += 0.15
            evidence.append("Identified planned subscription price tier change across recurring cycles.")
        else:
            amt_std = statistics.stdev([t.amount for t in txns]) if len(txns) > 1 else 0.0
            evidence.append(f"Varying debit amounts (std dev: ₹{amt_std:,.2f}).")

        # 5. Known merchant registry
        if is_known_merchant:
            score += 0.10
            evidence.append(f"Matches recognized recurring service provider ({txns[-1].normalized_merchant}).")

        # Clamp score between 0.05 and 0.99
        score = max(0.05, min(0.99, score))

        if score >= 0.70:
            level = ConfidenceLevel.HIGH
        elif score >= 0.45:
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW

        return level, round(score, 2), evidence

    @classmethod
    def detect_recurring(
        cls, transactions: List[Transaction]
    ) -> List[RecurringSeries]:
        """
        Main pipeline to detect recurring payment series from parsed transactions.
        """
        # Ensure transactions are enriched
        enriched_txns: List[Transaction] = []
        for t in transactions:
            if not t.normalized_merchant:
                NarrationNormalizer.enrich_transaction(t)
            enriched_txns.append(t)

        # Filter debits only
        debits = [t for t in enriched_txns if t.is_debit]

        # Group by normalized merchant name
        grouped: Dict[str, List[Transaction]] = defaultdict(list)
        for t in debits:
            key = t.normalized_merchant or t.cleaned_narration or "Unknown"
            grouped[key].append(t)

        recurring_list: List[RecurringSeries] = []

        for merchant_key, group in grouped.items():
            # Sort chronologically
            group.sort(key=lambda x: x.date)

            # Ignore single one-off transactions without any mandate keyword
            if len(group) < 2 and not any(t.has_mandate_indicator for t in group):
                continue

            # Calculate intervals
            intervals: List[int] = []
            for i in range(1, len(group)):
                diff = (group[i].date - group[i - 1].date).days
                intervals.append(diff)

            # Filter out rapid successive transactions that are clearly not recurring subscriptions
            # e.g., food orders on consecutive days (mean interval < 5 days, not weekly)
            if intervals:
                mean_int = statistics.mean(intervals)
                if mean_int < 5.0 and len(group) >= 3 and not any(t.has_mandate_indicator for t in group):
                    # Likely daily coffee, rides, or food orders, not subscriptions
                    continue

            cadence, mean_days, std_days = cls.determine_cadence(intervals)

            # Check amount consistency
            amounts = [t.amount for t in group]
            amounts_match = len(set(amounts)) == 1

            # Check for monotonic or step price change (e.g., 2 transactions at 499, then 2 at 649)
            has_price_step = False
            if not amounts_match and len(amounts) >= 3:
                # If amounts transitioned cleanly from one constant to another
                first_half = amounts[:len(amounts)//2]
                second_half = amounts[len(amounts)//2:]
                if len(set(first_half)) == 1 and len(set(second_half)) == 1 and first_half[0] != second_half[0]:
                    has_price_step = True

            has_mandate = any(t.has_mandate_indicator for t in group)
            is_known = any(
                merchant_key.lower() == info["name"].lower()
                for info in MERCHANT_KNOWLEDGE_BASE.values()
            )

            # False Positive Shield: Reject non-subscription discretionary spends
            # (e.g. coffee, fuel, dining, ride hails) where amounts fluctuate and no mandate is attached
            if not is_known and not has_mandate:
                if not amounts_match and not has_price_step:
                    if len(amounts) > 1:
                        amt_std = statistics.stdev(amounts)
                        amt_mean = statistics.mean(amounts)
                        cv = amt_std / amt_mean if amt_mean > 0 else 0
                        if cv > 0.10:
                            continue
                # Also require valid recognized cadence if no mandate is attached
                if cadence == CadenceType.IRREGULAR:
                    continue

            # Determine category
            category = "General / Other"
            for info in MERCHANT_KNOWLEDGE_BASE.values():
                if info["name"].lower() == merchant_key.lower():
                    category = info["category"]
                    break

            confidence_level, score, evidence = cls.score_series(
                group,
                cadence,
                mean_days,
                std_days,
                is_known,
                amounts_match,
                has_price_step,
                has_mandate
            )

            # Don't include series with very low confidence and irregular cadence unless mandate is present
            if confidence_level == ConfidenceLevel.LOW and cadence == CadenceType.IRREGULAR and not has_mandate:
                continue

            # Expected ongoing amount is latest observed transaction amount
            latest_amt = group[-1].amount
            monthly_eq, annual_eq = cls.calculate_monthly_annual_equivalent(cadence, latest_amt)

            series_id = f"SERIES-{re.sub(r'[^a-zA-Z0-9]', '', merchant_key).upper()}-{cadence.value[:3].upper()}"

            series = RecurringSeries(
                series_id=series_id,
                merchant_name=merchant_key,
                category=category,
                cadence=cadence,
                confidence=confidence_level,
                confidence_score=score,
                transactions=group,
                expected_amount=latest_amt,
                monthly_equivalent_amount=monthly_eq,
                annual_equivalent_amount=annual_eq,
                interval_mean_days=round(mean_days, 1),
                interval_std_days=round(std_days, 1),
                evidence_reasons=evidence
            )
            recurring_list.append(series)

        # Sort by confidence score descending, then monthly equivalent amount descending
        recurring_list.sort(key=lambda s: (-s.confidence_score, -s.monthly_equivalent_amount))
        return recurring_list
