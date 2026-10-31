"""Verifiable Subscription & Auto-Debit Cancellation Guidance.

Provides cancellation guidance ONLY when a canonical, verifiable source is known.
Strictly avoids fabricated or hallucinated URLs. Fallbacks to standard RBI/NPCI
bank-level e-mandate revocation procedures for unverified merchants.
"""

from __future__ import annotations
from typing import Dict, List, Optional
from app.models import CancellationGuide, RecurringSeries


# Verified first-party canonical cancellation registry
# Last verified: October 2026
VERIFIED_CANCELLATION_REGISTRY: Dict[str, Dict[str, any]] = {
    "netflix": {
        "portal": "Netflix Account Portal",
        "url": "https://www.netflix.com/youraccount",
        "domain": "netflix.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Log in to your Netflix account at netflix.com/youraccount.",
            "Under 'Membership & Billing', click 'Cancel Membership'.",
            "Click 'Finish Cancellation' to confirm. Your access continues until the end of the current billing cycle.",
            "If billed via UPI Autopay or Bank Mandate, also revoke the mandate in your UPI app (Google Pay / PhonePe) to prevent retry debits."
        ]
    },
    "spotify": {
        "portal": "Spotify Account Overview",
        "url": "https://www.spotify.com/account/overview/",
        "domain": "spotify.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Log in to your Spotify account at spotify.com/account.",
            "Under 'Your plan', click 'Change plan'.",
            "Scroll down to 'Cancel Spotify' and select 'Cancel Premium'.",
            "Confirm cancellation. Your Premium benefits remain active until your next billing date."
        ]
    },
    "amazon prime": {
        "portal": "Amazon India Prime Membership",
        "url": "https://www.amazon.in/mc/manage",
        "domain": "amazon.in",
        "last_verified": "2026-10-31",
        "steps": [
            "Go to Amazon.in and navigate to 'Your Account' -> 'Prime Membership'.",
            "Click on 'Manage Membership' (top right).",
            "Select 'Update, cancel and more', then choose 'End Membership'.",
            "Follow the on-screen prompts to confirm."
        ]
    },
    "disney+ hotstar": {
        "portal": "Disney+ Hotstar Help & Subscriptions",
        "url": "https://help.hotstar.com",
        "domain": "hotstar.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Open the Disney+ Hotstar app or visit hotstar.com and log in with your registered phone number.",
            "Go to 'My Space' -> 'Help & Settings' -> 'Subscriptions & Billing'.",
            "Click 'Cancel Subscription' and confirm.",
            "If purchased via Google Play or Apple App Store, cancel directly in your respective app store subscription manager."
        ]
    },
    "youtube premium": {
        "portal": "YouTube Paid Memberships",
        "url": "https://www.youtube.com/paid_memberships",
        "domain": "youtube.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Navigate to youtube.com/paid_memberships.",
            "Click 'Manage membership' next to your active subscription.",
            "Click 'Deactivate' or 'Cancel membership'.",
            "Select the reason and confirm cancellation."
        ]
    },
    "google one": {
        "portal": "Google Play Subscriptions / Google One",
        "url": "https://play.google.com/store/account/subscriptions",
        "domain": "play.google.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Open play.google.com/store/account/subscriptions or the Play Store app.",
            "Select 'Google One' from your active subscriptions list.",
            "Click 'Cancel subscription' and follow the verification prompts."
        ]
    },
    "apple services (icloud/appstore)": {
        "portal": "Apple Subscriptions Support",
        "url": "https://support.apple.com/HT202039",
        "domain": "apple.com",
        "last_verified": "2026-10-31",
        "steps": [
            "On iPhone/iPad: Open 'Settings' -> tap your Name/Apple ID -> tap 'Subscriptions'.",
            "On Mac: Open App Store -> click your profile -> Account Settings -> Subscriptions -> Manage.",
            "Select the active subscription and tap 'Cancel Subscription'."
        ]
    },
    "apple icloud": {
        "portal": "Apple iCloud Storage Management",
        "url": "https://support.apple.com/HT207594",
        "domain": "apple.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Go to 'Settings' on your iPhone/iPad -> tap your Name -> 'iCloud' -> 'Manage Account Storage'.",
            "Tap 'Change Storage Plan' -> 'Downgrade Options'.",
            "Choose the 5 GB Free plan to cancel recurring iCloud+ billing."
        ]
    },
    "microsoft 365": {
        "portal": "Microsoft Services & Subscriptions",
        "url": "https://account.microsoft.com/services",
        "domain": "microsoft.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Sign in to account.microsoft.com/services with your Microsoft account.",
            "Find your Microsoft 365 subscription and click 'Manage'.",
            "Select 'Cancel subscription' or 'Turn off recurring billing'.",
            "Confirm the cancellation."
        ]
    },
    "swiggy one": {
        "portal": "Swiggy App Account & Memberships",
        "url": "https://www.swiggy.com",
        "domain": "swiggy.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Open the Swiggy mobile app and tap your profile icon (top right).",
            "Select 'Swiggy One' membership details.",
            "Tap 'Manage Membership' -> turn off 'Auto-renewal'.",
            "Important: If paid via UPI Autopay, open your UPI app (GPay/PhonePe/Paytm) -> Autopay -> cancel 'Swiggy' mandate."
        ]
    },
    "zomato gold": {
        "portal": "Zomato App Profile",
        "url": "https://www.zomato.com",
        "domain": "zomato.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Open the Zomato app -> Profile icon.",
            "Tap 'Zomato Gold' -> 'Manage Membership'.",
            "Toggle off auto-renew or cancel active mandate via your linked UPI payment app."
        ]
    },
    "cult.fit": {
        "portal": "Cult.fit Profile & Passes",
        "url": "https://www.cult.fit/profile",
        "domain": "cult.fit",
        "last_verified": "2026-10-31",
        "steps": [
            "Open the Cult.fit app -> tap 'Profile' -> 'Active Packs & Subscriptions'.",
            "Select your active pack -> tap 'Manage / Cancel'.",
            "Confirm pause or cancellation. To immediately prevent future debits, revoke the e-mandate in your bank or UPI app."
        ]
    },
    "jiofiber": {
        "portal": "MyJio App / Jio.com",
        "url": "https://www.jio.com/selfcare",
        "domain": "jio.com",
        "last_verified": "2026-10-31",
        "steps": [
            "Open MyJio app or visit jio.com/selfcare.",
            "Select your JioFiber service number -> 'Manage Auto-Pay'.",
            "Click 'Disable Auto-Pay' or delete the registered payment instrument/mandate."
        ]
    },
    "airtel broadband": {
        "portal": "Airtel Thanks App",
        "url": "https://www.airtel.in",
        "domain": "airtel.in",
        "last_verified": "2026-10-31",
        "steps": [
            "Open Airtel Thanks app -> 'Pay' -> 'Auto-Pay Settings'.",
            "Select your Broadband/Fiber account.",
            "Tap 'Disable Auto-Pay' and confirm with OTP."
        ]
    }
}

# Standard NPCI & RBI Framework Bank-Level Autopay Revocation Instructions
NPCI_RBI_MANDATE_INSTRUCTIONS = [
    "Under the Reserve Bank of India (RBI) E-Mandate Framework, customers have the statutory right to withdraw any recurring mandate at any time directly through their issuing bank or payment app.",
    "For Google Pay: Tap your profile picture -> 'Autopay' (or 'Mandates') -> select the merchant -> tap 'Cancel Autopay' -> enter your UPI PIN.",
    "For PhonePe: Tap your profile picture -> 'Payment Management' -> 'Autopay' -> choose the mandate -> tap 'Remove Autopay'.",
    "For Paytm: Tap profile -> 'UPI & Payment Settings' -> 'UPI Automatic Payments' -> select merchant -> tap 'Cancel'.",
    "For Netbanking / Credit Cards (HDFC, ICICI, SBI, Axis): Log in to your bank portal -> Cards / Accounts -> 'E-Mandate Hub' or 'Standing Instructions' -> select the active mandate -> click 'Modify / Cancel Mandate'."
]


class CancellationRegistry:
    """Manages verified cancellation guides and bank-level e-mandate revocation."""

    @classmethod
    def get_guidance(cls, merchant_name: str) -> CancellationGuide:
        """
        Retrieves cancellation guidance for a given merchant.
        If a verified canonical source exists, returns direct links and verified steps.
        If not verified, returns bank-level RBI/NPCI e-mandate cancellation guidance with no fake URLs.
        """
        lookup_key = merchant_name.lower().strip()
        matched_info = None

        for reg_key, info in VERIFIED_CANCELLATION_REGISTRY.items():
            if reg_key in lookup_key or lookup_key in reg_key:
                matched_info = info
                break

        if matched_info:
            return CancellationGuide(
                merchant_name=merchant_name,
                portal_name=matched_info["portal"],
                direct_url=matched_info["url"],
                is_verified_source=True,
                source_domain=matched_info["domain"],
                last_verified=matched_info["last_verified"],
                steps=matched_info["steps"],
                npci_autopay_revocable=True,
                guidance_source_explanation=f"Verified canonical portal ({matched_info['domain']}) checked as of {matched_info['last_verified']}."
            )

        # Unverified merchant: strict anti-hallucination fallback
        return CancellationGuide(
            merchant_name=merchant_name,
            portal_name="Bank / UPI Autopay Management (RBI Framework)",
            direct_url=None,
            is_verified_source=False,
            source_domain=None,
            last_verified="Standard Regulatory Rule",
            steps=NPCI_RBI_MANDATE_INSTRUCTIONS,
            npci_autopay_revocable=True,
            guidance_source_explanation="No direct self-serve URL verified for this specific merchant. Guidance provides the official RBI/NPCI bank-level e-mandate revocation steps to stop debits safely."
        )

    @classmethod
    def attach_cancellation_guides(
        cls, series_list: List[RecurringSeries]
    ) -> List[RecurringSeries]:
        """Attaches cancellation guide to each RecurringSeries."""
        for s in series_list:
            s.cancellation_info = cls.get_guidance(s.merchant_name)
        return series_list
