"""Data Sanitization & Transaction Cleaning Pipeline.

Standardizes dates, sanitizes currency amounts, determines debit/credit direction,
flags duplicates and refunds/reversals, and assigns status flags to every row.
No row is silently dropped.
"""

from __future__ import annotations
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Any

from src.models import (
    CleanedTransaction,
    IngestedStatement,
    CleaningResult,
    RowStatus
)
from src.config import MANDATE_KEYWORDS


DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%Y-%m-%d",
    "%d/%m/%y",
    "%d-%m-%y",
    "%Y/%m/%d",
    "%d.%m.%Y",
    "%d.%m.%y",
)

REVERSAL_KEYWORDS = (
    "AUTOREVERSAL",
    "AUTO-REVERSAL",
    "REVERSAL",
    "REVERSED",
    "CHARGEBACK",
    "REV/",
    "/REV/",
    "FAILED-TXN",
)

REFUND_KEYWORDS = (
    "REFUND",
    "REFUNDED",
    "CASHBACK",
    "CANCELLED",
    "RETURN",
    "RTN",
)


DR_REGEX = re.compile(r'(?:^|[^\w])dr(?:\.|\b)|(?<=\d)dr\b|(?<=\d)dr(?=[^\w]|$)', re.IGNORECASE)
CR_REGEX = re.compile(r'(?:^|[^\w])cr(?:\.|\b)|(?<=\d)cr\b|(?<=\d)cr(?=[^\w]|$)', re.IGNORECASE)


class StatementCleaner:
    """Sanitizes raw statement rows and tags each with an explicit RowStatus."""

    @classmethod
    def parse_date(cls, val: Any) -> Optional[date]:
        """
        Parses various Indian banking date string formats (DD/MM/YYYY preferred).
        Strips time components if present.
        """
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None

        # Strip time part if present (e.g. '02/11/2025 14:32:00' -> '02/11/2025')
        date_token = re.split(r'\s+', s)[0]
        # Also strip trailing punctuation/commas
        date_token = date_token.rstrip(',')

        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(date_token, fmt).date()
            except ValueError:
                continue

        return None

    @classmethod
    def clean_amount(cls, val: Any) -> Tuple[Optional[float], Optional[bool]]:
        """
        Sanitizes currency amounts:
        - Strips currency symbols (₹, $, €, £), INR, Rs., commas, and whitespace.
        - Resolves parenthetical negatives: (1,499.00) -> -1499.00.
        - Checks for Dr/Cr indicators across common Indian bank formats:
          e.g. '499.00 Dr', '499.00Dr', '(Dr) 499.00', '140000.00 Cr', '140000.00Cr'.
        Returns (amount_float, is_explicit_debit_override).
        """
        if val is None:
            return None, None
        s = str(val).strip()
        if not s:
            return None, None

        # Check for Dr / Cr indicators
        is_dr = bool(DR_REGEX.search(s))
        is_cr = bool(CR_REGEX.search(s))

        # Check for parenthetical negative amount before stripping
        is_parenthetical = s.startswith("(") and s.endswith(")")

        # Strip Dr/Cr indicators first, then currency words, symbols, and commas
        s_no_drcr = re.sub(
            r"\(?\bdr\.?\)?|\(?\bcr\.?\)?|(?<=\d)dr(?:\.|\b)|(?<=\d)cr(?:\.|\b)",
            "",
            s,
            flags=re.IGNORECASE
        )
        cleaned = re.sub(r'[₹\$,€£\s]|INR|Rs\.?', '', s_no_drcr, flags=re.IGNORECASE)

        # Handle parentheses indicating negative/debit e.g. (1,499.00)
        if is_parenthetical:
            inner = cleaned.strip("()")
            cleaned = "-" + inner

        try:
            amt = float(cleaned)
            is_debit = None
            if is_dr:
                is_debit = True
            elif is_cr:
                is_debit = False
            return amt, is_debit
        except ValueError:
            return None, None

    @classmethod
    def clean_statement(
        cls,
        ingested: IngestedStatement
    ) -> CleaningResult:
        """
        Processes all raw rows from an IngestedStatement into standardized CleanedTransactions.
        Applies duplicate debit detection and refund/reversal linking.
        Preserves uncertainty when transaction direction cannot be determined.
        """
        col_map = ingested.column_mapping
        date_col = col_map.get("date")
        narration_col = col_map.get("narration")
        debit_col = col_map.get("debit")
        credit_col = col_map.get("credit")
        amount_col = col_map.get("amount")
        ref_col = col_map.get("reference")
        balance_col = col_map.get("balance")
        type_col = col_map.get("type")

        # Pre-scan for signed amount convention in single-column files
        file_has_negative_amounts = False
        if amount_col:
            for r in ingested.raw_rows:
                raw_val = r.get(amount_col, "")
                parsed_val, _ = cls.clean_amount(raw_val)
                if parsed_val is not None and parsed_val < 0:
                    file_has_negative_amounts = True
                    break

        transactions: List[CleanedTransaction] = []

        for row_idx, raw in enumerate(ingested.raw_rows):
            raw_date_str = raw.get(date_col, "") if date_col else ""
            raw_narration = raw.get(narration_col, "") if narration_col else ""
            raw_ref = raw.get(ref_col, "") if ref_col else ""
            if not raw_ref:
                raw_ref = f"ROW_{row_idx + 1}"
            raw_bal_str = raw.get(balance_col, "") if balance_col else ""

            parsed_date = cls.parse_date(raw_date_str)

            # Determine Amount and Direction
            parsed_amt: Optional[float] = None
            is_debit: Optional[bool] = None
            status: RowStatus = RowStatus.VALID

            # Case A: Separate Debit and Credit columns exist
            if debit_col and credit_col:
                raw_dr = raw.get(debit_col, "")
                raw_cr = raw.get(credit_col, "")

                dr_val, _ = cls.clean_amount(raw_dr)
                cr_val, _ = cls.clean_amount(raw_cr)

                if dr_val is not None and abs(dr_val) > 0:
                    parsed_amt = abs(dr_val)
                    is_debit = True
                elif cr_val is not None and abs(cr_val) > 0:
                    parsed_amt = abs(cr_val)
                    is_debit = False
                else:
                    if dr_val == 0.0 or cr_val == 0.0:
                        parsed_amt = 0.0
                        is_debit = True if (dr_val == 0.0 and (cr_val is None or abs(cr_val) == 0.0)) else False
                    else:
                        parsed_amt = None
            # Case B: Only debit column present
            elif debit_col:
                raw_dr = raw.get(debit_col, "")
                dr_val, _ = cls.clean_amount(raw_dr)
                if dr_val is not None:
                    parsed_amt = abs(dr_val)
                    is_debit = True
            # Case C: Only credit column present
            elif credit_col:
                raw_cr = raw.get(credit_col, "")
                cr_val, _ = cls.clean_amount(raw_cr)
                if cr_val is not None:
                    parsed_amt = abs(cr_val)
                    is_debit = False
            # Case D: Single Amount column
            elif amount_col:
                raw_amt = raw.get(amount_col, "")
                raw_amt_str = str(raw_amt).strip()
                amt_val, override_is_debit = cls.clean_amount(raw_amt)

                # Check dedicated transaction type column if present
                type_is_debit: Optional[bool] = None
                if type_col:
                    raw_type = str(raw.get(type_col, "")).strip().lower()
                    if re.search(r'\b(dr|debit|d)\b', raw_type):
                        type_is_debit = True
                    elif re.search(r'\b(cr|credit|c)\b', raw_type):
                        type_is_debit = False

                if amt_val is not None:
                    parsed_amt = abs(amt_val)

                    # 1. Explicit Dr/Cr marker in the amount cell
                    if override_is_debit is not None:
                        is_debit = override_is_debit
                    # 2. Explicit type column
                    elif type_is_debit is not None:
                        is_debit = type_is_debit
                    # 3. Explicit negative amount (- or parentheses): debit
                    elif amt_val < 0:
                        is_debit = True
                    # 4. Explicit leading '+' sign: credit
                    elif raw_amt_str.startswith("+"):
                        is_debit = False
                    # 5. File uses signed convention (has negative debits; positive = credit)
                    elif file_has_negative_amounts:
                        is_debit = False
                    else:
                        # 6. Check narration for explicit direction keywords
                        upper_narr = raw_narration.upper()
                        is_refund_kw = any(kw in upper_narr for kw in REFUND_KEYWORDS)
                        is_reversal_kw = any(kw in upper_narr for kw in REVERSAL_KEYWORDS)
                        is_credit_kw = bool(re.search(r'\b(credit|cr)\b', upper_narr))
                        is_debit_kw = bool(re.search(r'\b(debit|dr|wdl|withdrawal)\b', upper_narr))

                        if is_refund_kw or is_reversal_kw or (is_credit_kw and not is_debit_kw):
                            is_debit = False
                        elif is_debit_kw and not is_credit_kw:
                            is_debit = True
                        else:
                            # 7. Direction cannot be reliably determined: preserve uncertainty
                            is_debit = None
                            status = RowStatus.UNCERTAIN

            # Balance
            bal_val, _ = cls.clean_amount(raw_bal_str) if raw_bal_str else (None, None)

            # Validate Row Completeness
            if parsed_date is None or parsed_amt is None or not raw_narration.strip():
                status = RowStatus.INVALID
                parsed_amt = parsed_amt if parsed_amt is not None else 0.0
                parsed_date = parsed_date if parsed_date is not None else date.today()

            # Check for mandate keywords in raw narration
            upper_narr = raw_narration.upper()
            has_mandate = any(kw in upper_narr for kw in MANDATE_KEYWORDS)

            t = CleanedTransaction(
                date=parsed_date,
                narration=raw_narration.strip(),
                amount=parsed_amt,
                is_debit=is_debit,
                reference_id=raw_ref.strip() if raw_ref else None,
                balance=bal_val,
                row_status=status,
                has_mandate_indicator=has_mandate,
                source_bank=ingested.bank_name,
                raw_row=raw
            )
            transactions.append(t)

        # --------------------------------------------------------------------
        # Post-Processing: Duplicate Detection & Refund/Reversal Linking
        # --------------------------------------------------------------------
        cls._detect_duplicates(transactions)
        cls._link_refunds_and_reversals(transactions)

        valid_count = sum(1 for t in transactions if t.row_status == RowStatus.VALID)
        dup_count = sum(1 for t in transactions if t.row_status == RowStatus.DUPLICATE)
        ref_count = sum(1 for t in transactions if t.row_status == RowStatus.REFUND)
        rev_count = sum(1 for t in transactions if t.row_status == RowStatus.REVERSAL)
        inv_count = sum(1 for t in transactions if t.row_status == RowStatus.INVALID)
        unc_count = sum(1 for t in transactions if t.row_status == RowStatus.UNCERTAIN)

        return CleaningResult(
            transactions=transactions,
            total_rows=len(transactions),
            valid_count=valid_count,
            duplicate_count=dup_count,
            refund_count=ref_count,
            reversal_count=rev_count,
            invalid_count=inv_count,
            uncertain_count=unc_count
        )

    @classmethod
    def _detect_duplicates(cls, transactions: List[CleanedTransaction]) -> None:
        """
        Flags duplicate debits: same date, same debit amount, same narration.
        The first occurrence remains VALID; subsequent occurrences are marked DUPLICATE.
        """
        seen_debits: Dict[Tuple[date, float, str], CleanedTransaction] = {}

        for t in transactions:
            if t.row_status != RowStatus.VALID or t.is_debit is not True:
                continue

            key = (t.date, round(t.amount, 2), t.narration.upper())

            if key in seen_debits:
                t.row_status = RowStatus.DUPLICATE
                prior = seen_debits[key]
                t.refund_linked_id = prior.reference_id
            else:
                seen_debits[key] = t

    @classmethod
    def _link_refunds_and_reversals(cls, transactions: List[CleanedTransaction]) -> None:
        """
        Identifies credits that represent reversals or refunds of earlier debits.
        Searches matching debits within a 14-day lookback window.
        """
        debits: List[CleanedTransaction] = [
            t for t in transactions if t.is_debit is True and t.row_status == RowStatus.VALID
        ]

        for t in transactions:
            # Only consider non-debit rows (credits or uncertain rows)
            if t.is_debit is True or t.row_status not in (RowStatus.VALID, RowStatus.UNCERTAIN):
                continue

            upper_narr = t.narration.upper()
            is_refund = any(kw in upper_narr for kw in REFUND_KEYWORDS)
            is_reversal = any(kw in upper_narr for kw in REVERSAL_KEYWORDS)

            if not (is_refund or is_reversal):
                continue

            amt_target = round(t.amount, 2)
            matched_debit: Optional[CleanedTransaction] = None

            for d in debits:
                if round(d.amount, 2) == amt_target:
                    delta_days = (t.date - d.date).days
                    if 0 <= delta_days <= 14:
                        matched_debit = d
                        break

            # Refund takes precedence if keyword explicitly mentions refund
            if is_refund:
                t.row_status = RowStatus.REFUND
            else:
                t.row_status = RowStatus.REVERSAL
            t.is_debit = False

            if matched_debit:
                t.refund_linked_id = matched_debit.reference_id
