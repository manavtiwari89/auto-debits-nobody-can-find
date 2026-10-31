"""Cadence Clustering & Recurring Payment Detection Engine.

Analyzes cleaned, enriched debit transactions to identify recurring payment series,
determine cadences (with paused/resumed gap tolerance), compute transparent additive
0-100 confidence breakdowns, and produce structured rejection records for ordinary repeats.
"""

from __future__ import annotations
import math
import re
import statistics
from datetime import date
from collections import defaultdict, Counter
from typing import List, Dict, Tuple, Optional, Any

from src.models import (
    CleanedTransaction,
    RecurringSeries,
    RejectionRecord,
    CadenceType,
    ConfidenceLevel,
    ConfidenceBreakdown,
    ScoreFactor,
    Evidence,
    RowStatus,
    MatchMethod
)
from src.config import (
    CADENCE_SPECS,
    MAX_REGULAR_CV,
    LOOSE_REGULAR_CV,
    MIN_OCCURRENCES_WEEKLY_MONTHLY,
    MIN_OCCURRENCES_QUARTERLY_ANNUAL_KNOWN,
    DAY_OF_MONTH_TOLERANCE_DAYS,
    AMOUNT_MODAL_RATIO_THRESHOLD,
    AMOUNT_VARIANCE_TOLERANCE_PERCENT,
    WEIGHT_OCCURRENCES_MAX,
    WEIGHT_INTERVAL_REGULARITY_MAX,
    WEIGHT_AMOUNT_STABILITY_MAX,
    WEIGHT_MERCHANT_QUALITY_MAX,
    WEIGHT_DAY_OF_MONTH_MAX,
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    PENALTY_UNKNOWN_MERCHANT,
    PENALTY_FEW_OBSERVATIONS,
    PENALTY_RETAIL_CATEGORY,
    PENALTY_GAP_PAUSED,
    UNKNOWN_MERCHANT_MAX_CONFIDENCE_LEVEL,
    CATEGORY_RETAIL,
    MANDATE_KEYWORDS
)
from src.merchants import MerchantMatcher


class RecurringDetector:
    """Detects recurring payments from cleaned bank transactions."""

    @classmethod
    def calculate_run_rate_equivalents(
        cls, cadence: CadenceType, amount: float
    ) -> Tuple[float, float]:
        """Normalizes any cadence amount into monthly and annual equivalent values."""
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
    def determine_cadence_with_gap_tolerance(
        cls,
        intervals: List[int],
        is_known_merchant: bool = False
    ) -> Tuple[CadenceType, float, float, float, bool, List[str]]:
        """
        Calculates cadence with tolerance for paused/resumed subscriptions (e.g. Cult.fit).
        Returns (cadence_type, mean_days, std_days, cv, is_paused_resumed, notes).
        """
        if not intervals:
            return CadenceType.IRREGULAR, 0.0, 0.0, 0.0, False, ["Single transaction; no interval available."]

        raw_mean = statistics.mean(intervals)
        raw_std = statistics.stdev(intervals) if len(intervals) > 1 else 0.0
        raw_cv = raw_std / raw_mean if raw_mean > 0 else 0.0
        notes: List[str] = []

        # --------------------------------------------------------------------
        # Direct Match Against Cadence Specs
        # --------------------------------------------------------------------
        for cadence_name, (nominal, min_d, max_d, max_std) in CADENCE_SPECS.items():
            if min_d <= raw_mean <= max_d and raw_std <= max_std:
                cad_type = cls._name_to_cadence(cadence_name)
                notes.append(f"Direct match for {cad_type.value} schedule (mean: {raw_mean:.1f}d, std: {raw_std:.1f}d).")
                return cad_type, round(raw_mean, 1), round(raw_std, 1), round(raw_cv, 2), False, notes

        # Wider tolerance fallback for standard monthly debits (e.g. 26-35 days with holiday jitter)
        if 25.0 <= raw_mean <= 36.0 and raw_std <= 7.0:
            notes.append(f"Monthly cadence matched with calendar jitter tolerance (mean: {raw_mean:.1f}d, std: {raw_std:.1f}d).")
            return CadenceType.MONTHLY, round(raw_mean, 1), round(raw_std, 1), round(raw_cv, 2), False, notes

        # --------------------------------------------------------------------
        # Gap-Tolerant Paused / Resumed Analysis (Cult.fit Pattern)
        # --------------------------------------------------------------------
        # If the majority of intervals are monthly (25-35 days), but 1 or 2 intervals
        # represent an integer multiple (k * ~30 days, e.g. 55-65d or 85-95d)
        monthly_intervals = [i for i in intervals if 25 <= i <= 36]
        gap_intervals = [i for i in intervals if i > 36]

        if len(monthly_intervals) >= 2 and len(gap_intervals) >= 1:
            # Check if all gap intervals are roughly integer multiples of monthly base (~30 days)
            multiples_match = True
            gap_notes: List[str] = []
            for g in gap_intervals:
                k = round(g / 30.0)
                if k >= 2 and abs(g - (k * 30.0)) <= (k * 5.0):
                    gap_notes.append(f"Observed {g}-day gap (~{k} monthly billing cycles paused).")
                else:
                    multiples_match = False
                    break

            if multiples_match and (len(monthly_intervals) / len(intervals)) >= 0.50:
                active_mean = statistics.mean(monthly_intervals)
                active_std = statistics.stdev(monthly_intervals) if len(monthly_intervals) > 1 else 0.0
                active_cv = active_std / active_mean if active_mean > 0 else 0.0

                notes.append(
                    f"Subscription was paused/resumed: {len(monthly_intervals)} monthly cycles active, "
                    f"{len(gap_intervals)} pause gaps detected ({', '.join(gap_notes)})."
                )
                return CadenceType.MONTHLY, round(active_mean, 1), round(active_std, 1), round(active_cv, 2), True, notes

        # --------------------------------------------------------------------
        # Quarterly with pause / bi-quarterly gap
        # --------------------------------------------------------------------
        quarterly_intervals = [i for i in intervals if 80 <= i <= 102]
        if len(quarterly_intervals) >= 2 and (len(quarterly_intervals) / len(intervals)) >= 0.60:
            q_mean = statistics.mean(quarterly_intervals)
            q_std = statistics.stdev(quarterly_intervals) if len(quarterly_intervals) > 1 else 0.0
            q_cv = q_std / q_mean if q_mean > 0 else 0.0
            notes.append("Quarterly cadence matched with gap filtering.")
            return CadenceType.QUARTERLY, round(q_mean, 1), round(q_std, 1), round(q_cv, 2), True, notes

        # Fallback to Irregular
        notes.append(f"Intervals did not conform to regular recurring cadences (mean: {raw_mean:.1f}d, std: {raw_std:.1f}d, CV: {raw_cv:.2f}).")
        return CadenceType.IRREGULAR, round(raw_mean, 1), round(raw_std, 1), round(raw_cv, 2), False, notes

    @classmethod
    def _name_to_cadence(cls, name: str) -> CadenceType:
        name_lower = name.lower()
        if "week" in name_lower and "bi" not in name_lower:
            return CadenceType.WEEKLY
        if "biweek" in name_lower:
            return CadenceType.BIWEEKLY
        if "month" in name_lower:
            return CadenceType.MONTHLY
        if "quarter" in name_lower:
            return CadenceType.QUARTERLY
        if "semi" in name_lower:
            return CadenceType.SEMI_ANNUAL
        if "annual" in name_lower or "year" in name_lower:
            return CadenceType.ANNUAL
        return CadenceType.IRREGULAR

    @classmethod
    def score_confidence(
        cls,
        txns: List[CleanedTransaction],
        cadence: CadenceType,
        mean_interval: float,
        interval_cv: float,
        modal_ratio: float,
        has_price_step: bool,
        day_of_month_variance: float,
        match_method: MatchMethod,
        is_retail: bool,
        is_variable_bill: bool,
        is_paused_resumed: bool,
        has_mandate: bool
    ) -> ConfidenceBreakdown:
        """
        Computes transparent additive 0-100 confidence score breakdown and penalties.
        """
        count = len(txns)
        factors: List[ScoreFactor] = []
        penalties: List[ScoreFactor] = []

        # Factor 1: Occurrences (max 25 pts)
        if count >= 6:
            pts_occ = 25.0
            occ_rat = f"Extensive observation history ({count} cycles observed)."
        elif count >= 4:
            pts_occ = 20.0
            occ_rat = f"Strong observation history ({count} cycles observed)."
        elif count == 3:
            pts_occ = 15.0
            occ_rat = f"3 consistent billing cycles observed."
        elif count == 2:
            pts_occ = 10.0
            occ_rat = f"2 billing cycles observed."
        else:
            pts_occ = 5.0
            occ_rat = f"Only {count} cycle observed."
        factors.append(ScoreFactor("Occurrences & Cycle History", pts_occ, WEIGHT_OCCURRENCES_MAX, occ_rat))

        # Factor 2: Interval Regularity (max 30 pts)
        if cadence != CadenceType.IRREGULAR:
            if interval_cv <= 0.10:
                pts_reg = 30.0
                reg_rat = f"High regularity (CV: {interval_cv:.2f} <= 0.10)."
            elif interval_cv <= 0.20:
                pts_reg = 25.0
                reg_rat = f"Consistent interval cadence (CV: {interval_cv:.2f})."
            elif interval_cv <= MAX_REGULAR_CV:
                pts_reg = 18.0
                reg_rat = f"Acceptable interval regularity with calendar jitter (CV: {interval_cv:.2f})."
            else:
                pts_reg = 10.0
                reg_rat = f"Moderate interval variance (CV: {interval_cv:.2f})."
        else:
            pts_reg = 0.0
            reg_rat = f"Irregular interval spacing across transactions (CV: {interval_cv:.2f})."
        factors.append(ScoreFactor("Interval Regularity", pts_reg, WEIGHT_INTERVAL_REGULARITY_MAX, reg_rat))

        # Factor 3: Amount Stability (max 20 pts)
        if modal_ratio >= 0.99 or has_price_step:
            pts_amt = 20.0
            amt_rat = "Identical billing amount or planned tier step across cycles."
        elif modal_ratio >= 0.80:
            pts_amt = 16.0
            amt_rat = f"High amount stability ({modal_ratio:.0%} transactions at modal amount)."
        elif is_variable_bill:
            pts_amt = 15.0
            amt_rat = "Utility / variable bill; amount fluctuation is expected by category."
        elif modal_ratio >= AMOUNT_MODAL_RATIO_THRESHOLD:
            pts_amt = 12.0
            amt_rat = f"Acceptable amount stability ({modal_ratio:.0%} at modal amount)."
        else:
            pts_amt = 5.0
            amt_rat = f"Fluctuating debit amounts (only {modal_ratio:.0%} at modal amount)."
        factors.append(ScoreFactor("Amount Stability", pts_amt, WEIGHT_AMOUNT_STABILITY_MAX, amt_rat))

        # Factor 4: Merchant Match Quality (max 15 pts)
        if match_method == MatchMethod.EXACT_ALIAS:
            pts_merch = 15.0
            merch_rat = "Exact canonical merchant alias match."
        elif match_method == MatchMethod.RULE_REGEX:
            pts_merch = 13.0
            merch_rat = "Recognized merchant pattern / legal entity rule match."
        elif match_method == MatchMethod.FUZZY:
            pts_merch = 8.0
            merch_rat = "Fuzzy string similarity match for known subscription provider."
        else:
            pts_merch = 3.0
            merch_rat = "Unverified description cluster (unknown merchant)."
        factors.append(ScoreFactor("Merchant Verification Quality", pts_merch, WEIGHT_MERCHANT_QUALITY_MAX, merch_rat))

        # Factor 5: Day-of-Month Anchoring & Mandates (max 10 pts)
        if has_mandate:
            pts_anchor = 10.0
            anc_rat = "Narration contains explicit bank mandate / standing instruction marker."
        elif cadence in (CadenceType.MONTHLY, CadenceType.QUARTERLY, CadenceType.ANNUAL) and day_of_month_variance <= 4.0:
            pts_anchor = 8.0
            anc_rat = f"Anchored to calendar day of month (std dev: {day_of_month_variance:.1f} days)."
        elif cadence == CadenceType.WEEKLY:
            pts_anchor = 7.0
            anc_rat = "Anchored to weekly cadence."
        else:
            pts_anchor = 3.0
            anc_rat = f"Day-of-month varies across cycles (std dev: {day_of_month_variance:.1f} days)."
        factors.append(ScoreFactor("Day-of-Month / Mandate Indicator", pts_anchor, WEIGHT_DAY_OF_MONTH_MAX, anc_rat))

        # --------------------------------------------------------------------
        # Penalties
        # --------------------------------------------------------------------
        if match_method == MatchMethod.UNKNOWN:
            penalties.append(ScoreFactor("Unverified Merchant Penalty", float(PENALTY_UNKNOWN_MERCHANT), 0.0, "Provider is not in verified merchant database."))
        if is_retail:
            penalties.append(ScoreFactor("Retail Category Penalty", float(PENALTY_RETAIL_CATEGORY), 0.0, "Discretionary retail/dining category requires stronger proof."))
        if count < 3 and cadence in (CadenceType.WEEKLY, CadenceType.MONTHLY):
            penalties.append(ScoreFactor("Few Observations Penalty", float(PENALTY_FEW_OBSERVATIONS), 0.0, "Fewer than 3 cycles observed."))
        if is_paused_resumed:
            penalties.append(ScoreFactor("Paused Gap Penalty", float(PENALTY_GAP_PAUSED), 0.0, "Interrupted payment sequence observed."))

        raw_total = sum(f.points_awarded for f in factors) + sum(p.points_awarded for p in penalties)
        score = max(5.0, min(100.0, raw_total))

        # Level determination
        is_capped = False
        cap_reason = None

        if score >= CONFIDENCE_HIGH_THRESHOLD:
            level = ConfidenceLevel.HIGH
        elif score >= CONFIDENCE_MEDIUM_THRESHOLD:
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW

        # Cap unverified merchants
        if match_method == MatchMethod.UNKNOWN and level == ConfidenceLevel.HIGH:
            level = ConfidenceLevel.MEDIUM
            is_capped = True
            cap_reason = "Unverified merchants are capped at Medium confidence."

        return ConfidenceBreakdown(
            total_score=round(score, 1),
            level=level,
            factors=factors,
            penalties=penalties,
            is_capped=is_capped,
            cap_reason=cap_reason
        )

    @classmethod
    def detect(
        cls,
        transactions: List[CleanedTransaction]
    ) -> Tuple[List[RecurringSeries], List[RejectionRecord]]:
        """
        Main recurring detection engine for the authoritative src/ pipeline.
        Filters strictly to valid debits, groups by canonical merchant, analyzes cadence,
        and returns detected RecurringSeries alongside transparent RejectionRecords.
        """
        # Step 1: Ensure transactions are enriched with merchant normalization and mandate indicators
        enriched_txns: List[CleanedTransaction] = []
        for t in transactions:
            if not t.normalized_merchant or not t.merchant_match:
                MerchantMatcher.enrich_transaction(t)
            if not t.has_mandate_indicator and t.narration:
                t.has_mandate_indicator = any(k in t.narration.upper() for k in MANDATE_KEYWORDS)
            enriched_txns.append(t)

        # Step 2: STRICT FILTERING - Only valid debits are analyzed
        # Excludes credits, refunds, reversals, duplicates, invalid rows, and uncertain direction
        valid_debits = [
            t for t in enriched_txns
            if t.row_status == RowStatus.VALID and t.is_debit is True
        ]

        # Step 3: Group by normalized merchant name
        grouped: Dict[str, List[CleanedTransaction]] = defaultdict(list)
        for t in valid_debits:
            key = t.normalized_merchant or t.cleaned_narration or "Unknown Merchant"
            grouped[key].append(t)

        recurring_list: List[RecurringSeries] = []
        rejection_records: List[RejectionRecord] = []

        for merchant_key, group in grouped.items():
            # Sort chronologically
            group.sort(key=lambda x: x.date)

            total_spend = sum(t.amount for t in group)
            sample_narrations = list(dict.fromkeys(t.narration for t in group))[:3]
            match_meta = group[0].merchant_match
            is_retail = match_meta.is_retail if match_meta else False
            is_var_bill = match_meta.is_variable_bill if match_meta else False
            match_method = match_meta.method if match_meta else MatchMethod.UNKNOWN
            category = match_meta.category if match_meta else "General / Other"
            is_merchant_verified = (match_method != MatchMethod.UNKNOWN)
            has_mandate = any(t.has_mandate_indicator for t in group)

            # ----------------------------------------------------------------
            # Guard: Insufficient History (only 1 transaction)
            # ----------------------------------------------------------------
            if len(group) < 2:
                rejection_records.append(
                    RejectionRecord(
                        group_key=merchant_key,
                        merchant_name=merchant_key,
                        transaction_count=len(group),
                        total_spend=round(total_spend, 2),
                        rejection_reasons=[
                            "Insufficient history: only 1 transaction recorded (minimum 2-3 billing cycles required for recurring detection)."
                        ],
                        sample_narrations=sample_narrations,
                        mean_interval_days=None,
                        interval_cv=None
                    )
                )
                continue

            # Calculate intervals
            intervals = [(group[i].date - group[i - 1].date).days for i in range(1, len(group))]
            mean_int = statistics.mean(intervals) if intervals else 0.0
            std_int = statistics.stdev(intervals) if len(intervals) > 1 else 0.0
            raw_cv = std_int / mean_int if mean_int > 0 else 0.0

            # ----------------------------------------------------------------
            # Ordinary Repeat Spends Shield: Rapid succession (e.g. food delivery, cab rides)
            # ----------------------------------------------------------------
            if intervals and mean_int < 5.0 and len(group) >= 3 and not has_mandate:
                rejection_records.append(
                    RejectionRecord(
                        group_key=merchant_key,
                        merchant_name=merchant_key,
                        transaction_count=len(group),
                        total_spend=round(total_spend, 2),
                        rejection_reasons=[
                            f"Rapid on-demand purchases: average interval of {mean_int:.1f} days indicates discretionary orders, not an automated recurring subscription.",
                            "No bank mandate or standing instruction markers detected."
                        ],
                        sample_narrations=sample_narrations,
                        mean_interval_days=round(mean_int, 1),
                        interval_cv=round(raw_cv, 2)
                    )
                )
                continue

            # Cadence determination with paused/resumed gap tolerance
            cadence, cadence_mean, cadence_std, interval_cv, is_paused_resumed, cadence_notes = (
                cls.determine_cadence_with_gap_tolerance(intervals, is_known_merchant=is_merchant_verified)
            )

            # Minimum occurrences check for weekly/monthly series without mandate markers
            if (
                cadence in (CadenceType.WEEKLY, CadenceType.BIWEEKLY, CadenceType.MONTHLY)
                and len(group) < MIN_OCCURRENCES_WEEKLY_MONTHLY
                and not has_mandate
            ):
                rejection_records.append(
                    RejectionRecord(
                        group_key=merchant_key,
                        merchant_name=merchant_key,
                        transaction_count=len(group),
                        total_spend=round(total_spend, 2),
                        rejection_reasons=[
                            f"Insufficient history: only {len(group)} transactions recorded (minimum {MIN_OCCURRENCES_WEEKLY_MONTHLY} billing cycles required for {cadence.value.lower()} cadence without mandate markers)."
                        ],
                        sample_narrations=sample_narrations,
                        mean_interval_days=round(mean_int, 1),
                        interval_cv=round(raw_cv, 2)
                    )
                )
                continue

            # Amount analysis
            amounts = [round(t.amount, 2) for t in group]
            amount_counts = Counter(amounts)
            modal_amt, modal_count = amount_counts.most_common(1)[0]
            modal_ratio = modal_count / len(amounts)

            # Check for planned step price increase (e.g., ₹499 -> ₹649)
            has_price_step = False
            if len(amounts) >= 3 and modal_ratio < 0.90:
                first_half = amounts[:len(amounts) // 2]
                second_half = amounts[len(amounts) // 2:]
                if len(set(first_half)) == 1 and len(set(second_half)) == 1 and first_half[0] != second_half[0]:
                    has_price_step = True

            # Day-of-month analysis
            days_of_month = [t.date.day for t in group]
            dom_std = statistics.stdev(days_of_month) if len(days_of_month) > 1 else 0.0

            # ----------------------------------------------------------------
            # Ordinary Repeat Protection (Retail / Dining Categories)
            # ----------------------------------------------------------------
            if is_retail and not has_mandate:
                # Discretionary repeat purchases (Swiggy, Zomato, Blinkit, Uber) fluctuate in amounts and dates
                if cadence == CadenceType.IRREGULAR or modal_ratio < 0.80 or interval_cv > 0.25:
                    rejection_records.append(
                        RejectionRecord(
                            group_key=merchant_key,
                            merchant_name=merchant_key,
                            transaction_count=len(group),
                            total_spend=round(total_spend, 2),
                            rejection_reasons=[
                                f"Discretionary retail/dining spend ({category}): purchases do not follow an automated subscription schedule.",
                                f"Fluctuating amounts: only {modal_ratio:.0%} at modal amount ₹{modal_amt:,.2f}.",
                                f"Interval variance: CV of {interval_cv:.2f} exceeds strict regularity requirements.",
                                "No mandate or standing instruction attached."
                            ],
                            sample_narrations=sample_narrations,
                            mean_interval_days=round(mean_int, 1),
                            interval_cv=round(interval_cv, 2)
                        )
                    )
                    continue

            # ----------------------------------------------------------------
            # Unverified / Irregular Spends Protection
            # ----------------------------------------------------------------
            if not is_merchant_verified and not has_mandate:
                if cadence == CadenceType.IRREGULAR or (modal_ratio < 0.70 and not has_price_step):
                    rejection_records.append(
                        RejectionRecord(
                            group_key=merchant_key,
                            merchant_name=merchant_key,
                            transaction_count=len(group),
                            total_spend=round(total_spend, 2),
                            rejection_reasons=[
                                "Unverified merchant with irregular intervals and non-constant amounts.",
                                f"Cadence classified as {cadence.value} with CV {interval_cv:.2f}.",
                                "No mandate indicators found to support recurring mandate status."
                            ],
                            sample_narrations=sample_narrations,
                            mean_interval_days=round(mean_int, 1),
                            interval_cv=round(interval_cv, 2)
                        )
                    )
                    continue

            # Score confidence
            confidence_breakdown = cls.score_confidence(
                txns=group,
                cadence=cadence,
                mean_interval=cadence_mean,
                interval_cv=interval_cv,
                modal_ratio=modal_ratio,
                has_price_step=has_price_step,
                day_of_month_variance=dom_std,
                match_method=match_method,
                is_retail=is_retail,
                is_variable_bill=is_var_bill,
                is_paused_resumed=is_paused_resumed,
                has_mandate=has_mandate
            )

            # Filter out very low confidence irregular series without mandate
            if confidence_breakdown.level == ConfidenceLevel.LOW and cadence == CadenceType.IRREGULAR and not has_mandate:
                rejection_records.append(
                    RejectionRecord(
                        group_key=merchant_key,
                        merchant_name=merchant_key,
                        transaction_count=len(group),
                        total_spend=round(total_spend, 2),
                        rejection_reasons=[
                            f"Low overall confidence ({confidence_breakdown.total_score:.1f}/100) and irregular cadence."
                        ],
                        sample_narrations=sample_narrations,
                        mean_interval_days=round(mean_int, 1),
                        interval_cv=round(interval_cv, 2)
                    )
                )
                continue

            # Build diagnostic evidence
            notes = list(cadence_notes)
            if has_mandate:
                notes.append("Bank narration confirms auto-debit / mandate keyword presence.")
            if is_var_bill:
                notes.append("Variable utility / postpaid bill: amount variance is normal for this category.")
            if is_paused_resumed:
                notes.append("Subscription pause gap detected and tolerated; cadence maintained.")

            uncertainty_reasons: List[str] = []
            if not is_merchant_verified:
                uncertainty_reasons.append("Unverified merchant identity; extracted from narration tokens.")
            if interval_cv > 0.20:
                uncertainty_reasons.append(f"Moderate date jitter (interval CV: {interval_cv:.2f}).")
            if modal_ratio < 0.80 and not is_var_bill and not has_price_step:
                uncertainty_reasons.append(f"Varying amounts ({modal_ratio:.0%} modal consistency).")

            evidence = Evidence(
                intervals_days=intervals,
                mean_interval_days=cadence_mean,
                std_interval_days=cadence_std,
                cv_interval=interval_cv,
                day_of_month_list=days_of_month,
                day_of_month_variance=round(dom_std, 1),
                modal_amount=modal_amt,
                modal_amount_ratio=round(modal_ratio, 2),
                has_mandate_keywords=has_mandate,
                notes=notes,
                uncertainty_reasons=uncertainty_reasons,
                is_paused_resumed=is_paused_resumed
            )

            # Financial run-rate calculation
            latest_amt = group[-1].amount
            monthly_eq, annual_eq = cls.calculate_run_rate_equivalents(cadence, latest_amt)

            # Review candidates: quarterly/annual with high price, or irregular, or low confidence
            is_review = False
            review_reasons: List[str] = []
            if cadence == CadenceType.ANNUAL:
                is_review = True
                review_reasons.append("Annual commitment: high-impact renewal candidate.")
            elif confidence_breakdown.level == ConfidenceLevel.LOW:
                is_review = True
                review_reasons.append("Low confidence series: recommend manual user verification.")
            elif is_paused_resumed:
                is_review = True
                review_reasons.append("Paused/resumed pattern detected: check if still desired.")

            series = RecurringSeries(
                merchant_name=merchant_key,
                category=category,
                cadence=cadence,
                confidence_level=confidence_breakdown.level,
                confidence_score=confidence_breakdown.total_score,
                confidence_breakdown=confidence_breakdown,
                evidence=evidence,
                transactions=group,
                latest_amount=latest_amt,
                monthly_equivalent=monthly_eq,
                annual_equivalent=annual_eq,
                is_merchant_verified=is_merchant_verified,
                is_review_candidate=is_review,
                review_reasons=review_reasons,
                is_paused_resumed=is_paused_resumed,
                is_variable_bill=is_var_bill
            )
            recurring_list.append(series)

        # Sort detected series by confidence score descending, then monthly equivalent descending
        recurring_list.sort(key=lambda s: (-s.confidence_score, -s.monthly_equivalent))
        return recurring_list, rejection_records
