"""Recurring Costs, Totals & Run-rate Estimator.

Calculates normalized monthly and annual expenditure run-rates,
groups by expense categories, and summarizes price alerts.
"""

from __future__ import annotations
from typing import List, Dict
from collections import defaultdict
from app.models import RecurringSeries, CostSummary, ConfidenceLevel


class CostEstimator:
    """Computes aggregate recurring costs, burn rates, and category distributions."""

    @classmethod
    def calculate_summary(
        cls,
        series_list: List[RecurringSeries],
        min_confidence: ConfidenceLevel = ConfidenceLevel.LOW
    ) -> CostSummary:
        """
        Calculates aggregate recurring cost summary for recurring series
        meeting minimum confidence threshold.
        """
        confidence_weights = {
            ConfidenceLevel.HIGH: 3,
            ConfidenceLevel.MEDIUM: 2,
            ConfidenceLevel.LOW: 1,
        }
        min_weight = confidence_weights.get(min_confidence, 1)

        filtered = [
            s for s in series_list
            if confidence_weights.get(s.confidence, 1) >= min_weight
        ]

        total_monthly = 0.0
        total_annual = 0.0
        category_map: Dict[str, float] = defaultdict(float)
        price_hike_count = 0
        high_cnt = 0
        med_cnt = 0
        low_cnt = 0

        for s in filtered:
            total_monthly += s.monthly_equivalent_amount
            total_annual += s.annual_equivalent_amount
            category_map[s.category] += s.monthly_equivalent_amount

            if s.price_alert:
                price_hike_count += 1

            if s.confidence == ConfidenceLevel.HIGH:
                high_cnt += 1
            elif s.confidence == ConfidenceLevel.MEDIUM:
                med_cnt += 1
            else:
                low_cnt += 1

        # Calculate potential annual savings (entertainment + memberships as discretionary)
        discretionary_categories = {
            "Streaming & Entertainment",
            "Delivery & Memberships",
            "News & Subscriptions"
        }
        potential_savings = sum(
            s.annual_equivalent_amount
            for s in filtered
            if s.category in discretionary_categories
        )

        return CostSummary(
            total_monthly_recurring=round(total_monthly, 2),
            total_annual_recurring=round(total_annual, 2),
            active_subscriptions_count=len(filtered),
            category_breakdown={k: round(v, 2) for k, v in category_map.items()},
            price_hike_count=price_hike_count,
            potential_annual_savings=round(potential_savings, 2),
            high_confidence_count=high_cnt,
            medium_confidence_count=med_cnt,
            low_confidence_count=low_cnt
        )
