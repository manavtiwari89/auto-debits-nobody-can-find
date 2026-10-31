"""Unit tests for CSV Ingestion and Schema Validation (src/ingestion.py)."""

import unittest
from src.ingestion import StatementIngestor
from src.models import SchemaValidationError


class TestStatementIngestion(unittest.TestCase):

    def test_ingest_hdfc_format_with_metadata_preamble(self):
        csv_text = """HDFC BANK STATEMENT
Customer Name: AARAV PATEL
Account Number: SYNTHETIC-ACCOUNT
Statement Period: 01/11/2025 to 31/10/2026
Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
02/11/2025,UPI/P2M/NETFLIX,REF001,02/11/2025,499.00,,124501.00
05/11/2025,ACH D- SPOTIFY,REF002,05/11/2025,119.00,,124382.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text, "hdfc_sample.csv")
        self.assertEqual(ingested.bank_name, "HDFC Bank")
        self.assertEqual(ingested.delimiter, ",")
        self.assertEqual(ingested.header_row_index, 4)
        self.assertEqual(len(ingested.raw_rows), 2)
        self.assertIn("date", ingested.column_mapping)
        self.assertIn("narration", ingested.column_mapping)
        self.assertIn("debit", ingested.column_mapping)
        self.assertIn("credit", ingested.column_mapping)

    def test_ingest_sbi_format_semicolon_delimited(self):
        csv_text = """STATE BANK OF INDIA
Txn Date;Value Date;Description;Ref No./Cheque No.;Debit;Credit;Balance
02-11-2025;02-11-2025;UPI/NETFLIX;REF001;649.00;;84351.00
05-11-2025;05-11-2025;ACH/SPOTIFY;REF002;119.00;;84232.00
"""
        ingested = StatementIngestor.ingest_csv_text(csv_text, "sbi_statement.csv")
        self.assertEqual(ingested.bank_name, "State Bank of India")
        self.assertEqual(ingested.delimiter, ";")
        self.assertEqual(ingested.header_row_index, 1)
        self.assertEqual(len(ingested.raw_rows), 2)

    def test_ingest_tab_delimited_generic_statement(self):
        csv_text = "Date\tNarration\tReference\tAmount\n01/01/2026\tGOOGLE ONE\tREF1\t130.00\n"
        ingested = StatementIngestor.ingest_csv_text(csv_text)
        self.assertEqual(ingested.delimiter, "\t")
        self.assertEqual(ingested.header_row_index, 0)
        self.assertEqual(len(ingested.raw_rows), 1)

    def test_empty_csv_raises_schema_validation_error(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            StatementIngestor.ingest_csv_text("")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_missing_date_column_raises_schema_validation_error(self):
        csv_text = "Description,Withdrawal,Deposit,Balance\nNetflix,499.00,,1000.00\n"
        with self.assertRaises(SchemaValidationError) as ctx:
            StatementIngestor.ingest_csv_text(csv_text)
        self.assertIn("date", str(ctx.exception).lower())
        self.assertIn("Date", ctx.exception.missing_fields)

    def test_missing_amount_columns_raises_schema_validation_error(self):
        csv_text = "Date,Description,Reference,Balance\n01/01/2026,Netflix,REF1,1000.00\n"
        with self.assertRaises(SchemaValidationError) as ctx:
            StatementIngestor.ingest_csv_text(csv_text)
        self.assertIn("amount", str(ctx.exception).lower())

    def test_no_header_found_raises_schema_validation_error(self):
        csv_text = "Random Line 1\nRandom Line 2\nJust some notes without columns"
        with self.assertRaises(SchemaValidationError) as ctx:
            StatementIngestor.ingest_csv_text(csv_text)
        self.assertIn("header", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
