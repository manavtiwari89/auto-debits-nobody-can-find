"""Financial Insights, Recurring Burn, and Potential Savings Simulator.

Stage 7 of The Auto Debits Nobody Can Find pipeline.

Calculates:
1. Actual recurring spend from observed transactions, separated from estimated monthly
   and annual forward commitment run-rates.
2. Monthly and category-level breakdowns using existing recurring series and merchant metadata.
3. Review-candidate savings estimates, strictly labeled as potential savings rather than
   guaranteed savings (without labeling payments as 'forgotten' or claiming unconditional cancellation).
4. Deterministic and explainable handling for weekly, monthly, quarterly, and annual cadences,
   missing or insufficient history, paused/resumed series, and variable utility bills.
5. Strict exclusion of duplicates, refunds, reversals, invalid rows, and uncertain debits
   to avoid double-counting or treating unconfirmed debits as spend.
"""

from __future__ import annotations
from datetime import date
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Any, Set

from src.models import (
    CleanedTransaction,
    RecurringSeries,
    CadenceType,
    ConfidenceLevel,
    RowStatus,
    InsightsSummary,
    SavingsCandidate,
    SavingsSimulationResult,
    SeriesFinancialDetail,
    MonthlyBreakdownItem,
)
from src.config import (
    CATEGORY_STREAMING,
    CATEGORY_SOFTWARE,
    CATEGORY_DELIVERY,
    CATEGORY_HEALTH,
    CATEGORY_TELECOM,
    CATEGORY_UTILITIES,
    CATEGORY_OTHER,
)

# Standardized transparent disclaimer for potential savings
POTENTIAL_SAVINGS_DISCLAIMER: str = (
    "Savings estimates represent potential savings and recurring cost reductions if services are discontinued. "
    "These are not guaranteed savings. We do not assume payments are unintended, unneeded, or eligible "
    "for cancellation without penalty. Review contractual terms, active billing cycles, and bank e-mandates "
    "before discontinuing services."
)


class CostEstimator:
    """Computes aggregate recurring costs, observed burn rates, timelines, and category distributions."""

    @classmethod
    def get_transaction_dedup_key(cls, t: CleanedTransaction) -> Tuple[Any, ...]:
        """
        Generates a stable, deterministic deduplication key based strictly on transaction fields.
        Does NOT rely on Python object identity (id(t)).

        Logic:
        1. When reference_id is present and non-empty (ignoring dummy markers like 'NA', 'None', '-'),
           returns ('ref', cleaned_reference_id).
        2. When reference_id is missing or empty, returns a documented combination:
           ('fields', date, amount, direction, normalized_narration, balance, source_bank).
           This ensures separate Python objects representing the same underlying debit are deduplicated,
           while legitimate separate transactions with different references or narrations are preserved.
        """
        ref = (t.reference_id or "").strip()
        if ref and ref.upper() not in {"", "NA", "N/A", "NONE", "NULL", "0", "-"}:
            return ("ref", ref.upper())

        norm_narration = (t.cleaned_narration or t.narration or "").strip().upper()
        norm_bank = (t.source_bank or "").strip().upper()
        norm_balance = round(t.balance, 2) if t.balance is not None else None
        return (
            "fields",
            t.date,
            round(t.amount, 2),
            t.is_debit,
            norm_narration,
            norm_balance,
            norm_bank,
        )

    @classmethod
    def calculate_run_rate(cls, cadence: CadenceType, amount: float) -> Tuple[float, float]:
        """
        Normalizes any cadence amount into monthly and annual forward commitment equivalents.
        Returns (monthly_equivalent, annual_equivalent) rounded to 2 decimal places.
        """
        if amount < 0:
            amount = abs(amount)

        if cadence == CadenceType.WEEKLY:
            monthly = amount * (52.0 / 12.0)
            annual = amount * 52.0
        elif cadence == CadenceType.BIWEEKLY:
            monthly = amount * (26.0 / 12.0)
            annual = amount * 26.0
        elif cadence == CadenceType.MONTHLY:
            monthly = amount
            annual = amount * 12.0
        elif cadence == CadenceType.QUARTERLY:
            monthly = amount / 3.0
            annual = amount * 4.0
        elif cadence == CadenceType.SEMI_ANNUAL:
            monthly = amount / 6.0
            annual = amount * 2.0
        elif cadence == CadenceType.ANNUAL:
            monthly = amount / 12.0
            annual = amount
        else:
            monthly = amount
            annual = amount * 12.0
        return round(monthly, 2), round(annual, 2)

    @classmethod
    def calculate_summary(
        cls,
        series_list: List[RecurringSeries],
        min_confidence: ConfidenceLevel = ConfidenceLevel.LOW,
        statement_start_date: Optional[date] = None,
        statement_end_date: Optional[date] = None,
        statement_months: Optional[float] = None,
        statement_period_months: Optional[float] = None,
    ) -> InsightsSummary:
        """
        Calculates aggregate recurring cost summary for recurring series meeting minimum confidence.

        Separates:
        - Actual recurring spend from observed historical transactions (observed cash outflow).
        - Forward projected monthly and annual commitment run-rates based on cadence & latest price.

        Parameters:
            series_list: List of detected RecurringSeries objects.
            min_confidence: Minimum confidence tier to include (HIGH, MEDIUM, or LOW).
            statement_start_date: Optional full statement start date.
            statement_end_date: Optional full statement end date.
            statement_months: Optional explicit statement duration in months.
            statement_period_months: Optional explicit statement duration in months (alias for statement_months).

        When explicit start/end dates or months are provided, monthly_actual_burn is calculated
        over that confirmed statement period. If unavailable, the period is automatically inferred
        from detected recurring transactions as a documented fallback (flagged via is_period_inferred=True).
        """
        confidence_weights = {
            ConfidenceLevel.HIGH: 3,
            ConfidenceLevel.MEDIUM: 2,
            ConfidenceLevel.LOW: 1,
        }
        min_weight = confidence_weights.get(min_confidence, 1)

        filtered = [
            s for s in series_list
            if confidence_weights.get(s.confidence_level, 1) >= min_weight
        ]

        if not filtered:
            return InsightsSummary(
                monthly_actual_burn=0.0,
                monthly_projected_commitment=0.0,
                annual_projected_commitment=0.0,
                detected_series_count=0,
                price_alerts_count=0,
                category_totals={},
                merchant_annual_burn={},
                review_candidates=[],
                total_review_annual_savings=0.0,
                total_actual_spend=0.0,
                total_review_monthly_savings=0.0,
                category_annual_commitments={},
                category_actual_spend={},
                monthly_breakdown={},
                observed_period_months=0.0,
                observed_start_date=statement_start_date,
                observed_end_date=statement_end_date,
                savings_disclaimer=POTENTIAL_SAVINGS_DISCLAIMER,
                is_period_inferred=(statement_start_date is None or statement_end_date is None),
                period_notes="No active recurring series met the confidence criteria.",
            )

        # 1. Forward Projected Commitments
        total_monthly_commitment = 0.0
        total_annual_commitment = 0.0
        category_monthly: Dict[str, float] = defaultdict(float)
        category_annual: Dict[str, float] = defaultdict(float)
        merchant_annual: Dict[str, float] = {}
        price_alerts_count = 0

        for s in filtered:
            if s.monthly_equivalent > 0 and s.annual_equivalent > 0:
                m_eq = s.monthly_equivalent
                a_eq = s.annual_equivalent
            else:
                m_eq, a_eq = cls.calculate_run_rate(s.cadence, s.latest_amount)

            total_monthly_commitment += m_eq
            total_annual_commitment += a_eq
            category_monthly[s.category] += m_eq
            category_annual[s.category] += a_eq
            merchant_annual[s.merchant_name] = round(a_eq, 2)

            if s.price_alert:
                price_alerts_count += 1

        # 2. Observed Actual Historical Spend (Stable Field-Based Deduplication)
        seen_keys: Set[Tuple[Any, ...]] = set()
        category_actual: Dict[str, float] = defaultdict(float)
        total_actual_spend = 0.0
        all_valid_dates: List[date] = []

        for s in filtered:
            series_actual = 0.0
            for t in s.transactions:
                # Exclude refunds, reversals, duplicates, invalid rows, and uncertain debits
                if t.row_status == RowStatus.VALID and t.is_debit is True:
                    dedup_key = cls.get_transaction_dedup_key(t)
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        series_actual += t.amount
                        all_valid_dates.append(t.date)
            total_actual_spend += series_actual
            category_actual[s.category] += series_actual

        # 3. Statement Period Resolution (Explicit vs Inferred Fallback)
        effective_explicit_months = (
            statement_period_months if statement_period_months is not None else statement_months
        )
        is_period_inferred: bool = True
        period_start_date: Optional[date] = None
        period_end_date: Optional[date] = None
        period_months: float = 0.0
        period_notes: str = ""

        if statement_start_date is not None and statement_end_date is not None:
            # Full statement period provided explicitly via start and end dates
            start_d = min(statement_start_date, statement_end_date)
            end_d = max(statement_start_date, statement_end_date)
            period_start_date = start_d
            period_end_date = end_d
            is_period_inferred = False

            if effective_explicit_months is not None and effective_explicit_months > 0:
                period_months = float(effective_explicit_months)
            else:
                cal_months = (end_d.year - start_d.year) * 12 + (end_d.month - start_d.month) + 1
                period_months = float(max(1, cal_months))

            period_notes = (
                f"Calculated over explicit statement period ({period_start_date.isoformat()} "
                f"to {period_end_date.isoformat()}, {period_months:.1f} month(s))."
            )
        elif effective_explicit_months is not None and effective_explicit_months > 0:
            # Statement duration provided explicitly in months without exact boundary dates
            period_months = float(effective_explicit_months)
            is_period_inferred = False
            period_start_date = min(all_valid_dates) if all_valid_dates else None
            period_end_date = max(all_valid_dates) if all_valid_dates else None
            period_notes = f"Calculated over explicit statement duration ({period_months:.1f} month(s))."
        else:
            # Fallback: Infer period from detected recurring transactions
            is_period_inferred = True
            if all_valid_dates:
                period_start_date = min(all_valid_dates)
                period_end_date = max(all_valid_dates)
                cal_months = (
                    (period_end_date.year - period_start_date.year) * 12
                    + (period_end_date.month - period_start_date.month)
                    + 1
                )
                period_months = float(max(1, cal_months))
                period_notes = (
                    f"Inferred fallback period from recurring transactions ({period_start_date.isoformat()} "
                    f"to {period_end_date.isoformat()}, {period_months:.0f} month(s)). "
                    "Full statement period was not provided; actual burn may differ if statement spans a wider date range."
                )
            else:
                period_start_date = None
                period_end_date = None
                period_months = 0.0
                period_notes = "No recurring transactions available; period could not be determined."

        monthly_actual_burn = (
            round(total_actual_spend / period_months, 2)
            if period_months > 0
            else 0.0
        )

        # 4. Monthly Timeline Breakdown (Consistent Field-Based Deduplication)
        monthly_timeline = cls.calculate_monthly_timeline(
            filtered,
            start_date=period_start_date,
            end_date=period_end_date,
        )

        # 5. Review Candidates & Potential Savings
        review_candidates = SavingsSimulator.identify_review_candidates(filtered)
        total_review_annual_savings = sum(s.annual_equivalent for s in review_candidates)
        total_review_monthly_savings = sum(s.monthly_equivalent for s in review_candidates)

        return InsightsSummary(
            monthly_actual_burn=monthly_actual_burn,
            monthly_projected_commitment=round(total_monthly_commitment, 2),
            annual_projected_commitment=round(total_annual_commitment, 2),
            detected_series_count=len(filtered),
            price_alerts_count=price_alerts_count,
            category_totals={k: round(v, 2) for k, v in category_monthly.items()},
            merchant_annual_burn=merchant_annual,
            review_candidates=review_candidates,
            total_review_annual_savings=round(total_review_annual_savings, 2),
            total_actual_spend=round(total_actual_spend, 2),
            total_review_monthly_savings=round(total_review_monthly_savings, 2),
            category_annual_commitments={k: round(v, 2) for k, v in category_annual.items()},
            category_actual_spend={k: round(v, 2) for k, v in category_actual.items()},
            monthly_breakdown=monthly_timeline,
            observed_period_months=period_months,
            observed_start_date=period_start_date,
            observed_end_date=period_end_date,
            savings_disclaimer=POTENTIAL_SAVINGS_DISCLAIMER,
            is_period_inferred=is_period_inferred,
            period_notes=period_notes,
        )

    @classmethod
    def calculate_monthly_timeline(
        cls,
        series_list: List[RecurringSeries],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Groups valid debit transactions into calendar month buckets ('YYYY-MM').
        Applies stable field-based transaction deduplication.
        If start_date and end_date are provided, all intervening calendar months are represented.
        Returns mapping: 'YYYY-MM' -> {total_spend, transaction_count, by_category, by_merchant}.
        """
        monthly_data: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "total_spend": 0.0,
                "transaction_count": 0,
                "by_category": defaultdict(float),
                "by_merchant": defaultdict(float),
            }
        )

        # Pre-seed calendar months if start and end dates are specified
        if start_date and end_date:
            cur_y, cur_m = start_date.year, start_date.month
            end_y, end_m = end_date.year, end_date.month
            while (cur_y, cur_m) <= (end_y, end_m):
                ym = f"{cur_y:04d}-{cur_m:02d}"
                # Touch key to instantiate entry
                _ = monthly_data[ym]
                if cur_m == 12:
                    cur_y += 1
                    cur_m = 1
                else:
                    cur_m += 1

        seen_keys: Set[Tuple[Any, ...]] = set()

        for s in series_list:
            for t in s.transactions:
                if t.row_status == RowStatus.VALID and t.is_debit is True:
                    dedup_key = cls.get_transaction_dedup_key(t)
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        ym = t.date.strftime("%Y-%m")
                        entry = monthly_data[ym]
                        entry["total_spend"] += t.amount
                        entry["transaction_count"] += 1
                        entry["by_category"][s.category] += t.amount
                        entry["by_merchant"][s.merchant_name] += t.amount

        # Normalize floats and sort months chronologically
        timeline: Dict[str, Dict[str, Any]] = {}
        for ym in sorted(monthly_data.keys()):
            entry = monthly_data[ym]
            timeline[ym] = {
                "year_month": ym,
                "total_spend": round(entry["total_spend"], 2),
                "transaction_count": entry["transaction_count"],
                "by_category": {k: round(v, 2) for k, v in entry["by_category"].items()},
                "by_merchant": {k: round(v, 2) for k, v in entry["by_merchant"].items()},
            }
        return timeline

    @classmethod
    def calculate_series_details(
        cls,
        series_list: List[RecurringSeries],
        observed_months: float = 0.0,
    ) -> List[SeriesFinancialDetail]:
        """
        Computes granular per-series metrics including cycle statistics, min/max amounts,
        variable-bill flags, paused/resumed flags, and transparent evidence summaries.
        Applies stable field-based deduplication to each series' transactions.
        """
        details: List[SeriesFinancialDetail] = []

        for s in series_list:
            seen_series_keys: Set[Tuple[Any, ...]] = set()
            valid_txns = []
            for t in s.transactions:
                if t.row_status == RowStatus.VALID and t.is_debit is True:
                    k = cls.get_transaction_dedup_key(t)
                    if k not in seen_series_keys:
                        seen_series_keys.add(k)
                        valid_txns.append(t)

            cycle_count = len(valid_txns)
            total_spend = sum(t.amount for t in valid_txns)
            amounts = [t.amount for t in valid_txns] if valid_txns else [s.latest_amount]

            min_amt = min(amounts)
            max_amt = max(amounts)
            avg_amt = (total_spend / cycle_count) if cycle_count > 0 else s.latest_amount

            # Build explainable evidence summary
            evidence_parts: List[str] = [
                f"{s.cadence.value} cadence ({cycle_count} observed cycles, ₹{total_spend:,.2f} total spend)."
            ]
            if s.is_variable_bill:
                evidence_parts.append(
                    f"Variable bill: monthly amounts range from ₹{min_amt:,.2f} to ₹{max_amt:,.2f} (mean ₹{avg_amt:,.2f})."
                )
            if s.is_paused_resumed:
                evidence_parts.append("Paused/resumed gap tolerated in interval history.")
            if s.price_alert:
                evidence_parts.append(
                    f"Price increased from ₹{s.price_alert.old_amount:,.2f} to ₹{s.price_alert.new_amount:,.2f} "
                    f"({s.price_alert.formatted_difference})."
                )

            detail = SeriesFinancialDetail(
                merchant_name=s.merchant_name,
                category=s.category,
                cadence=s.cadence,
                latest_amount=s.latest_amount,
                monthly_commitment=s.monthly_equivalent,
                annual_commitment=s.annual_equivalent,
                actual_total_spend=round(total_spend, 2),
                observed_cycles=cycle_count,
                average_cycle_amount=round(avg_amt, 2),
                min_cycle_amount=round(min_amt, 2),
                max_cycle_amount=round(max_amt, 2),
                is_variable_bill=s.is_variable_bill,
                is_paused_resumed=s.is_paused_resumed,
                is_review_candidate=s.is_review_candidate,
                review_reasons=list(s.review_reasons),
                has_price_hike=(s.price_alert is not None),
                price_hike_difference=s.price_alert.formatted_difference if s.price_alert else None,
                evidence_summary=" ".join(evidence_parts),
            )
            details.append(detail)

        return details


class SavingsSimulator:
    """
    Identifies review candidates and simulates potential recurring cost savings.
    Strictly avoids labeling debits as 'forgotten' or claiming guaranteed cancellations.
    """

    @classmethod
    def identify_review_candidates(
        cls,
        series_list: List[RecurringSeries],
        include_price_hikes: bool = True,
    ) -> List[RecurringSeries]:
        """
        Identifies recurring series that are candidates for user review.

        Inclusion criteria:
        1. Explicitly flagged as review candidate by detector (Annual commitment, low confidence, paused/resumed).
        2. Recent verified price hike detected (if include_price_hikes=True).
        3. Excludes variable utility bills (e.g. BESCOM electricity) from discretionary review.
        """
        candidates: List[RecurringSeries] = []

        for s in series_list:
            reasons = list(s.review_reasons)
            is_candidate = s.is_review_candidate

            # If recent price hike detected, flag as review candidate with hike evidence
            if include_price_hikes and s.price_alert is not None:
                hike_reason = (
                    f"Recent price increase detected ({s.price_alert.formatted_difference}): "
                    f"review if plan still offers sufficient value."
                )
                if hike_reason not in reasons:
                    reasons.append(hike_reason)
                is_candidate = True

            # If paused/resumed pattern detected, ensure reason is present
            if s.is_paused_resumed:
                pause_reason = "Paused/resumed pattern detected: check if still desired."
                if pause_reason not in reasons:
                    reasons.append(pause_reason)
                is_candidate = True

            # If annual commitment, ensure reason is present
            if s.cadence == CadenceType.ANNUAL:
                annual_reason = "Annual commitment: high-impact renewal candidate."
                if annual_reason not in reasons:
                    reasons.append(annual_reason)
                is_candidate = True

            # Variable utility bills are essential household services; avoid adding them as review candidates
            if s.is_variable_bill and not s.is_paused_resumed and not (s.cadence == CadenceType.ANNUAL):
                continue

            if is_candidate:
                # Update series review reasons without mutating caller's original list in unexpected ways
                s.is_review_candidate = True
                s.review_reasons = reasons
                candidates.append(s)

        return candidates

    @classmethod
    def build_candidate_details(
        cls, candidates: List[RecurringSeries]
    ) -> List[SavingsCandidate]:
        """Converts RecurringSeries objects to transparent SavingsCandidate records."""
        records: List[SavingsCandidate] = []
        for s in candidates:
            evidence_desc = (
                f"{s.cadence.value} payment of ₹{s.latest_amount:,.2f} "
                f"(₹{s.monthly_equivalent:,.2f}/mo, ₹{s.annual_equivalent:,.2f}/yr). "
                f"Reasons for review: {'; '.join(s.review_reasons) if s.review_reasons else 'General discretionary review'}."
            )
            record = SavingsCandidate(
                merchant_name=s.merchant_name,
                category=s.category,
                cadence=s.cadence,
                latest_amount=s.latest_amount,
                monthly_potential_savings=s.monthly_equivalent,
                annual_potential_savings=s.annual_equivalent,
                review_reasons=list(s.review_reasons),
                evidence=evidence_desc,
                disclaimer=POTENTIAL_SAVINGS_DISCLAIMER,
            )
            records.append(record)
        return records

    @classmethod
    def simulate_savings(
        cls,
        series_list: List[RecurringSeries],
        selected_merchants: Optional[List[str]] = None,
    ) -> SavingsSimulationResult:
        """
        Simulates potential monthly and annual cost savings if selected candidate merchants
        are discontinued by the user.

        If selected_merchants is None, defaults to all identified review candidates.
        Clearly labels all savings as potential, explainable reductions.
        """
        all_candidates = cls.identify_review_candidates(series_list)

        if selected_merchants is None:
            # Default to all review candidates
            target_series = all_candidates
            selected_names = [s.merchant_name for s in target_series]
        else:
            # Filter series matching selected merchant names (case-insensitive)
            normalized_selected = {m.strip().lower() for m in selected_merchants}
            target_series = [
                s for s in series_list
                if s.merchant_name.strip().lower() in normalized_selected
            ]
            selected_names = [s.merchant_name for s in target_series]

        # Calculate potential savings
        potential_monthly = sum(s.monthly_equivalent for s in target_series)
        potential_annual = sum(s.annual_equivalent for s in target_series)

        total_monthly = sum(s.monthly_equivalent for s in series_list)
        total_annual = sum(s.annual_equivalent for s in series_list)

        remaining_monthly = max(0.0, total_monthly - potential_monthly)
        remaining_annual = max(0.0, total_annual - potential_annual)

        # Category distribution of potential savings
        savings_by_category: Dict[str, float] = defaultdict(float)
        for s in target_series:
            savings_by_category[s.category] += s.annual_equivalent

        candidate_records = cls.build_candidate_details(target_series)

        return SavingsSimulationResult(
            selected_merchants=selected_names,
            potential_monthly_savings=round(potential_monthly, 2),
            potential_annual_savings=round(potential_annual, 2),
            remaining_monthly_commitment=round(remaining_monthly, 2),
            remaining_annual_commitment=round(remaining_annual, 2),
            retained_series_count=len(series_list) - len(target_series),
            discontinued_series_count=len(target_series),
            savings_by_category={k: round(v, 2) for k, v in savings_by_category.items()},
            candidate_details=candidate_records,
            disclaimer=POTENTIAL_SAVINGS_DISCLAIMER,
        )
