# Architecture & Technical Design: The Auto Debits Nobody Can Find

> **HackFront 2026 — Fintech Track**  
> **Privacy-First Recurring Payment & Stealth Auto-Debit Intelligence for Indian Banking Users**  
> **Repository Path:** `/Users/manavtiwari/.gemini/antigravity/scratch/auto-debits`

---

## 1. System Overview & Architectural Topology

"The Auto Debits Nobody Can Find" is engineered as an in-memory, local-first analytical pipeline. It processes Indian bank statement CSV exports (HDFC, SBI, ICICI, Axis, Kotak, and generic single/multi-column dialects), maps chaotic narrations to canonical merchants using an explainable 4-tier cascade, classifies recurring debit cadence, alerts users to stealth price increases, and generates auditable cancellation and mandate revocation guidance.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                  PIPELINE ARCHITECTURE                                      │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

    Bank Statement CSV (HDFC, SBI, ICICI, Axis, Kotak, Generic)
               │
               ▼
    ┌───────────────────────┐
    │  StatementIngestor    │  ◄── Sniffs delimiters (',', ';', '\t'), skips preambles,
    │  (src/ingestion.py)   │      identifies bank dialect & header row, validates schema
    └──────────┬────────────┘
               │ IngestedStatement
               ▼
    ┌───────────────────────┐
    │   StatementCleaner    │  ◄── Parses dates & amounts, resolves Dr/Cr direction,
    │   (src/cleaning.py)   │      tags duplicates & refunds, guarantees ZERO silent drops
    └──────────┬────────────┘
               │ CleaningResult (List[CleanedTransaction], RowStatus typed)
               ▼
    ┌───────────────────────┐
    │    MerchantMatcher    │  ◄── 4-Tier Cascade: Exact Alias ➔ Regex Rules ➔ Fuzzy ➔ Unknown;
    │   (src/merchants.py)  │      strips UPI VPAs, flags retail and variable bills
    └──────────┬────────────┘
               │ Enriched Transactions
               ▼
    ┌───────────────────────┐
    │   RecurringDetector   │  ◄── Filters valid debits, groups by merchant, gap-tolerant
    │   (src/detection.py)  │      cadence clustering (Cult.fit resolved), CV calculation,
    └──────────┬────────────┘      repeat spend rejection shield, 0-100 additive confidence
               │
               ├───────────────────────────────────────────┐
               ▼                                           ▼
    ┌───────────────────────┐                   ┌───────────────────────┐
    │   PriceHikeTracker    │                   │ RejectionRecord List  │
    │ (src/price_changes.py)│                   │ (Swiggy, Zomato, etc.)│
    └──────────┬────────────┘                   └───────────────────────┘
               │ Series with PriceAlerts (>=2% hike, >=2 cycles, variable bills suppressed)
               ▼
    ┌───────────────────────┐
    │ CancellationRegistry  │  ◄── Sourced guide lookup (8 verified merchants with URLs/dates)
    │  (src/cancellation.py)│      + safe unverified fallback + NPCI/RBI AutoPay instructions
    └──────────┬────────────┘
               │ Series with CancellationDetails
               ▼
    ┌───────────────────────┐
    │ CostEstimator &       │  ◄── Observed actual burn separated from forward commitments,
    │ SavingsSimulator      │      deterministic run-rates, category totals, savings simulator
    │  (src/insights.py)    │
    └──────────┬────────────┘
               │ InsightsSummary & SavingsSimulationResult
               ▼
    ┌───────────────────────┐
    │   Streamlit Web UI    │  ◄── 6 Interactive Tabs, KPI cards, Plotly spend/category charts,
    │  (app.py & src/ui/*)  │      evidence diagnostics, masking toggle, demo statement loader
    └───────────────────────┘
```

---

## 2. Component Design & Responsibilities

### 2.1 Ingestion & Preamble Sniffing (`src/ingestion.py`)
- **Dialect Recognition**: Inspects file headers for known bank signatures (`HDFC BANK`, `STATE BANK OF INDIA`, `ICICI BANK`, `AXIS BANK`, `KOTAK MAHINDRA BANK`).
- **Delimiter Detection**: Evaluates line candidate delimiters (`,`, `;`, `\t`) and scores delimiter consistency.
- **Metadata Preamble Skipping**: Scans rows until it finds a row matching required column semantics (`Date`, `Narration`/`Description`, and `Amount` or `Withdrawal`/`Deposit`).
- **Schema Validation**: Ensures all required fields are present; raises typed `SchemaValidationError` with detected headers and supported alternatives if columns are missing.

### 2.2 Cleaning & Zero-Silent-Drops Invariant (`src/cleaning.py`)
- **Strict Row Preservation**: Every CSV row is preserved as a `CleanedTransaction`. Rows are never silently discarded.
- **Typed Row Status (`RowStatus`)**:
  - `VALID`: Valid debit or credit with unambiguous date, narration, and amount.
  - `INVALID_FORMAT`: Malformed dates or non-numeric amounts.
  - `DUPLICATE`: Same date, amount, and narration within a 24-hour window (linked to original transaction ID).
  - `REFUND`: Credit matching a prior debit with refund indicators (`CR-REFUND`, `REV`, `CASHBACK`).
  - `UNCERTAIN`: Unsigned amount in a single-column statement without directional markers (`Dr`/`Cr`).
- **Direction Resolution**:
  - Multi-column statements: Uses separate `Withdrawal Amt.` and `Deposit Amt.` columns.
  - Single-column statements: Resolves `Dr`/`Cr` suffixes (`499.00 Dr`), signed amounts (`-649.00` is debit, `+140000.00` is credit), parentheses (`(499.00)` is debit), and defaults ambiguous positive numbers to `RowStatus.UNCERTAIN` to prevent treating unconfirmed entries as confirmed debits.

### 2.3 4-Tier Explainable Merchant Normalization (`src/merchants.py`)
Cryptic bank narrations are mapped to canonical merchants through a strict 4-tier cascade:

```
Input Narration: "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY"
       │
       ▼ [NarrationCleaner: strips VPAs, card masks, banking noise]
Cleaned Token: "NETFLIX ENTERTAINMENT"
       │
       ├─► Tier 1: Exact Alias Match ───────────► (MatchMethod.EXACT_ALIAS, conf=1.00)
       │
       ├─► Tier 2: Token / Regex Rules Match ────► (MatchMethod.RULE_REGEX, conf=0.90–0.95)
       │           (Sorted by alias length desc: "Swiggy One" before "Swiggy")
       │
       ├─► Tier 3: Fuzzy Similarity Match ───────► (MatchMethod.FUZZY, conf=0.60–0.82)
       │           (difflib SequenceMatcher >= 0.78 threshold for typos like 'SPOTFY PREMUM')
       │
       └─► Tier 4: Unknown Merchant Fallback ────► (MatchMethod.UNKNOWN, conf=0.30)
                   (Extracts clean entity tokens into "General / Other" without hallucinating)
```

- **Unrelated Business False-Match Shield**: Rejects business phrases containing brand words (e.g. "The Netflix Cafe", "Amazon Tea Stall", "Apple Dental Clinic") using `UNRELATED_BUSINESS_INDICATORS`, preventing false subscription matches.
- **Boundary-Safe VPA Stripping**: Strips UPI handles (`user@icici`) without stripping hyphens inside vendor handles, ensuring hyphenated merchant tokens (e.g. `GOOGLE*STORAGE-GOOGLE@ICICI`) retain merchant identity.

### 2.4 Recurring Cadence Detection Engine (`src/detection.py`)
- **Strict Valid-Debit Filtering**: Only transactions where `row_status == RowStatus.VALID and is_debit is True` are eligible for recurring detection. Duplicates, refunds, salary deposits, reversals, and uncertain entries are strictly excluded.
- **Cadence Classification**:
  - `Weekly`: Mean interval 5–10 days.
  - `Monthly`: Mean interval 25–35 days (nominal 30 days).
  - `Quarterly`: Mean interval 80–100 days (nominal 90 days).
  - `Annual`: Mean interval 350–380 days (nominal 365 days).
  - `Irregular`: Variances failing regular interval bounds.
- **Gap-Tolerant Interval Clustering (Cult.fit Resolution)**:
  When a user pauses a subscription (e.g. Cult.fit paused for 60 days), the raw interval variance would artificially degrade cadence to `Irregular`. The gap-tolerant engine recognizes pause intervals that are integer multiples $k \times 30$ ($k \in \{2, 3, 4\}$) of a base monthly cycle. It maintains `CadenceType.MONTHLY`, tags `is_paused_resumed = True`, records the pause gap in `Evidence.notes`, applies `PENALTY_GAP_PAUSED` (-10), and marks the series as a review candidate.
- **Ordinary Repeat Spend Rejection Shield**:
  Discretionary food delivery, grocery, and ride-hailing orders (Swiggy, Zomato, Blinkit, Zepto, Uber) frequently repeat on irregular dates with fluctuating amounts. The detector shields against false positives by:
  1. Detecting rapid succession intervals ($< 5$ days).
  2. Checking `is_retail` merchant flags.
  3. Requiring standing instruction or AutoPay mandate indicators to qualify retail repeat spends.
  4. Rejecting unverified repeats into transparent `RejectionRecord` audits with plain-language diagnostic reasons.

### 2.5 Calibrated 0–100 Additive Confidence Scoring
Confidence scores are computed deterministically using additive transparent factors and explicit penalties:

$$\text{Confidence Score} = \text{Clamp}_{0}^{100}\left(\sum \text{Factors} - \sum \text{Penalties}\right)$$

| Factor | Maximum Points | Scoring Rationale |
|---|---|---|
| **Cycle Occurrences** | 25 pts | 25 pts for $\ge 6$ cycles, 20 pts for 4–5 cycles, 15 pts for 3 cycles, 10 pts for 2 cycles. |
| **Interval Regularity** | 30 pts | 30 pts for CV $\le 0.05$, 25 pts for CV $\le 0.10$, 20 pts for CV $\le 0.20$, 10 pts for CV $\le 0.35$. |
| **Amount Stability** | 20 pts | 20 pts for modal share $\ge 90\%$, 15 pts for $\ge 75\%$, 10 pts for $\ge 50\%$. |
| **Merchant Match Quality** | 15 pts | 15 pts for Tier 1 Exact / Tier 2 Rule; 10 pts for Tier 3 Fuzzy; 5 pts for Tier 4 Unknown. |
| **Day-of-Month Consistency** | 10 pts | 10 pts for variance $\le 2$ days; 5 pts for variance $\le 5$ days. |

**Deductions & Penalties**:
- `PENALTY_GAP_PAUSED` (-10 pts): Series exhibited a multi-cycle pause gap.
- `PENALTY_UNVERIFIED_MERCHANT` (-15 pts): Merchant not recognized in catalog.
- `PENALTY_FEW_OBSERVATIONS` (-10 pts): Only 2 observations available.
- `PENALTY_RETAIL_CATEGORY` (-20 pts): Retail or dining category without mandate indicators.

**Rating Tiers**:
- **High**: Score $\ge 75$
- **Medium**: Score $50–74$ (Tier 4 unknown merchants capped at Medium)
- **Low**: Score $< 50$

### 2.6 Stealth Price Hike Detection (`src/price_changes.py`)
- **Criteria**: Flags price increases $\ge 2\%$ that persist across $\ge 2$ consecutive billing cycles.
- **Variable Utility Bill Suppression**: Inspects `is_variable_bill` from merchant metadata. For fluctuating utilities (e.g. BESCOM electricity bills varying from ₹1,190 to ₹1,820), price hike alerts are suppressed, eliminating false alarms while preserving price change monitoring for fixed-tier digital subscriptions (Netflix ₹499 $\rightarrow$ ₹649, Spotify ₹119 $\rightarrow$ ₹129).
- **Persistence Verification**: One-cycle spikes (e.g. temporary one-time pay-per-view purchase) do not trigger confirmed price alerts.

### 2.7 Sourced Cancellation Intelligence & Mandate Revocation (`src/cancellation.py`)
- **Strict Anti-Hallucination Gate**:
  Every guide in `data/cancellation_guide.json` requires an audited official first-party support URL and a verification timestamp. If either is missing or invalid, the registry strictly falls back to the safe, generic unverified protocol with an empty URL (`source_url=""`) and `last_verified="Unverified"`.
- **Verified vs Unverified Catalog**:
  - **Verified (8 Merchants)**: Netflix, Spotify, Amazon Prime, Disney+ Hotstar, YouTube Premium, Google One, Apple Services, Microsoft 365.
  - **Unverified (3 Catalog Merchants + Unknowns)**: Swiggy One, Zomato Gold, Cult.fit, and local/unknown merchants. Strictly returns standardized 4-step in-app guidance with zero fabricated corporate identifiers or menu paths.
- **Statutory Mandate Revocation Guidance**:
  Clearly explains that cancelling an in-app subscription stops the merchant from requesting renewals, but does **not** automatically revoke the bank-level standing instruction or UPI AutoPay mandate. Cites official regulatory frameworks:
  - **NPCI UPI AutoPay Framework**: Mandate pause, modification, and revocation via UPI apps.
  - **RBI Circular RBI/2019-20/47**: Cards and Prepaid Instruments e-mandate framework.
  - **RBI Circular RBI/2019-20/139**: E-mandates on Unified Payments Interface (UPI).
  - **RBI Circular RBI/2022-23/73**: Additional Factor of Authentication (AFA) waiver threshold up to ₹15,000.
- **Non-Agency Guarantee**: Explicitly states that the app is informational and never cancels subscriptions or revokes mandates on the user's behalf.

### 2.8 Financial Insights & Savings Simulator (`src/insights.py`)
- **Spend Separation**: Strictly separates **actual historical burn** (sum of confirmed debits observed during the statement period) from **forward projected commitment** (annualized run rate based on latest cycle amounts).
- **Run-Rate Normalization**:
  - Weekly: $\times 52 / 12$ monthly, $\times 52$ annual
  - Bi-weekly: $\times 26 / 12$ monthly, $\times 26$ annual
  - Monthly: $\times 1$ monthly, $\times 12$ annual
  - Quarterly: $/ 3$ monthly, $\times 4$ annual
  - Annual: $/ 12$ monthly, $\times 1$ annual
- **Review Candidates**: Flags series warranting user review (annual commitments, paused/resumed series, price hike alerts, and low confidence subscriptions) without labeling them "forgotten".
- **Potential Savings Simulation**: Deterministically computes monthly and annual savings when selected review candidates are discontinued, always appending `POTENTIAL_SAVINGS_DISCLAIMER`.

---

## 3. Data Contracts & Type Schema (`src/models.py`)

All pipeline interactions operate across strongly typed Python dataclasses:

| Data Structure | Key Fields | Purpose |
|---|---|---|
| `CleanedTransaction` | `date`, `narration`, `amount`, `is_debit`, `reference_id`, `balance`, `row_status`, `normalized_merchant`, `merchant_match`, `has_mandate_indicator` | Cleaned and normalized representation of an individual CSV transaction row. |
| `MerchantMatch` | `normalized_name`, `category`, `is_variable_bill`, `is_retail`, `method`, `match_confidence` | Metadata output of the 4-tier normalization cascade. |
| `Evidence` | `intervals_days`, `mean_interval_days`, `cv_interval`, `day_of_month_variance`, `modal_amount_ratio`, `is_paused_resumed`, `notes` | Auditable evidence justifying why a series was classified as recurring. |
| `ConfidenceBreakdown` | `total_score`, `level`, `factors`, `penalties`, `is_capped`, `cap_reason` | Additive transparent point breakdown (0–100). |
| `PriceAlert` | `merchant_name`, `old_amount`, `new_amount`, `change_percent`, `effective_date`, `is_confirmed`, `persistence_cycles` | Record of detected price increase persisting across cycles. |
| `CancellationDetails` | `merchant_name`, `is_verified`, `source_url`, `last_verified`, `settings_location`, `steps`, `mandate_guidance` | Actionable, auditable cancellation and mandate revocation protocol. |
| `RecurringSeries` | `merchant_name`, `category`, `cadence`, `confidence_level`, `confidence_score`, `latest_amount`, `monthly_equivalent`, `annual_equivalent`, `evidence`, `price_alert`, `cancellation_details` | Unified representation of a detected recurring debit series. |
| `RejectionRecord` | `group_key`, `merchant_name`, `transaction_count`, `total_spend`, `rejection_reasons`, `sample_narrations` | Audit trail for repeat spend groups rejected from recurring status. |
| `InsightsSummary` | `detected_series_count`, `total_actual_spend`, `monthly_actual_burn`, `monthly_projected_commitment`, `annual_projected_commitment`, `category_totals`, `review_candidates` | Summary metrics separating actual historical spend from forward commitments. |

---

## 4. Privacy & Execution Boundaries

- **100% In-Memory Execution**: Bank statements are ingested and processed in memory. Statement contents are never persisted to disk, never cached in an external database, and never sent to external AI APIs or cloud telemetry.
- **Local vs Remote Hosting Behavior**:
  - *Local execution (`streamlit run app.py`)*: Processing occurs inside the local Python process on the user's personal machine; financial data never leaves the device.
  - *Remote server deployment*: Uploaded statement bytes are processed in the server's ephemeral process memory for the duration of the HTTP session and discarded immediately upon session teardown. No external calls are made.
- **Privacy Masking**: The UI automatically masks transaction reference IDs (`TXN***1102`), credit card numbers (`4012XXXXXXXX1234`), and phone numbers (`987****210`) by default, with a user-controlled toggle.
