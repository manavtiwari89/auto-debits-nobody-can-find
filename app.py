"""The Auto Debits Nobody Can Find - Production Streamlit Application.

A local, privacy-first personal finance audit tool for Indian banking users.
Identifies recurring subscriptions, UPI AutoPay mandates, stealth price hikes,
observed vs projected burn rates, review candidates, and verified cancellation guidance.

Stage 8 UI Entry Point.
Connects the modular src/ pipeline:
StatementIngestor -> StatementCleaner -> MerchantMatcher -> RecurringDetector
-> PriceHikeTracker -> CancellationRegistry -> CostEstimator & SavingsSimulator
"""

from __future__ import annotations
import os
import io
from datetime import date
from typing import List, Optional, Tuple, Dict, Any
import streamlit as st
import pandas as pd

from src.models import (
    ConfidenceLevel,
    CadenceType,
    RowStatus,
    SchemaValidationError,
    RecurringSeries,
    CleaningResult,
    RejectionRecord,
    CleanedTransaction,
    InsightsSummary,
)
from src.ingestion import StatementIngestor
from src.cleaning import StatementCleaner
from src.merchants import MerchantMatcher
from src.detection import RecurringDetector
from src.price_changes import PriceHikeTracker
from src.cancellation import CancellationRegistry
from src.insights import (
    CostEstimator,
    SavingsSimulator,
    POTENTIAL_SAVINGS_DISCLAIMER,
)
from src.ui.styles import (
    get_custom_css,
    render_confidence_badge,
    render_cadence_badge,
    render_price_hike_badge,
)
from src.ui.charts import (
    create_monthly_burn_chart,
    create_category_donut_chart,
    create_cadence_breakdown_chart,
)
from src.ui.components import (
    render_privacy_banner,
    render_kpi_cards,
    render_price_alerts_banner,
    render_recurring_series_card,
    render_savings_simulator,
    render_statement_audit,
)
from src.ui.pipeline import (
    DEMO_FILES,
    load_file_content,
    run_pipeline,
)


# -----------------------------------------------------------------------------
# Streamlit App Configuration
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Auto Debits Nobody Can Find | Indian Banking Audit",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject global CSS
st.markdown(get_custom_css(), unsafe_allow_html=True)


def main():
    # Header & Privacy Banner
    st.title("🔍 The Auto Debits Nobody Can Find")
    st.subheader("Privacy-First Recurring Payment & Stealth Auto-Debit Detector for Indian Users")
    render_privacy_banner()

    with st.expander("🏁 Judge walkthrough · follow these 5 quick stops", expanded=False):
        st.markdown(
            """
            **The problem:** bank statements hide recurring payments behind cryptic merchant names. This prototype turns a CSV into an explainable review.

            **Start here:** In the left panel, choose **13-Case Test Benchmark (Clean - 223 transactions, 11 Series)**. This sample is set up to show the main features below.

            1. **Find commitments:** In *Subscriptions & Mandates*, open **Cult.fit** to see a paused-and-resumed pattern and **Amazon Prime** for an annual payment. Open a card to see why it was matched.
            2. **Spot lasting increases:** In *Stealth Price Hikes*, see persistent increases for **Netflix** and **Spotify**. **BESCOM** is treated as a variable electricity bill.
            3. **See the yearly cost:** In *Spend & Category Analytics*, compare money already spent with the projected annual commitment.
            4. **See the next steps:** In *Cancellation & Mandate Guidance*, compare an official verified guide with generic guidance. Merchant cancellation and bank/UPI mandate revocation are separate actions; the app performs neither.
            5. **Check the audit:** In *Statement Hygiene & Audit*, inspect how rows were handled and why everyday repeat purchases were not labeled subscriptions.

            **Terms in plain words:** *Monthly burn* = money already spent. *Commitment* = estimated future repeat payments. *Confidence* = strength of the clues, not a guarantee. *Potential savings* = a what-if estimate, not guaranteed savings.
            """
        )
        with st.expander("Prototype scope and honest limits"):
            st.caption(
                "This prototype analyzes CSV bank statements. It does not ingest payment notifications, detect trial-to-paid conversions, "
                "or infer whether a person stopped using a service. Its benchmark files are synthetic and do not establish real-world accuracy."
            )

    # -------------------------------------------------------------------------
    # Sidebar: Data Source & Controls
    # -------------------------------------------------------------------------
    st.sidebar.header("📁 Bank Statement Import")
    data_source = st.sidebar.radio(
        "Choose Data Input Source:",
        ["Load Synthetic Demo Statement", "Upload Statement CSV"],
        index=0,
    )

    csv_content: Optional[str] = None
    statement_label = "Demo Statement"

    if data_source == "Upload Statement CSV":
        uploaded_file = st.sidebar.file_uploader(
            "Upload Bank Statement (CSV format):",
            type=["csv"],
            help="Upload an exported CSV from HDFC, SBI, ICICI, Axis, Kotak, or any standard bank statement.",
        )
        if uploaded_file is not None:
            csv_content = io.StringIO(uploaded_file.getvalue().decode("utf-8", errors="replace")).read()
            statement_label = uploaded_file.name
    else:
        demo_choice = st.sidebar.selectbox(
            "Select Pre-Packaged Demo Statement:",
            list(DEMO_FILES.keys()),
            index=1,
            help="The clean benchmark is the recommended judge walkthrough; choose the stress statement to see noisy dates and narrations.",
        )
        file_path, default_label = DEMO_FILES[demo_choice]
        csv_content = load_file_content(file_path)
        statement_label = default_label

    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Audit Controls & Filters")

    # Minimum Confidence Tier
    conf_option = st.sidebar.selectbox(
        "Minimum Confidence Tier:",
        ["All (High, Medium, Low)", "Medium & High", "High Only"],
        index=0,
        help="Filter detected recurring series by calibrated confidence score.",
    )
    if conf_option == "High Only":
        min_conf = ConfidenceLevel.HIGH
    elif conf_option == "Medium & High":
        min_conf = ConfidenceLevel.MEDIUM
    else:
        min_conf = ConfidenceLevel.LOW

    # Optional Statement Period Override
    st.sidebar.markdown("##### 📅 Statement Period Window")
    enable_date_override = st.sidebar.checkbox(
        "Specify Explicit Statement Dates",
        value=False,
        help="Use full statement period dates to calculate accurate monthly actual burn when recurring debits cover only part of the statement.",
    )
    override_start: Optional[date] = None
    override_end: Optional[date] = None
    if enable_date_override:
        c_d1, c_d2 = st.sidebar.columns(2)
        with c_d1:
            override_start = st.date_input("Start Date", value=date(2025, 11, 1))
        with c_d2:
            override_end = st.date_input("End Date", value=date(2026, 10, 31))

    # Merchant Search Filter
    search_query = st.sidebar.text_input(
        "Search Merchants / Category:",
        value="",
        placeholder="e.g. Netflix, Spotify, Gym...",
    ).strip().lower()

    # Privacy Toggle
    show_sensitive = st.sidebar.checkbox(
        "Show Unmasked References & Accounts",
        value=False,
        help="By default, transaction reference IDs and account digits are masked on screen to preserve privacy.",
    )

    st.sidebar.markdown("---")
    st.sidebar.caption("🚀 **HackFront 2026** • Authoritative `src/` Engine")

    # -------------------------------------------------------------------------
    # Execution & Validation Handling
    # -------------------------------------------------------------------------
    if not csv_content:
        if data_source == "Upload Statement CSV":
            st.info("👈 Upload a bank statement CSV from the sidebar to start.")
        else:
            st.error(
                f"### ❌ Sample statement could not be loaded\n"
                f"The file for **{demo_choice}** was not found or is empty: `{file_path}`.\n\n"
                "Please make sure the project’s `data/` folder is included and try again."
            )
        return

    try:
        with st.spinner("Analyzing bank statement, intervals, mandates, and price changes..."):
            cleaning_result, all_series, rejections, summary = run_pipeline(
                csv_text=csv_content,
                filename_hint=statement_label,
                min_confidence=min_conf,
                override_start_date=override_start,
                override_end_date=override_end,
            )
    except SchemaValidationError as e:
        st.error(f"### ❌ Unsupported or Invalid Bank Statement CSV\n**{e.message}**")
        st.markdown(
            f"""
            <div class="disclaimer-box">
                <strong>Columns Detected in File:</strong> {', '.join(f'`{c}`' for c in e.detected_columns) if e.detected_columns else 'None'}<br>
                <strong>Missing Required Fields:</strong> {', '.join(f'`{m}`' for m in e.missing_fields) if e.missing_fields else 'Unrecognized bank header structure'}
                <br><br>
                <strong>Supported Formats:</strong>
                <ul>
                    <li>Standard Indian Bank CSVs: <strong>HDFC, SBI, ICICI, Axis, Kotak</strong></li>
                    <li>Generic 3-Column CSV: <code>Date, Narration, Amount</code> (with signed amounts or Dr/Cr markers)</li>
                    <li>Generic 4-Column CSV: <code>Date, Narration, Withdrawal / Debit, Deposit / Credit</code></li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    except Exception as e:
        st.error(f"### ❌ Pipeline Execution Error\nAn unexpected error occurred during processing: `{e}`")
        return

    # Filter series list for UI view
    filtered_series = [
        s for s in all_series
        if (
            min_conf == ConfidenceLevel.LOW
            or (min_conf == ConfidenceLevel.MEDIUM and s.confidence_level in (ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH))
            or (min_conf == ConfidenceLevel.HIGH and s.confidence_level == ConfidenceLevel.HIGH)
        )
    ]

    if search_query:
        filtered_series = [
            s for s in filtered_series
            if search_query in s.merchant_name.lower() or search_query in s.category.lower()
        ]

    # Re-calculate summary if search query was applied
    if search_query:
        summary = CostEstimator.calculate_summary(
            filtered_series,
            min_confidence=min_conf,
            statement_start_date=override_start,
            statement_end_date=override_end,
        )

    # -------------------------------------------------------------------------
    # Top KPI Metrics & Price Alert Banner
    # -------------------------------------------------------------------------
    render_kpi_cards(summary)
    render_price_alerts_banner(filtered_series)

    # -------------------------------------------------------------------------
    # Main Dashboard Tabs
    # -------------------------------------------------------------------------
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            f"📋 Subscriptions & Mandates ({len(filtered_series)})",
            f"⚠️ Stealth Price Hikes ({summary.price_alerts_count})",
            "📊 Spend & Category Analytics",
            f"💡 Review Candidates & Simulator ({len(summary.review_candidates)})",
            "🛑 Cancellation & Mandate Guidance",
            "🧾 Statement Hygiene & Audit",
        ]
    )

    # TAB 1: Subscriptions & Mandates
    with tab1:
        st.markdown(f"### Detected Recurring Subscriptions & Mandates ({len(filtered_series)})")
        st.caption(
            "These are payments that may repeat, such as subscriptions or memberships. Open a payment to see the clues. "
            "The confidence rating tells you how strong those clues are; check the details before acting."
        )

        if not filtered_series:
            st.info("🎉 No recurring auto-debits found matching the active filter.")
        else:
            for idx, s in enumerate(filtered_series, 1):
                render_recurring_series_card(
                    series=s,
                    index=idx,
                    show_sensitive_details=show_sensitive,
                )

    # TAB 2: Stealth Price Hikes
    with tab2:
        st.markdown(f"### ⚠️ Stealth Price Hikes ({summary.price_alerts_count})")
        st.caption(
            "Shows repeat payments that became more expensive and stayed higher for at least two billing cycles. "
            "Normal ups and downs in bills like electricity are treated separately."
        )

        hiked_series = [s for s in filtered_series if s.price_alert is not None]
        if not hiked_series:
            st.success("🎉 No persistent price hikes detected in the current statement.")
        else:
            hike_table = []
            for s in hiked_series:
                a = s.price_alert
                hike_table.append(
                    {
                        "Merchant": s.merchant_name,
                        "Category": s.category,
                        "Cadence": s.cadence.value,
                        "Old Amount": f"₹{a.old_amount:,.2f}",
                        "New Amount": f"₹{a.new_amount:,.2f}",
                        "Increase": a.formatted_difference,
                        "Effective Date": a.effective_date.strftime("%d-%b-%Y"),
                        "Persistence Verified": f"{a.persistence_cycles} consecutive cycles",
                        "Evidence Note": a.evidence_note,
                    }
                )
            df_hikes = pd.DataFrame(hike_table)
            st.dataframe(df_hikes, use_container_width=True, hide_index=True)

        # Variable Bill Suppression Note
        variable_series = [s for s in filtered_series if s.is_variable_bill]
        if variable_series:
            with st.expander("ℹ️ Variable Utility Bills Suppressed from Price Hike Alerts"):
                st.caption(
                    "Utility debits fluctuate based on monthly usage (e.g. power consumption, postpaid mobile). "
                    "The pipeline automatically suppresses false hike alerts for these merchants using curated metadata:"
                )
                for vs in variable_series:
                    st.markdown(f"- **{vs.merchant_name}** ({vs.category}): Monthly amounts vary based on meter consumption.")

    # TAB 3: Spend & Category Analytics
    with tab3:
        st.markdown("### 📊 Spend & Category Analytics")
        st.caption(
            "See where money went by month and category. Past spend is money already paid; the commitment figures "
            "estimate what repeat payments could cost if they continue."
        )

        # Chart row 1
        col_c1, col_c2 = st.columns([3, 2])
        with col_c1:
            fig_timeline = create_monthly_burn_chart(summary.monthly_breakdown)
            if fig_timeline:
                st.plotly_chart(fig_timeline, use_container_width=True)
            else:
                st.info("Monthly spend timeline not available.")

        with col_c2:
            fig_donut = create_category_donut_chart(summary.category_totals)
            if fig_donut:
                st.plotly_chart(fig_donut, use_container_width=True)
            else:
                st.info("Category breakdown not available.")

        # Chart row 2: Cadence breakdown
        fig_cadence = create_cadence_breakdown_chart(filtered_series)
        if fig_cadence:
            st.plotly_chart(fig_cadence, use_container_width=True)

        # Category Breakdown Table
        st.markdown("#### 📋 Category Commitments & Observed Burn Summary")
        if summary.category_totals:
            cat_rows = []
            for cat, monthly_amt in sorted(summary.category_totals.items(), key=lambda x: -x[1]):
                annual_amt = summary.category_annual_commitments.get(cat, monthly_amt * 12.0)
                actual_spent = summary.category_actual_spend.get(cat, 0.0)
                share = (monthly_amt / summary.monthly_projected_commitment * 100) if summary.monthly_projected_commitment > 0 else 0
                cat_rows.append(
                    {
                        "Category": cat,
                        "Monthly Commitment": f"₹{monthly_amt:,.2f}",
                        "Annual Projected": f"₹{annual_amt:,.2f}",
                        "Share of Recurring Spend": f"{share:.1f}%",
                        "Observed Historical Spend": f"₹{actual_spent:,.2f}",
                    }
                )
            df_cat = pd.DataFrame(cat_rows)
            st.dataframe(df_cat, use_container_width=True, hide_index=True)

    # TAB 4: Review Candidates & Simulator
    with tab4:
        st.markdown("### 💡 What if you reviewed a payment?")
        st.caption(
            "Choose payments to explore a possible savings estimate. This is only a planning tool: it does not cancel "
            "anything, and the amount is not guaranteed savings."
        )
        render_savings_simulator(filtered_series, summary)

    # TAB 5: Cancellation & Mandate Guidance
    with tab5:
        st.markdown("### 🛑 Cancellation & Mandate Revocation Guidance")
        st.caption(
            "See how to contact the service and stop its renewal. ‘Verified’ means an official guide was checked; "
            "‘Generic’ means the app could not verify service-specific steps. To stop future charges, you may also need "
            "to revoke the payment permission in your bank or UPI app. This app does not perform either action for you."
        )

        st.markdown(
            """
            <div class="disclaimer-box">
                <strong>Crucial Regulatory Notice (RBI & NPCI):</strong><br>
                In Indian banking, cancelling a subscription in a merchant app only tells the merchant to stop requesting billing.
                <strong>It does NOT revoke your bank-level standing mandate or UPI AutoPay authorization.</strong><br>
                Conversely, revoking an e-mandate in your bank or UPI app withdraws payment authority, but does not cancel active contractual agreements.<br>
                <strong>Handle these separately where applicable:</strong> (1) Cancel or manage the service with the merchant, and (2) review or revoke its payment mandate in your bank or UPI app if you want to stop that payment authority. Revoking a mandate alone may not end a service contract or settle any amount already owed; check the merchant’s terms and your bank’s guidance.
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Overview Table of Detected Subscriptions & Cancellation Links
        st.markdown("#### 🔗 Cancellation Directory for Detected Services (Verified & Generic Guidance)")
        guide_rows = []
        for s in filtered_series:
            d = s.cancellation_details
            if d:
                guide_rows.append(
                    {
                        "Merchant": s.merchant_name,
                        "Category": s.category,
                        "Status": "✓ Verified Guide" if d.is_verified else "ℹ️ Generic Unverified",
                        "Portal / Settings Location": d.settings_location,
                        "Official Web Link": d.source_url if (d.is_verified and d.source_url) else "N/A (Generic In-App Guidance)",
                        "Last Verified": d.last_verified,
                    }
                )
        if guide_rows:
            df_guides = pd.DataFrame(guide_rows)
            st.dataframe(df_guides, use_container_width=True, hide_index=True)

        st.markdown("#### 🔗 Open a cancellation guide")
        st.caption(
            "These buttons open the merchant’s official instructions. You must complete cancellation on the merchant’s site or app. "
            "For unverified entries, the app shows safe general steps instead of guessing a link."
        )
        for s in filtered_series:
            details = s.cancellation_details
            if not details:
                continue
            status_label = "Verified official guide" if details.is_verified else "Generic guidance · no verified link"
            with st.expander(f"{details.merchant_name} · {status_label}"):
                st.caption(f"Settings area: {details.settings_location}")
                if details.is_verified and details.source_url.startswith("https://"):
                    st.link_button(
                        f"Open {details.merchant_name} official cancellation instructions",
                        details.source_url,
                        help="Opens the official guide. This app does not cancel the subscription for you.",
                    )
                    st.caption(f"Guide last checked: {details.last_verified}")
                else:
                    st.info(
                        "No merchant-specific web link has been verified. Open the service’s app or website directly and use these general steps."
                    )
                st.markdown("**Steps to cancel with the service**")
                for step_index, step in enumerate(details.steps, 1):
                    st.markdown(f"{step_index}. {step}")
                if details.mandate_guidance:
                    st.markdown("**Also check your bank or UPI payment permission**")
                    for mandate_step in details.mandate_guidance:
                        st.markdown(f"- {mandate_step}")

        # Regulatory Framework Explainer
        with st.expander("🏛️ Regulatory Basis & Bank E-Mandate Framework (RBI & NPCI)"):
            st.markdown(
                """
                - **NPCI UPI AutoPay Framework**: Recurring mandates on UPI (GPay, PhonePe, Paytm, BHIM, CRED).
                  You can pause, modify, or revoke mandates anytime using your UPI PIN inside your UPI app under
                  **Profile > UPI AutoPay / Recurring Payments**.
                - **RBI/2019-20/47 (Debit/Credit Cards & PPIs)**: Mandates that banks must send a pre-debit SMS/email
                  notification at least 24 hours prior to every recurring debit. Customers have the right to withdraw
                  debit authority at any time via their bank's NetBanking SI Hub.
                - **RBI/2019-20/139 (Recurring UPI Transactions)**: Formally applied the e-mandate framework to UPI,
                  mandating AFA (UPI PIN) on registration and customer-facing revocation facilities.
                - **RBI/2022-23/73 (AFA Threshold Limit)**: Raised the per-transaction limit for recurring debits without
                  an OTP from ₹5,000 to ₹15,000 across cards, PPIs, and UPI.
                """
            )

    # TAB 6: Statement Hygiene & Audit
    with tab6:
        st.markdown("### 🧾 Did the app account for every row?")
        st.caption(
            "This audit shows how statement lines were read, including payments, money coming in, refunds, duplicates, "
            "and rows the app could not confidently interpret. It also explains repeat purchases that were not treated as subscriptions."
        )
        render_statement_audit(
            cleaning_result=cleaning_result,
            rejections=rejections,
            raw_txns=cleaning_result.transactions,
            show_sensitive_details=show_sensitive,
        )


if __name__ == "__main__":
    main()
