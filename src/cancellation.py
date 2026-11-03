"""Verifiable Subscription Cancellation & Mandate Revocation Registry.

Provides human-verified, canonical cancellation pathways for recurring services,
with direct links to official help portals and verified verification dates.
Strictly adheres to an anti-hallucination policy: unverified merchants receive
the safe, standardized NPCI/RBI first-party mandate revocation protocol without
inventing URLs or fabricated steps.

Clarifies the critical regulatory distinction: cancelling an app subscription
does NOT automatically revoke a bank-level e-mandate or UPI AutoPay authorization.
"""

from __future__ import annotations
import os
import json
from typing import Dict, List, Optional, Any

from src.models import (
    CancellationDetails,
    RecurringSeries
)

DEFAULT_CANCELLATION_GUIDE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "cancellation_guide.json"
)

# Standardized NPCI & RBI Regulatory Framework
MANDATE_REGULATORY_SUMMARY: Dict[str, Any] = {
    "framework": "RBI Digital Payments E-Mandate Regulatory Framework & NPCI UPI AutoPay",
    "core_principle": (
        "In Indian banking, cancelling an in-app subscription stops the merchant from requesting renewals, "
        "but does NOT automatically revoke the bank-level standing mandate. Conversely, revoking a mandate "
        "withdraws the bank's debit authority, but does not cancel active contractual agreements. "
        "If you want to stop both service renewals and payment authority, handle merchant cancellation "
        "and bank/UPI mandate revocation as separate steps where applicable. Check the service terms; "
        "revoking a mandate alone may not end a contract or settle an amount already owed."
    ),
    "official_sources": [
        {
            "authority": "National Payments Corporation of India (NPCI)",
            "subject": "UPI AutoPay Operational Framework & Customer Mandate Management",
            "scope": (
                "Governs creation, modification, pause, unpause, and revocation of recurring payment "
                "mandates executed directly within UPI apps (Google Pay, PhonePe, Paytm, BHIM, CRED) "
                "secured by user UPI PIN."
            ),
            "url": "https://www.npci.org.in/what-we-do/upi/upi-autopay"
        },
        {
            "authority": "Reserve Bank of India (RBI)",
            "subject": "Processing of e-mandate on cards for recurring transactions",
            "circular_ref": "RBI/2019-20/47 (DPSS.CO.PD.No.447/02.14.003/2019-20)",
            "date": "2019-08-21",
            "scope": (
                "Baseline framework for recurring e-mandates on cards and Prepaid Payment Instruments (PPIs). "
                "Mandated 24-hour pre-debit notifications and cardholder opt-out/revocation facility."
            )
        },
        {
            "authority": "Reserve Bank of India (RBI)",
            "subject": "Processing of e-mandates for recurring transactions through Unified Payments Interface (UPI)",
            "circular_ref": "RBI/2019-20/139 (DPSS.CO.PD No.1324/02.23.001/2019-20)",
            "date": "2020-01-10",
            "scope": (
                "Formally extended the e-mandate framework to recurring UPI transactions. Mandated user "
                "authorization via Additional Factor of Authentication (AFA/UPI PIN) during registration, "
                "24-hour pre-debit notifications, and customer-facing mandate modification/revocation in UPI apps."
            )
        },
        {
            "authority": "Reserve Bank of India (RBI)",
            "subject": "Enhancement of limit for e-mandates on cards / PPIs / UPI with AFA relaxation",
            "circular_ref": "RBI/2022-23/73 (CO.DPSS.POLC.No.S-518/02.14.003/2022-23)",
            "date": "2022-06-16",
            "scope": (
                "Raised the AFA waiver threshold limit for recurring transactions from ₹5,000 to ₹15,000 "
                "per transaction across cards, PPIs, and UPI."
            )
        }
    ],
    "app_boundary_disclaimer": (
        "Privacy & Safety Notice: This application is purely diagnostic. Statement data is processed "
        "in memory by the machine running the app; when run locally, it stays on your device, while "
        "a hosted deployment processes it on the hosting server. "
        "It never accesses your bank credentials, never connects to third-party APIs, and NEVER cancels "
        "subscriptions or revokes mandates on your behalf. All cancellations must be completed by you directly."
    )
}


def is_valid_source_url(url: Optional[str]) -> bool:
    """Validates that a source URL is non-empty and has a valid http(s) scheme."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    return u.startswith("https://") or u.startswith("http://")


def is_valid_verification_date(last_verified: Optional[str]) -> bool:
    """Validates that a verification date is explicitly recorded and not marked Unverified."""
    if not last_verified or not isinstance(last_verified, str):
        return False
    v = last_verified.strip()
    return bool(v) and v.lower() != "unverified"


class CancellationRegistry:
    """Manages verified cancellation guides and mandate revocation protocols."""

    _instance: Optional[CancellationRegistry] = None

    def __init__(self, guide_path: Optional[str] = None):
        self.guide_path = guide_path or DEFAULT_CANCELLATION_GUIDE_PATH
        self.verified_guides: Dict[str, Dict[str, Any]] = {}
        self.generic_fallback: Dict[str, Any] = {}
        self._load_guides()

    def _load_guides(self) -> None:
        if not os.path.exists(self.guide_path):
            raise FileNotFoundError(f"Cancellation guide file not found: {self.guide_path}")

        with open(self.guide_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for guide in data.get("cancellation_guides", []):
            merchant_name = guide.get("merchant", "").lower().strip()
            if merchant_name:
                self.verified_guides[merchant_name] = guide

        self.generic_fallback = data.get("generic_fallback", {})

    @classmethod
    def get_instance(cls, guide_path: Optional[str] = None) -> CancellationRegistry:
        target_path = guide_path or DEFAULT_CANCELLATION_GUIDE_PATH
        if cls._instance is None or cls._instance.guide_path != target_path:
            cls._instance = cls(guide_path=target_path)
        return cls._instance

    @classmethod
    def get_cancellation_details(
        cls,
        merchant_name: str,
        category: Optional[str] = None,
        guide_path: Optional[str] = None
    ) -> CancellationDetails:
        """
        Retrieves cancellation guidance for a given merchant.

        Strict Verification Protocol:
        - Must be found in the database with `is_verified: True`.
        - Must have a valid, non-empty HTTP/HTTPS `source_url`.
        - Must have an explicitly recorded, non-empty `last_verified` date (never defaulted).
        If any of these conditions are not met, returns the safe unverified fallback with
        `is_verified=False`, `source_url=""`, and `last_verified="Unverified"`.
        """
        registry = cls.get_instance(guide_path=guide_path)
        lookup_key = merchant_name.lower().strip()

        # Check exact key or alias matches
        match_guide = registry.verified_guides.get(lookup_key)
        if not match_guide:
            # Fuzzy/partial fallback check among verified guides
            for k, g in registry.verified_guides.items():
                if k in lookup_key or lookup_key in k:
                    match_guide = g
                    break

        if match_guide:
            guide_is_verified = match_guide.get("is_verified", False)
            source_url = match_guide.get("source_url")
            last_verified = match_guide.get("last_verified")

            # Must satisfy all three strict verification criteria
            if (
                guide_is_verified
                and is_valid_source_url(source_url)
                and is_valid_verification_date(last_verified)
            ):
                return CancellationDetails(
                    merchant_name=match_guide.get("merchant", merchant_name),
                    category=category or match_guide.get("category", "General / Other"),
                    settings_location=match_guide.get("settings_location", "Account Settings"),
                    steps=list(match_guide.get("cancellation_steps", [])),
                    source_url=str(source_url).strip(),
                    last_verified=str(last_verified).strip(),
                    mandate_guidance=list(match_guide.get("mandate_guidance", [])),
                    is_verified=True
                )

        # Unverified Merchant Safe Fallback (Strict Anti-Hallucination)
        # For any unverified merchant (including catalog entries marked is_verified: false
        # like Swiggy One, Zomato Gold, Cult.fit, and uncataloged merchants), return ONLY
        # the generic fallback instructions. No unverified app menu paths, specific merchant
        # mandate identifiers, or guarantees are returned.
        fallback = registry.generic_fallback
        generic_steps = list(fallback.get("merchant_level_steps", [
            "Log into the merchant's official web portal or mobile application directly.",
            "Navigate to Account / Profile > Settings > Subscriptions, Billing, or Payments.",
            "Look for an option labelled 'Cancel Subscription', 'Turn Off Auto-Renew', or 'Manage Plan'.",
            "Ensure you receive a confirmation email or SMS acknowledging cancellation."
        ]))
        generic_mandate = list(fallback.get("mandate_level_steps", [
            "In Indian banking, cancelling an in-app subscription does NOT always revoke the bank-level standing mandate.",
            "Open your UPI Application (Google Pay, PhonePe, Paytm, BHIM, CRED).",
            "Go to Settings / Profile > 'AutoPay' / 'Recurring Payments' / 'E-mandates'.",
            "Locate the merchant name or VPA, tap 'Revoke Mandate' or 'Cancel', and enter your UPI PIN to stop future debits.",
            "For debit/credit card e-mandates, log into your issuing bank's NetBanking portal and visit the 'SI Hub / E-Mandate Management' section to cancel."
        ]))
        generic_settings_loc = fallback.get(
            "settings_location",
            "Merchant Official App/Web > Profile > Settings > Subscriptions"
        )

        merchant_display = match_guide.get("merchant", merchant_name) if match_guide else merchant_name
        cat = category or (match_guide.get("category") if match_guide else "General / Other")

        return CancellationDetails(
            merchant_name=merchant_display,
            category=cat,
            settings_location=generic_settings_loc,
            steps=generic_steps,
            source_url="",  # Never invent URLs for unverified merchants
            last_verified="Unverified",
            mandate_guidance=generic_mandate,
            is_verified=False
        )

    @classmethod
    def attach_cancellation_details(
        cls,
        series_list: List[RecurringSeries],
        guide_path: Optional[str] = None
    ) -> List[RecurringSeries]:
        """
        Attaches CancellationDetails to each RecurringSeries in the list.
        """
        for s in series_list:
            s.cancellation_details = cls.get_cancellation_details(
                merchant_name=s.merchant_name,
                category=s.category,
                guide_path=guide_path
            )
        return series_list

    @classmethod
    def get_mandate_revocation_summary(cls) -> Dict[str, Any]:
        """Returns standard NPCI and RBI mandate revocation regulatory information."""
        return MANDATE_REGULATORY_SUMMARY
