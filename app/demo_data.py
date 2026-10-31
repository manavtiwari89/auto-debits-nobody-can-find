"""Synthetic Indian Bank Statement Generator & Ground-Truth Dataset.

Generates realistic, noisy Indian bank statements (HDFC, SBI, ICICI formats)
containing active subscriptions, price hikes, and non-recurring transactions.
"""

from __future__ import annotations
import os
import csv
from datetime import date, timedelta
from typing import List, Dict, Tuple, Any


# Ground truth definitions for benchmarking
GROUND_TRUTH_RECURRING = {
    "Netflix": {"cadence": "Monthly", "expected_amount": 649.0, "has_price_hike": True},
    "Spotify": {"cadence": "Monthly", "expected_amount": 119.0, "has_price_hike": False},
    "Amazon Prime": {"cadence": "Annual", "expected_amount": 1499.0, "has_price_hike": False},
    "Disney+ Hotstar": {"cadence": "Quarterly", "expected_amount": 499.0, "has_price_hike": False},
    "Google One": {"cadence": "Monthly", "expected_amount": 130.0, "has_price_hike": False},
    "Cult.fit": {"cadence": "Monthly", "expected_amount": 1750.0, "has_price_hike": False},
    "JioFiber": {"cadence": "Monthly", "expected_amount": 1179.0, "has_price_hike": False},
}


def generate_hdfc_statement() -> Tuple[str, List[Dict[str, Any]]]:
    """
    Generates a 12-month synthetic HDFC statement with recurring subscriptions,
    a Netflix stealth price increase, and realistic noise transactions.
    """
    lines = [
        "HDFC BANK STATEMENT",
        "Customer Name: ROHAN SHARMA",
        "Account Number: SYNTHETIC-ACCOUNT",
        "Branch: INDIRANAGAR, BENGALURU",
        "Currency: INR",
        "Statement Period: 01/11/2025 to 31/10/2026",
        "Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance"
    ]

    balance = 125000.0
    transactions_meta = []
    start_date = date(2025, 11, 1)

    # Monthly cycles across 12 months
    for month_idx in range(12):
        # Current month date anchor (around the 1st to 5th of each month)
        m_date = start_date + timedelta(days=month_idx * 30.5)
        
        # 1. Salary Credit on the 1st
        balance += 140000.0
        lines.append(f"{m_date.strftime('%d/%m/%Y')},ACH C- TECH SOLUTIONS INDIA PVT LTD-SALARY,SAL{month_idx:03d},{m_date.strftime('%d/%m/%Y')},,140000.00,{balance:.2f}")

        # 2. Netflix (Price hike from 499 to 649 starting month 6 / May 2026)
        netflix_date = m_date + timedelta(days=1)
        netflix_amt = 499.0 if month_idx < 6 else 649.0
        balance -= netflix_amt
        lines.append(f"{netflix_date.strftime('%d/%m/%Y')},UPI/P2M/0000000000/NETFLIX ENTERTAINMENT/HDFC/AUTOPAY,REF{month_idx}01,{netflix_date.strftime('%d/%m/%Y')},{netflix_amt:.2f},,{balance:.2f}")

        # 3. Spotify Monthly (ACH Mandate)
        spotify_date = m_date + timedelta(days=4)
        spotify_amt = 119.0
        balance -= spotify_amt
        lines.append(f"{spotify_date.strftime('%d/%m/%Y')},ACH D- SPOTIFY INDIA PRIVATE LIMITED-4567,NACH{month_idx}02,{spotify_date.strftime('%d/%m/%Y')},{spotify_amt:.2f},,{balance:.2f}")

        # 4. Google One Monthly (UPI Mandate)
        g_date = m_date + timedelta(days=7)
        g_amt = 130.0
        balance -= g_amt
        lines.append(f"{g_date.strftime('%d/%m/%Y')},UPI-GOOGLE*STORAGE-GOOGLE@ICICI-887766,REF{month_idx}03,{g_date.strftime('%d/%m/%Y')},{g_amt:.2f},,{balance:.2f}")

        # 5. JioFiber Monthly Broadband (NACH)
        jio_date = m_date + timedelta(days=12)
        jio_amt = 1179.0
        balance -= jio_amt
        lines.append(f"{jio_date.strftime('%d/%m/%Y')},NACH D- JIO FIBER BROADBAND-9876,NACH{month_idx}04,{jio_date.strftime('%d/%m/%Y')},{jio_amt:.2f},,{balance:.2f}")

        # 6. Cult.fit Monthly (Standing Instruction)
        cult_date = m_date + timedelta(days=15)
        cult_amt = 1750.0
        balance -= cult_amt
        lines.append(f"{cult_date.strftime('%d/%m/%Y')},SI - CULTFIT HEALTHCARE - 9982,SI{month_idx}05,{cult_date.strftime('%d/%m/%Y')},{cult_amt:.2f},,{balance:.2f}")

        # 7. Disney+ Hotstar Quarterly (Months 0, 3, 6, 9)
        if month_idx % 3 == 0:
            hotstar_date = m_date + timedelta(days=18)
            hotstar_amt = 499.0
            balance -= hotstar_amt
            lines.append(f"{hotstar_date.strftime('%d/%m/%Y')},BIL/ONL/000987654/HOTSTAR/MUMBAI,BIL{month_idx}06,{hotstar_date.strftime('%d/%m/%Y')},{hotstar_amt:.2f},,{balance:.2f}")

        # 8. Amazon Prime Annual (Months 0 and 11, timed ~365 days apart)
        if month_idx == 0:
            prime_date = date(2025, 11, 20)
            balance -= 1499.0
            lines.append(f"{prime_date.strftime('%d/%m/%Y')},POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI,POS007,{prime_date.strftime('%d/%m/%Y')},1499.00,,{balance:.2f}")
        elif month_idx == 11:
            prime_date = date(2026, 11, 20)
            balance -= 1499.0
            lines.append(f"{prime_date.strftime('%d/%m/%Y')},POS 4012XXXXXXXX1234 AMZN PRIME MUMBAI,POS117,{prime_date.strftime('%d/%m/%Y')},1499.00,,{balance:.2f}")

        # 9. Realistic Noise / One-off non-recurring transactions with varying dates & amounts
        # Real-world discretionary spends fluctuate in dates and amounts, not artificial exact schedules
        noise_day_offset1 = (month_idx * 7) % 25 + 1
        noise_day_offset2 = (month_idx * 11) % 27 + 2
        noise_day_offset3 = (month_idx * 13) % 26 + 3
        
        noise_txns = [
            (m_date + timedelta(days=noise_day_offset1), "UPI-SWIGGY-ORDER-BLR", round(280.0 + (month_idx * 37) % 450, 2)),
            (m_date + timedelta(days=noise_day_offset2), "UPI-ZEPTO-QUICK-IND", round(150.0 + (month_idx * 53) % 600, 2)),
            (m_date + timedelta(days=noise_day_offset3), "POS 4012XXXXXXXX1234 STARBUCKS COFFEE BLR", round(310.0 + (month_idx * 29) % 280, 2)),
            (m_date + timedelta(days=(noise_day_offset1 + 4) % 28), "UPI-UBER-RIDE-IND", round(140.0 + (month_idx * 43) % 320, 2)),
            (m_date + timedelta(days=(noise_day_offset2 + 5) % 28), "UPI-ZOMATO-RESTAURANT", round(650.0 + (month_idx * 71) % 1100, 2)),
            (m_date + timedelta(days=(noise_day_offset3 + 6) % 28), "POS 4012XXXXXXXX1234 HPCL PETROL PUMP", round(1800.0 + (month_idx * 150) % 1500, 2)),
        ]
        for n_date, n_desc, n_amt in noise_txns:
            balance -= n_amt
            lines.append(f"{n_date.strftime('%d/%m/%Y')},{n_desc},REF{month_idx}99,{n_date.strftime('%d/%m/%Y')},{n_amt:.2f},,{balance:.2f}")

    return "\n".join(lines), []


def generate_sbi_statement() -> str:
    """Generates an SBI formatted statement."""
    lines = [
        "STATE BANK OF INDIA",
        "Account Name: PRIYA VERMA",
        "Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance"
    ]
    balance = 85000.0
    start = date(2026, 1, 1)

    for i in range(6):
        d = start + timedelta(days=i * 30.5)
        # Netflix
        amt_netflix = 649.0
        balance -= amt_netflix
        lines.append(f"{(d + timedelta(days=2)).strftime('%d-%b-%Y')},{(d + timedelta(days=2)).strftime('%d-%b-%Y')},UPI/P2M/NETFLIX ENTERTAINMENT/AUTOPAY,SBI{i}01,{amt_netflix:.2f},,{balance:.2f}")

        # Spotify
        balance -= 119.0
        lines.append(f"{(d + timedelta(days=5)).strftime('%d-%b-%Y')},{(d + timedelta(days=5)).strftime('%d-%b-%Y')},ACH D- SPOTIFY INDIA-4567,SBI{i}02,119.00,,{balance:.2f}")

        # Non-recurring noise
        balance -= 450.0
        lines.append(f"{(d + timedelta(days=12)).strftime('%d-%b-%Y')},{(d + timedelta(days=12)).strftime('%d-%b-%Y')},UPI-BLINKIT-DELHI,SBI{i}03,450.00,,{balance:.2f}")

    return "\n".join(lines)


def generate_icici_statement() -> str:
    """Generates an ICICI formatted statement."""
    lines = [
        "ICICI BANK STATEMENT",
        "Transaction Date,Value Date,Description,Cheque Number,Dr Amount,Cr Amount,Balance"
    ]
    balance = 62000.0
    start = date(2026, 1, 15)

    for i in range(5):
        d = start + timedelta(days=i * 30.0)
        # Cult.fit
        balance -= 1750.0
        lines.append(f"{d.strftime('%d/%m/%Y')},{d.strftime('%d/%m/%Y')},SI - CULTFIT HEALTHCARE - 9982,,1750.00,,{balance:.2f}")

        # Google One
        balance -= 130.0
        lines.append(f"{(d + timedelta(days=3)).strftime('%d/%m/%Y')},{(d + timedelta(days=3)).strftime('%d/%m/%Y')},UPI-GOOGLE*STORAGE-GOOGLE@ICICI-887766,,130.00,,{balance:.2f}")

        # Non-recurring noise
        balance -= 780.0
        lines.append(f"{(d + timedelta(days=10)).strftime('%d/%m/%Y')},{(d + timedelta(days=10)).strftime('%d/%m/%Y')},POS 5241XXXXXXXX9988 NATURES BASKET MUMBAI,,780.00,,{balance:.2f}")

    return "\n".join(lines)


def save_sample_statements(target_dir: str):
    """Writes all sample statements to the given directory."""
    os.makedirs(target_dir, exist_ok=True)

    hdfc_csv, _ = generate_hdfc_statement()
    with open(os.path.join(target_dir, "hdfc_sample_statement.csv"), "w", encoding="utf-8") as f:
        f.write(hdfc_csv)

    sbi_csv = generate_sbi_statement()
    with open(os.path.join(target_dir, "sbi_sample_statement.csv"), "w", encoding="utf-8") as f:
        f.write(sbi_csv)

    icici_csv = generate_icici_statement()
    with open(os.path.join(target_dir, "icici_sample_statement.csv"), "w", encoding="utf-8") as f:
        f.write(icici_csv)
