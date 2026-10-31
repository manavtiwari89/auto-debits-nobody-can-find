"""Custom CSS and HTML styling helpers for The Auto Debits Nobody Can Find dashboard.

Stage 8 UI Module.
Provides accessible, responsive styles, confidence badges, privacy badges,
and card layouts with consistent Indian banking fintech visual language.
"""

from __future__ import annotations
from typing import Optional
from src.models import ConfidenceLevel, CadenceType, RowStatus


CUSTOM_CSS = """
<style>
    /* Global Container Adjustments */
    .block-container {
        padding-top: 1.8rem;
        padding-bottom: 3rem;
        max-width: 1300px;
    }

    /* Privacy & Security Header Pill */
    .privacy-vault-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background-color: #e8f5e9;
        color: #1b5e20;
        border: 1px solid #a5d6a7;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 1rem;
        letter-spacing: 0.2px;
    }

    /* Summary Metric Card */
    .kpi-card {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 14px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .kpi-card:hover {
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);
        border-color: #b0bec5;
    }
    .kpi-card-header {
        font-size: 0.82rem;
        text-transform: uppercase;
        font-weight: 700;
        color: #546e7a;
        margin-bottom: 6px;
        letter-spacing: 0.5px;
    }
    .kpi-card-value {
        font-size: 1.65rem;
        font-weight: 700;
        color: #1a237e;
        line-height: 1.2;
    }
    .kpi-card-sub {
        font-size: 0.78rem;
        color: #78909c;
        margin-top: 6px;
    }
    .kpi-card-delta-pos {
        color: #2e7d32;
        font-weight: 600;
        font-size: 0.8rem;
    }
    .kpi-card-delta-alert {
        color: #c62828;
        font-weight: 600;
        font-size: 0.8rem;
    }

    /* Confidence Badges */
    .badge-high {
        background-color: #e8f5e9;
        color: #1b5e20;
        border: 1px solid #81c784;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.78rem;
        display: inline-block;
        white-space: nowrap;
    }
    .badge-medium {
        background-color: #fff8e1;
        color: #f57f17;
        border: 1px solid #ffd54f;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.78rem;
        display: inline-block;
        white-space: nowrap;
    }
    .badge-low {
        background-color: #fbe9e7;
        color: #bf360c;
        border: 1px solid #ffab91;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.78rem;
        display: inline-block;
        white-space: nowrap;
    }

    /* Cadence Badges */
    .badge-cadence {
        background-color: #e3f2fd;
        color: #0d47a1;
        border: 1px solid #90caf9;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.78rem;
        display: inline-block;
    }

    /* Tag & Marker Badges */
    .badge-price-hike {
        background-color: #ffebee;
        color: #c62828;
        border: 1px solid #ef9a9a;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 700;
        font-size: 0.78rem;
        display: inline-block;
    }
    .badge-review {
        background-color: #ede7f6;
        color: #4a148c;
        border: 1px solid #b39ddb;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.78rem;
        display: inline-block;
    }
    .badge-paused {
        background-color: #fff3e0;
        color: #e65100;
        border: 1px solid #ffb74d;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.78rem;
        display: inline-block;
    }
    .badge-variable {
        background-color: #e0f2f1;
        color: #004d40;
        border: 1px solid #80cbc4;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.78rem;
        display: inline-block;
    }
    .badge-mandate {
        background-color: #e8eaf6;
        color: #1a237e;
        border: 1px solid #9fa8da;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.78rem;
        display: inline-block;
    }

    /* Price Alert Box */
    .price-alert-box {
        background-color: #fff8e1;
        border-left: 5px solid #ffb300;
        border-radius: 6px;
        padding: 12px 16px;
        margin-bottom: 12px;
        color: #37474f;
    }
    .price-alert-title {
        font-weight: 700;
        color: #d84315;
        font-size: 0.95rem;
    }

    /* Disclaimer & Informational Box */
    .disclaimer-box {
        background-color: #f5f7fa;
        border: 1px solid #cfd8dc;
        border-left: 4px solid #78909c;
        border-radius: 6px;
        padding: 12px 14px;
        font-size: 0.82rem;
        color: #455a64;
        margin: 12px 0;
        line-height: 1.45;
    }

    /* Verification Status Banner */
    .verified-banner {
        background-color: #f1f8e9;
        border-left: 4px solid #558b2f;
        padding: 8px 12px;
        border-radius: 4px;
        font-size: 0.85rem;
        color: #33691e;
        margin-bottom: 10px;
    }
    .unverified-banner {
        background-color: #f9fbe7;
        border-left: 4px solid #afb42b;
        padding: 8px 12px;
        border-radius: 4px;
        font-size: 0.85rem;
        color: #827717;
        margin-bottom: 10px;
    }

    /* Section Subheadings */
    .section-title {
        font-size: 1.15rem;
        font-weight: 700;
        color: #263238;
        margin-top: 12px;
        margin-bottom: 8px;
    }
</style>
"""


def get_custom_css() -> str:
    """Returns the CSS string for inclusion in st.markdown."""
    return CUSTOM_CSS


def render_confidence_badge(level: ConfidenceLevel, score: Optional[float] = None) -> str:
    """Formats an accessible HTML confidence badge."""
    score_str = f" ({score:.0f}/100)" if score is not None else ""
    if level == ConfidenceLevel.HIGH:
        return f'<span class="badge-high">✓ High Confidence{score_str}</span>'
    elif level == ConfidenceLevel.MEDIUM:
        return f'<span class="badge-medium">⚡ Medium Confidence{score_str}</span>'
    else:
        return f'<span class="badge-low">? Low Confidence{score_str}</span>'


def render_cadence_badge(cadence: CadenceType) -> str:
    """Formats a clean cadence pill badge."""
    return f'<span class="badge-cadence">🔄 {cadence.value}</span>'


def render_price_hike_badge(formatted_diff: str) -> str:
    """Formats a price hike badge with difference percentage."""
    return f'<span class="badge-price-hike">⚠️ Price Hike {formatted_diff}</span>'


def render_review_badge() -> str:
    """Formats a review candidate tag."""
    return '<span class="badge-review">💡 Review Candidate</span>'


def render_paused_badge() -> str:
    """Formats a paused/resumed badge."""
    return '<span class="badge-paused">⏸️ Paused & Resumed</span>'


def render_variable_badge() -> str:
    """Formats a variable bill badge."""
    return '<span class="badge-variable">⚡ Variable Bill</span>'


def render_kpi_card_html(
    label: str,
    value: str,
    subtext: str = "",
    delta: Optional[str] = None,
    delta_type: str = "pos",
) -> str:
    """Renders a responsive KPI metric card in HTML."""
    delta_class = "kpi-card-delta-alert" if delta_type == "alert" else "kpi-card-delta-pos"
    delta_html = f'<div class="{delta_class}">{delta}</div>' if delta else ""
    sub_html = f'<div class="kpi-card-sub">{subtext}</div>' if subtext else ""

    return f"""
    <div class="kpi-card">
        <div class="kpi-card-header">{label}</div>
        <div class="kpi-card-value">{value}</div>
        {delta_html}
        {sub_html}
    </div>
    """
