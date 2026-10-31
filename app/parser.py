"""Indian Bank Statement CSV Parser.

Parses CSV files from major Indian banks (HDFC, ICICI, SBI, Axis, Kotak)
as well as generic statements, handling diverse date formats, Indian numbering,
metadata headers, and debit/credit column separation.
"""

from __future__ import annotations
import csv
import io
import re
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional, Any
from app.models import Transaction


# Common date format patterns in Indian bank statements
DATE_FORMATS = [
    "%d/%m/%Y",      # 31/10/2026
    "%d-%m-%Y",      # 31-10-2026
    "%d.%m.%Y",      # 31.10.2026
    "%d/%m/%y",      # 31/10/26
    "%d-%m-%y",      # 31-10-26
    "%Y-%m-%d",      # 2026-10-31
    "%d-%b-%Y",      # 31-Oct-2026
    "%d/%b/%Y",      # 31/Oct/2026
    "%d-%b-%y",      # 31-Oct-26
    "%b %d, %Y",     # Oct 31, 2026
]


def clean_amount(val: Any) -> Optional[float]:
    """Parse a monetary value into a float, handling Indian number formatting."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "null", "none", "-"):
        return None

    # Check for trailing or leading Dr/Cr notation
    is_dr = bool(re.search(r'\bdr\b|\(dr\)', s, re.IGNORECASE))
    is_cr = bool(re.search(r'\bcr\b|\(cr\)', s, re.IGNORECASE))

    # Remove currency symbols, commas, spaces, Dr/Cr suffixes
    cleaned = re.sub(r'[₹\$,\s]|INR|Rs\.?|Dr|Cr', '', s, flags=re.IGNORECASE)

    # Handle parentheses indicating negative/debit e.g. (1,499.00)
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]

    try:
        amt = float(cleaned)
        # If explicitly marked Dr, it's a debit
        if is_dr and amt > 0:
            return amt
        return amt
    except ValueError:
        return None


def parse_date(val: Any) -> Optional[date]:
    """Parse various Indian banking date string representations."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None

    # Remove time part if attached (e.g. "31/10/2026 14:32:00")
    s = re.split(r'\s+', s)[0]

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class BankStatementParser:
    """Robust parser for Indian bank statement CSVs."""

    HEADER_DATE_KEYWORDS = {"date", "txn date", "transaction date", "tran date", "trans date"}
    HEADER_NARRATION_KEYWORDS = {"narration", "description", "particulars", "transaction details", "details", "remarks"}
    HEADER_DEBIT_KEYWORDS = {"withdrawal amt.", "withdrawal amt", "withdrawal", "debit", "dr", "dr amount", "dr.", "debit amount"}
    HEADER_CREDIT_KEYWORDS = {"deposit amt.", "deposit amt", "deposit", "credit", "cr", "cr amount", "cr.", "credit amount"}
    HEADER_REF_KEYWORDS = {"chq./ref.no.", "chq/ref no", "ref no", "reference", "cheque number", "chq no", "ref no./cheque no."}
    HEADER_BALANCE_KEYWORDS = {"closing balance", "balance", "bal", "available balance"}

    @classmethod
    def detect_header_row(cls, lines: List[str]) -> Tuple[int, str, List[str]]:
        """
        Scans lines to find the actual table header row, skipping top account metadata.
        Returns (header_index, delimiter, column_names).
        """
        delimiters = [',', '\t', ';']
        
        for idx, line in enumerate(lines[:50]): # search first 50 lines
            for delim in delimiters:
                parts = [p.strip().strip('"').strip("'") for p in line.split(delim)]
                lower_parts = [p.lower() for p in parts]

                has_date = any(any(kw in col for kw in cls.HEADER_DATE_KEYWORDS) for col in lower_parts)
                has_desc = any(any(kw in col for kw in cls.HEADER_NARRATION_KEYWORDS) for col in lower_parts)
                has_amt = any(
                    any(kw in col for kw in cls.HEADER_DEBIT_KEYWORDS) or
                    any(kw in col for kw in cls.HEADER_CREDIT_KEYWORDS) or
                    "amount" in col
                    for col in lower_parts
                )

                if has_date and (has_desc or has_amt):
                    return idx, delim, parts

        # Default fallback to first non-empty line
        for idx, line in enumerate(lines):
            if line.strip():
                return idx, ',', [p.strip() for p in line.split(',')]
        return 0, ',', []

    @classmethod
    def map_columns(cls, header: List[str]) -> Dict[str, Optional[int]]:
        """Map canonical field names to column indexes."""
        mapping: Dict[str, Optional[int]] = {
            "date": None,
            "narration": None,
            "debit": None,
            "credit": None,
            "amount": None,
            "reference": None,
            "balance": None
        }

        for idx, col in enumerate(header):
            c_low = col.lower().strip()
            
            # Date
            if mapping["date"] is None and any(kw in c_low for kw in cls.HEADER_DATE_KEYWORDS):
                mapping["date"] = idx
            # Narration / Particulars
            elif mapping["narration"] is None and any(kw in c_low for kw in cls.HEADER_NARRATION_KEYWORDS):
                mapping["narration"] = idx
            # Debit / Withdrawal
            elif mapping["debit"] is None and any(kw == c_low or kw in c_low for kw in cls.HEADER_DEBIT_KEYWORDS):
                mapping["debit"] = idx
            # Credit / Deposit
            elif mapping["credit"] is None and any(kw == c_low or kw in c_low for kw in cls.HEADER_CREDIT_KEYWORDS):
                mapping["credit"] = idx
            # General Amount (e.g. single column for Amount with sign)
            elif "amount" in c_low and mapping["amount"] is None:
                mapping["amount"] = idx
            # Reference / Chq No
            elif mapping["reference"] is None and any(kw in c_low for kw in cls.HEADER_REF_KEYWORDS):
                mapping["reference"] = idx
            # Balance
            elif mapping["balance"] is None and any(kw in c_low for kw in cls.HEADER_BALANCE_KEYWORDS):
                mapping["balance"] = idx

        return mapping

    @classmethod
    def parse_csv_content(cls, content: str, source_name: str = "CSV") -> List[Transaction]:
        """Parse raw CSV string content into a list of Transaction records."""
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            return []

        header_idx, delimiter, header_cols = cls.detect_header_row(lines)
        col_map = cls.map_columns(header_cols)

        # Prepare CSV reader starting from data rows
        reader = csv.reader(io.StringIO("\n".join(lines[header_idx + 1:])), delimiter=delimiter)
        transactions: List[Transaction] = []

        for row_idx, row in enumerate(reader):
            if not row or not any(field.strip() for field in row):
                continue

            # Extract date
            txn_date = None
            if col_map["date"] is not None and col_map["date"] < len(row):
                txn_date = parse_date(row[col_map["date"]])
            if not txn_date:
                continue

            # Extract narration
            narration = ""
            if col_map["narration"] is not None and col_map["narration"] < len(row):
                narration = row[col_map["narration"]].strip()

            # Extract debit amount
            debit_val: Optional[float] = None
            credit_val: Optional[float] = None
            is_debit = True

            if col_map["debit"] is not None and col_map["debit"] < len(row):
                debit_val = clean_amount(row[col_map["debit"]])

            if col_map["credit"] is not None and col_map["credit"] < len(row):
                credit_val = clean_amount(row[col_map["credit"]])

            # If separate debit and credit columns
            if debit_val is not None and debit_val > 0:
                amount = debit_val
                is_debit = True
            elif credit_val is not None and credit_val > 0:
                amount = credit_val
                is_debit = False
            elif col_map["amount"] is not None and col_map["amount"] < len(row):
                # Single amount column
                raw_amt = clean_amount(row[col_map["amount"]])
                if raw_amt is not None:
                    # Often negative values are debits, or positive with explicit Dr tag
                    raw_str = row[col_map["amount"]].lower()
                    if raw_amt < 0 or "dr" in raw_str:
                        amount = abs(raw_amt)
                        is_debit = True
                    else:
                        amount = abs(raw_amt)
                        is_debit = False
                else:
                    continue
            else:
                continue

            # Extract reference ID and balance
            ref_id = None
            if col_map["reference"] is not None and col_map["reference"] < len(row):
                ref_id = row[col_map["reference"]].strip()

            balance = None
            if col_map["balance"] is not None and col_map["balance"] < len(row):
                balance = clean_amount(row[col_map["balance"]])

            # Build raw data dict
            raw_data = {
                header_cols[i] if i < len(header_cols) else f"col_{i}": row[i]
                for i in range(len(row))
            }

            txn = Transaction(
                date=txn_date,
                narration=narration,
                amount=amount,
                is_debit=is_debit,
                reference_id=ref_id,
                balance=balance,
                raw_data=raw_data,
                source_bank=source_name
            )
            transactions.append(txn)

        # Sort by date ascending
        transactions.sort(key=lambda t: t.date)
        return transactions

    @classmethod
    def parse_file(cls, filepath: str) -> List[Transaction]:
        """Convenience method to parse a CSV from disk."""
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return cls.parse_csv_content(content, source_name=filepath)
