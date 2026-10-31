"""Unit Tests for Stage 6 Verifiable Cancellation & Mandate Guidance (src/cancellation.py).

Verifies:
1. Human-verified guide retrieval with official URLs, verified timestamps, and steps.
2. Strict anti-hallucination policy for unverified merchants (empty URL, safe fallback).
3. Fallback when source URL or verification date is missing or unverified.
4. Explicit regulatory citations distinguishing cards (RBI/2019-20/47), UPI (RBI/2019-20/139),
   and AFA limit enhancements (RBI/2022-23/73), plus NPCI UPI AutoPay.
5. Non-agency safety principle: app never claims to cancel subscriptions for users.
6. Batch attachment to RecurringSeries objects.
"""

import os
import json
import tempfile
import unittest
from src.models import (
    RecurringSeries,
    CadenceType,
    ConfidenceLevel,
    ConfidenceBreakdown,
    Evidence
)
from src.cancellation import (
    CancellationRegistry,
    MANDATE_REGULATORY_SUMMARY,
    is_valid_source_url,
    is_valid_verification_date
)


def make_dummy_series(merchant_name: str, category: str = "General / Other") -> RecurringSeries:
    """Helper to create dummy RecurringSeries."""
    return RecurringSeries(
        merchant_name=merchant_name,
        category=category,
        cadence=CadenceType.MONTHLY,
        confidence_level=ConfidenceLevel.HIGH,
        confidence_score=90.0,
        confidence_breakdown=ConfidenceBreakdown(total_score=90.0, level=ConfidenceLevel.HIGH),
        evidence=Evidence(
            intervals_days=[30],
            mean_interval_days=30.0,
            std_interval_days=0.0,
            cv_interval=0.0,
            day_of_month_list=[1],
            day_of_month_variance=0.0,
            modal_amount=500.0,
            modal_amount_ratio=1.0,
            has_mandate_keywords=True,
            notes=[]
        ),
        transactions=[],
        latest_amount=500.0,
        monthly_equivalent=500.0,
        annual_equivalent=6000.0
    )


class TestCancellationService(unittest.TestCase):
    """Test suite for CancellationRegistry in src/cancellation.py."""

    def test_verified_netflix_guidance(self):
        """Tests that Netflix returns the verified official Help Center URL and mandate steps."""
        guide = CancellationRegistry.get_cancellation_details("Netflix")
        self.assertTrue(guide.is_verified)
        self.assertEqual(guide.source_url, "https://help.netflix.com/en/node/407")
        self.assertEqual(guide.last_verified, "31 October 2026")
        self.assertIn("help.netflix.com", guide.source_url)
        self.assertTrue(len(guide.steps) >= 3)
        self.assertTrue(any("Cancel Membership" in s for s in guide.steps))
        # Mandate guidance must mention UPI AutoPay / bank mandate revocation
        self.assertTrue(any("AutoPay" in g or "mandate" in g.lower() for g in guide.mandate_guidance))

    def test_verified_spotify_guidance(self):
        """Tests Spotify verified guide lookup and steps."""
        guide = CancellationRegistry.get_cancellation_details("Spotify")
        self.assertTrue(guide.is_verified)
        self.assertEqual(guide.source_url, "https://support.spotify.com/article/how-to-cancel-premium-plans/")
        self.assertEqual(guide.last_verified, "31 October 2026")
        self.assertTrue(any("Cancel Premium" in s for s in guide.steps))

    def test_verified_amazon_prime_guidance(self):
        """Tests Amazon Prime verified guide lookup and steps."""
        guide = CancellationRegistry.get_cancellation_details("Amazon Prime")
        self.assertTrue(guide.is_verified)
        self.assertIn("amazon.in", guide.source_url)
        self.assertEqual(guide.last_verified, "31 October 2026")
        self.assertTrue(any("End Membership" in s for s in guide.steps))

    def test_verified_disney_hotstar_guidance(self):
        """Tests Disney+ Hotstar verified guide lookup."""
        guide = CancellationRegistry.get_cancellation_details("Disney+ Hotstar")
        self.assertTrue(guide.is_verified)
        self.assertIn("help.hotstar.com", guide.source_url)
        self.assertEqual(guide.last_verified, "31 October 2026")
        self.assertTrue(any("Cancel Membership" in s for s in guide.steps))

    def test_unverified_catalog_merchants_return_pure_generic_fallback(self):
        """
        Safety Test: For entries marked is_verified: false in the catalog
        (Swiggy One, Zomato Gold, Cult.fit), the service MUST return ONLY the
        generic fallback instructions. No unverified app menu paths, specific merchant
        mandate identifiers (Curefit, Bundl, Zomato Limited), or guarantees must be returned.
        """
        registry = CancellationRegistry.get_instance()
        expected_generic_steps = registry.generic_fallback["merchant_level_steps"]
        expected_generic_mandate = registry.generic_fallback["mandate_level_steps"]
        expected_generic_settings = registry.generic_fallback.get(
            "settings_location",
            "Merchant Official App/Web > Profile > Settings > Subscriptions"
        )

        unverified_merchants = [
            ("Cult.fit", ["Curefit", "cultpass"]),
            ("Swiggy One", ["Bundl", "Swiggy App > Account"]),
            ("Zomato Gold", ["Zomato Limited", "Zomato App > Profile"])
        ]

        for merchant_name, forbidden_tokens in unverified_merchants:
            guide = CancellationRegistry.get_cancellation_details(merchant_name)
            # Must be marked unverified
            self.assertFalse(guide.is_verified, f"{merchant_name} must have is_verified=False")
            self.assertEqual(guide.source_url, "", f"{merchant_name} must have empty source_url")
            self.assertEqual(guide.last_verified, "Unverified", f"{merchant_name} last_verified must be 'Unverified'")
            self.assertEqual(guide.merchant_name, merchant_name)

            # Must return purely generic steps & mandate guidance
            self.assertEqual(guide.steps, expected_generic_steps)
            self.assertEqual(guide.mandate_guidance, expected_generic_mandate)
            self.assertEqual(guide.settings_location, expected_generic_settings)

            # Strict negative assertions: no merchant mandate identifiers, unverified menu paths, or guarantees
            combined_text = " ".join(guide.steps + guide.mandate_guidance + [guide.settings_location])
            for token in forbidden_tokens:
                self.assertNotIn(token, combined_text, f"Forbidden unverified token '{token}' found in {merchant_name} guidance")
            self.assertNotIn("guarantee", combined_text.lower(), f"Forbidden word 'guarantee' found in {merchant_name} guidance")

    def test_cultfit_returns_generic_fallback(self):
        """Explicit check that Cult.fit uses the generic fallback with no Curefit identifiers."""
        guide = CancellationRegistry.get_cancellation_details("Cult.fit")
        self.assertFalse(guide.is_verified)
        self.assertEqual(guide.source_url, "")
        self.assertEqual(guide.last_verified, "Unverified")
        self.assertEqual(guide.settings_location, "Merchant Official App/Web > Profile > Settings > Subscriptions")
        self.assertNotIn("Curefit", " ".join(guide.mandate_guidance))
        self.assertTrue(any("In Indian banking" in m for m in guide.mandate_guidance))

    def test_swiggy_and_zomato_return_generic_fallback(self):
        """Explicit check that Swiggy One and Zomato Gold return generic fallback with no guarantee claims."""
        for name, forbidden in [("Swiggy One", "Bundl"), ("Zomato Gold", "Zomato Limited")]:
            guide = CancellationRegistry.get_cancellation_details(name)
            self.assertFalse(guide.is_verified)
            self.assertEqual(guide.source_url, "")
            self.assertEqual(guide.last_verified, "Unverified")
            self.assertEqual(guide.settings_location, "Merchant Official App/Web > Profile > Settings > Subscriptions")
            self.assertNotIn(forbidden, " ".join(guide.mandate_guidance))
            self.assertNotIn("guarantee", " ".join(guide.mandate_guidance).lower())

    def test_unverified_merchant_strict_anti_hallucination(self):
        """
        Anti-Hallucination Test: For an unknown or uncataloged merchant,
        the registry MUST NOT invent a URL, must mark is_verified=False,
        and must provide the safe generic first-party protocol.
        """
        guide = CancellationRegistry.get_cancellation_details("ABC Crossfit Whitefield")
        self.assertFalse(guide.is_verified)
        self.assertEqual(guide.source_url, "")
        self.assertEqual(guide.last_verified, "Unverified")
        self.assertTrue(len(guide.steps) >= 3)
        self.assertTrue(len(guide.mandate_guidance) >= 2)
        self.assertTrue(any("UPI" in m for m in guide.mandate_guidance))

    def test_entry_with_missing_source_url_triggers_unverified_fallback(self):
        """
        Regression Test: If a guide entry in JSON is marked is_verified: True
        but has a missing, empty, or invalid source_url, it MUST return the unverified fallback.
        """
        mock_data = {
          "cancellation_guides": [
            {
              "merchant": "Flawed Service",
              "category": "Streaming",
              "is_verified": True,
              "source_url": "",  # Missing/empty URL!
              "last_verified": "31 October 2026",
              "cancellation_steps": ["Click Cancel"],
              "mandate_guidance": ["Revoke mandate in UPI"]
            }
          ],
          "generic_fallback": {
            "merchant_level_steps": ["Go to app > Settings > Cancel"],
            "mandate_level_steps": ["Revoke mandate in UPI app"]
          }
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(mock_data, f)
            temp_path = f.name

        try:
            guide = CancellationRegistry.get_cancellation_details("Flawed Service", guide_path=temp_path)
            self.assertFalse(guide.is_verified)
            self.assertEqual(guide.source_url, "")
            self.assertEqual(guide.last_verified, "Unverified")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_entry_with_missing_verification_date_triggers_unverified_fallback(self):
        """
        Regression Test: If a guide entry in JSON is marked is_verified: True
        and has a valid source_url but lacks an explicitly recorded last_verified date,
        it MUST NOT default to any date and MUST return the unverified fallback.
        """
        mock_data = {
          "cancellation_guides": [
            {
              "merchant": "Undated Service",
              "category": "Cloud",
              "is_verified": True,
              "source_url": "https://example.com/cancel",
              "last_verified": None,  # Missing verification date!
              "cancellation_steps": ["Click Cancel"],
              "mandate_guidance": ["Revoke mandate in UPI"]
            }
          ],
          "generic_fallback": {
            "merchant_level_steps": ["Go to app > Settings > Cancel"],
            "mandate_level_steps": ["Revoke mandate in UPI app"]
          }
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(mock_data, f)
            temp_path = f.name

        try:
            guide = CancellationRegistry.get_cancellation_details("Undated Service", guide_path=temp_path)
            self.assertFalse(guide.is_verified)
            self.assertEqual(guide.source_url, "")
            self.assertEqual(guide.last_verified, "Unverified")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_regulatory_references_accuracy(self):
        """
        Regulatory Test: Verifies accurate citations for:
        - Cards & PPIs: RBI/2019-20/47
        - UPI: RBI/2019-20/139
        - Limit Enhancement: RBI/2022-23/73
        - NPCI UPI AutoPay Framework
        """
        summary = CancellationRegistry.get_mandate_revocation_summary()
        self.assertIn("E-Mandate", summary["framework"])
        self.assertIn("does NOT automatically revoke", summary["core_principle"])

        sources = summary["official_sources"]
        circular_refs = [s.get("circular_ref", "") for s in sources]
        subjects = [s.get("subject", "") for s in sources]

        # Check card circular
        card_entry = next(s for s in sources if "cards" in s.get("subject", "").lower())
        self.assertIn("RBI/2019-20/47", card_entry["circular_ref"])
        self.assertIn("cards", card_entry["scope"].lower())

        # Check separate UPI circular
        upi_entry = next(s for s in sources if "unified payments interface" in s.get("subject", "").lower())
        self.assertIn("RBI/2019-20/139", upi_entry["circular_ref"])
        self.assertIn("upi", upi_entry["scope"].lower())

        # Check AFA limit enhancement circular
        limit_entry = next(s for s in sources if "enhancement of limit" in s.get("subject", "").lower())
        self.assertIn("RBI/2022-23/73", limit_entry["circular_ref"])
        self.assertIn("15,000", limit_entry["scope"])

        # Check NPCI AutoPay
        npci_entry = next(s for s in sources if "NPCI" in s.get("authority", ""))
        self.assertEqual(npci_entry["url"], "https://www.npci.org.in/what-we-do/upi/upi-autopay")

    def test_app_never_cancels_on_behalf_of_user(self):
        """Verifies clear disclosure that the application does not cancel on behalf of users."""
        summary = CancellationRegistry.get_mandate_revocation_summary()
        disclaimer = summary["app_boundary_disclaimer"]
        self.assertIn("NEVER cancels", disclaimer)
        self.assertIn("must be completed by you directly", disclaimer)

    def test_attach_cancellation_details(self):
        """Tests batch attachment of cancellation details to RecurringSeries list."""
        series_netflix = make_dummy_series("Netflix", "Streaming & Media")
        series_unknown = make_dummy_series("Local Coworking Space", "General / Other")

        series_list = [series_netflix, series_unknown]
        CancellationRegistry.attach_cancellation_details(series_list)

        self.assertIsNotNone(series_netflix.cancellation_details)
        self.assertTrue(series_netflix.cancellation_details.is_verified)
        self.assertEqual(series_netflix.cancellation_details.merchant_name, "Netflix")
        self.assertEqual(series_netflix.cancellation_details.last_verified, "31 October 2026")

        self.assertIsNotNone(series_unknown.cancellation_details)
        self.assertFalse(series_unknown.cancellation_details.is_verified)
        self.assertEqual(series_unknown.cancellation_details.source_url, "")
        self.assertEqual(series_unknown.cancellation_details.last_verified, "Unverified")


if __name__ == "__main__":
    unittest.main()
