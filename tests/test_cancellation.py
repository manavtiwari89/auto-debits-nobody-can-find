"""Unit tests for Verifiable Cancellation Guidance."""

import unittest
from app.models import RecurringSeries, CadenceType, ConfidenceLevel
from app.cancellation import CancellationRegistry


class TestCancellationRegistry(unittest.TestCase):

    def test_verified_netflix_guidance(self):
        guide = CancellationRegistry.get_guidance("Netflix")
        self.assertTrue(guide.is_verified_source)
        self.assertEqual(guide.source_domain, "netflix.com")
        self.assertEqual(guide.direct_url, "https://www.netflix.com/youraccount")
        self.assertTrue(len(guide.steps) >= 3)
        self.assertTrue(guide.npci_autopay_revocable)

    def test_verified_spotify_guidance(self):
        guide = CancellationRegistry.get_guidance("Spotify")
        self.assertTrue(guide.is_verified_source)
        self.assertEqual(guide.source_domain, "spotify.com")
        self.assertIn("spotify.com", guide.direct_url)

    def test_unverified_merchant_strict_anti_hallucination(self):
        # A completely unknown or generic merchant
        guide = CancellationRegistry.get_guidance("ABC Fitness Hub Whitefield")
        self.assertFalse(guide.is_verified_source)
        self.assertIsNone(guide.direct_url)  # Must NOT hallucinate an URL!
        self.assertIsNone(guide.source_domain)
        self.assertTrue(guide.npci_autopay_revocable)
        self.assertIn("RBI", guide.guidance_source_explanation)
        self.assertTrue(any("Google Pay" in s for s in guide.steps))

    def test_attach_cancellation_guides(self):
        series = RecurringSeries(
            series_id="S1",
            merchant_name="Netflix",
            category="Streaming & Entertainment",
            cadence=CadenceType.MONTHLY,
            confidence=ConfidenceLevel.HIGH,
            confidence_score=0.9,
            transactions=[],
            expected_amount=649.0,
            monthly_equivalent_amount=649.0,
            annual_equivalent_amount=649.0 * 12,
            interval_mean_days=30.0,
            interval_std_days=0.5,
            evidence_reasons=[]
        )
        CancellationRegistry.attach_cancellation_guides([series])
        self.assertIsNotNone(series.cancellation_info)
        self.assertTrue(series.cancellation_info.is_verified_source)


if __name__ == "__main__":
    unittest.main()
