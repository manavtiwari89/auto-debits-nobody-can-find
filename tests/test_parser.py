"""Unit tests for Indian Bank Statement CSV Parser."""

import unittest
from datetime import date
from app.parser import BankStatementParser, clean_amount, parse_date


class TestBankStatementParser(unittest.TestCase):

    def test_clean_amount(self):
        self.assertEqual(clean_amount("₹ 1,499.00"), 1499.0)
        self.assertEqual(clean_amount("1,50,000.50"), 150000.5)
        self.assertEqual(clean_amount("Rs. 199"), 199.0)
        self.assertEqual(clean_amount("(499.00)"), -499.0)
        self.assertEqual(clean_amount("499.00 Dr"), 499.0)
        self.assertIsNone(clean_amount("-"))
        self.assertIsNone(clean_amount(""))
        self.assertIsNone(clean_amount(None))

    def test_parse_date(self):
        self.assertEqual(parse_date("31/10/2026"), date(2026, 10, 31))
        self.assertEqual(parse_date("15-08-2026"), date(2026, 8, 15))
        self.assertEqual(parse_date("2026-05-01"), date(2026, 5, 1))
        self.assertEqual(parse_date("01.06.2026"), date(2026, 6, 1))
        self.assertEqual(parse_date("15-Oct-2026"), date(2026, 10, 15))
        self.assertEqual(parse_date("31/10/2026 18:30:00"), date(2026, 10, 31))
        self.assertIsNone(parse_date("Invalid"))

    def test_parse_hdfc_format_with_metadata(self):
        csv_text = """HDFC BANK STATEMENT
Account Number: SYNTHETIC-ACCOUNT
Generated On: 31/10/2026
Branch: KORAMANGALA BANGALORE
Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
01/01/2026,UPI-NETFLIX-NETFLIX@HDFC-123456,REF100,01/01/2026,649.00,,45200.00
05/01/2026,SALARY CREDIT FROM TECH CORP,SAL001,05/01/2026,,95000.00,140200.00
01/02/2026,UPI-NETFLIX-NETFLIX@HDFC-234567,REF101,01/02/2026,649.00,,139551.00
"""
        txns = BankStatementParser.parse_csv_content(csv_text, "HDFC")
        self.assertEqual(len(txns), 3)
        self.assertEqual(txns[0].date, date(2026, 1, 1))
        self.assertEqual(txns[0].amount, 649.0)
        self.assertTrue(txns[0].is_debit)
        self.assertEqual(txns[1].amount, 95000.0)
        self.assertFalse(txns[1].is_debit)
        self.assertEqual(txns[2].amount, 649.0)
        self.assertTrue(txns[2].is_debit)

    def test_parse_icici_format(self):
        csv_text = """Transaction Date,Value Date,Description,Cheque Number,Dr Amount,Cr Amount,Balance
15/03/2026,15/03/2026,ACH D- SPOTIFY INDIA-9988,,119.00,,32100.00
15/04/2026,15/04/2026,ACH D- SPOTIFY INDIA-9989,,129.00,,31971.00
"""
        txns = BankStatementParser.parse_csv_content(csv_text, "ICICI")
        self.assertEqual(len(txns), 2)
        self.assertEqual(txns[0].amount, 119.0)
        self.assertTrue(txns[0].is_debit)
        self.assertEqual(txns[1].amount, 129.0)
        self.assertTrue(txns[1].is_debit)

    def test_parse_sbi_format(self):
        csv_text = """Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance
10-Jan-2026,10-Jan-2026,POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI,REF999,1499.00,,18500.00
20-Jan-2026,20-Jan-2026,UPI-SWIGGY-BANGALORE,REF1000,340.00,,18160.00
"""
        txns = BankStatementParser.parse_csv_content(csv_text, "SBI")
        self.assertEqual(len(txns), 2)
        self.assertEqual(txns[0].amount, 1499.0)
        self.assertEqual(txns[0].date, date(2026, 1, 10))
        self.assertTrue(txns[0].is_debit)


if __name__ == "__main__":
    unittest.main()
