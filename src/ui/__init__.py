"""UI package for The Auto Debits Nobody Can Find dashboard.

Stage 8 UI Modules:
- styles: CSS styling, accessible badges, responsive KPI cards.
- charts: Plotly visualizations for monthly spend, categories, cadence, savings.
- components: Reusable widgets, diagnostics, simulator, audit drawers.
- pipeline: Full src/ pipeline execution and demo loader helper.
"""

from src.ui.styles import (
    get_custom_css,
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
from src.ui.components import (
    render_privacy_banner,
    render_kpi_cards,
    render_price_alerts_banner,
    render_recurring_series_card,
    render_savings_simulator,
    render_statement_audit,
    mask_reference_id,
    mask_narration,
)
from src.ui.pipeline import (
    DEMO_FILES,
    load_file_content,
    run_pipeline,
)

__all__ = [
    "get_custom_css",
    "render_confidence_badge",
    "render_cadence_badge",
    "render_price_hike_badge",
    "render_review_badge",
    "render_paused_badge",
    "render_variable_badge",
    "render_kpi_card_html",
    "create_monthly_burn_chart",
    "create_category_donut_chart",
    "create_cadence_breakdown_chart",
    "create_savings_comparison_chart",
    "render_privacy_banner",
    "render_kpi_cards",
    "render_price_alerts_banner",
    "render_recurring_series_card",
    "render_savings_simulator",
    "render_statement_audit",
    "mask_reference_id",
    "mask_narration",
    "DEMO_FILES",
    "load_file_content",
    "run_pipeline",
]
