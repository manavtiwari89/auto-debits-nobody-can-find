"""Plotly chart components for The Auto Debits Nobody Can Find dashboard.

Stage 8 UI Module.
Generates responsive, publication-quality Plotly figures for monthly spend burn,
category commitments, cadence distributions, and potential savings comparisons.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional
import plotly.graph_objects as go
from src.models import RecurringSeries, CadenceType


CATEGORY_COLORS = {
    "Streaming & Media": "#E50914",
    "Software & Cloud": "#1A73E8",
    "Health & Fitness": "#00897B",
    "Delivery & Food": "#FF6D00",
    "Utilities & Bills": "#F9A825",
    "Telecom & Broadband": "#673AB7",
    "General / Other": "#78909C",
}

DEFAULT_PALETTE = [
    "#1E88E5", "#43A047", "#FB8C00", "#E53935",
    "#8E24AA", "#00ACC1", "#3949AB", "#D81B60",
]


def create_monthly_burn_chart(
    monthly_breakdown: Dict[str, Dict[str, Any]]
) -> Optional[go.Figure]:
    """
    Renders a stacked bar chart of actual recurring spend across calendar months ('YYYY-MM').
    Each bar is segmented by spending category.
    """
    if not monthly_breakdown:
        return None

    sorted_months = sorted(monthly_breakdown.keys())
    if not sorted_months:
        return None

    # Collect all categories present across months
    all_categories = set()
    for ym in sorted_months:
        entry = monthly_breakdown[ym]
        by_cat = entry.get("by_category", {})
        all_categories.update(by_cat.keys())

    sorted_categories = sorted(list(all_categories))

    fig = go.Figure()

    if not sorted_categories:
        # Fallback to single series if categories not populated
        y_values = [monthly_breakdown[ym].get("total_spend", 0.0) for ym in sorted_months]
        fig.add_trace(
            go.Bar(
                x=sorted_months,
                y=y_values,
                name="Total Spend",
                marker_color="#1E88E5",
                hovertemplate="<b>%{x}</b><br>Spend: ₹%{y:,.2f}<extra></extra>",
            )
        )
    else:
        for idx, cat in enumerate(sorted_categories):
            y_values = [
                monthly_breakdown[ym].get("by_category", {}).get(cat, 0.0)
                for ym in sorted_months
            ]
            color = CATEGORY_COLORS.get(cat, DEFAULT_PALETTE[idx % len(DEFAULT_PALETTE)])
            fig.add_trace(
                go.Bar(
                    x=sorted_months,
                    y=y_values,
                    name=cat,
                    marker_color=color,
                    hovertemplate=f"<b>{cat}</b><br>%{{x}}: ₹%{{y:,.2f}}<extra></extra>",
                )
            )

    fig.update_layout(
        barmode="stack",
        template="plotly_white",
        title=dict(
            text="<b>Monthly Spend Burn (Observed)</b>",
            x=0.02,
            xanchor="left",
            y=0.98,
            yanchor="top",
            font=dict(size=14),
        ),
        xaxis=dict(title="Calendar Month", tickangle=-30),
        yaxis=dict(title="Observed Spend (₹)", tickprefix="₹", tickformat=","),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.28,
            xanchor="center",
            x=0.5,
            font=dict(size=11),
        ),
        margin=dict(l=40, r=20, t=65, b=105),
        height=420,
    )
    return fig


def create_category_donut_chart(
    category_totals: Dict[str, float]
) -> Optional[go.Figure]:
    """
    Renders an interactive donut chart showing category distribution of monthly commitments.
    """
    if not category_totals:
        return None

    # Filter zero or negative amounts
    valid_items = [(cat, amt) for cat, amt in category_totals.items() if amt > 0]
    if not valid_items:
        return None

    labels = [cat for cat, _ in valid_items]
    values = [amt for _, amt in valid_items]
    colors = [CATEGORY_COLORS.get(cat, DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)]) for i, cat in enumerate(labels)]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.48,
                marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
                textinfo="percent+label",
                hovertemplate="<b>%{label}</b><br>Monthly Commitment: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
            )
        ]
    )

    fig.update_layout(
        template="plotly_white",
        title=dict(text="<b>Monthly Commitment by Category</b>", font=dict(size=14)),
        showlegend=False,
        margin=dict(l=20, r=20, t=40, b=20),
        height=360,
    )
    return fig


def create_cadence_breakdown_chart(
    series_list: List[RecurringSeries]
) -> Optional[go.Figure]:
    """
    Renders a grouped bar chart of recurring series count and annual commitment by cadence.
    """
    if not series_list:
        return None

    cadence_counts: Dict[str, int] = {}
    cadence_annual: Dict[str, float] = {}

    for s in series_list:
        c_label = s.cadence.value
        cadence_counts[c_label] = cadence_counts.get(c_label, 0) + 1
        cadence_annual[c_label] = cadence_annual.get(c_label, 0.0) + s.annual_equivalent

    labels = sorted(cadence_counts.keys())
    counts = [cadence_counts[c] for c in labels]
    annual_commitments = [round(cadence_annual[c], 2) for c in labels]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=labels,
            y=annual_commitments,
            name="Annual Commitment (₹)",
            marker_color="#3949AB",
            yaxis="y",
            hovertemplate="<b>%{x}</b><br>Annual Cost: ₹%{y:,.2f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=labels,
            y=counts,
            name="Subscription Count",
            marker=dict(color="#FF6F00", size=10),
            line=dict(color="#FF6F00", width=2),
            mode="lines+markers+text",
            text=[f"{c} sub(s)" for c in counts],
            textposition="top center",
            yaxis="y2",
            hovertemplate="<b>%{x}</b><br>Count: %{y}<extra></extra>",
        )
    )

    fig.update_layout(
        template="plotly_white",
        title=dict(text="<b>Recurring Commitments by Cadence Type</b>", font=dict(size=14)),
        xaxis=dict(title="Cadence Schedule"),
        yaxis=dict(
            title="Annual Commitment (₹)",
            tickprefix="₹",
            tickformat=",",
            side="left",
        ),
        yaxis2=dict(
            title="Active Subscriptions",
            overlaying="y",
            side="right",
            showgrid=False,
            rangemode="tozero",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
        margin=dict(l=40, r=40, t=60, b=40),
        height=360,
    )
    return fig


def create_savings_comparison_chart(
    current_annual: float,
    potential_savings: float
) -> Optional[go.Figure]:
    """
    Renders a waterfall/bar comparison between current annual run-rate commitment
    and potential reduced annual commitment if review candidates are discontinued.
    """
    if current_annual <= 0:
        return None

    retained = max(0.0, current_annual - potential_savings)

    fig = go.Figure(
        data=[
            go.Bar(
                name="Annual Commitment Comparison",
                x=["Current Commitment", "Potential Savings", "Retained Commitment"],
                y=[current_annual, -potential_savings, retained],
                marker_color=["#1E88E5", "#43A047", "#5C6BC0"],
                text=[
                    f"₹{current_annual:,.2f}",
                    f"-₹{potential_savings:,.2f}",
                    f"₹{retained:,.2f}",
                ],
                textposition="auto",
                hovertemplate="<b>%{x}</b><br>Amount: ₹%{y:,.2f}<extra></extra>",
            )
        ]
    )

    fig.update_layout(
        template="plotly_white",
        title=dict(text="<b>Annual Commitment vs Potential Savings Simulation</b>", font=dict(size=14)),
        yaxis=dict(title="Annual Projected Commitment (₹)", tickprefix="₹", tickformat=","),
        showlegend=False,
        margin=dict(l=40, r=20, t=50, b=40),
        height=340,
    )
    return fig
