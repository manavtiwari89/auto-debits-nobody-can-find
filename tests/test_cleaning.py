"""Unit tests for Transaction Cleaning, Sanitization & Flagging (src/cleaning.py)."""

import unittest
from datetime import date
from src.ingestion import StatementIngestor
from src.cleaning import StatementCleaner
from src.models import RowStatus


class TestStatementCleaning(unittest.TestCase):

    def test_date_normalization_various_formats(self):
        self.assertEqual(StatementCleaner.parse_date("02/11/2025"), date(2025, 11, 2))
        self.assertEqual(StatementCleaner.parse_date("02-11-2025"), date(2025, 11, 2))
        self.assertEqual(StatementCleaner.parse_date("02-Nov-2025"), date(2025, 11, 2))
        self.assertEqual(StatementCleaner.parse_date("2025-11-02"), date(2025, 11, 2))
        self.assertEqual(StatementCleaner.parse_date("02.11.2025"), date(2025, 11, 2))
        # With timestamp attached
        self.assertEqual(StatementCleaner.parse_date("02/11/2025 14:32:00"), date(2025, 11, 2))
        # Invalid date string
        self.assertIsNone(StatementCleaner.parse_date("NOT_A_DATE"))
        self.assertIsNone(StatementCleaner.parse_date(""))
        self.assertIsNone(StatementCleaner.parse_date(None))

    def test_amount_sanitization_currency_symbols_and_formats(self):
        # Indian comma numbering with Rupee symbol
        amt, is_dr = StatementCleaner.clean_amount("₹ 1,49,900.00")
        self.assertEqual(amt, 149900.0)
        self.assertIsNone(is_dr)

        # Standard subscription amount with Rs. and Dr indicator
        amt, is_dr = StatementCleaner.clean_amount("Rs. 499.00 Dr")
        self.assertEqual(amt, 499.0)
        self.assertTrue(is_dr)

        # Salary credit with Cr indicator
        amt, is_dr = StatementCleaner.clean_amount("1,40,000.00 Cr")
        self.assertEqual(amt, 140000.0)
        self.assertFalse(is_dr)

        # Parenthetical negative amount
        amt, is_dr = StatementCleaner.clean_amount("(1,499.00)")
        self.assertEqual(amt, -1499.0)

        # Invalid amount
        amt, is_dr = StatementCleaner.clean_amount("INVALID_AMT")
        self.assertIsNone(amt)

    def test_debit_credit_direction_handling(self):
        csv_text = """Date,Narration,Ref,Debit,Credit,Balance
01/11/2025,SALARY CREDIT,REF1,,140000.00,140000.00
02/11/2025,NETFLIX AUTOPAY,REF2,499.00,,139501.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        result = StatementCleaner.clean_statement(ingested)

        self.assertEqual(result.total_rows, 2)
        salary_txn = result.transactions[0]
        netflix_txn = result.transactions[1]

        self.assertFalse(salary_txn.is_debit)
        self.assertEqual(salary_txn.amount, 140000.0)
        self.assertEqual(salary_txn.row_status, RowStatus.VALID)

        self.assertTrue(netflix_txn.is_debit)
        self.assertEqual(netflix_txn.amount, 499.0)
        self.assertEqual(netflix_txn.row_status, RowStatus.VALID)

    def test_duplicate_debit_detection(self):
        csv_text = """Date,Narration,Ref,Debit,Credit,Balance
14/04/2026,UPI-SWIGGY-ORDER,SWIG1,349.00,,50000.00
14/04/2026,UPI-SWIGGY-ORDER,SWIG2,349.00,,49651.00
15/04/2026,UPI-SWIGGY-ORDER,SWIG3,349.00,,49302.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        result = StatementCleaner.clean_statement(ingested)

        self.assertEqual(result.total_rows, 3)
        self.assertEqual(result.duplicate_count, 1)

        t1, t2, t3 = result.transactions
        self.assertEqual(t1.row_status, RowStatus.VALID)
        self.assertEqual(t2.row_status, RowStatus.DUPLICATE)
        self.assertEqual(t2.refund_linked_id, "SWIG1")
        # Different day is NOT marked duplicate
        self.assertEqual(t3.row_status, RowStatus.VALID)

    def test_refund_and_reversal_linking(self):
        csv_text = """Date,Narration,Ref,Debit,Credit,Balance
10/03/2026,UPI-UBER-TRIP-BANGALORE,UBER420,420.00,,25000.00
11/03/2026,UPI/REV/UBER INDIA/REFUND420,REF420,,420.00,25420.00
22/05/2026,UPI-PAYMENT-FAILED-TXN,FAIL500,500.00,,24920.00
22/05/2026,UPI/REV/AUTOREVERSAL/FAILED-TXN,REV500,,500.00,25420.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        result = StatementCleaner.clean_statement(ingested)

        self.assertEqual(result.refund_count, 1)
        self.assertEqual(result.reversal_count, 1)

        refund_txn = result.transactions[1]
        reversal_txn = result.transactions[3]

        self.assertEqual(refund_txn.row_status, RowStatus.REFUND)
        self.assertEqual(refund_txn.refund_linked_id, "UBER420")

        self.assertEqual(reversal_txn.row_status, RowStatus.REVERSAL)
        self.assertEqual(reversal_txn.refund_linked_id, "FAIL500")

    def test_no_silent_drops_invalid_row_flagged(self):
        csv_text = """Date,Narration,Ref,Debit,Credit,Balance
01/11/2025,NETFLIX,REF1,499.00,,10000.00
BAD_DATE_ROW,NETFLIX,REF2,499.00,,9501.00
03/11/2025,CORRUPT_AMOUNT,REF3,BAD_AMT,,9501.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        result = StatementCleaner.clean_statement(ingested)

        # No rows dropped: total_rows is 3
        self.assertEqual(result.total_rows, 3)
        self.assertEqual(result.valid_count, 1)
        self.assertEqual(result.invalid_count, 2)

        self.assertEqual(result.transactions[0].row_status, RowStatus.VALID)
        self.assertEqual(result.transactions[1].row_status, RowStatus.INVALID)
        self.assertEqual(result.transactions[2].row_status, RowStatus.INVALID)

    def test_mandate_indicator_tagging(self):
        csv_text = """Date,Narration,Ref,Debit,Credit,Balance
02/11/2025,UPI/P2M/NETFLIX/AUTOPAY,REF1,499.00,,10000.00
05/11/2025,ACH D- SPOTIFY,REF2,119.00,,9881.00
10/11/2025,SWIGGY BANGALORE ORDER,REF3,280.00,,9601.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        result = StatementCleaner.clean_statement(ingested)

        self.assertTrue(result.transactions[0].has_mandate_indicator)
        self.assertTrue(result.transactions[1].has_mandate_indicator)
        self.assertFalse(result.transactions[2].has_mandate_indicator)

    def test_single_column_drcr_markers_and_suffixes(self):
        """Single-column Amount with explicit Dr/Cr suffixes and prefixes."""
        csv_text = """Date,Narration,Ref,Amount
01/11/2025,NETFLIX AUTOPAY,REF1,499.00 Dr
02/11/2025,SALARY DEPOSIT,REF2,140000.00 Cr
03/11/2025,SPOTIFY SUBSCRIPTION,REF3,119.00DR
04/11/2025,INTEREST CREDIT,REF4,250.50CR
05/11/2025,AMAZON PURCHASE,REF5,Dr. 1499.00
06/11/2025,DIVIDEND,REF6,Cr. 350.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        result = StatementCleaner.clean_statement(ingested)

        self.assertEqual(result.total_rows, 6)
        t1, t2, t3, t4, t5, t6 = result.transactions

        # Dr -> Debit
        self.assertTrue(t1.is_debit)
        self.assertEqual(t1.amount, 499.0)
        self.assertEqual(t1.row_status, RowStatus.VALID)

        # Cr -> Credit (NOT a debit)
        self.assertFalse(t2.is_debit)
        self.assertEqual(t2.amount, 140000.0)
        self.assertEqual(t2.row_status, RowStatus.VALID)

        # DR suffix
        self.assertTrue(t3.is_debit)
        self.assertEqual(t3.amount, 119.0)

        # CR suffix
        self.assertFalse(t4.is_debit)
        self.assertEqual(t4.amount, 250.50)

        # Dr. prefix
        self.assertTrue(t5.is_debit)
        self.assertEqual(t5.amount, 1499.0)

        # Cr. prefix
        self.assertFalse(t6.is_debit)
        self.assertEqual(t6.amount, 350.0)

        # Only valid debits in valid_debits
        self.assertEqual(len(result.valid_debits), 3)
        self.assertEqual([t.amount for t in result.valid_debits], [499.0, 119.0, 1499.0])

    def test_single_column_signed_amounts_rule(self):
        """Signed amounts rule: negative values are debits, positive values are credits."""
        csv_text = """Date,Narration,Ref,Amount
01/11/2025,NETFLIX SUBSCRIPTION,REF1,-499.00
02/11/2025,SALARY CREDIT,REF2,140000.00
03/11/2025,HOTSTAR VIP,REF3,(899.00)
04/11/2025,DIVIDEND PAYOUT,REF4,+50.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        result = StatementCleaner.clean_statement(ingested)

        self.assertEqual(result.total_rows, 4)
        netflix, salary, hotstar, dividend = result.transactions

        # Negative amounts are debits
        self.assertTrue(netflix.is_debit)
        self.assertEqual(netflix.amount, 499.0)
        self.assertEqual(netflix.row_status, RowStatus.VALID)

        self.assertTrue(hotstar.is_debit)
        self.assertEqual(hotstar.amount, 899.0)
        self.assertEqual(hotstar.row_status, RowStatus.VALID)

        # Positive amounts are credits, never silently classified as debits
        self.assertFalse(salary.is_debit)
        self.assertEqual(salary.amount, 140000.0)
        self.assertEqual(salary.row_status, RowStatus.VALID)

        self.assertFalse(dividend.is_debit)
        self.assertEqual(dividend.amount, 50.0)
        self.assertEqual(dividend.row_status, RowStatus.VALID)

        # Valid debits only contains the 2 debit rows
        self.assertEqual(len(result.valid_debits), 2)
        self.assertEqual({t.reference_id for t in result.valid_debits}, {"REF1", "REF3"})

    def test_single_column_refund_and_reversal_linking(self):
        """Single-column statement refund and reversal handling with positive credit rows."""
        csv_text = """Date,Narration,Ref,Amount
10/03/2026,UPI-UBER-TRIP-BANGALORE,UBER420,-420.00
11/03/2026,UPI/REV/UBER INDIA/REFUND420,REF420,+420.00
15/03/2026,UPI-FAILED-PAYMENT,FAIL500,-500.00
15/03/2026,UPI/REV/AUTOREVERSAL/FAILED-TXN,REV500,500.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        result = StatementCleaner.clean_statement(ingested)

        self.assertEqual(result.total_rows, 4)
        self.assertEqual(result.refund_count, 1)
        self.assertEqual(result.reversal_count, 1)

        refund_txn = result.transactions[1]
        reversal_txn = result.transactions[3]

        # Positive refund/reversal rows must be credits, not debits
        self.assertFalse(refund_txn.is_debit)
        self.assertEqual(refund_txn.row_status, RowStatus.REFUND)
        self.assertEqual(refund_txn.refund_linked_id, "UBER420")

        self.assertFalse(reversal_txn.is_debit)
        self.assertEqual(reversal_txn.row_status, RowStatus.REVERSAL)
        self.assertEqual(reversal_txn.refund_linked_id, "FAIL500")

    def test_single_column_uncertain_direction_preservation(self):
        """When direction cannot be determined from file, preserve uncertainty without guessing."""
        csv_text = """Date,Narration,Ref,Amount
01/11/2025,TRANSACTION ONE,REF1,500.00
02/11/2025,TRANSACTION TWO,REF2,1200.00
03/11/2025,TRANSACTION THREE,REF3,350.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        result = StatementCleaner.clean_statement(ingested)

        self.assertEqual(result.total_rows, 3)
        self.assertEqual(result.uncertain_count, 3)
        self.assertEqual(result.valid_count, 0)
        self.assertEqual(len(result.valid_debits), 0)

        for t in result.transactions:
            self.assertEqual(t.row_status, RowStatus.UNCERTAIN)
            self.assertIsNone(t.is_debit)

    def test_transaction_construction_without_direction_defaults_to_uncertain(self):
        """
        Regression test: Constructing CleanedTransaction without specifying direction
        must NOT silently create a valid debit. It must default to is_debit=None
        and row_status=RowStatus.UNCERTAIN, while preserving callers that explicitly
        pass is_debit=True or is_debit=False.
        """
        from src.models import CleanedTransaction

        # Case 1: No direction specified -> stays uncertain
        t_unspecified = CleanedTransaction(
            date=date(2025, 11, 1),
            narration="UNKNOWN DIRECTION TXN",
            amount=499.0
        )
        self.assertIsNone(t_unspecified.is_debit)
        self.assertEqual(t_unspecified.row_status, RowStatus.UNCERTAIN)

        # Case 2: Intentional debit specified without row_status -> promotes to VALID debit
        t_debit = CleanedTransaction(
            date=date(2025, 11, 1),
            narration="EXPLICIT DEBIT TXN",
            amount=499.0,
            is_debit=True
        )
        self.assertTrue(t_debit.is_debit)
        self.assertEqual(t_debit.row_status, RowStatus.VALID)

        # Case 3: Intentional credit specified without row_status -> promotes to VALID credit
        t_credit = CleanedTransaction(
            date=date(2025, 11, 1),
            narration="EXPLICIT CREDIT TXN",
            amount=50000.0,
            is_debit=False
        )
        self.assertFalse(t_credit.is_debit)
        self.assertEqual(t_credit.row_status, RowStatus.VALID)

        # Case 4: Explicit status preserved when direction is set
        t_dupe = CleanedTransaction(
            date=date(2025, 11, 1),
            narration="DUPLICATE DEBIT",
            amount=499.0,
            is_debit=True,
            row_status=RowStatus.DUPLICATE
        )
        self.assertTrue(t_dupe.is_debit)
        self.assertEqual(t_dupe.row_status, RowStatus.DUPLICATE)

        # Case 5: Cannot force VALID row_status without direction (stays UNCERTAIN)
        t_forced = CleanedTransaction(
            date=date(2025, 11, 1),
            narration="FORCED WITHOUT DIRECTION",
            amount=499.0,
            is_debit=None,
            row_status=RowStatus.VALID
        )
        self.assertIsNone(t_forced.is_debit)
        self.assertEqual(t_forced.row_status, RowStatus.UNCERTAIN)


if __name__ == "__main__":
    unittest.main()
