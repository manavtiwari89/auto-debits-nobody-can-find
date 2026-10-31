"""Price Change & Stealth Auto-Debit Hike Detector.

Monitors recurring payment series over time to identify price increases,
calculating percentage changes and effective transition dates.
"""

from __future__ import annotations
from typing import List, Optional
from datetime import date
from app.models import RecurringSeries, PriceAlert, Transaction


class PriceTracker:
    """Detects price changes in recurring series."""

    @classmethod
    def evaluate_series_price_change(
        cls, series: RecurringSeries
    ) -> Optional[PriceAlert]:
        """
        Analyzes the chronological transactions of a RecurringSeries.
        Returns a PriceAlert if a price increase is detected between earlier and latest cycles.
        """
        txns = series.transactions
        if len(txns) < 2:
            return None

        # Gather distinct amounts in chronological order
        amounts_by_date = [(t.date, t.amount) for t in txns]
        amounts_by_date.sort(key=lambda x: x[0])

        latest_date, latest_amt = amounts_by_date[-1]

        # Scan backwards to find the earliest distinct previous baseline amount
        old_amt: Optional[float] = None
        effective_date: Optional[date] = None

        for dt, amt in reversed(amounts_by_date[:-1]):
            if amt != latest_amt:
                old_amt = amt
                # Find the earliest date where latest_amt started occurring
                for d_curr, a_curr in amounts_by_date:
                    if a_curr == latest_amt:
                        effective_date = d_curr
                        break
                break

        if old_amt is not None and latest_amt > old_amt:
            pct_change = ((latest_amt - old_amt) / old_amt) * 100.0
            diff = latest_amt - old_amt
            details = (
                f"Subscription price increased from ₹{old_amt:,.2f} to ₹{latest_amt:,.2f} "
                f"(+₹{diff:,.2f} or {pct_change:+.1f}%) effective {effective_date}."
            )

            alert = PriceAlert(
                merchant_name=series.merchant_name,
                old_amount=old_amt,
                new_amount=latest_amt,
                percent_change=round(pct_change, 1),
                effective_date=effective_date or latest_date,
                details=details
            )
            return alert

        return None

    @classmethod
    def attach_price_alerts(
        cls, series_list: List[RecurringSeries]
    ) -> List[RecurringSeries]:
        """
        Iterates over all recurring series, evaluates price changes,
        and attaches alerts and evidence statements.
        """
        for s in series_list:
            alert = cls.evaluate_series_price_change(s)
            if alert:
                s.price_alert = alert
                s.evidence_reasons.append(
                    f"⚠️ Price hike detected: rose from ₹{alert.old_amount:,.2f} to ₹{alert.new_amount:,.2f} ({alert.percent_change:+.1f}%) on {alert.effective_date}."
                )
        return series_list
