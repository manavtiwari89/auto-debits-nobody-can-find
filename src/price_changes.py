"""Price Change & Stealth Subscription Hike Detection Engine.

Monitors recurring payment series over time to identify price increases,
enforcing minimum percentage thresholds (>= 2%), persistence confirmation
across consecutive billing cycles, and suppressing false alarms for variable
utility and postpaid bills (e.g. BESCOM electricity).
"""

from __future__ import annotations
from typing import List, Optional, Tuple, Dict, Any
from datetime import date

from src.models import (
    RecurringSeries,
    PriceAlert,
    CleanedTransaction
)
from src.config import (
    PRICE_HIKE_MIN_PERCENT,
    PRICE_HIKE_MIN_BASELINE_CYCLES,
    PRICE_HIKE_CONFIRMED_CYCLES
)


class PriceHikeTracker:
    """Detects price changes and stealth hikes in recurring series."""

    @classmethod
    def evaluate_series(
        cls,
        series: RecurringSeries,
        require_persistence: bool = True
    ) -> Optional[PriceAlert]:
        """
        Analyzes the chronological transactions of a RecurringSeries.
        Returns a confirmed PriceAlert if a price increase >= 2.0% is detected
        that persisted across at least 2 consecutive billing cycles.
        Suppresses alerts for variable utility/postpaid bills (e.g. BESCOM).
        """
        txns = series.transactions
        if len(txns) < 2:
            return None

        # --------------------------------------------------------------------
        # Guard: Suppress Variable Utility & Postpaid Bills (e.g. BESCOM)
        # --------------------------------------------------------------------
        is_variable = getattr(series, "is_variable_bill", False)
        if not is_variable and txns:
            # Check transaction-level metadata
            is_variable = any(
                t.merchant_match and t.merchant_match.is_variable_bill
                for t in txns
            )

        if is_variable:
            # Variable utility bills fluctuate based on consumption; suppress alerts
            return None

        # Sort transactions chronologically
        sorted_txns = sorted(txns, key=lambda t: t.date)
        latest_amt = round(sorted_txns[-1].amount, 2)

        # --------------------------------------------------------------------
        # Persistence Check: Count consecutive cycles at latest_amt at the tail
        # --------------------------------------------------------------------
        persistence_cycles = 0
        for t in reversed(sorted_txns):
            if abs(round(t.amount, 2) - latest_amt) < 0.01:
                persistence_cycles += 1
            else:
                break

        if require_persistence and persistence_cycles < PRICE_HIKE_CONFIRMED_CYCLES:
            # The higher price has not persisted for at least 2 consecutive cycles
            return None

        # --------------------------------------------------------------------
        # Baseline Check: Identify the earlier distinct amount before transition
        # --------------------------------------------------------------------
        earlier_txns = sorted_txns[:-persistence_cycles]
        if not earlier_txns:
            # All transactions in series were at the same amount; no price change
            return None

        old_amt = round(earlier_txns[-1].amount, 2)

        # Must be an increase
        if latest_amt <= old_amt:
            return None

        # Percentage increase calculation
        change_pct = ((latest_amt - old_amt) / old_amt) * 100.0
        if change_pct < PRICE_HIKE_MIN_PERCENT:
            return None

        # Count how many consecutive cycles prior to the transition were at old_amt
        baseline_cycles = 0
        for t in reversed(earlier_txns):
            if abs(round(t.amount, 2) - old_amt) < 0.01:
                baseline_cycles += 1
            else:
                break

        # Effective date is the date of the first transaction at latest_amt
        effective_date = sorted_txns[-persistence_cycles].date
        diff = latest_amt - old_amt

        evidence_note = (
            f"Subscription price increased from ₹{old_amt:,.2f} to ₹{latest_amt:,.2f} "
            f"(+₹{diff:,.2f} / +{change_pct:.1f}%) effective {effective_date}; "
            f"confirmed and persisted for {persistence_cycles} consecutive billing cycles."
        )

        return PriceAlert(
            merchant_name=series.merchant_name,
            old_amount=old_amt,
            new_amount=latest_amt,
            change_percent=round(change_pct, 1),
            effective_date=effective_date,
            is_confirmed=True,
            baseline_cycles=baseline_cycles,
            persistence_cycles=persistence_cycles,
            evidence_note=evidence_note
        )

    @classmethod
    def attach_price_alerts(
        cls,
        series_list: List[RecurringSeries]
    ) -> List[RecurringSeries]:
        """
        Evaluates price changes across all recurring series and attaches PriceAlerts.
        Adds transparent diagnostic notes to evidence.
        """
        for s in series_list:
            alert = cls.evaluate_series(s)
            if alert:
                s.price_alert = alert
                s.evidence.notes.append(
                    f"⚠️ Price hike detected: rose from ₹{alert.old_amount:,.2f} to "
                    f"₹{alert.new_amount:,.2f} (+{alert.change_percent:.1f}%) on "
                    f"{alert.effective_date} (persisted for {alert.persistence_cycles} cycles)."
                )
        return series_list
