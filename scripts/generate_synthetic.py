#!/usr/bin/env python3
"""Seeded Synthetic Bank Statement Generator for The Auto Debits Nobody Can Find.

Generates reproducible, realistic Indian bank statement CSVs:
- demo_transactions.csv: 12-month statement for persona 'Aarav'
- test_transactions.csv: Comprehensive labelled test set covering all 13 brief cases
- stress_transactions.csv: Noisier stress set with format jitter, typos, and holiday drift
- ground_truth.json: Machine-readable ground truth for benchmarking (includes test and stress sections)
- ground_truth_stress.json: Dedicated ground truth file for the stress dataset

Guarantees 100% byte-identical reproducibility for identical seeds.
"""

from __future__ import annotations
import os
import sys
import json
import random
import argparse
from datetime import date, timedelta
from typing import List, Dict, Any, Tuple


def get_month_year(base_year: int, start_month: int, step: int) -> Tuple[int, int]:
    """Computes exact calendar (year, month) given a starting month and 0-indexed step."""
    total_months = (start_month - 1) + step
    year = base_year + (total_months // 12)
    month = (total_months % 12) + 1
    return year, month


def create_date_str(d: date, fmt: str = "%d/%m/%Y") -> str:
    """Format date deterministically."""
    return d.strftime(fmt)


class SyntheticDataGenerator:
    """Deterministic generator for synthetic Indian bank statement datasets."""

    def __init__(self, seed: int = 42):
        self.seed = seed

    def _sort_and_format_transactions(
        self,
        txns: List[Dict[str, Any]],
        initial_balance: float = 125000.0,
        bank_name: str = "HDFC",
        date_format: str = "%d/%m/%Y"
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Sorts transactions chronologically, computes running balance, and formats CSV.
        """
        # Stable deterministic sort by date, then narration, then reference
        txns.sort(key=lambda t: (t["date"], t["narration"], t.get("ref", "")))

        balance = initial_balance
        rows: List[Dict[str, Any]] = []

        if bank_name == "HDFC":
            lines = [
                "HDFC BANK STATEMENT",
                "Customer Name: AARAV PATEL",
                "Account Number: SYNTHETIC-ACCOUNT",
                "Branch: INDIRANAGAR, BENGALURU",
                "Currency: INR",
                "Statement Period: 01/11/2025 to 31/10/2026",
                "Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance"
            ]
        elif bank_name == "SBI":
            lines = [
                "STATE BANK OF INDIA",
                "Account Name: AARAV PATEL",
                "Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance"
            ]
        else:
            lines = [
                "Date,Narration,Reference,Debit,Credit,Balance"
            ]

        for idx, t in enumerate(txns):
            d_str = create_date_str(t["date"], date_format)
            ref_str = t.get("ref", f"REF{idx:05d}")
            narration = t["narration"]
            is_debit = t.get("is_debit", True)
            amount = round(float(t["amount"]), 2)

            if is_debit:
                balance -= amount
                dr_str = f"{amount:.2f}"
                cr_str = ""
            else:
                balance += amount
                dr_str = ""
                cr_str = f"{amount:.2f}"

            bal_str = f"{balance:.2f}"

            if bank_name == "HDFC":
                line = f"{d_str},{narration},{ref_str},{d_str},{dr_str},{cr_str},{bal_str}"
            elif bank_name == "SBI":
                line = f"{d_str},{d_str},{narration},{ref_str},{dr_str},{cr_str},{bal_str}"
            else:
                line = f"{d_str},{narration},{ref_str},{dr_str},{cr_str},{bal_str}"

            lines.append(line)
            t_record = dict(t)
            t_record["balance"] = balance
            rows.append(t_record)

        return "\n".join(lines) + "\n", rows

    def generate_demo_dataset(self) -> str:
        """
        Generates 12-month demo dataset for persona 'Aarav' (Nov 2025 - Oct 2026).
        Contains standard monthly subscriptions, Netflix stealth price hike,
        annual Amazon Prime, quarterly Hotstar, and noisy Swiggy/Zomato/Uber repeats.
        """
        rng = random.Random(self.seed)
        txns: List[Dict[str, Any]] = []

        for m in range(12):
            year, month = get_month_year(2025, 11, m)

            # 1. Salary Credit on the 1st
            txns.append({
                "date": date(year, month, 1),
                "narration": "ACH C- TECHCORP INDIA PVT LTD-SALARY",
                "amount": 140000.0,
                "is_debit": False,
                "ref": f"SAL{m:02d}01"
            })

            # 2. Netflix (Monthly, ~2nd of month)
            # Stealth price hike: ₹499 for first 6 months, then ₹649 for remaining 6 months
            net_amt = 499.0 if m < 6 else 649.0
            txns.append({
                "date": date(year, month, 2),
                "narration": "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/HDFC/AUTOPAY",
                "amount": net_amt,
                "is_debit": True,
                "ref": f"NFLX{m:02d}02"
            })

            # 3. Spotify (Monthly, ~5th of month)
            txns.append({
                "date": date(year, month, 5),
                "narration": "ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567",
                "amount": 119.0,
                "is_debit": True,
                "ref": f"SPOT{m:02d}05"
            })

            # 4. Google One (Monthly, ~8th of month)
            txns.append({
                "date": date(year, month, 8),
                "narration": "UPI-GOOGLE*STORAGE-GOOGLE@ICICI-887766",
                "amount": 130.0,
                "is_debit": True,
                "ref": f"GONE{m:02d}08"
            })

            # 5. JioFiber Broadband (Monthly, ~12th of month)
            txns.append({
                "date": date(year, month, 12),
                "narration": "NACH D- JIO FIBER BROADBAND-9876",
                "amount": 1179.0,
                "is_debit": True,
                "ref": f"JIOF{m:02d}12"
            })

            # 6. Cult.fit Gym (Monthly, ~15th of month)
            txns.append({
                "date": date(year, month, 15),
                "narration": "SI - CULTFIT HEALTHCARE - 9982",
                "amount": 1750.0,
                "is_debit": True,
                "ref": f"CULT{m:02d}15"
            })

            # 7. Disney+ Hotstar (Quarterly: months 0, 3, 6, 9)
            if m % 3 == 0:
                txns.append({
                    "date": date(year, month, 18),
                    "narration": "BIL/ONL/000987654/HOTSTAR/MUMBAI",
                    "amount": 499.0,
                    "is_debit": True,
                    "ref": f"HOT{m:02d}18"
                })

            # 8. Ordinary Discretionary Spends (Swiggy, Zomato, Uber, Starbucks)
            # Must NOT be detected as subscriptions! Erratic intervals & variable amounts.
            for s_idx in range(3):
                s_day = min(28, (s_idx * 9 + m * 5) % 27 + 1)
                s_amt = round(180.0 + ((s_idx + m) * 47) % 550, 2)
                txns.append({
                    "date": date(year, month, s_day),
                    "narration": "UPI-SWIGGY-ORDER-BANGALORE",
                    "amount": s_amt,
                    "is_debit": True,
                    "ref": f"SWIG{m:02d}{s_idx:02d}"
                })

            for z_idx in range(2):
                z_day = min(28, (z_idx * 11 + m * 7) % 27 + 1)
                z_amt = round(250.0 + ((z_idx + m) * 63) % 750, 2)
                txns.append({
                    "date": date(year, month, z_day),
                    "narration": "UPI-ZOMATO-RESTAURANT-ORDER",
                    "amount": z_amt,
                    "is_debit": True,
                    "ref": f"ZOM{m:02d}{z_idx:02d}"
                })

            for u_idx in range(2):
                u_day = min(28, (u_idx * 13 + m * 9) % 27 + 1)
                u_amt = round(120.0 + ((u_idx + m) * 51) % 450, 2)
                txns.append({
                    "date": date(year, month, u_day),
                    "narration": "UPI-UBER-TRIP-BANGALORE",
                    "amount": u_amt,
                    "is_debit": True,
                    "ref": f"UBER{m:02d}{u_idx:02d}"
                })

            for sb_idx in range(rng.randint(0, 1)):
                sb_day = min(28, (sb_idx * 7 + m * 3) % 27 + 1)
                sb_amt = round(310.0 + (m * 29) % 280, 2)
                txns.append({
                    "date": date(year, month, sb_day),
                    "narration": "POS 4012XXXXXXXX1234 STARBUCKS COFFEE BLR",
                    "amount": sb_amt,
                    "is_debit": True,
                    "ref": f"SBUX{m:02d}{sb_idx:02d}"
                })

        # 9. Amazon Prime (Annual: Nov 2025 and Nov 2026 - exactly 365 days)
        txns.append({
            "date": date(2025, 11, 20),
            "narration": "POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI",
            "amount": 1499.0,
            "is_debit": True,
            "ref": "PRIME2025"
        })
        txns.append({
            "date": date(2026, 11, 20),
            "narration": "POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI",
            "amount": 1499.0,
            "is_debit": True,
            "ref": "PRIME2026"
        })

        # Add single duplicate debit case (Swiggy on 14/04/2026)
        dup_date = date(2026, 4, 14)
        txns.append({
            "date": dup_date,
            "narration": "UPI-SWIGGY-ORDER-BANGALORE",
            "amount": 349.0,
            "is_debit": True,
            "ref": "SWIGDUP01"
        })
        txns.append({
            "date": dup_date,
            "narration": "UPI-SWIGGY-ORDER-BANGALORE",
            "amount": 349.0,
            "is_debit": True,
            "ref": "SWIGDUP02"
        })

        # Add single refund / reversal case (Uber refund on 10/03/2026)
        txns.append({
            "date": date(2026, 3, 10),
            "narration": "UPI-UBER-TRIP-BANGALORE",
            "amount": 420.0,
            "is_debit": True,
            "ref": "UBERRIDE420"
        })
        txns.append({
            "date": date(2026, 3, 11),
            "narration": "UPI/REV/UBER INDIA/REFUND420",
            "amount": 420.0,
            "is_debit": False,
            "ref": "UBERREF420"
        })

        csv_text, _ = self._sort_and_format_transactions(txns, bank_name="HDFC")
        return csv_text

    def generate_test_dataset(self) -> Tuple[str, Dict[str, Any]]:
        """
        Generates comprehensive test dataset and matching ground truth JSON covering all 13 brief cases.
        """
        rng = random.Random(self.seed)
        txns: List[Dict[str, Any]] = []

        # 1. Salary Credit monthly
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            txns.append({
                "date": date(year, month, 1),
                "narration": "ACH C- TECH ENTERPRISE INDIA-SALARY",
                "amount": 160000.0,
                "is_debit": False,
                "ref": f"SAL{m:02d}"
            })

        # 2. Netflix (Monthly, Hike 499 -> 649 at month 6)
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            amt = 499.0 if m < 6 else 649.0
            txns.append({
                "date": date(year, month, 2),
                "narration": "UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/AUTOPAY",
                "amount": amt,
                "is_debit": True,
                "ref": f"NFLX{m:02d}"
            })

        # 3. Spotify (Monthly, Hike 119 -> 129 at month 7)
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            amt = 119.0 if m < 7 else 129.0
            txns.append({
                "date": date(year, month, 5),
                "narration": "ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567",
                "amount": amt,
                "is_debit": True,
                "ref": f"SPOT{m:02d}"
            })

        # 4. Google One (Monthly ₹130 flat)
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            txns.append({
                "date": date(year, month, 8),
                "narration": "UPI-GOOGLE*STORAGE-GOOGLE@ICICI-887766",
                "amount": 130.0,
                "is_debit": True,
                "ref": f"GONE{m:02d}"
            })

        # 5. JioFiber Broadband (Monthly ₹1179 flat)
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            txns.append({
                "date": date(year, month, 12),
                "narration": "NACH D- JIO FIBER BROADBAND-9876",
                "amount": 1179.0,
                "is_debit": True,
                "ref": f"JIOF{m:02d}"
            })

        # 6. Disney+ Hotstar (Quarterly: months 0, 3, 6, 9 at ₹499)
        for q in [0, 3, 6, 9]:
            year, month = get_month_year(2025, 11, q)
            txns.append({
                "date": date(year, month, 18),
                "narration": "BIL/ONL/000987654/HOTSTAR/MUMBAI",
                "amount": 499.0,
                "is_debit": True,
                "ref": f"HOT{q:02d}"
            })

        # 7. Swiggy One Membership (Quarterly: months 1, 4, 7, 10 at ₹299)
        for q in [1, 4, 7, 10]:
            year, month = get_month_year(2025, 11, q)
            txns.append({
                "date": date(year, month, 22),
                "narration": "UPI/P2M/BUNDL TECH SWIGGY ONE MEMBERSHIP/AUTOPAY",
                "amount": 299.0,
                "is_debit": True,
                "ref": f"SWONE{q:02d}"
            })

        # 8. Amazon Prime (Annual: exactly 365 days apart)
        txns.append({
            "date": date(2025, 11, 20),
            "narration": "POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI",
            "amount": 1499.0,
            "is_debit": True,
            "ref": "PRIME01"
        })
        txns.append({
            "date": date(2026, 11, 20),
            "narration": "POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI",
            "amount": 1499.0,
            "is_debit": True,
            "ref": "PRIME02"
        })

        # 9. Microsoft 365 (Annual: exactly 365 days apart)
        txns.append({
            "date": date(2025, 11, 25),
            "narration": "MSFT *OFFICE 365 SUBSCRIPTION MICROSOFT INDIA",
            "amount": 4899.0,
            "is_debit": True,
            "ref": "MSFT01"
        })
        txns.append({
            "date": date(2026, 11, 25),
            "narration": "MSFT *OFFICE 365 SUBSCRIPTION MICROSOFT INDIA",
            "amount": 4899.0,
            "is_debit": True,
            "ref": "MSFT02"
        })

        # 10. BESCOM Electricity (Variable-amount monthly bill, ₹1150 to ₹1850)
        bescom_amounts = [1240.0, 1580.0, 1190.0, 1820.0, 1430.0, 1650.0, 1380.0, 1720.0, 1290.0, 1510.0, 1450.0, 1620.0]
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            txns.append({
                "date": date(year, month, 16),
                "narration": "BIL/ONL/BESCOM BANGALORE ELECTRICITY AUTOPAY",
                "amount": bescom_amounts[m],
                "is_debit": True,
                "ref": f"BESC{m:02d}"
            })

        # 11. Paused / Resumed: Cult.fit Gym (Active m=0,1,2, PAUSED m=3,4, RESUMED m=5..11)
        for m in [0, 1, 2, 5, 6, 7, 8, 9, 10, 11]:
            year, month = get_month_year(2025, 11, m)
            txns.append({
                "date": date(year, month, 15),
                "narration": "SI - CULTFIT HEALTHCARE - 9982",
                "amount": 1750.0,
                "is_debit": True,
                "ref": f"CULTPAUSE{m:02d}"
            })

        # 12. Unknown Merchant: Fitness First Gym (₹2500 monthly recurring, unverified alias)
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            txns.append({
                "date": date(year, month, 10),
                "narration": "UPI/P2M/883311/FITNESS FIRST GYM/AUTOPAY",
                "amount": 2500.0,
                "is_debit": True,
                "ref": f"FITGYM{m:02d}"
            })

        # 13. Insufficient History Series (<3 observations, must be rejected or marked insufficient)
        txns.append({
            "date": date(2026, 9, 15),
            "narration": "ACH D- THE HINDU DIGITAL SUBSCRIPTION-991",
            "amount": 999.0,
            "is_debit": True,
            "ref": "HINDU01"
        })
        txns.append({
            "date": date(2026, 8, 1),
            "narration": "UPI-HEADSPACE-MEDITATION-APP",
            "amount": 1299.0,
            "is_debit": True,
            "ref": "HEAD01"
        })
        txns.append({
            "date": date(2026, 9, 1),
            "narration": "UPI-HEADSPACE-MEDITATION-APP",
            "amount": 1299.0,
            "is_debit": True,
            "ref": "HEAD02"
        })

        # 14. Ordinary Repeated Purchases (Swiggy, Zomato, Blinkit, Uber, Starbucks)
        # These MUST NOT be detected as subscriptions!
        for m in range(12):
            year, month = get_month_year(2025, 11, m)

            for s_idx in range(3):
                s_day = min(28, (s_idx * 9 + m * 5) % 27 + 1)
                s_amt = round(180.0 + ((s_idx + m) * 43) % 550, 2)
                txns.append({
                    "date": date(year, month, s_day),
                    "narration": "UPI-SWIGGY-ORDER-BANGALORE",
                    "amount": s_amt,
                    "is_debit": True,
                    "ref": f"TSWIG{m:02d}{s_idx:02d}"
                })

            for z_idx in range(2):
                z_day = min(28, (z_idx * 11 + m * 7) % 27 + 1)
                z_amt = round(280.0 + ((z_idx + m) * 67) % 700, 2)
                txns.append({
                    "date": date(year, month, z_day),
                    "narration": "UPI-ZOMATO-RESTAURANT-ORDER",
                    "amount": z_amt,
                    "is_debit": True,
                    "ref": f"TZOM{m:02d}{z_idx:02d}"
                })

            for b_idx in range(2):
                b_day = min(28, (b_idx * 13 + m * 9) % 27 + 1)
                b_amt = round(140.0 + ((b_idx + m) * 31) % 400, 2)
                txns.append({
                    "date": date(year, month, b_day),
                    "narration": "UPI-BLINKIT-BANGALORE",
                    "amount": b_amt,
                    "is_debit": True,
                    "ref": f"TBLINK{m:02d}{b_idx:02d}"
                })

            for u_idx in range(2):
                u_day = min(28, (u_idx * 15 + m * 11) % 27 + 1)
                u_amt = round(120.0 + ((u_idx + m) * 51) % 450, 2)
                txns.append({
                    "date": date(year, month, u_day),
                    "narration": "UPI-UBER-TRIP-BANGALORE",
                    "amount": u_amt,
                    "is_debit": True,
                    "ref": f"TUBER{m:02d}{u_idx:02d}"
                })

        # 15. Duplicates, Refunds, and Reversals
        txns.append({
            "date": date(2026, 8, 28),
            "narration": "UPI-SWIGGY-ORDER-BANGALORE",
            "amount": 299.0,
            "is_debit": True,
            "ref": "DUPREF01"
        })
        txns.append({
            "date": date(2026, 8, 28),
            "narration": "UPI-SWIGGY-ORDER-BANGALORE",
            "amount": 299.0,
            "is_debit": True,
            "ref": "DUPREF02"
        })

        txns.append({
            "date": date(2026, 1, 15),
            "narration": "POS 4012XXXXXXXX1234 SHOPPERS STOP BLR",
            "amount": 899.0,
            "is_debit": True,
            "ref": "SHOPDEBIT899"
        })
        txns.append({
            "date": date(2026, 1, 16),
            "narration": "CR-REFUND-SHOPPERS STOP BLR-899",
            "amount": 899.0,
            "is_debit": False,
            "ref": "SHOPREFUND899"
        })

        txns.append({
            "date": date(2026, 5, 22),
            "narration": "UPI-PAYMENT-FAILED-TXN",
            "amount": 500.0,
            "is_debit": True,
            "ref": "UPIFAIL500"
        })
        txns.append({
            "date": date(2026, 5, 22),
            "narration": "UPI/REV/AUTOREVERSAL/FAILED-TXN",
            "amount": 500.0,
            "is_debit": False,
            "ref": "UPIREV500"
        })

        # Ground truth definition
        ground_truth: Dict[str, Any] = {
            "meta": {
                "generated_with_seed": self.seed,
                "statement_period": "01/11/2025 to 31/10/2026",
                "total_months": 12,
                "dataset_name": "test_transactions.csv"
            },
            "recurring_series": [
                {
                    "merchant": "Netflix",
                    "cadence": "Monthly",
                    "expected_amount": 649.0,
                    "has_price_hike": True,
                    "old_amount": 499.0,
                    "new_amount": 649.0,
                    "hike_percentage": 30.06,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Spotify",
                    "cadence": "Monthly",
                    "expected_amount": 129.0,
                    "has_price_hike": True,
                    "old_amount": 119.0,
                    "new_amount": 129.0,
                    "hike_percentage": 8.40,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Google One",
                    "cadence": "Monthly",
                    "expected_amount": 130.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "JioFiber",
                    "cadence": "Monthly",
                    "expected_amount": 1179.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Disney+ Hotstar",
                    "cadence": "Quarterly",
                    "expected_amount": 499.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Swiggy One",
                    "cadence": "Quarterly",
                    "expected_amount": 299.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Amazon Prime",
                    "cadence": "Annual",
                    "expected_amount": 1499.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Microsoft 365",
                    "cadence": "Annual",
                    "expected_amount": 4899.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Cult.fit",
                    "cadence": "Monthly",
                    "expected_amount": 1750.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": True,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "BESCOM Electricity",
                    "cadence": "Monthly",
                    "expected_amount": 1620.0,
                    "has_price_hike": False,
                    "is_variable_bill": True,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Fitness First Gym",
                    "cadence": "Monthly",
                    "expected_amount": 2500.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": True
                }
            ],
            "ordinary_repeats_to_reject": [
                "Swiggy",
                "Zomato",
                "Blinkit",
                "Uber"
            ],
            "insufficient_history_to_reject": [
                "The Hindu Digital",
                "Headspace"
            ],
            "anomalies": {
                "duplicate_ref_pairs": [["DUPREF01", "DUPREF02"]],
                "refund_pairs": [["SHOPDEBIT899", "SHOPREFUND899"]],
                "reversal_pairs": [["UPIFAIL500", "UPIREV500"]]
            }
        }

        csv_text, _ = self._sort_and_format_transactions(txns, bank_name="HDFC")
        return csv_text, ground_truth

    def generate_stress_dataset(self) -> Tuple[str, Dict[str, Any]]:
        """
        Generates a second, noisier 'stress' set with seed 99 and matching ground truth:
        - All 11 subscriptions under stress conditions:
          - Weekend/bank holiday jitter (±1 to 3 days on payment dates)
          - Minor typographical noise and variant narrations
          - Cult.fit has a missed/skipped month (month 4 missed due to card renewal)
          - Date format DD-MM-YYYY
        - Heavy discretionary retail and delivery noise (Swiggy, Zomato, Uber, Zepto, Starbucks, Shell Petrol)
        """
        rng = random.Random(99)
        txns: List[Dict[str, Any]] = []

        # 1. Salary
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            d = date(year, month, 1)
            txns.append({
                "date": d,
                "narration": "ACH C- TECHCORP BLR-SALARY",
                "amount": 135000.0,
                "is_debit": False,
                "ref": f"STRSSAL{m:02d}"
            })

        # 2. Netflix with jitter and narration variant
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            jitter = rng.choice([-1, 0, 1, 2])
            day = max(1, min(28, 2 + jitter))
            d = date(year, month, day)
            amt = 499.0 if m < 5 else 649.0
            narr = rng.choice([
                "UPI/P2M/99182/NETFLIX ENTERTAINMENT/MUMBAI/AUTOPAY",
                "UPI/DR/123049/NETFLIX INDIA/AUTOPAY",
                "UPI/P2M/88123/NETFLIX.COM IN/AUTOPAY"
            ])
            txns.append({
                "date": d,
                "narration": narr,
                "amount": amt,
                "is_debit": True,
                "ref": f"STRNFLX{m:02d}"
            })

        # 3. Spotify with slight jitter
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            jitter = rng.choice([0, 1])
            day = max(1, min(28, 5 + jitter))
            d = date(year, month, day)
            narr = rng.choice([
                "ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567",
                "NACH D- SPOTIFY PREMIUM INDIA-8891",
                "ACH D- SPOTIFY AB SWEDEN-4567"
            ])
            txns.append({
                "date": d,
                "narration": narr,
                "amount": 119.0,
                "is_debit": True,
                "ref": f"STRSPOT{m:02d}"
            })

        # 4. Google One with slight jitter
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            jitter = rng.choice([-1, 0, 1])
            day = max(1, min(28, 8 + jitter))
            d = date(year, month, day)
            txns.append({
                "date": d,
                "narration": "UPI-GOOGLE*STORAGE-GOOGLE@ICICI-887766",
                "amount": 130.0,
                "is_debit": True,
                "ref": f"STRGONE{m:02d}"
            })

        # 5. JioFiber with jitter
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            jitter = rng.choice([0, 1, 2])
            day = max(1, min(28, 12 + jitter))
            d = date(year, month, day)
            txns.append({
                "date": d,
                "narration": "NACH D- JIO FIBER BROADBAND-9876",
                "amount": 1179.0,
                "is_debit": True,
                "ref": f"STRJIO{m:02d}"
            })

        # 6. Cult.fit with missed month (month 4 missed due to card re-issue)
        for m in [0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11]:
            year, month = get_month_year(2025, 11, m)
            jitter = rng.choice([-1, 0, 1])
            day = max(1, min(28, 15 + jitter))
            d = date(year, month, day)
            txns.append({
                "date": d,
                "narration": "SI - CULTFIT HEALTHCARE - 9982",
                "amount": 1750.0,
                "is_debit": True,
                "ref": f"STRCULT{m:02d}"
            })

        # 7. Disney+ Hotstar (Quarterly: months 0, 3, 6, 9) with jitter
        for q in [0, 3, 6, 9]:
            year, month = get_month_year(2025, 11, q)
            jitter = rng.choice([-1, 0, 1, 2])
            day = max(1, min(28, 18 + jitter))
            d = date(year, month, day)
            txns.append({
                "date": d,
                "narration": "BIL/ONL/000987654/HOTSTAR/MUMBAI",
                "amount": 499.0,
                "is_debit": True,
                "ref": f"STRHOT{q:02d}"
            })

        # 8. Swiggy One Membership (Quarterly: months 1, 4, 7, 10) with jitter
        for q in [1, 4, 7, 10]:
            year, month = get_month_year(2025, 11, q)
            jitter = rng.choice([-1, 0, 1])
            day = max(1, min(28, 22 + jitter))
            d = date(year, month, day)
            txns.append({
                "date": d,
                "narration": "UPI/P2M/BUNDL TECH SWIGGY ONE MEMBERSHIP/AUTOPAY",
                "amount": 299.0,
                "is_debit": True,
                "ref": f"STRSWONE{q:02d}"
            })

        # 9. Amazon Prime (Annual: 366 days apart with leap day / weekend shift)
        txns.append({
            "date": date(2025, 11, 20),
            "narration": "POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI",
            "amount": 1499.0,
            "is_debit": True,
            "ref": "STRPRIME01"
        })
        txns.append({
            "date": date(2026, 11, 21),
            "narration": "POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI",
            "amount": 1499.0,
            "is_debit": True,
            "ref": "STRPRIME02"
        })

        # 10. Microsoft 365 (Annual: 364 days apart)
        txns.append({
            "date": date(2025, 11, 25),
            "narration": "MSFT *OFFICE 365 SUBSCRIPTION MICROSOFT INDIA",
            "amount": 4899.0,
            "is_debit": True,
            "ref": "STRMSFT01"
        })
        txns.append({
            "date": date(2026, 11, 24),
            "narration": "MSFT *OFFICE 365 SUBSCRIPTION MICROSOFT INDIA",
            "amount": 4899.0,
            "is_debit": True,
            "ref": "STRMSFT02"
        })

        # 11. BESCOM Electricity (Variable bill with jitter)
        bescom_amounts = [1310.0, 1490.0, 1220.0, 1750.0, 1480.0, 1610.0, 1340.0, 1820.0, 1270.0, 1540.0, 1420.0, 1590.0]
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            jitter = rng.choice([-1, 0, 1, 2])
            day = max(1, min(28, 16 + jitter))
            d = date(year, month, day)
            txns.append({
                "date": d,
                "narration": "BIL/ONL/BESCOM BANGALORE ELECTRICITY AUTOPAY",
                "amount": bescom_amounts[m],
                "is_debit": True,
                "ref": f"STRBESC{m:02d}"
            })

        # 12. Fitness First Gym (Unknown merchant with jitter)
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            jitter = rng.choice([-1, 0, 1])
            day = max(1, min(28, 10 + jitter))
            d = date(year, month, day)
            txns.append({
                "date": d,
                "narration": "UPI/P2M/883311/FITNESS FIRST GYM/AUTOPAY",
                "amount": 2500.0,
                "is_debit": True,
                "ref": f"STRFITGYM{m:02d}"
            })

        # 13. Heavy random noise (Swiggy, Zomato, Uber, Zepto, Pharmacy, Grocery)
        for m in range(12):
            year, month = get_month_year(2025, 11, m)
            for _ in range(rng.randint(4, 7)):
                noise_day = rng.randint(1, 28)
                noise_amt = round(rng.uniform(85.0, 1450.0), 2)
                narr = rng.choice([
                    "UPI-SWIGGY-BANGALORE-ORDER",
                    "UPI-ZOMATO-FOOD-DELIVERY",
                    "UPI-ZEPTO-10MIN-GROCERY",
                    "POS 4012XXXXXXXX1234 APOLLO PHARMACY BLR",
                    "UPI-UBER-INDIA-RIDE",
                    "POS 4012XXXXXXXX1234 NATURES BASKET",
                    "POS 4012XXXXXXXX1234 SHELL PETROL BENGALURU"
                ])
                txns.append({
                    "date": date(year, month, noise_day),
                    "narration": narr,
                    "amount": noise_amt,
                    "is_debit": True,
                    "ref": f"STRNOISE{m:02d}{rng.randint(100,999)}"
                })

        stress_ground_truth: Dict[str, Any] = {
            "meta": {
                "generated_with_seed": 99,
                "statement_period": "01/11/2025 to 31/10/2026",
                "total_months": 12,
                "dataset_name": "stress_transactions.csv"
            },
            "recurring_series": [
                {
                    "merchant": "Netflix",
                    "cadence": "Monthly",
                    "expected_amount": 649.0,
                    "has_price_hike": True,
                    "old_amount": 499.0,
                    "new_amount": 649.0,
                    "hike_percentage": 30.06,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Spotify",
                    "cadence": "Monthly",
                    "expected_amount": 119.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Google One",
                    "cadence": "Monthly",
                    "expected_amount": 130.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "JioFiber",
                    "cadence": "Monthly",
                    "expected_amount": 1179.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Disney+ Hotstar",
                    "cadence": "Quarterly",
                    "expected_amount": 499.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Swiggy One",
                    "cadence": "Quarterly",
                    "expected_amount": 299.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Amazon Prime",
                    "cadence": "Annual",
                    "expected_amount": 1499.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Microsoft 365",
                    "cadence": "Annual",
                    "expected_amount": 4899.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Cult.fit",
                    "cadence": "Monthly",
                    "expected_amount": 1750.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": True,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "BESCOM Electricity",
                    "cadence": "Monthly",
                    "expected_amount": 1590.0,
                    "has_price_hike": False,
                    "is_variable_bill": True,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": False
                },
                {
                    "merchant": "Fitness First Gym",
                    "cadence": "Monthly",
                    "expected_amount": 2500.0,
                    "has_price_hike": False,
                    "is_variable_bill": False,
                    "is_paused_resumed": False,
                    "is_unknown_merchant": True
                }
            ],
            "ordinary_repeats_to_reject": [
                "Swiggy",
                "Zomato",
                "Zepto",
                "Uber"
            ]
        }

        csv_text, _ = self._sort_and_format_transactions(
            txns, bank_name="HDFC", date_format="%d-%m-%Y"
        )
        return csv_text, stress_ground_truth


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic bank statements and ground truth.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility (default: 42)")
    parser.add_argument("--output-dir", type=str, default="data/synthetic", help="Output directory for generated files")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    generator = SyntheticDataGenerator(seed=args.seed)

    print(f"Generating synthetic datasets with seed {args.seed}...")

    # 1. Demo transactions CSV (Aarav persona)
    demo_csv = generator.generate_demo_dataset()
    demo_path = os.path.join(args.output_dir, "demo_transactions.csv")
    with open(demo_path, "w", encoding="utf-8") as f:
        f.write(demo_csv)
    print(f"  [OK] Created {demo_path} ({len(demo_csv.splitlines())} lines)")

    # 2. Test transactions CSV & ground_truth.json
    test_csv, ground_truth = generator.generate_test_dataset()
    test_path = os.path.join(args.output_dir, "test_transactions.csv")
    with open(test_path, "w", encoding="utf-8") as f:
        f.write(test_csv)
    print(f"  [OK] Created {test_path} ({len(test_csv.splitlines())} lines)")

    # 3. Stress transactions CSV & ground_truth_stress.json
    stress_csv, stress_ground_truth = generator.generate_stress_dataset()
    stress_path = os.path.join(args.output_dir, "stress_transactions.csv")
    with open(stress_path, "w", encoding="utf-8") as f:
        f.write(stress_csv)
    print(f"  [OK] Created {stress_path} ({len(stress_csv.splitlines())} lines)")

    # Write separate ground_truth_stress.json
    gt_stress_path = os.path.join(args.output_dir, "ground_truth_stress.json")
    with open(gt_stress_path, "w", encoding="utf-8") as f:
        json.dump(stress_ground_truth, f, indent=2)
    print(f"  [OK] Created {gt_stress_path} ({len(stress_ground_truth['recurring_series'])} ground-truth series)")

    # Write unified ground_truth.json with stress section included
    ground_truth["stress"] = stress_ground_truth
    gt_path = os.path.join(args.output_dir, "ground_truth.json")
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2)
    print(f"  [OK] Created {gt_path} ({len(ground_truth['recurring_series'])} test + {len(stress_ground_truth['recurring_series'])} stress series)")

    print("Synthetic dataset generation complete!")


if __name__ == "__main__":
    main()
