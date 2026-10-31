"""Unit tests for Indian Transaction Narration Normalizer."""

import unittest
from datetime import date
from app.models import Transaction
from app.normalizer import NarrationNormalizer


class TestNarrationNormalizer(unittest.TestCase):

    def test_upi_netflix_match(self):
        narration = "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/HDFC/AUTOPAY"
        name, cat, is_known = NarrationNormalizer.match_merchant(narration)
        self.assertEqual(name, "Netflix")
        self.assertEqual(cat, "Streaming & Entertainment")
        self.assertTrue(is_known)
        self.assertTrue(NarrationNormalizer.has_mandate_keywords(narration))

    def test_ach_spotify_match(self):
        narration = "ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567"
        name, cat, is_known = NarrationNormalizer.match_merchant(narration)
        self.assertEqual(name, "Spotify")
        self.assertTrue(is_known)
        self.assertTrue(NarrationNormalizer.has_mandate_keywords(narration))

    def test_pos_amazon_prime_match(self):
        narration = "POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI"
        name, cat, is_known = NarrationNormalizer.match_merchant(narration)
        self.assertEqual(name, "Amazon Prime")
        self.assertTrue(is_known)

    def test_si_cultfit_match(self):
        narration = "SI - CULTFIT HEALTHCARE - 9982"
        name, cat, is_known = NarrationNormalizer.match_merchant(narration)
        self.assertEqual(name, "Cult.fit")
        self.assertEqual(cat, "Health & Fitness")
        self.assertTrue(NarrationNormalizer.has_mandate_keywords(narration))

    def test_hotstar_billdesk_match(self):
        narration = "BIL/ONL/000987654/HOTSTAR/MUMBAI"
        name, cat, is_known = NarrationNormalizer.match_merchant(narration)
        self.assertEqual(name, "Disney+ Hotstar")
        self.assertTrue(is_known)

    def test_google_storage_match(self):
        narration = "UPI-GOOGLE*STORAGE-GOOGLE@ICICI-887766"
        name, cat, is_known = NarrationNormalizer.match_merchant(narration)
        self.assertEqual(name, "Google One")
        self.assertEqual(cat, "Software & Cloud")

    def test_swiggy_one_match(self):
        narration = "UPI/autopay@razorpay/SWIGGY_SUPER/HDFC"
        name, cat, is_known = NarrationNormalizer.match_merchant(narration)
        self.assertEqual(name, "Swiggy One")
        self.assertTrue(NarrationNormalizer.has_mandate_keywords(narration))

    def test_unknown_merchant_clean_extraction(self):
        narration = "POS 4012XXXXXXXX5678 BLUE TOKAI COFFEE ROASTERS BANGALORE"
        name, cat, is_known = NarrationNormalizer.match_merchant(narration)
        self.assertFalse(is_known)
        self.assertIn("Blue Tokai", name)

    def test_enrich_transaction(self):
        txn = Transaction(
            date=date(2026, 1, 1),
            narration="ACH D- NETFLIX SERVICES INDIA-9911",
            amount=649.0,
            is_debit=True
        )
        enriched = NarrationNormalizer.enrich_transaction(txn)
        self.assertEqual(enriched.normalized_merchant, "Netflix")
        self.assertTrue(enriched.has_mandate_indicator)


if __name__ == "__main__":
    unittest.main()
