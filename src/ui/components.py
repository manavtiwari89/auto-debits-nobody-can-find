"""Reusable UI components for The Auto Debits Nobody Can Find dashboard.

Stage 8 UI Module.
Builds KPI metric cards, confidence score diagnostic expanders,
price hike alerts, verified cancellation guides with regulatory references,
interactive potential savings simulator, and statement hygiene audit tables.
"""

from __future__ import annotations
import re
from typing import List, Dict, Any, Optional
import streamlit as st
import pandas as pd

from src.models import (
    CleanedTransaction,
    RecurringSeries,
    ConfidenceLevel,
    CadenceType,
    RowStatus,
    RejectionRecord,
    InsightsSummary,
    CleaningResult,
)
from src.insights import (
    SavingsSimulator,
    POTENTIAL_SAVINGS_DISCLAIMER,
)
from src.ui.styles import (
    render_confidence_badge,
    render_cadence_badge,
    render_price_hike_badge,
    render_review_badge,
    render_paused_badge,
    render_variable_badge,
    render_kpi_card_html,
)
from src.ui.charts import (
    create_monthly_burn_chart,
    create_category_donut_chart,
    create_cadence_breakdown_chart,
    create_savings_comparison_chart,
)


def mask_reference_id(ref: Optional[str]) -> str:
    """Masks banking reference IDs to preserve privacy on screen by default."""
    if not ref or ref.upper() in {"", "NA", "N/A", "NONE", "NULL", "0", "-"}:
        return "-"
    cleaned = ref.strip()
    if len(cleaned) <= 6:
        return cleaned
    return f"{cleaned[:3]}***{cleaned[-4:]}"


def mask_narration(narration: str) -> str:
    """Masks long account or card numbers inside transaction narrations."""
    # Mask 16-digit card numbers or 10-14 digit account numbers
    masked = re.sub(r"\b(\d{4})\d{4,10}(\d{4})\b", r"\1XXXXXXXX\2", narration)
    # Mask mobile numbers (10 digits starting with 6-9)
    masked = re.sub(r"\b([6-9]\d{2})\d{4}(\d{3})\b", r"\1****\2", masked)
    return masked


def render_privacy_banner() -> None:
    """Renders the privacy badge and expandable privacy disclosure."""
    st.markdown(
        """
        <div class="privacy-vault-pill">
            🛡️ In-Memory Process Execution • Zero Third-Party API Calls • Private Financial Vault
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("🔒 How Your Privacy & Financial Data Are Protected"):
        st.markdown(
            """
            - **In-Memory Python Processing**: Statement processing occurs strictly inside the Python process running the application.
              When running the app locally on your own machine, your statement data remains entirely on your device.
              If the application is deployed or hosted remotely, uploaded data is processed in memory by that hosting server.
            - **Zero Third-Party API Calls**: No transaction data, balances, or narrations are transmitted to external AI/LLM APIs, telemetry services, or remote trackers.
            - **Non-Agency Guarantee**: This application is strictly an informational audit tool. It never connects to your
              bank accounts, never asks for banking credentials or OTPs, and **never cancels payments, mandates, or subscriptions
              on your behalf**.
            - **Sensitive Details Masked by Default**: Account numbers, card masks, and transaction reference IDs are masked
              by default in the display to prevent shoulder-surfing.
            """
        )


def render_kpi_cards(summary: InsightsSummary) -> None:
    """Renders five robust Streamlit metric cards for the financial summary."""
    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.metric("Observed Monthly Burn", f"₹{summary.monthly_actual_burn:,.2f}")
        st.caption(
            f"Over {summary.observed_period_months:.1f} months; "
            f"total spend ₹{summary.total_actual_spend:,.2f}"
        )

    with c2:
        st.metric("Monthly Run-Rate", f"₹{summary.monthly_projected_commitment:,.2f}")
        st.caption("Projected 30-day recurring commitment")

    with c3:
        st.metric("Annual Commitment", f"₹{summary.annual_projected_commitment:,.2f}")
        st.caption("Forward 12-month run-rate commitment")

    with c4:
        delta = (
            f"{summary.price_alerts_count} Price Hike Alert(s)"
            if summary.price_alerts_count > 0
            else None
        )
        st.metric("Active Auto-Debits", str(summary.detected_series_count), delta=delta)
        st.caption("Detected across statements")

    with c5:
        st.metric("Potential Review Savings", f"₹{summary.total_review_annual_savings:,.2f}")
        st.caption(
            f"Potential, not guaranteed · ₹{summary.total_review_monthly_savings:,.2f}/mo · "
            f"{len(summary.review_candidates)} review candidates"
        )

def render_price_alerts_banner(series_list: List[RecurringSeries]) -> None:
    """Highlights detected price hikes with old and new amounts."""
    hiked_series = [s for s in series_list if s.price_alert is not None]
    if not hiked_series:
        return

    st.markdown("### ⚠️ Stealth Price Hikes Detected")
    st.caption("These merchants increased their recurring debit amount by ≥ 2%, persisting across ≥ 2 consecutive billing cycles.")

    for s in hiked_series:
        alert = s.price_alert
        if not alert:
            continue
        diff = alert.new_amount - alert.old_amount
        st.markdown(
            f"""
            <div class="price-alert-box">
                <div class="price-alert-title">🔔 {s.merchant_name} ({s.category}) — Price Increased by {alert.formatted_difference}</div>
                <div style="font-size: 0.88rem; margin-top: 4px;">
                    <strong>Previous Amount:</strong> ₹{alert.old_amount:,.2f} &nbsp;➜&nbsp;
                    <strong>New Amount:</strong> ₹{alert.new_amount:,.2f} &nbsp;|&nbsp;
                    <strong>Effective Date:</strong> {alert.effective_date.strftime('%d-%b-%Y')}<br>
                    <strong>Verification Evidence:</strong> {alert.evidence_note}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_recurring_series_card(
    series: RecurringSeries,
    index: int,
    show_sensitive_details: bool = False,
) -> None:
    """
    Renders an expandable card for a detected recurring series, including diagnostic evidence,
    additive confidence breakdown, verified cancellation steps, and historical billing occurrences.
    """
    # Badges row
    badges = [
        render_cadence_badge(series.cadence),
        render_confidence_badge(series.confidence_level, series.confidence_score),
    ]
    if series.price_alert:
        badges.append(render_price_hike_badge(series.price_alert.formatted_difference))
    if series.is_paused_resumed:
        badges.append(render_paused_badge())
    if series.is_variable_bill:
        badges.append(render_variable_badge())
    if series.is_review_candidate:
        badges.append(render_review_badge())

    header_label = (
        f"{series.merchant_name} — ₹{series.latest_amount:,.2f} / {series.cadence.value} "
        f"({series.confidence_level.value} Confidence, {series.confidence_score:.0f}/100)"
    )

    with st.expander(header_label, expanded=False):
        st.markdown(" ".join(badges), unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.markdown("#### 🔍 Evidence & Cadence Diagnostics")
            st.markdown(f"- **Category:** `{series.category}`")
            st.markdown(f"- **Cadence Schedule:** **{series.cadence.value}** (Interval Mean: `{series.evidence.mean_interval_days:.1f}` days, Std: `{series.evidence.std_interval_days:.1f}` days, CV: `{series.evidence.cv_interval:.2f}`)")
            st.markdown(f"- **Observed Billing Cycles:** {len(series.transactions)}")
            st.markdown(f"- **Normalized Monthly Equivalent:** ₹{series.monthly_equivalent:,.2f}")
            st.markdown(f"- **Projected Annual Commitment:** ₹{series.annual_equivalent:,.2f}")

            # Confidence Breakdown Drawer
            cb = series.confidence_breakdown
            with st.expander(f"📊 Calibrated Score Breakdown ({cb.total_score:.0f} / 100 pts)"):
                st.caption("Additive scoring based on interval regularity, amount stability, merchant identity, and cadence penalties:")
                score_items = []
                for f in cb.factors:
                    score_items.append(f"• **{f.name}**: +{f.points_awarded:.1f} / {f.max_points:.0f} pts — *{f.rationale}*")
                for p in cb.penalties:
                    score_items.append(f"• ⚠️ **{p.name}**: {p.points_awarded:.1f} pts — *{p.rationale}*")
                if cb.is_capped:
                    score_items.append(f"• 🔒 **Score Cap**: {cb.cap_reason}")
                st.markdown("<br>".join(score_items), unsafe_allow_html=True)

            # Diagnostic Notes & Review Reasons
            if series.evidence.notes:
                st.markdown("**Diagnostic Evidence:**")
                for note in series.evidence.notes:
                    st.markdown(f"- {note}")

            if series.is_review_candidate and series.review_reasons:
                st.markdown("**Review Reasons:**")
                for r in series.review_reasons:
                    st.markdown(f"- 💡 {r}")

        with col_right:
            st.markdown("#### 🛑 Actionable Cancellation Guidance")
            details = series.cancellation_details
            if details:
                if details.is_verified and details.source_url:
                    st.markdown(
                        f"""
                        <div class="verified-banner">
                            <strong>✓ Human-Verified First-Party Guide</strong><br>
                            Verified as of <strong>{details.last_verified}</strong> via official help documentation.
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"[🔗 Open Official Cancellation Portal ({details.merchant_name})]({details.source_url})")
                else:
                    st.markdown(
                        """
                        <div class="unverified-banner">
                            <strong>ℹ️ Generic Unverified Guidance (Standard Bank-Level / In-App Fallback)</strong><br>
                            No first-party web portal link verified. Follow standard in-app steps or revoke debit authority via your bank/UPI app.
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                st.markdown(f"**Settings Location:** `{details.settings_location}`")

                st.markdown("**Step-by-Step Cancellation Instructions:**")
                for idx, step in enumerate(details.steps, 1):
                    st.markdown(f"{idx}. {step}")

                if details.mandate_guidance:
                    with st.expander("🏛️ Bank E-Mandate & UPI AutoPay Revocation (Crucial Step)"):
                        st.caption(
                            "In Indian banking, cancelling an in-app subscription only stops merchant billing requests; "
                            "it does NOT cancel your bank-level standing mandate. Always revoke debit authority directly:"
                        )
                        for m_step in details.mandate_guidance:
                            st.markdown(f"- {m_step}")

                st.markdown(
                    """
                    <div class="disclaimer-box">
                        <strong>Non-Agency Notice:</strong> This application is purely diagnostic and informational.
                        It never accesses your bank account and <strong>never cancels payments or revokes mandates on your behalf</strong>.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.info("No cancellation details registered for this merchant.")

        # Billing Occurrences Table
        st.markdown("##### 📜 Observed Billing Occurrences")
        table_rows = []
        for t in series.transactions:
            ref_display = t.reference_id if show_sensitive_details else mask_reference_id(t.reference_id)
            narr_display = t.narration if show_sensitive_details else mask_narration(t.narration)
            table_rows.append(
                {
                    "Date": t.date.strftime("%d-%b-%Y"),
                    "Amount": f"₹{t.amount:,.2f}",
                    "Status": t.row_status.value,
                    "Reference ID": ref_display,
                    "Mandate Indicator": "✓ Yes" if t.has_mandate_indicator else "No",
                    "Narration": narr_display,
                }
            )

        df_occ = pd.DataFrame(table_rows)
        st.dataframe(df_occ, use_container_width=True, hide_index=True)


def render_savings_simulator(
    series_list: List[RecurringSeries],
    summary: InsightsSummary,
) -> None:
    """Renders the potential savings simulator allowing users to model cost reductions."""
    st.markdown("### 💡 Potential Savings Simulator")
    st.markdown(
        f"""
        <div class="disclaimer-box">
            <strong>Important Notice:</strong> {POTENTIAL_SAVINGS_DISCLAIMER}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not series_list:
        st.info("No active recurring debits available for simulation.")
        return

    # Extract default candidate names (review candidates)
    default_candidates = [s.merchant_name for s in summary.review_candidates]
    all_merchants = [s.merchant_name for s in series_list]

    selected_merchants = st.multiselect(
        "Select subscriptions to simulate discontinuing:",
        options=all_merchants,
        default=default_candidates,
        help="Select any recurring payments you are evaluating to see potential monthly and annual cost reductions.",
    )

    sim_result = SavingsSimulator.simulate_savings(series_list, selected_merchants=selected_merchants)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "Potential Monthly Savings",
            f"₹{sim_result.potential_monthly_savings:,.2f}",
            help="Estimated recurring monthly cost reduction if selected services are cancelled.",
        )
    with c2:
        st.metric(
            "Potential Annual Savings",
            f"₹{sim_result.potential_annual_savings:,.2f}",
            help="Estimated 12-month forward savings if selected services are cancelled.",
        )
    with c3:
        st.metric(
            "Retained Monthly Commitment",
            f"₹{sim_result.remaining_monthly_commitment:,.2f}",
            delta=f"-₹{sim_result.potential_monthly_savings:,.2f}" if sim_result.potential_monthly_savings > 0 else None,
            delta_color="inverse",
        )
    with c4:
        st.metric(
            "Retained Annual Commitment",
            f"₹{sim_result.remaining_annual_commitment:,.2f}",
            delta=f"-₹{sim_result.potential_annual_savings:,.2f}" if sim_result.potential_annual_savings > 0 else None,
            delta_color="inverse",
        )

    # Comparison Chart
    fig_savings = create_savings_comparison_chart(
        summary.annual_projected_commitment,
        sim_result.potential_annual_savings,
    )
    if fig_savings:
        st.plotly_chart(fig_savings, use_container_width=True)

    # Candidate details breakdown
    if sim_result.candidate_details:
        st.markdown("#### 📋 Selected Discontinuation Candidates")
        cand_df = pd.DataFrame(
            [
                {
                    "Merchant": c.merchant_name,
                    "Category": c.category,
                    "Cadence": c.cadence.value,
                    "Latest Amount": f"₹{c.latest_amount:,.2f}",
                    "Potential Monthly Savings": f"₹{c.monthly_potential_savings:,.2f}",
                    "Potential Annual Savings": f"₹{c.annual_potential_savings:,.2f}",
                    "Reasons for Review": "; ".join(c.review_reasons) if c.review_reasons else "Discretionary Selection",
                }
                for c in sim_result.candidate_details
            ]
        )
        st.dataframe(cand_df, use_container_width=True, hide_index=True)


def render_statement_audit(
    cleaning_result: CleaningResult,
    rejections: List[RejectionRecord],
    raw_txns: List[CleanedTransaction],
    show_sensitive_details: bool = False,
) -> None:
    """Renders statement hygiene metrics, ordinary repeat rejections, and raw transaction log."""
    st.markdown("### 🧾 Statement Hygiene & Ingestion Audit")

    # Metrics row
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("Total Rows", cleaning_result.total_rows)
    with c2:
        st.metric("Valid Debits", cleaning_result.valid_count)
    with c3:
        st.metric("Duplicate Debits", cleaning_result.duplicate_count)
    with c4:
        st.metric("Refunds / Reversals", cleaning_result.refund_count + cleaning_result.reversal_count)
    with c5:
        st.metric("Uncertain Direction", cleaning_result.uncertain_count)
    with c6:
        st.metric("Malformed Rows", cleaning_result.invalid_count)

    # Rejection Audit Section
    st.markdown("#### 🛡️ Rejection Shield (Ordinary Repeat Purchases)")
    st.caption(
        "To avoid false positives, ordinary repeat discretionary orders (e.g. Swiggy, Zomato, Uber, Blinkit) "
        "that lack e-mandate markers, have high interval variance (CV > 0.35), or occur in rapid succession (< 5 days) "
        "are safely rejected into an auditable rejection record."
    )

    if rejections:
        rej_df = pd.DataFrame(
            [
                {
                    "Merchant Group": r.merchant_name,
                    "Transactions": r.transaction_count,
                    "Total Spend": f"₹{r.total_spend:,.2f}",
                    "Mean Interval (Days)": f"{r.mean_interval_days:.1f}" if r.mean_interval_days is not None else "N/A",
                    "Interval CV": f"{r.interval_cv:.2f}" if r.interval_cv is not None else "N/A",
                    "Rejection Reasons": "; ".join(r.rejection_reasons),
                }
                for r in rejections
            ]
        )
        st.dataframe(rej_df, use_container_width=True, hide_index=True)
    else:
        st.info("No repeated merchant groups were rejected.")

    # Raw Transactions Section
    st.markdown("#### 📜 Full Statement Parsed Transactions")
    status_filter = st.selectbox(
        "Filter Transactions by Status:",
        ["All Rows", "Valid Debits Only", "Duplicates Only", "Refunds Only", "Uncertain Only"],
        index=0,
    )

    filtered_txns = raw_txns
    if status_filter == "Valid Debits Only":
        filtered_txns = [t for t in raw_txns if t.row_status == RowStatus.VALID and t.is_debit is True]
    elif status_filter == "Duplicates Only":
        filtered_txns = [t for t in raw_txns if t.row_status == RowStatus.DUPLICATE]
    elif status_filter == "Refunds Only":
        filtered_txns = [t for t in raw_txns if t.row_status in (RowStatus.REFUND, RowStatus.REVERSAL)]
    elif status_filter == "Uncertain Only":
        filtered_txns = [t for t in raw_txns if t.row_status == RowStatus.UNCERTAIN]

    raw_table = []
    for t in filtered_txns:
        ref = t.reference_id if show_sensitive_details else mask_reference_id(t.reference_id)
        narr = t.narration if show_sensitive_details else mask_narration(t.narration)
        raw_table.append(
            {
                "Date": t.date.strftime("%d-%b-%Y"),
                "Merchant": t.normalized_merchant or "-",
                "Amount": f"₹{t.amount:,.2f}",
                "Direction": "Debit" if t.is_debit is True else ("Credit" if t.is_debit is False else "Uncertain"),
                "Status": t.row_status.value,
                "Reference": ref,
                "Mandate Flag": "✓ Yes" if t.has_mandate_indicator else "No",
                "Narration": narr,
            }
        )

    df_raw = pd.DataFrame(raw_table)
    st.dataframe(df_raw, use_container_width=True, hide_index=True)
