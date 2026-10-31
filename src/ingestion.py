"""CSV Ingestion & Schema Validation Engine.

Parses Indian bank statement CSVs, auto-detects delimiters and bank formats,
skips top metadata preambles, and enforces schema requirements with clear errors.
"""

from __future__ import annotations
import csv
import io
import re
from typing import List, Dict, Optional, Tuple, Any

from src.models import IngestedStatement, SchemaValidationError


class StatementIngestor:
    """Robust CSV ingestion and schema validation for Indian bank statements."""

    DELIMITERS = [',', '\t', ';']

    # Normalized target column keys mapped to keywords
    HEADER_MATCHERS: Dict[str, List[str]] = {
        "date": [
            "txn date", "transaction date", "tran date", "trans date",
            "date", "value dt", "value date", "posting date"
        ],
        "narration": [
            "narration", "description", "particulars", "transaction details",
            "details", "remarks", "memo", "transaction remarks"
        ],
        "debit": [
            "withdrawal amt.", "withdrawal amt", "withdrawal", "debit",
            "dr amount", "dr.", "dr", "debit amount", "withdrawals", "debit (inr)"
        ],
        "credit": [
            "deposit amt.", "deposit amt", "deposit", "credit",
            "cr amount", "cr.", "cr", "credit amount", "deposits", "credit (inr)"
        ],
        "amount": [
            "net amount", "transaction amount", "txn amount", "amount (inr)",
            "amount (rs)", "amount", "total amount"
        ],
        "reference": [
            "chq./ref.no.", "chq/ref no", "ref no", "reference",
            "cheque number", "chq no", "ref no./cheque no.", "txn id",
            "transaction id", "utr", "reference number", "ref #", "ref"
        ],
        "type": [
            "txn type", "transaction type", "dr/cr", "cr/dr", "d/c",
            "dr / cr", "cr / dr", "tran type", "type"
        ],
        "balance": [
            "closing balance", "available balance", "balance", "bal", "account balance"
        ]
    }

    BANK_SIGNATURES: Dict[str, List[str]] = {
        "HDFC Bank": ["hdfc bank", "hdfc", "50100", "hdfc000"],
        "State Bank of India": ["state bank of india", "sbi", "sbin000"],
        "ICICI Bank": ["icici bank", "icici", "icic000"],
        "Axis Bank": ["axis bank", "utib000"],
        "Kotak Mahindra Bank": ["kotak", "kotak mahindra", "kkbk000"]
    }

    @classmethod
    def _matches_keyword(cls, kw: str, col: str) -> bool:
        """Helper to match column keyword with boundary sensitivity."""
        kw_lower = kw.strip().lower()
        col_lower = col.strip().lower()
        if kw_lower == col_lower:
            return True
        # For short tokens (<= 3 chars, e.g. 'cr', 'dr', 'bal', 'ref'), require word boundary
        if len(kw_lower) <= 3:
            return bool(re.search(r'\b' + re.escape(kw_lower) + r'\b', col_lower))
        return kw_lower in col_lower

    @classmethod
    def detect_bank_name(
        cls,
        metadata_lines: List[str],
        header_cols: List[str],
        filename_hint: Optional[str] = None
    ) -> str:
        """Identifies issuing bank from top metadata, column naming, or file hints."""
        search_blob = (" ".join(metadata_lines) + " " + (filename_hint or "")).lower()

        for bank, signatures in cls.BANK_SIGNATURES.items():
            if any(sig in search_blob for sig in signatures):
                return bank

        # Column signature fallback
        lower_cols = [c.lower() for c in header_cols]
        if any("withdrawal amt." in c for c in lower_cols) and any("deposit amt." in c for c in lower_cols):
            return "HDFC Bank"
        if any("dr amount" in c for c in lower_cols) and any("cr amount" in c for c in lower_cols):
            return "ICICI Bank"
        if any("txn date" in c for c in lower_cols) and any("ref no./cheque no." in c for c in lower_cols):
            return "State Bank of India"

        return "Generic Statement"

    @classmethod
    def detect_header_row(
        cls, lines: List[str]
    ) -> Tuple[int, str, List[str], Dict[str, str]]:
        """
        Scans lines up to first 50 lines to find the true table header row.
        Returns (header_index, delimiter, column_names, column_mapping).
        """
        best_candidate: Tuple[int, str, List[str], Dict[str, str], int] = (-1, ",", [], {}, 0)

        for idx, line in enumerate(lines[:50]):
            cleaned_line = line.strip()
            if not cleaned_line:
                continue

            for delim in cls.DELIMITERS:
                try:
                    reader = csv.reader([cleaned_line], delimiter=delim)
                    parts = next(reader)
                except Exception:
                    parts = [p.strip().strip('"').strip("'") for p in cleaned_line.split(delim)]

                if len(parts) < 2:
                    continue

                col_mapping: Dict[str, str] = {}
                for canonical_key, keywords in cls.HEADER_MATCHERS.items():
                    for actual_col in parts:
                        if not actual_col.strip():
                            continue
                        if any(cls._matches_keyword(kw, actual_col) for kw in keywords):
                            if canonical_key not in col_mapping:
                                col_mapping[canonical_key] = actual_col
                            break

                has_date = "date" in col_mapping
                has_narration = "narration" in col_mapping
                has_amount = "amount" in col_mapping or ("debit" in col_mapping or "credit" in col_mapping)

                # Perfect match: all 3 core groups present
                if has_date and has_narration and has_amount:
                    return idx, delim, parts, col_mapping

                # Track best candidate row (must match at least 2 distinct banking column types)
                match_count = len(col_mapping)
                if match_count >= 2 and match_count > best_candidate[4]:
                    best_candidate = (idx, delim, parts, col_mapping, match_count)

        if best_candidate[4] >= 2:
            return best_candidate[0], best_candidate[1], best_candidate[2], best_candidate[3]

        return -1, ",", [], {}

    @classmethod
    def validate_schema(
        cls, column_mapping: Dict[str, str], detected_columns: List[str]
    ) -> None:
        """Validates that necessary core fields exist, raising SchemaValidationError if missing."""
        missing: List[str] = []

        if "date" not in column_mapping:
            missing.append("Date")
        if "narration" not in column_mapping:
            missing.append("Narration / Description")
        if "amount" not in column_mapping and not ("debit" in column_mapping or "credit" in column_mapping):
            missing.append("Amount or (Debit / Credit)")

        if missing:
            col_list_str = ", ".join(f"'{c}'" for c in detected_columns) if detected_columns else "None"
            raise SchemaValidationError(
                f"Uploaded bank statement fails schema requirements. Missing mandatory column(s): {', '.join(missing)}. "
                f"Detected columns: [{col_list_str}]. Please provide a statement with Date, Description, and Debit/Credit amount fields.",
                missing_fields=missing,
                detected_columns=detected_columns
            )

    @classmethod
    def ingest_csv_text(
        cls,
        csv_text: str,
        filename_hint: Optional[str] = None
    ) -> IngestedStatement:
        """
        Parses raw CSV content into IngestedStatement with validation.
        """
        if not csv_text or not csv_text.strip():
            raise SchemaValidationError("The uploaded CSV file is empty. Please select a valid bank statement file.")

        lines = [line.strip('\r') for line in csv_text.splitlines() if line.strip('\r\n')]
        if not lines:
            raise SchemaValidationError("The uploaded CSV contains no readable lines.")

        header_idx, delimiter, header_cols, col_mapping = cls.detect_header_row(lines)

        if header_idx == -1:
            raise SchemaValidationError(
                "Could not find a valid transaction table header in the CSV. "
                "Ensure the statement contains header columns for Date, Description/Narration, and Amount/Debit."
            )

        # Enforce validation
        cls.validate_schema(col_mapping, header_cols)

        metadata_lines = [l.strip() for l in lines[:header_idx] if l.strip()]
        bank_name = cls.detect_bank_name(metadata_lines, header_cols, filename_hint)

        # Parse data rows starting after header_idx
        data_text = "\n".join(lines[header_idx:])
        reader = csv.DictReader(io.StringIO(data_text), delimiter=delimiter)

        raw_rows: List[Dict[str, str]] = []
        for r in reader:
            if any(val.strip() for val in r.values() if val is not None):
                raw_rows.append({k.strip(): (v.strip() if v else "") for k, v in r.items() if k is not None})

        return IngestedStatement(
            bank_name=bank_name,
            delimiter=delimiter,
            header_row_index=header_idx,
            columns=header_cols,
            column_mapping=col_mapping,
            raw_rows=raw_rows,
            metadata_lines=metadata_lines,
            total_lines=len(lines)
        )

    @classmethod
    def ingest_csv_file(
        cls,
        file_path: str
    ) -> IngestedStatement:
        """Convenience method to ingest a CSV directly from disk."""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return cls.ingest_csv_text(content, filename_hint=file_path)
