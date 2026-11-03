"""Zero-Dependency Local Web Application for The Auto Debits Nobody Can Find.

Uses Python standard library (http.server) to deliver an interactive UI with zero
external package dependencies. Uploaded statements are processed by this server;
when hosted remotely, that server is not the user's device.
"""

from __future__ import annotations
import os
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import List, Dict, Any

from app.models import RecurringSeries, ConfidenceLevel, CadenceType
from app.parser import BankStatementParser
from app.normalizer import NarrationNormalizer
from app.detector import RecurringDetector
from app.price_tracker import PriceTracker
from app.cancellation import CancellationRegistry
from app.totals import CostEstimator
from app.demo_data import generate_hdfc_statement, generate_sbi_statement, generate_icici_statement


def process_csv_payload(csv_text: str, source_label: str = "Statement") -> Dict[str, Any]:
    """Runs the analysis pipeline and produces JSON-serializable results."""
    txns = BankStatementParser.parse_csv_content(csv_text, source_label)
    for t in txns:
        NarrationNormalizer.enrich_transaction(t)
    series_list = RecurringDetector.detect_recurring(txns)
    PriceTracker.attach_price_alerts(series_list)
    CancellationRegistry.attach_cancellation_guides(series_list)
    summary = CostEstimator.calculate_summary(series_list)

    series_data = []
    for s in series_list:
        series_data.append({
            "series_id": s.series_id,
            "merchant_name": s.merchant_name,
            "category": s.category,
            "cadence": s.cadence.value,
            "confidence": s.confidence.value,
            "confidence_score": s.confidence_score,
            "expected_amount": s.expected_amount,
            "monthly_equivalent_amount": s.monthly_equivalent_amount,
            "annual_equivalent_amount": s.annual_equivalent_amount,
            "interval_mean_days": s.interval_mean_days,
            "interval_std_days": s.interval_std_days,
            "evidence_reasons": s.evidence_reasons,
            "price_alert": {
                "old_amount": s.price_alert.old_amount,
                "new_amount": s.price_alert.new_amount,
                "percent_change": s.price_alert.percent_change,
                "effective_date": str(s.price_alert.effective_date),
                "details": s.price_alert.details,
                "formatted_diff": s.price_alert.formatted_difference
            } if s.price_alert else None,
            "cancellation": {
                "portal_name": s.cancellation_info.portal_name,
                "direct_url": s.cancellation_info.direct_url,
                "is_verified_source": s.cancellation_info.is_verified_source,
                "source_domain": s.cancellation_info.source_domain,
                "last_verified": s.cancellation_info.last_verified,
                "steps": s.cancellation_info.steps,
                "explanation": s.cancellation_info.guidance_source_explanation
            } if s.cancellation_info else None,
            "transactions": [
                {
                    "date": str(t.date),
                    "narration": t.narration,
                    "amount": t.amount,
                    "has_mandate": t.has_mandate_indicator
                }
                for t in s.transactions
            ]
        })

    raw_txns_data = [
        {
            "date": str(t.date),
            "narration": t.narration,
            "merchant": t.normalized_merchant or "-",
            "amount": t.amount,
            "is_debit": t.is_debit,
            "has_mandate": t.has_mandate_indicator
        }
        for t in txns
    ]

    return {
        "status": "success",
        "summary": {
            "total_monthly": summary.total_monthly_recurring,
            "total_annual": summary.total_annual_recurring,
            "active_count": summary.active_subscriptions_count,
            "price_hike_count": summary.price_hike_count,
            "potential_savings": summary.potential_annual_savings,
            "category_breakdown": summary.category_breakdown
        },
        "series": series_data,
        "raw_transactions": raw_txns_data
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Auto Debits Nobody Can Find | Indian Banking Audit</title>
    <style>
        :root {
            --primary: #1e40af;
            --primary-light: #3b82f6;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --danger: #dc2626;
            --warning: #d97706;
            --success: #16a34a;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 24px; line-height: 1.5; }
        .container { max-width: 1200px; margin: 0 auto; }
        header { margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 16px; }
        h1 { font-size: 1.8rem; font-weight: 700; color: #0f172a; display: flex; align-items: center; gap: 8px; }
        .subtitle { color: var(--text-muted); font-size: 0.95rem; margin-top: 4px; }
        .privacy-pill { display: inline-flex; align-items: center; gap: 6px; background: #ecfdf5; color: #065f46; padding: 6px 14px; border-radius: 9999px; font-size: 0.82rem; font-weight: 600; margin-top: 10px; border: 1px solid #a7f3d0; }
        .grid-kpi { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .kpi-title { font-size: 0.8rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; letter-spacing: 0.05em; }
        .kpi-value { font-size: 1.6rem; font-weight: 700; margin-top: 4px; color: var(--text); }
        .kpi-alert { color: var(--danger); }
        .panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 24px; }
        .btn { background: var(--primary); color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 0.9rem; transition: background 0.2s; }
        .btn:hover { background: var(--primary-light); }
        .btn-outline { background: white; color: var(--text); border: 1px solid var(--border); }
        .btn-outline:hover { background: #f1f5f9; }
        .demo-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 12px; }
        .alert-banner { background: #fffbeb; border: 1px solid #fde68a; border-left: 5px solid var(--warning); border-radius: 6px; padding: 12px 16px; margin-bottom: 20px; }
        .alert-item { margin-top: 6px; font-size: 0.9rem; }
        .series-card { background: white; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
        .series-header { padding: 16px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; user-select: none; background: #fafafa; }
        .series-header:hover { background: #f1f5f9; }
        .series-title { font-size: 1.1rem; font-weight: 600; display: flex; align-items: center; gap: 10px; }
        .badge { font-size: 0.75rem; padding: 3px 8px; border-radius: 4px; font-weight: 600; }
        .badge-high { background: #dcfce7; color: #166534; }
        .badge-medium { background: #fef3c7; color: #92400e; }
        .badge-low { background: #fee2e2; color: #991b1b; }
        .series-body { padding: 16px; border-top: 1px solid var(--border); display: none; }
        .series-body.open { display: block; }
        .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }
        table { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-top: 10px; }
        th, td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
        th { background: #f8fafc; font-weight: 600; }
        .cancellation-box { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px; padding: 12px; }
        .unverified-box { background: #f8fafc; border: 1px solid var(--border); border-radius: 6px; padding: 12px; }
        ol { padding-left: 20px; margin-top: 8px; }
        li { margin-bottom: 4px; font-size: 0.88rem; }
        .tab-btn { background: none; border: none; padding: 10px 16px; font-size: 0.95rem; font-weight: 600; color: var(--text-muted); cursor: pointer; border-bottom: 2px solid transparent; }
        .tab-btn.active { color: var(--primary); border-bottom-color: var(--primary); }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🔍 The Auto Debits Nobody Can Find</h1>
            <p class="subtitle">HackFront 2026 • Privacy-First Indian Bank Statement Subscription & Stealth Debit Audit</p>
            <div class="privacy-pill">🛡️ Processed by This Server • No External API Calls</div>
        </header>

        <section class="panel">
            <h3>📁 Import Bank Statement (HDFC, SBI, ICICI, Axis, Kotak)</h3>
            <p class="subtitle">Select a pre-configured synthetic demo statement or upload your local bank CSV.</p>
            <div class="demo-bar">
                <button class="btn" onclick="loadDemo('hdfc')">Load HDFC 12-Month Demo</button>
                <button class="btn btn-outline" onclick="loadDemo('sbi')">Load SBI 6-Month Demo</button>
                <button class="btn btn-outline" onclick="loadDemo('icici')">Load ICICI 5-Month Demo</button>
                <input type="file" id="csvFileInput" accept=".csv" style="display:none" onchange="handleFileUpload(event)">
                <button class="btn btn-outline" onclick="document.getElementById('csvFileInput').click()">Upload Custom CSV</button>
            </div>
        </section>

        <div id="resultsArea" style="display:none;">
            <div class="grid-kpi">
                <div class="card">
                    <div class="kpi-title">Monthly Run-Rate</div>
                    <div class="kpi-value" id="kpiMonthly">₹0</div>
                </div>
                <div class="card">
                    <div class="kpi-title">Annual Recurring Cost</div>
                    <div class="kpi-value" id="kpiAnnual">₹0</div>
                </div>
                <div class="card">
                    <div class="kpi-title">Active Subscriptions</div>
                    <div class="kpi-value" id="kpiCount">0</div>
                </div>
                <div class="card">
                    <div class="kpi-title">Price Hikes Detected</div>
                    <div class="kpi-value kpi-alert" id="kpiHikes">0</div>
                </div>
                <div class="card">
                    <div class="kpi-title">Discretionary Savings</div>
                    <div class="kpi-value" style="color:var(--success);" id="kpiSavings">₹0</div>
                </div>
            </div>

            <div id="priceHikeBanner" class="alert-banner" style="display:none;">
                <strong>⚠️ Stealth Price Hikes Detected</strong>
                <div id="priceHikeList"></div>
            </div>

            <div style="margin-bottom: 16px; border-bottom: 1px solid var(--border);">
                <button class="tab-btn active" onclick="switchTab('tabSubscriptions')">📋 Recurring Subscriptions (<span id="subCountTab">0</span>)</button>
                <button class="tab-btn" onclick="switchTab('tabCategories')">📊 Category Breakdown</button>
                <button class="tab-btn" onclick="switchTab('tabRaw')">🧾 All Transactions</button>
            </div>

            <div id="tabSubscriptions">
                <div id="seriesContainer"></div>
            </div>

            <div id="tabCategories" style="display:none;" class="panel">
                <h3>Spending by Category</h3>
                <div id="categoryContainer"></div>
            </div>

            <div id="tabRaw" style="display:none;" class="panel">
                <h3>All Parsed Transactions</h3>
                <div style="max-height: 400px; overflow-y: auto;">
                    <table id="rawTxnTable">
                        <thead>
                            <tr><th>Date</th><th>Narration</th><th>Matched Merchant</th><th>Amount</th><th>Type</th><th>Mandate?</th></tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentData = null;

        function formatINR(val) {
            return '₹' + Number(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }

        async function loadDemo(bank) {
            const res = await fetch('/api/demo?bank=' + bank);
            const data = await res.json();
            renderResults(data);
        }

        function handleFileUpload(e) {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = async function(evt) {
                const text = evt.target.result;
                const res = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ csv: text, name: file.name })
                });
                const data = await res.json();
                renderResults(data);
            };
            reader.readAsText(file);
        }

        function switchTab(tabId) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
            ['tabSubscriptions', 'tabCategories', 'tabRaw'].forEach(t => {
                document.getElementById(t).style.display = (t === tabId) ? 'block' : 'none';
            });
        }

        function toggleSeries(idx) {
            const body = document.getElementById('series-body-' + idx);
            body.classList.toggle('open');
        }

        function renderResults(data) {
            currentData = data;
            document.getElementById('resultsArea').style.display = 'block';
            
            // KPIs
            document.getElementById('kpiMonthly').innerText = formatINR(data.summary.total_monthly);
            document.getElementById('kpiAnnual').innerText = formatINR(data.summary.total_annual);
            document.getElementById('kpiCount').innerText = data.summary.active_count;
            document.getElementById('kpiHikes').innerText = data.summary.price_hike_count;
            document.getElementById('kpiSavings').innerText = formatINR(data.summary.potential_savings);
            document.getElementById('subCountTab').innerText = data.series.length;

            // Price Hikes Banner
            const hikes = data.series.filter(s => s.price_alert);
            const hikeBanner = document.getElementById('priceHikeBanner');
            const hikeList = document.getElementById('priceHikeList');
            hikeList.innerHTML = '';
            if (hikes.length > 0) {
                hikeBanner.style.display = 'block';
                hikes.forEach(s => {
                    const item = document.createElement('div');
                    item.className = 'alert-item';
                    item.innerHTML = `🔔 <strong>${s.merchant_name}</strong>: ${s.price_alert.details}`;
                    hikeList.appendChild(item);
                });
            } else {
                hikeBanner.style.display = 'none';
            }

            // Series List
            const seriesContainer = document.getElementById('seriesContainer');
            seriesContainer.innerHTML = '';
            data.series.forEach((s, idx) => {
                const card = document.createElement('div');
                card.className = 'series-card';
                const badgeClass = 'badge-' + s.confidence.toLowerCase();
                const hikeTag = s.price_alert ? '<span style="color:#d97706; font-weight:700; font-size:0.8rem; margin-left:8px;">[⚠️ Price Hike]</span>' : '';
                
                let cancelHtml = '';
                if (s.cancellation) {
                    const c = s.cancellation;
                    if (c.is_verified_source && c.direct_url) {
                        cancelHtml = `
                            <div class="cancellation-box">
                                <strong style="color:var(--success);">✅ Verified Canonical Source (${c.source_domain})</strong>
                                <div style="font-size:0.8rem; color:#15803d;">Verified as of ${c.last_verified}</div>
                                <div style="margin: 8px 0;">
                                    <a href="${c.direct_url}" target="_blank" style="color:var(--primary); font-weight:600;">🔗 Direct Cancellation Portal (${c.portal_name})</a>
                                </div>
                                <ol>${c.steps.map(step => `<li>${step}</li>`).join('')}</ol>
                            </div>
                        `;
                    } else {
                        cancelHtml = `
                            <div class="unverified-box">
                                <strong>ℹ️ Bank-Level E-Mandate Cancellation (RBI Framework)</strong>
                                <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:6px;">${c.explanation}</div>
                                <ol>${c.steps.map(step => `<li>${step}</li>`).join('')}</ol>
                            </div>
                        `;
                    }
                }

                card.innerHTML = `
                    <div class="series-header" onclick="toggleSeries(${idx})">
                        <div class="series-title">
                            <span>${s.merchant_name}</span>
                            <span class="badge ${badgeClass}">${s.confidence.toUpperCase()} CONFIDENCE</span>
                            ${hikeTag}
                        </div>
                        <div style="font-weight:700; color:var(--text);">
                            ${formatINR(s.expected_amount)} <span style="font-size:0.85rem; font-weight:normal; color:var(--text-muted);">/ ${s.cadence}</span>
                        </div>
                    </div>
                    <div id="series-body-${idx}" class="series-body">
                        <div class="two-col">
                            <div>
                                <h4 style="margin-bottom:8px;">🔍 Cadence & Evidence Details</h4>
                                <p style="font-size:0.9rem;"><strong>Category:</strong> ${s.category}</p>
                                <p style="font-size:0.9rem;"><strong>Cadence Schedule:</strong> ${s.cadence} (Avg: ${s.interval_mean_days} days, Std: ${s.interval_std_days} days)</p>
                                <p style="font-size:0.9rem;"><strong>Confidence Score:</strong> ${Math.round(s.confidence_score * 100)}% (${s.confidence})</p>
                                <p style="font-size:0.9rem;"><strong>Monthly Equivalent:</strong> ${formatINR(s.monthly_equivalent_amount)}</p>
                                <p style="font-size:0.9rem;"><strong>Annual Run-rate:</strong> ${formatINR(s.annual_equivalent_amount)}</p>
                                <div style="margin-top:10px;">
                                    <strong>Evidence Rationale:</strong>
                                    <ul>${s.evidence_reasons.map(r => `<li style="font-size:0.88rem;">${r}</li>`).join('')}</ul>
                                </div>
                            </div>
                            <div>
                                <h4 style="margin-bottom:8px;">🛑 Cancellation Guidance</h4>
                                ${cancelHtml}
                            </div>
                        </div>
                        <h5 style="margin-top:16px; margin-bottom:4px;">📜 Billing Cycle History (${s.transactions.length} debits)</h5>
                        <table>
                            <thead><tr><th>Date</th><th>Narration</th><th>Amount</th><th>Mandate?</th></tr></thead>
                            <tbody>
                                ${s.transactions.map(t => `<tr><td>${t.date}</td><td>${t.narration}</td><td>${formatINR(t.amount)}</td><td>${t.has_mandate ? '✅ Yes' : 'No'}</td></tr>`).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
                seriesContainer.appendChild(card);
            });

            // Categories Table
            const catContainer = document.getElementById('categoryContainer');
            const cats = data.summary.category_breakdown;
            let catTable = '<table><thead><tr><th>Category</th><th>Monthly Run-rate</th><th>Annual Projected</th></tr></thead><tbody>';
            for (let c in cats) {
                catTable += `<tr><td><strong>${c}</strong></td><td>${formatINR(cats[c])}</td><td>${formatINR(cats[c] * 12)}</td></tr>`;
            }
            catTable += '</tbody></table>';
            catContainer.innerHTML = catTable;

            // Raw Transactions
            const rawBody = document.querySelector('#rawTxnTable tbody');
            rawBody.innerHTML = data.raw_transactions.map(t => `
                <tr>
                    <td>${t.date}</td>
                    <td>${t.narration}</td>
                    <td>${t.merchant}</td>
                    <td>${formatINR(t.amount)}</td>
                    <td>${t.is_debit ? 'Debit' : 'Credit'}</td>
                    <td>${t.has_mandate ? '✅ Yes' : 'No'}</td>
                </tr>
            `).join('');
        }

        // Auto load HDFC demo on initial open
        window.addEventListener('DOMContentLoaded', () => {
            loadDemo('hdfc');
        });
    </script>
</body>
</html>
"""


class AutoDebitsServer(BaseHTTPRequestHandler):
    """HTTP Request Handler for local zero-dependency UI."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        elif path == "/api/demo":
            bank = query.get("bank", ["hdfc"])[0]
            if bank == "sbi":
                csv_text = generate_sbi_statement()
            elif bank == "icici":
                csv_text = generate_icici_statement()
            else:
                csv_text, _ = generate_hdfc_statement()

            result = process_csv_payload(csv_text, f"{bank.upper()}_Demo")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/analyze":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)
            csv_text = data.get("csv", "")
            name = data.get("name", "Uploaded_Statement")

            result = process_csv_payload(csv_text, name)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


def run_server(port: int = 8501):
    server_address = ("", port)
    httpd = HTTPServer(server_address, AutoDebitsServer)
    print(f"Auto Debits Zero-Dependency Server running at http://localhost:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()


if __name__ == "__main__":
    import sys
    port = 8501
    if len(sys.argv) > 2 and sys.argv[1] == "--port":
        port = int(sys.argv[2])
    run_server(port)
