"""Merchant Normalization & Matching Engine.

Implements the 4-tier matching cascade:
  Tier 1: Exact Alias Match (Confidence: 1.0)
  Tier 2: Token / Regex Rules Match (Confidence: 0.85 - 0.95)
  Tier 3: Fuzzy String Similarity Match (Confidence: 0.60 - 0.80)
  Tier 4: Unknown Merchant Fallback (Confidence: 0.20 - 0.40)

Every match records its method, calibrated match confidence, and canonical metadata.
Original narrations are strictly preserved.
"""

from __future__ import annotations
import os
import re
import json
import difflib
from typing import List, Dict, Optional, Tuple, Any

from src.models import (
    CleanedTransaction,
    MerchantMatch,
    MatchMethod
)


# Default path to curated Indian merchant database
DEFAULT_MERCHANTS_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "merchants.json"
)

# Banking noise cleaning regexes
CARD_MASK_REGEX = re.compile(r'\b\d{4}[X\*\s-]{4,10}\d{4}\b', re.IGNORECASE)
VPA_STRIP_REGEX = re.compile(
    r'\b[a-zA-Z0-9_\.]+@(okhdfcbank|okaxis|okicici|oksbi|hdfcbank|icici|axisbank|paytm|ybl|apl|upi|razorpay|freecharge|barodampay|kotak)\b',
    re.IGNORECASE
)
REF_NUMBER_REGEX = re.compile(r'\b\d{8,16}\b')
DATE_STAMP_REGEX = re.compile(r'\b\d{2}[-/]\d{2}[-/]\d{2,4}\b|\b\d{6,8}\b')
LOCATION_NOISE_REGEX = re.compile(
    r'\b(mumbai|bangalore|bengaluru|delhi|gurgaon|noida|hyderabad|pune|chennai|kolkata|blr|bom|del|hyd|india|ind)\b',
    re.IGNORECASE
)

NOISE_PREFIXES = [
    r'^(upi|ach|nach|ecs|pos|cms|clg|inb|bil|pg|neft|rtgs|imps)[\s/:\-_]+',
    r'^(p2m|p2a|dr|cr|onl|billdesk|paytm|billpay)[\s/:\-_]+',
    r'^(d[\s-]+|c[\s-]+)',  # e.g. "ACH D- " or "NACH D- "
    r'^(si\s*-\s*|si\s+)',  # e.g. "SI - "
]

GENERIC_DISCARD_TOKENS = {
    "auto", "pay", "autopay", "debit", "mandate", "recurring",
    "services", "service", "private", "limited", "pvt", "ltd",
    "india", "payment", "bill", "online", "retail", "corp",
    "healthcare", "technologies", "tech", "entertainment",
    "subscription", "membership"
}

UNRELATED_BUSINESS_INDICATORS = {
    # Food, Beverage, Dining & Hospitality
    "cafe", "cafeteria", "coffee", "tea", "chai", "stall", "dhaba", "restaurant",
    "bistro", "bakery", "bakes", "sweets", "sweet", "kitchen", "canteen", "tiffin",
    "chaat", "juice", "bar", "pub", "lounge", "brewery", "hotel", "motel", "resort",
    "inn", "lodge", "caterer", "caterers", "catering", "mess", "eatery", "fastfood",
    "pizzeria", "burger", "grill",

    # Healthcare & Clinical
    "clinic", "hospital", "dental", "dentist", "ortho", "optical", "opticals",
    "optician", "pharmacy", "chemist", "medicos", "medical", "diagnostics",
    "pathology", "lab", "laboratory", "scan", "scans", "ayurvedic", "homeo",
    "homeopathy", "physio", "physiotherapy",

    # Personal Grooming & Wellness
    "salon", "saloon", "spa", "beauty", "parlour", "parlor", "barber", "haircut",
    "makeover", "tattoo",

    # Apparel, Tailoring & Lifestyle
    "tailor", "tailors", "tailoring", "boutique", "drycleaner", "drycleaners",
    "laundry", "textiles", "cloth", "clothes", "garments", "fashion", "dresses",
    "hosiery", "footwear", "shoes",

    # Jewelry & Luxury
    "jewellers", "jewelers", "jewellery", "jewelry", "goldsmith", "silversmith",
    "gems", "diamond", "diamonds",

    # Automotive, Fuel, Hardware & Repairs
    "garage", "motors", "motor", "mechanic", "tyres", "tires", "puncture",
    "petrol", "pump", "fuel", "diesel", "hardware", "electricals", "electrical",
    "sanitary", "plumbing", "paints", "timber", "plywood", "marbles", "granite",
    "glass", "repair", "repairs",

    # Printing & Stationery
    "xerox", "photocopy", "stationery", "stationers", "printing", "press",

    # General Retail, Markets & Stores
    "bazaar", "kirana", "provision", "provisions", "dairy", "poultry", "meat", "fish",
    "supermarket", "mart"
}

UNRELATED_PHRASES = (
    "fast food", "juice bar", "tea stall", "dental clinic", "dry cleaner",
    "dry cleaners", "service centre", "service center", "general store",
    "departmental store", "fancy store", "eye care", "hair cut"
)


def has_unrelated_business_context(text: str, allowed_alias: str) -> bool:
    """
    Returns True if text contains unrelated business indicators that are not
    part of the merchant's registered alias.
    """
    text_lower = text.lower()
    allowed_tokens = set(re.findall(r'[a-zA-Z0-9]+', allowed_alias.lower()))

    # Check multi-word phrases first
    for phrase in UNRELATED_PHRASES:
        if phrase in text_lower and phrase not in allowed_alias.lower():
            return True

    # Check individual indicator tokens
    tokens = re.findall(r'[a-zA-Z]+', text_lower)
    for tok in tokens:
        if tok in UNRELATED_BUSINESS_INDICATORS and tok not in allowed_tokens:
            return True

    return False


class NarrationCleaner:
    """Sanitizes raw banking narrations by stripping masks, VPAs, and banking codes."""

    @classmethod
    def clean(cls, narration: str) -> str:
        """Strips transaction noise while preserving brand and merchant identity tokens."""
        text = narration.strip()

        # 1. Remove card masks, VPAs, reference numbers, date stamps
        text = CARD_MASK_REGEX.sub(" ", text)
        text = VPA_STRIP_REGEX.sub(" ", text)
        text = REF_NUMBER_REGEX.sub(" ", text)
        text = DATE_STAMP_REGEX.sub(" ", text)

        # 2. Repeatedly strip banking prefixes
        for _ in range(3):
            for pattern in NOISE_PREFIXES:
                text = re.sub(pattern, " ", text, flags=re.IGNORECASE).strip()

        # 3. Remove location noise
        text = LOCATION_NOISE_REGEX.sub(" ", text)

        # 4. Replace separators (*, /, -, _, :, .) with spaces
        text = re.sub(r'[\*\/\-_:\.]', ' ', text)

        # 5. Remove non-alphanumeric (except + and &) and collapse whitespace
        text = re.sub(r'[^a-zA-Z0-9\+&]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    @classmethod
    def extract_unknown_key(cls, cleaned_narration: str, raw_narration: str) -> str:
        """Extracts a stable merchant identity key for unknown / unverified merchants."""
        tokens = cleaned_narration.split()
        filtered = [
            t for t in tokens
            if len(t) > 2 and not t.isdigit() and t.lower() not in GENERIC_DISCARD_TOKENS
        ]

        if filtered:
            return " ".join(filtered[:3]).title()

        # Fallback to truncated raw narration
        raw_clean = re.sub(r'[\*\/\-_:\.]', ' ', raw_narration).strip()
        return raw_clean[:24].title() or "Unverified Merchant"


class MerchantRegistry:
    """Loads and compiles merchant rules from merchants.json."""

    def __init__(self, json_path: str = DEFAULT_MERCHANTS_JSON):
        self.json_path = json_path
        self.merchants: List[Dict[str, Any]] = []
        self.exact_alias_map: Dict[str, Dict[str, Any]] = {}
        self.rule_patterns: List[Tuple[re.Pattern, Dict[str, Any]]] = []
        self.all_alias_pairs: List[Tuple[str, str, Dict[str, Any]]] = []
        self._load_and_compile()

    def _load_and_compile(self) -> None:
        """Loads merchants.json and builds fast lookup indexes."""
        if not os.path.exists(self.json_path):
            return

        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.merchants = data.get("merchants", [])

        raw_rules: List[Tuple[int, re.Pattern, Dict[str, Any]]] = []

        for m in self.merchants:
            canonical = m["name"]
            category = m.get("category", "Other Recurring")
            is_var = m.get("is_variable_bill", False)
            is_retail = m.get("is_retail", False)
            aliases = m.get("aliases", [canonical])

            meta = {
                "name": canonical,
                "category": category,
                "is_variable_bill": is_var,
                "is_retail": is_retail,
            }

            # Tier 1: Exact alias lookup (normalized uppercase)
            for alias in aliases:
                norm_alias = re.sub(r'\s+', ' ', alias.strip().upper())
                self.exact_alias_map[norm_alias] = meta
                # Tier 3: Candidates for fuzzy matching
                self.all_alias_pairs.append((alias.upper(), canonical, meta))

                # Prepare Tier 2 pattern rule
                words = re.split(r'[\s\*\/\-_:\.]+', alias.strip())
                escaped_words = [re.escape(w) for w in words if w]
                if not escaped_words:
                    continue
                pattern_str = r'\b' + r'[\s\*\/\-_:\.]+'.join(escaped_words) + r'\b'
                pattern = re.compile(pattern_str, re.IGNORECASE)
                # Store with length key for global priority sorting and track raw alias
                raw_rules.append((len(alias), pattern, {**meta, "raw_alias": alias}))

        # Sort Tier 2 rules globally by length descending so specific rules (e.g. "SWIGGY ONE") precede "SWIGGY"
        raw_rules.sort(key=lambda x: -x[0])
        self.rule_patterns = [(pat, meta) for _, pat, meta in raw_rules]


class MerchantMatcher:
    """
    Executes the 4-tier merchant normalization cascade.
    """

    _registry: Optional[MerchantRegistry] = None

    @classmethod
    def get_registry(cls) -> MerchantRegistry:
        """Singleton accessor for MerchantRegistry."""
        if cls._registry is None:
            cls._registry = MerchantRegistry()
        return cls._registry

    @classmethod
    def set_registry(cls, registry: MerchantRegistry) -> None:
        """Allows injecting custom registry for testing."""
        cls._registry = registry

    @classmethod
    def match(cls, raw_narration: str) -> MerchantMatch:
        """
        Runs the 4-tier matching cascade on raw narration:
          1. Exact Alias Match (Confidence: 1.0)
          2. Token & Regex Pattern Match (Confidence: 0.90 - 0.95)
          3. Fuzzy Similarity Match (Confidence: 0.60 - 0.80)
          4. Unknown Merchant Fallback (Confidence: 0.20 - 0.40)
        """
        registry = cls.get_registry()
        cleaned = NarrationCleaner.clean(raw_narration)
        cleaned_upper = cleaned.upper()
        
        # Check raw narration for exact alias match (stripping outer punctuation and excess whitespace)
        raw_trimmed = re.sub(r'^[^\w]+|[^\w]+$', '', raw_narration.strip()).upper()
        raw_norm = re.sub(r'\s+', ' ', raw_trimmed)

        # --------------------------------------------------------------------
        # Tier 1: Exact Alias Match (Confidence 1.0)
        # --------------------------------------------------------------------
        if raw_norm in registry.exact_alias_map:
            meta = registry.exact_alias_map[raw_norm]
            return MerchantMatch(
                normalized_name=meta["name"],
                category=meta["category"],
                is_variable_bill=meta["is_variable_bill"],
                is_retail=meta["is_retail"],
                method=MatchMethod.EXACT_ALIAS,
                match_confidence=1.0,
                raw_key=raw_norm
            )

        # --------------------------------------------------------------------
        # Tier 2: Token & Regex Rules Match (Confidence 0.90 - 0.95)
        # --------------------------------------------------------------------
        for pattern, meta in registry.rule_patterns:
            # Check pattern on raw narration and cleaned narration
            if pattern.search(raw_narration) or pattern.search(cleaned):
                # Suppress false matches when narration contains unrelated business markers (e.g. 'The Netflix Cafe')
                alias_name = meta.get("raw_alias", meta["name"])
                if has_unrelated_business_context(cleaned, alias_name) or has_unrelated_business_context(raw_narration, alias_name):
                    continue

                confidence = 0.90 if meta.get("is_retail", False) else 0.95
                return MerchantMatch(
                    normalized_name=meta["name"],
                    category=meta["category"],
                    is_variable_bill=meta["is_variable_bill"],
                    is_retail=meta["is_retail"],
                    method=MatchMethod.RULE_REGEX,
                    match_confidence=confidence,
                    raw_key=meta["name"]
                )

        # --------------------------------------------------------------------
        # Tier 3: Fuzzy String Similarity Match (Confidence 0.60 - 0.80)
        # --------------------------------------------------------------------
        # Match cleaned tokens against known aliases using SequenceMatcher
        tokens = [t for t in cleaned_upper.split() if len(t) >= 4]
        best_ratio = 0.0
        best_meta: Optional[Dict[str, Any]] = None

        # Compare both the entire cleaned string and individual tokens
        candidate_strings = [cleaned_upper] + tokens

        for alias_upper, canonical, meta in registry.all_alias_pairs:
            # Skip fuzzy matching on short generic words
            if len(alias_upper) < 4:
                continue

            # Reject fuzzy matching if narration has unrelated business indicators
            if has_unrelated_business_context(cleaned, alias_upper) or has_unrelated_business_context(raw_narration, alias_upper):
                continue

            for cand in candidate_strings:
                ratio = difflib.SequenceMatcher(None, cand, alias_upper).ratio()
                # If cand is an individual token, do not allow ratio 1.0 (exact match) to bypass Tier 2
                if cand != cleaned_upper and ratio >= 0.99:
                    continue

                if ratio > best_ratio:
                    best_ratio = ratio
                    best_meta = meta

        # Minimum similarity threshold of 0.78 for fuzzy acceptance
        if best_ratio >= 0.78 and best_meta is not None:
            # Calibrate confidence score between 0.60 and 0.82
            fuzzy_conf = round(min(0.82, max(0.60, best_ratio * 0.85)), 2)
            return MerchantMatch(
                normalized_name=best_meta["name"],
                category=best_meta["category"],
                is_variable_bill=best_meta["is_variable_bill"],
                is_retail=best_meta["is_retail"],
                method=MatchMethod.FUZZY,
                match_confidence=fuzzy_conf,
                raw_key=cleaned_upper
            )

        # --------------------------------------------------------------------
        # Tier 4: Unknown Merchant Fallback (Confidence 0.25 - 0.35)
        # --------------------------------------------------------------------
        unknown_key = NarrationCleaner.extract_unknown_key(cleaned, raw_narration)
        return MerchantMatch(
            normalized_name=unknown_key,
            category="General / Other",
            is_variable_bill=False,
            is_retail=False,
            method=MatchMethod.UNKNOWN,
            match_confidence=0.30,
            raw_key=unknown_key.upper()
        )

    @classmethod
    def enrich_transaction(cls, txn: Any) -> Any:
        """
        Enriches a transaction with cleaned narration, merchant match, and normalized name.
        Compatible with CleanedTransaction (src.models) and Transaction (app.models).
        """
        raw_narration = getattr(txn, "narration", "")
        cleaned = NarrationCleaner.clean(raw_narration)
        match = cls.match(raw_narration)

        txn.cleaned_narration = cleaned
        txn.normalized_merchant = match.normalized_name

        if hasattr(txn, "merchant_match"):
            txn.merchant_match = match

        return txn

    @classmethod
    def enrich_transactions(cls, txns: List[Any]) -> List[Any]:
        """Convenience method to enrich a list of transactions."""
        for t in txns:
            cls.enrich_transaction(t)
        return txns
