"""Indian Transaction Narration Normalizer & Merchant Matcher.

Cleans noisy Indian bank narration strings (UPI, NACH, ACH, ECS, POS masks,
BillDesk/BillPay gateways) and normalizes merchant names with categorization.
"""

from __future__ import annotations
import re
from typing import Tuple, Optional, Dict, Any
from app.models import Transaction


# Known Indian & Global subscription merchants with category and canonical name
MERCHANT_KNOWLEDGE_BASE: Dict[str, Dict[str, str]] = {
    # Streaming & Entertainment
    "netflix": {"name": "Netflix", "category": "Streaming & Entertainment"},
    "spotify": {"name": "Spotify", "category": "Streaming & Entertainment"},
    "amazon prime": {"name": "Amazon Prime", "category": "Streaming & Entertainment"},
    "amzn prime": {"name": "Amazon Prime", "category": "Streaming & Entertainment"},
    "prime video": {"name": "Amazon Prime", "category": "Streaming & Entertainment"},
    "hotstar": {"name": "Disney+ Hotstar", "category": "Streaming & Entertainment"},
    "disneystar": {"name": "Disney+ Hotstar", "category": "Streaming & Entertainment"},
    "disney+": {"name": "Disney+ Hotstar", "category": "Streaming & Entertainment"},
    "youtube": {"name": "YouTube Premium", "category": "Streaming & Entertainment"},
    "yt premium": {"name": "YouTube Premium", "category": "Streaming & Entertainment"},
    "sony liv": {"name": "Sony LIV", "category": "Streaming & Entertainment"},
    "sonyliv": {"name": "Sony LIV", "category": "Streaming & Entertainment"},
    "zee5": {"name": "Zee5", "category": "Streaming & Entertainment"},
    "jiocinema": {"name": "JioCinema", "category": "Streaming & Entertainment"},
    "audible": {"name": "Audible", "category": "Streaming & Entertainment"},
    "storytel": {"name": "Storytel", "category": "Streaming & Entertainment"},
    "apple music": {"name": "Apple Music", "category": "Streaming & Entertainment"},
    "apple tv": {"name": "Apple TV+", "category": "Streaming & Entertainment"},
    
    # Software, SaaS & Cloud Storage
    "google storage": {"name": "Google One", "category": "Software & Cloud"},
    "google one": {"name": "Google One", "category": "Software & Cloud"},
    "google play": {"name": "Google Play", "category": "Software & Cloud"},
    "google cloud": {"name": "Google Cloud", "category": "Software & Cloud"},
    "apple.com/bill": {"name": "Apple Services (iCloud/AppStore)", "category": "Software & Cloud"},
    "icloud": {"name": "Apple iCloud", "category": "Software & Cloud"},
    "microsoft 365": {"name": "Microsoft 365", "category": "Software & Cloud"},
    "msft *": {"name": "Microsoft 365", "category": "Software & Cloud"},
    "microsoft": {"name": "Microsoft 365", "category": "Software & Cloud"},
    "openai": {"name": "OpenAI (ChatGPT)", "category": "Software & Cloud"},
    "chatgpt": {"name": "OpenAI (ChatGPT)", "category": "Software & Cloud"},
    "github": {"name": "GitHub", "category": "Software & Cloud"},
    "notion": {"name": "Notion", "category": "Software & Cloud"},
    "canva": {"name": "Canva", "category": "Software & Cloud"},
    "dropbox": {"name": "Dropbox", "category": "Software & Cloud"},
    "adobe": {"name": "Adobe Creative Cloud", "category": "Software & Cloud"},
    "linkedin": {"name": "LinkedIn Premium", "category": "Software & Cloud"},
    
    # Food & Quick Commerce Memberships
    "swiggy one": {"name": "Swiggy One", "category": "Delivery & Memberships"},
    "swiggy super": {"name": "Swiggy One", "category": "Delivery & Memberships"},
    "swiggy_super": {"name": "Swiggy One", "category": "Delivery & Memberships"},
    "zomato gold": {"name": "Zomato Gold", "category": "Delivery & Memberships"},
    "zomato pro": {"name": "Zomato Gold", "category": "Delivery & Memberships"},
    "zepto pass": {"name": "Zepto Pass", "category": "Delivery & Memberships"},
    "bbstar": {"name": "BigBasket BBstar", "category": "Delivery & Memberships"},
    "bigbasket": {"name": "BigBasket BBstar", "category": "Delivery & Memberships"},
    "blinkit": {"name": "Blinkit", "category": "Delivery & Memberships"},
    
    # Health & Fitness
    "cultfit": {"name": "Cult.fit", "category": "Health & Fitness"},
    "cult.fit": {"name": "Cult.fit", "category": "Health & Fitness"},
    "curefit": {"name": "Cult.fit", "category": "Health & Fitness"},
    "gold gym": {"name": "Gold's Gym", "category": "Health & Fitness"},
    "fittr": {"name": "Fittr", "category": "Health & Fitness"},
    "headspace": {"name": "Headspace", "category": "Health & Fitness"},
    "calm.com": {"name": "Calm", "category": "Health & Fitness"},
    
    # Utilities, Telecom & Broadband
    "jio fiber": {"name": "JioFiber", "category": "Utilities & Telecom"},
    "jiofiber": {"name": "JioFiber", "category": "Utilities & Telecom"},
    "reliance jio": {"name": "Reliance Jio", "category": "Utilities & Telecom"},
    "airtel broadband": {"name": "Airtel Broadband", "category": "Utilities & Telecom"},
    "airtel fiber": {"name": "Airtel Broadband", "category": "Utilities & Telecom"},
    "airtel dth": {"name": "Airtel DTH", "category": "Utilities & Telecom"},
    "airtel": {"name": "Airtel", "category": "Utilities & Telecom"},
    "act fibernet": {"name": "ACT Fibernet", "category": "Utilities & Telecom"},
    "tata play": {"name": "Tata Play", "category": "Utilities & Telecom"},
    "tata sky": {"name": "Tata Play", "category": "Utilities & Telecom"},
    "bescom": {"name": "BESCOM Electricity", "category": "Utilities & Telecom"},
    "bses": {"name": "BSES Electricity", "category": "Utilities & Telecom"},
    "adani electricity": {"name": "Adani Electricity", "category": "Utilities & Telecom"},
    "mahanagar gas": {"name": "Mahanagar Gas", "category": "Utilities & Telecom"},
    "igl": {"name": "Indraprastha Gas (IGL)", "category": "Utilities & Telecom"},
    
    # News & Subscriptions
    "times prime": {"name": "Times Prime", "category": "News & Subscriptions"},
    "the ken": {"name": "The Ken", "category": "News & Subscriptions"},
    "theken": {"name": "The Ken", "category": "News & Subscriptions"},
    "morning context": {"name": "The Morning Context", "category": "News & Subscriptions"},
    "indian express": {"name": "The Indian Express", "category": "News & Subscriptions"},
    "medium.com": {"name": "Medium", "category": "News & Subscriptions"},
    "duolingo": {"name": "Duolingo Plus/Super", "category": "Education"},
    "coursera": {"name": "Coursera Plus", "category": "Education"},
}

# Mandate / Auto-debit regex patterns
MANDATE_KEYWORDS = re.compile(
    r'\b(si|standing\s*instr\w*|e[\s-]?mandate|emandate|nach|ach|ecs|autopay|auto[\s-]?debit|recurring)\b',
    re.IGNORECASE
)

# Common banking noise prefixes and suffixes
NOISE_PREFIXES = [
    r'^(upi|ach|nach|ecs|pos|cms|clg|inb|bil|pg|neft|rtgs|imps)[\s/:\-_]+',
    r'^(p2m|p2a|dr|cr|onl|billdesk|paytm|billpay)[\s/:\-_]+',
    r'^(d[\s-]+|c[\s-]+)',  # e.g. "ACH D- "
]

VPA_STRIP_REGEX = re.compile(r'[\w\.-]+@(okhdfcbank|okaxis|okicici|oksbi|hdfcbank|icici|axisbank|paytm|ybl|apl|upi|razorpay|freecharge)\b', re.IGNORECASE)
CARD_MASK_REGEX = re.compile(r'\b\d{4}[X\*\s-]{4,10}\d{4}\b', re.IGNORECASE)
REF_NUMBER_REGEX = re.compile(r'\b\d{8,16}\b')
DATE_STAMP_REGEX = re.compile(r'\b\d{6,8}\b|\b\d{2}[-/]\d{2}[-/]\d{2,4}\b')
LOCATION_NOISE_REGEX = re.compile(r'\b(mumbai|bangalore|bengaluru|delhi|gurgaon|noida|hyderabad|pune|chennai|in|india)\b', re.IGNORECASE)


class NarrationNormalizer:
    """Normalizes noisy Indian bank narrations into clean merchant identities."""

    @classmethod
    def has_mandate_keywords(cls, narration: str) -> bool:
        """Check if narration contains explicit auto-debit/mandate markers."""
        return bool(MANDATE_KEYWORDS.search(narration))

    @classmethod
    def clean_narration(cls, narration: str) -> str:
        """Strip transaction prefixes, VPA handles, card masks, and reference numbers."""
        text = narration.strip()
        
        # Strip masks, VPAs, reference numbers, date stamps
        text = CARD_MASK_REGEX.sub(" ", text)
        text = VPA_STRIP_REGEX.sub(" ", text)
        text = REF_NUMBER_REGEX.sub(" ", text)
        text = DATE_STAMP_REGEX.sub(" ", text)

        # Repeatedly clean common prefixes like "UPI/P2M/", "ACH D-", "BIL/ONL/"
        for _ in range(3):
            for pattern in NOISE_PREFIXES:
                text = re.sub(pattern, " ", text, flags=re.IGNORECASE).strip()

        # Remove location noise
        text = LOCATION_NOISE_REGEX.sub(" ", text)

        # Replace separators (asterisks, slashes, hyphens, underscores) with spaces
        text = re.sub(r'[\*\/\-_:\.]', ' ', text)

        # Replace remaining non-alphanumeric with spaces, collapse multiple spaces
        text = re.sub(r'[^a-zA-Z0-9\+&]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    @classmethod
    def match_merchant(cls, raw_narration: str) -> Tuple[str, str, bool]:
        """
        Matches a raw narration against known merchants and returns:
        (canonical_merchant_name, category, is_known_merchant).
        """
        # Create normalized spaces-only versions for lookup
        simplified_raw = re.sub(r'[\*\/\-_:\.]', ' ', raw_narration).lower()
        cleaned = cls.clean_narration(raw_narration)
        cleaned_lower = cleaned.lower()

        # 1. Match against known merchant dictionary
        for key, info in sorted(MERCHANT_KNOWLEDGE_BASE.items(), key=lambda x: -len(x[0])):
            pattern = r'\b' + re.escape(key) + r'\b'
            if re.search(pattern, simplified_raw) or re.search(pattern, cleaned_lower):
                return info["name"], info["category"], True

        # 2. Heuristic fallback for unknown merchant: use dominant cleaned tokens
        tokens = cleaned.split()
        filtered_tokens = [
            t for t in tokens
            if len(t) > 2 and not t.isdigit() and t.lower() not in {"auto", "pay", "debit", "mandate", "services", "private", "limited", "pvt", "ltd"}
        ]

        if filtered_tokens:
            fallback_name = " ".join(filtered_tokens[:3]).title()
            return fallback_name, "General / Other", False

        return raw_narration[:24].strip() or "Unknown Merchant", "General / Other", False

    @classmethod
    def enrich_transaction(cls, txn: Transaction) -> Transaction:
        """Enriches a Transaction with cleaned narration, merchant, and mandate indicators."""
        txn.has_mandate_indicator = cls.has_mandate_keywords(txn.narration)
        txn.cleaned_narration = cls.clean_narration(txn.narration)
        canonical_name, category, is_known = cls.match_merchant(txn.narration)
        txn.normalized_merchant = canonical_name
        return txn
