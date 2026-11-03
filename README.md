# The Auto Debits Nobody Can Find

**HackFront India 2026 · Fintech · Team HACKJXF3**

A privacy-first audit assistant that turns Indian bank-statement CSVs into an understandable list of recurring payments, possible price increases, projected costs, and cancellation or mandate guidance.

## Run 
> **Hackathon Theme:** T4 (Fintech)  
> **Problem Statement:** T4.1 — *"The Auto Debits Nobody Can Find"*  
> **Live Web App:** https://autodebitsnobodycanfind.streamlit.app/  





Choose **Load Synthetic Demo Statement** to explore the app without supplying a personal bank statement.

## What it does

- Reads CSV exports from HDFC, SBI, ICICI, Axis, Kotak and compatible generic formats.
- Cleans and classifies rows, while surfacing duplicates, refunds, uncertain direction and malformed entries for review.
- Maps cryptic transaction descriptions to recognizable merchants and groups likely recurring debits by cadence.
- Shows confidence and evidence, persistent price-change alerts, past spend, projected monthly/annual commitments and a what-if savings simulator.
- Offers merchant help links and bank/UPI mandate guidance where available. The user performs and confirms any cancellation.
- Masks account/reference details by default.

## Privacy and scope

When run locally, analysis happens in the local Python process; the app does not request bank credentials or connect to bank APIs. A hosted deployment processes uploaded data on the host running the app, so deployment operators and retention settings matter. The app is informational: it does not cancel subscriptions or revoke mandates.

## Benchmark note

The included benchmark CSVs and labels are generated synthetic data. The reported 100% precision/recall/F1 is performance on controlled synthetic cases, not a claim of production or real-world accuracy. Review detections and source statements before acting.

## Project structure

- `app.py` — Streamlit entry point
- `src/` — ingestion, cleaning, merchant matching, detection, insights and UI pipeline
- `app/` — supporting baseline modules and cancellation guidance
- `data/synthetic/` — generated demo and benchmark data
- `scripts/` — synthetic-data generator and evaluator
- `tests/` — automated test suite

## License

No license is currently provided. All rights remain with the contributors unless a license is added.
