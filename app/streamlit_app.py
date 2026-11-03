"""The Auto Debits Nobody Can Find - Streamlit Application.

A local, privacy-first dashboard for Indian banking users to detect hidden
recurring payments, cadence evidence, price hikes, and verified cancellation steps.
"""

from __future__ import annotations
import io
import os
import streamlit as st
import pandas as pd
from datetime import date
from typing import List, Optional

from app.models import RecurringSeries, ConfidenceLevel, CadenceType
from app.parser import BankStatementParser
from app.normalizer import NarrationNormalizer
from app.detector import RecurringDetector
from app.price_tracker import PriceTracker
from app.cancellation import CancellationRegistry
from app.totals import CostEstimator
from app.demo_data import generate_hdfc_statement, generate_sbi_statement, generate_icici_statement


st.set_page_config(
    page_title="Auto Debits Nobody Can Find | Indian Banking Audit",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        border-left: 5px solid #1f77b4;
        margin-bottom: 12px;
    }
    .badge-high {
        background-color: #d4edda;
        color: #155724;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.85em;
    }
    .badge-medium {
        background-color: #fff3cd;
        color: #856404;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.85em;
    }
    .badge-low {
        background-color: #f8d7da;
        color: #721c24;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.85em;
    }
    .price-alert-box {
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
        border-radius: 6px;
        padding: 12px;
        margin-bottom: 10px;
    }
    .privacy-pill {
        display: inline-block;
        background-color: #e8f5e9;
        color: #2e7d32;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)


def analyze_statement_content(csv_content: str, source_label: str) -> List[RecurringSeries]:
    """Runs the full analysis pipeline on CSV content."""
    # 1. Parse CSV
    txns = BankStatementParser.parse_csv_content(csv_content, source_label)
    
    # 2. Enrich with merchant normalization and mandate detection
    for t in txns:
        NarrationNormalizer.enrich_transaction(t)
        
    # 3. Detect recurring series
    series_list = RecurringDetector.detect_recurring(txns)
    
    # 4. Detect price changes
    PriceTracker.attach_price_alerts(series_list)
    
    # 5. Attach verified cancellation guidance
    CancellationRegistry.attach_cancellation_guides(series_list)
    
    return series_list, txns


def main():
    # Header
    st.title("🔍 The Auto Debits Nobody Can Find")
    st.markdown(
        "<div class='privacy-pill'>🛡️ In-Memory Processing • No External API Calls • Sensitive Details Masked by Default</div>",
        unsafe_allow_html=True
    )
    st.markdown(
        "Audit Indian bank statement CSVs (HDFC, ICICI, SBI, Axis, Kotak) to identify stealth recurring debits, "
        "UPI Autopay mandates, quiet price hikes, and verified cancellation guidance."
    )

    # Sidebar Controls
    st.sidebar.header("📁 Bank Statement Import")
    data_source = st.sidebar.radio(
        "Choose Data Input Method:",
        ["Upload CSV Statement", "Load Synthetic Demo Data"]
    )

    csv_content: Optional[str] = None
    statement_name = "User Statement"

    if data_source == "Upload CSV Statement":
        uploaded_file = st.sidebar.file_uploader(
            "Upload your bank statement (CSV format):",
            type=["csv"],
            help="Upload statement exported from HDFC, SBI, ICICI, Axis, or Kotak Netbanking."
        )
        if uploaded_file is not None:
            csv_content = io.StringIO(uploaded_file.getvalue().decode("utf-8", errors="replace")).read()
            statement_name = uploaded_file.name
    else:
        demo_choice = st.sidebar.selectbox(
            "Select Demo Bank Statement:",
            ["HDFC Bank (12-Month Realistic Audit)", "SBI Bank (6-Month Statement)", "ICICI Bank (5-Month Statement)"]
        )
        if st.sidebar.button("Load Demo Statement", use_container_width=True) or "loaded_demo" not in st.session_state:
            st.session_state["loaded_demo"] = demo_choice
            
        choice = st.session_state.get("loaded_demo", demo_choice)
        if "HDFC" in choice:
            csv_content, _ = generate_hdfc_statement()
            statement_name = "HDFC_Demo_Audit.csv"
        elif "SBI" in choice:
            csv_content = generate_sbi_statement()
            statement_name = "SBI_Demo_Audit.csv"
        else:
            csv_content = generate_icici_statement()
            statement_name = "ICICI_Demo_Audit.csv"

    # Confidence Filter
    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Filters")
    min_confidence = st.sidebar.selectbox(
        "Minimum Confidence Rating:",
        ["All (High, Medium, Low)", "Medium & High", "High Only"],
        index=0
    )

    if not csv_content:
        st.info("👈 Please upload a bank statement CSV or choose a Synthetic Demo from the sidebar to begin.")
        return

    # Run Analysis
    with st.spinner("Analyzing bank transactions, cadence intervals, and mandates..."):
        series_list, raw_txns = analyze_statement_content(csv_content, statement_name)

    # Filter by confidence
    if min_confidence == "High Only":
        filtered_series = [s for s in series_list if s.confidence == ConfidenceLevel.HIGH]
    elif min_confidence == "Medium & High":
        filtered_series = [s for s in series_list if s.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)]
    else:
        filtered_series = series_list

    # Compute Summary
    summary = CostEstimator.calculate_summary(filtered_series)

    # Top KPI Cards
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Monthly Run-rate", f"₹{summary.total_monthly_recurring:,.2f}")
    with col2:
        st.metric("Annual Recurring Cost", f"₹{summary.total_annual_recurring:,.2f}")
    with col3:
        st.metric("Active Subscriptions", summary.active_subscriptions_count)
    with col4:
        st.metric("Price Hikes Detected", summary.price_hike_count, delta=f"{summary.price_hike_count} Alert(s)" if summary.price_hike_count else None, delta_color="inverse")
    with col5:
        st.metric("Discretionary Savings", f"₹{summary.potential_annual_savings:,.2f}")

    # Price Hike Alert Banner
    price_alerts = [s for s in filtered_series if s.price_alert]
    if price_alerts:
        st.markdown("### ⚠️ Stealth Price Hikes Detected")
        for s in price_alerts:
            alert = s.price_alert
            st.markdown(f"""
            <div class='price-alert-box'>
                <strong>🔔 {s.merchant_name}</strong>: {alert.details}
            </div>
            """, unsafe_allow_html=True)

    # Main Tabs
    tab1, tab2, tab3 = st.tabs(["📋 Recurring Subscriptions & Mandates", "📊 Category Run-Rate Breakdown", "🧾 Raw Statement Audit"])

    with tab1:
        st.markdown(f"### Detected Auto-Debits ({len(filtered_series)})")
        if not filtered_series:
            st.success("🎉 No recurring auto-debits detected matching the current filter.")
        else:
            for s in filtered_series:
                conf_badge = f"<span class='badge-{s.confidence.value.lower()}'>{s.confidence.value.upper()} CONFIDENCE</span>"
                hike_badge = " <span style='color:#b78103; font-weight:bold;'>[⚠️ Price Hike]</span>" if s.price_alert else ""

                header_text = f"**{s.merchant_name}** • {s.category} • ₹{s.expected_amount:,.2f} ({s.cadence.value}) — {s.confidence.value} Confidence"
                with st.expander(f"{s.merchant_name} — ₹{s.expected_amount:,.2f} / {s.cadence.value} ({s.confidence.value} Confidence)"):
                    c1, c2 = st.columns([1, 1])

                    with c1:
                        st.markdown("#### 🔍 Evidence & Cadence Details")
                        st.markdown(f"- **Cadence:** {s.cadence.value} (avg interval: {s.interval_mean_days} days, std: {s.interval_std_days} days)")
                        st.markdown(f"- **Confidence Score:** {s.confidence_score * 100:.0f}% ({s.confidence.value})")
                        st.markdown(f"- **Monthly Equivalent:** ₹{s.monthly_equivalent_amount:,.2f}")
                        st.markdown(f"- **Annual Projected Cost:** ₹{s.annual_equivalent_amount:,.2f}")
                        st.markdown("**Evidence Breakdown:**")
                        for reason in s.evidence_reasons:
                            st.markdown(f"  - {reason}")

                    with c2:
                        st.markdown("#### 🛑 Verified Cancellation Guidance")
                        guide = s.cancellation_info
                        if guide:
                            if guide.is_verified_source and guide.direct_url:
                                st.success(f"✅ **Verified Source ({guide.source_domain})** — Verified as of {guide.last_verified}")
                                st.markdown(f"[🔗 Open Direct Cancellation Portal ({guide.portal_name})]({guide.direct_url})")
                            else:
                                st.info("ℹ️ **Standard Bank-Level Cancellation (RBI E-Mandate Framework)**")
                                st.caption("No public self-serve link verified. Revoke directly from your bank or payment app.")

                            st.markdown("**Actionable Steps to Stop Charges:**")
                            for step_idx, step in enumerate(guide.steps, 1):
                                st.markdown(f"{step_idx}. {step}")

                    # Historical Transactions Table
                    st.markdown("##### 📜 Historical Billing Occurrences")
                    df_history = pd.DataFrame([
                        {
                            "Date": t.date.strftime("%d-%b-%Y"),
                            "Narration": t.narration,
                            "Amount": f"₹{t.amount:,.2f}",
                            "Mandate Indicator": "✅ Yes" if t.has_mandate_indicator else "No"
                        }
                        for t in s.transactions
                    ])
                    st.dataframe(df_history, use_container_width=True)

    with tab2:
        st.markdown("### Spending by Category")
        if summary.category_breakdown:
            cat_df = pd.DataFrame([
                {
                    "Category": k,
                    "Monthly Cost (₹)": v,
                    "Annual Projected (₹)": v * 12,
                    "% of Recurring Total": f"{(v / summary.total_monthly_recurring * 100):.1f}%" if summary.total_monthly_recurring > 0 else "0%"
                }
                for k, v in sorted(summary.category_breakdown.items(), key=lambda x: -x[1])
            ])
            st.dataframe(cat_df, use_container_width=True)
            st.bar_chart(cat_df.set_index("Category")["Monthly Cost (₹)"])
        else:
            st.info("No category data available.")

    with tab3:
        st.markdown(f"### Total Parsed Transactions ({len(raw_txns)})")
        if raw_txns:
            raw_df = pd.DataFrame([
                {
                    "Date": t.date.strftime("%d-%b-%Y"),
                    "Narration": t.narration,
                    "Normalized Merchant": t.normalized_merchant or "-",
                    "Amount": f"₹{t.amount:,.2f}",
                    "Type": "Debit" if t.is_debit else "Credit",
                    "Mandate Flag": "Yes" if t.has_mandate_indicator else "No"
                }
                for t in raw_txns
            ])
            st.dataframe(raw_df, use_container_width=True)


if __name__ == "__main__":
    main()
