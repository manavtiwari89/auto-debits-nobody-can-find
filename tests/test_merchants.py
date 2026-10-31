"""Unit tests for Merchant Normalization & 4-Tier Matching Cascade (src/merchants.py)."""

import unittest
from datetime import date
from src.merchants import MerchantMatcher, NarrationCleaner
from src.models import MatchMethod, CleanedTransaction, RowStatus


class TestMerchantNormalization(unittest.TestCase):

    def test_tier1_exact_alias_match(self):
        """Tier 1: Exact alias match with 1.0 confidence."""
        m_netflix = MerchantMatcher.match("NETFLIX")
        self.assertEqual(m_netflix.normalized_name, "Netflix")
        self.assertEqual(m_netflix.category, "Streaming & Media")
        self.assertEqual(m_netflix.method, MatchMethod.EXACT_ALIAS)
        self.assertEqual(m_netflix.match_confidence, 1.0)
        self.assertFalse(m_netflix.is_variable_bill)
        self.assertFalse(m_netflix.is_retail)

        m_spotify = MerchantMatcher.match("SPOTIFY PREMIUM")
        self.assertEqual(m_spotify.normalized_name, "Spotify")
        self.assertEqual(m_spotify.method, MatchMethod.EXACT_ALIAS)
        self.assertEqual(m_spotify.match_confidence, 1.0)

        m_prime = MerchantMatcher.match("AMAZON PRIME")
        self.assertEqual(m_prime.normalized_name, "Amazon Prime")
        self.assertEqual(m_prime.method, MatchMethod.EXACT_ALIAS)
        self.assertEqual(m_prime.match_confidence, 1.0)

    def test_tier2_rule_regex_match(self):
        """Tier 2: Token / regex pattern match with high confidence (0.90 - 0.95)."""
        # UPI prefix + reference + location
        m1 = MerchantMatcher.match("UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/HDFC/AUTOPAY")
        self.assertEqual(m1.normalized_name, "Netflix")
        self.assertEqual(m1.method, MatchMethod.RULE_REGEX)
        self.assertGreaterEqual(m1.match_confidence, 0.90)

        # ACH debit prefix + entity name
        m2 = MerchantMatcher.match("ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567")
        self.assertEqual(m2.normalized_name, "Spotify")
        self.assertEqual(m2.method, MatchMethod.RULE_REGEX)
        self.assertGreaterEqual(m2.match_confidence, 0.90)

        # BillDesk billing prefix + Hotstar
        m3 = MerchantMatcher.match("BIL/ONL/000987654/HOTSTAR/MUMBAI")
        self.assertEqual(m3.normalized_name, "Disney+ Hotstar")
        self.assertEqual(m3.method, MatchMethod.RULE_REGEX)
        self.assertGreaterEqual(m3.match_confidence, 0.90)

        # Google storage with ICICI VPA handle
        m4 = MerchantMatcher.match("UPI-GOOGLE*STORAGE-GOOGLE@ICICI-887766")
        self.assertEqual(m4.normalized_name, "Google One")
        self.assertEqual(m4.category, "Software & Cloud")
        self.assertEqual(m4.method, MatchMethod.RULE_REGEX)

        # Card mask with Amazon Prime
        m5 = MerchantMatcher.match("POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI")
        self.assertEqual(m5.normalized_name, "Amazon Prime")
        self.assertEqual(m5.method, MatchMethod.RULE_REGEX)

        # Swiggy One membership (specific match should not trigger generic Swiggy)
        m6 = MerchantMatcher.match("UPI/P2M/BUNDL TECH SWIGGY ONE MEMBERSHIP/AUTOPAY")
        self.assertEqual(m6.normalized_name, "Swiggy One")
        self.assertFalse(m6.is_retail)
        self.assertEqual(m6.method, MatchMethod.RULE_REGEX)

    def test_tier3_fuzzy_similarity_match(self):
        """Tier 3: Fuzzy string similarity for minor typos (confidence 0.60 - 0.80)."""
        # Typo: 'NETFLX ENTERTAINMNT' (vowels dropped)
        m1 = MerchantMatcher.match("UPI/P2M/NETFLX ENTERTAINMNT/AUTOPAY")
        self.assertEqual(m1.normalized_name, "Netflix")
        self.assertEqual(m1.method, MatchMethod.FUZZY)
        self.assertGreaterEqual(m1.match_confidence, 0.60)
        self.assertLessEqual(m1.match_confidence, 0.85)

        # Typo: 'SPOTFY PREMUM'
        m2 = MerchantMatcher.match("ACH D- SPOTFY PREMUM-8877")
        self.assertEqual(m2.normalized_name, "Spotify")
        self.assertEqual(m2.method, MatchMethod.FUZZY)
        self.assertGreaterEqual(m2.match_confidence, 0.60)

        # Typo: 'HOTSTARR'
        m3 = MerchantMatcher.match("BIL/ONL/HOTSTARR/MUMBAI")
        self.assertEqual(m3.normalized_name, "Disney+ Hotstar")
        self.assertEqual(m3.method, MatchMethod.FUZZY)

    def test_tier4_unknown_merchant_fallback(self):
        """Tier 4: Unknown merchant fallback extracts business tokens without inventing fake brand."""
        # Unverified local gym
        m_gym = MerchantMatcher.match("UPI/P2M/883311/FITNESS FIRST GYM/AUTOPAY")
        self.assertEqual(m_gym.normalized_name, "Fitness First Gym")
        self.assertEqual(m_gym.category, "General / Other")
        self.assertEqual(m_gym.method, MatchMethod.UNKNOWN)
        self.assertLessEqual(m_gym.match_confidence, 0.40)
        self.assertFalse(m_gym.is_retail)

        # Unverified publication
        m_hindu = MerchantMatcher.match("ACH D- THE HINDU DIGITAL-991")
        self.assertEqual(m_hindu.normalized_name, "The Hindu Digital")
        self.assertEqual(m_hindu.method, MatchMethod.UNKNOWN)
        self.assertLessEqual(m_hindu.match_confidence, 0.40)

        # Generic unknown transaction
        m_random = MerchantMatcher.match("UPI/P2M/UNKNOWN VENDOR 99882/PAY")
        self.assertEqual(m_random.method, MatchMethod.UNKNOWN)
        self.assertNotEqual(m_random.normalized_name, "Netflix")
        self.assertNotEqual(m_random.normalized_name, "Spotify")

    def test_variable_bill_and_retail_flags(self):
        """Verify that variable utility bills and retail food delivery are properly flagged."""
        m_bescom = MerchantMatcher.match("BIL/ONL/BESCOM BANGALORE ELECTRICITY AUTOPAY")
        self.assertEqual(m_bescom.normalized_name, "BESCOM Electricity")
        self.assertTrue(m_bescom.is_variable_bill)
        self.assertFalse(m_bescom.is_retail)

        m_swiggy = MerchantMatcher.match("UPI-SWIGGY-ORDER-BANGALORE")
        self.assertEqual(m_swiggy.normalized_name, "Swiggy")
        self.assertTrue(m_swiggy.is_retail)
        self.assertFalse(m_swiggy.is_variable_bill)

        m_zomato = MerchantMatcher.match("UPI-ZOMATO-RESTAURANT-ORDER")
        self.assertEqual(m_zomato.normalized_name, "Zomato")
        self.assertTrue(m_zomato.is_retail)

    def test_enrich_transaction(self):
        """Verify transaction enrichment preserves original raw narration."""
        txn = CleanedTransaction(
            date=date(2025, 11, 2),
            narration="UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/HDFC/AUTOPAY",
            amount=499.0,
            is_debit=True,
            reference_id="REF001",
            row_status=RowStatus.VALID
        )

        enriched = MerchantMatcher.enrich_transaction(txn)
        self.assertEqual(enriched.narration, "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/HDFC/AUTOPAY")
        self.assertEqual(enriched.normalized_merchant, "Netflix")
        self.assertIsNotNone(enriched.merchant_match)
        self.assertEqual(enriched.merchant_match.normalized_name, "Netflix")
        self.assertEqual(enriched.merchant_match.method, MatchMethod.RULE_REGEX)
        self.assertEqual(enriched.merchant_match.category, "Streaming & Media")
        self.assertFalse(enriched.merchant_match.is_variable_bill)

    def test_false_merchant_match_prevention_unrelated_business_names(self):
        """
        Regression tests: narrations containing a merchant name as part of an
        unrelated business name (e.g. 'The Netflix Cafe') must NOT be falsely
        classified as subscription merchants with high confidence.
        """
        test_cases = [
            ("The Netflix Cafe", "The Netflix Cafe"),
            ("Netflix Cafe", "Netflix Cafe"),
            ("Amazon Tea Stall", "Amazon Tea Stall"),
            ("Apple Dental Clinic", "Apple Dental Clinic"),
            ("Spotify Juice Bar", "Spotify Juice Bar"),
            ("Hotstar Bakery", "Hotstar Bakery"),
            ("Google Fast Food", "Google Fast Food"),
        ]

        for narration, expected_key in test_cases:
            match = MerchantMatcher.match(narration)
            self.assertEqual(
                match.method,
                MatchMethod.UNKNOWN,
                f"Expected UNKNOWN match method for '{narration}', but got {match.method} with normalized name '{match.normalized_name}'"
            )
            self.assertEqual(match.normalized_name, expected_key)
            self.assertLessEqual(
                match.match_confidence,
                0.40,
                f"Confidence for '{narration}' should not exceed 0.40, got {match.match_confidence}"
            )
            self.assertNotEqual(match.normalized_name, "Netflix")
            self.assertNotEqual(match.normalized_name, "Amazon Prime")
            self.assertNotEqual(match.normalized_name, "Apple Services")
            self.assertNotEqual(match.normalized_name, "Spotify")
            self.assertNotEqual(match.normalized_name, "Disney+ Hotstar")
            self.assertNotEqual(match.normalized_name, "Google One")

    def test_genuine_bank_narrations_continue_matching_correctly(self):
        """Verifies that legitimate bank narrations with noise and mandates continue matching."""
        genuine_cases = [
            ("UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/HDFC/AUTOPAY", "Netflix", 0.95),
            ("ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567", "Spotify", 0.95),
            ("BIL/ONL/000987654/HOTSTAR/MUMBAI", "Disney+ Hotstar", 0.95),
            ("POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI", "Amazon Prime", 0.95),
            ("UPI-GOOGLE*STORAGE-GOOGLE@ICICI-887766", "Google One", 0.95),
            ("STARBUCKS COFFEE", "Starbucks", 0.90),
            ("UPI-ZOMATO-RESTAURANT-ORDER", "Zomato", 0.90),
        ]

        for narration, expected_name, min_conf in genuine_cases:
            match = MerchantMatcher.match(narration)
            self.assertEqual(match.normalized_name, expected_name)
            self.assertIn(match.method, (MatchMethod.EXACT_ALIAS, MatchMethod.RULE_REGEX))
            self.assertGreaterEqual(match.match_confidence, min_conf)


if __name__ == "__main__":
    unittest.main()
