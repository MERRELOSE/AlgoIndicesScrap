#!/usr/bin/env python3
"""
LICENSE KEY GENERATOR
=====================
Tool for generating license keys for EA subscribers.
Run this on YOUR machine only. Never share this file.

Usage:
  python generate_license.py --account 12345678 --months 3
  python generate_license.py --account 12345678 --expiry 2026.09.28
  python generate_license.py --list              (show all licenses)
  python generate_license.py --revoke KEY        (revoke a license)
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================
# SECRET - Must match the one in LicenseManager.mqh
# ============================================================
LICENSE_SECRET = "AIS_X7k9Pm2vR4tQ8wL5nJ6yB3cF1dH0"

# License database
DB_FILE = Path(__file__).parent / "licenses_db.json"


def generate_hash(account_number: int, expiry_date: str) -> str:
    """Generate license key - MUST match MQL5 GenerateHash()"""
    raw = str(account_number) + expiry_date + LICENSE_SECRET

    hash1 = 5381
    hash2 = 52711

    for c in raw:
        v = ord(c)
        hash1 = ((hash1 << 5) + hash1) ^ v
        hash1 &= 0xFFFFFFFFFFFFFFFF  # Keep as 64-bit
        hash2 = ((hash2 << 5) + hash2) ^ v
        hash2 &= 0xFFFFFFFFFFFFFFFF

    combined = (hash1 * 31 + hash2) & 0xFFFFFFFFFFFFFFFF

    # Convert to base-36 key
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    hex_str = ""
    for _ in range(16):
        hex_str += chars[combined % 36]
        combined //= 36

    # Format: XXXX-XXXX-XXXX-XXXX
    return f"{hex_str[0:4]}-{hex_str[4:8]}-{hex_str[8:12]}-{hex_str[12:16]}"


def load_db():
    if DB_FILE.exists():
        with open(DB_FILE) as f:
            return json.load(f)
    return {"licenses": []}


def save_db(db):
    with open(DB_FILE, 'w') as f:
        json.dump(db, f, indent=2)


def generate_license(account: int, months: int = 3, expiry: str = None, client_name: str = ""):
    """Generate a new license"""
    if expiry:
        expiry_date = expiry
    else:
        exp = datetime.now() + timedelta(days=months * 30)
        expiry_date = exp.strftime("%Y.%m.%d")

    key = generate_hash(account, expiry_date)

    # Save to database
    db = load_db()
    license_entry = {
        "key": key,
        "account": account,
        "expiry": expiry_date,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "client": client_name,
        "status": "active",
        "months": months,
    }
    db["licenses"].append(license_entry)
    save_db(db)

    return key, expiry_date, license_entry


def list_licenses():
    db = load_db()
    if not db["licenses"]:
        print("No licenses generated yet.")
        return

    print(f"\n{'Key':<22} {'Account':<12} {'Expiry':<12} {'Client':<15} {'Status':<10} {'Created'}")
    print("-" * 90)

    for lic in db["licenses"]:
        # Check if expired
        try:
            exp = datetime.strptime(lic["expiry"], "%Y.%m.%d")
            if exp < datetime.now() and lic["status"] == "active":
                lic["status"] = "expired"
        except:
            pass

        status = lic.get("status", "?")
        color_status = status.upper()

        print(f"{lic['key']:<22} {lic['account']:<12} {lic['expiry']:<12} {lic.get('client', ''):<15} {color_status:<10} {lic.get('created', '')}")

    save_db(db)

    # Summary
    active = sum(1 for l in db["licenses"] if l.get("status") == "active")
    total = len(db["licenses"])
    print(f"\nTotal: {total} licenses | Active: {active}")


def revoke_license(key):
    db = load_db()
    for lic in db["licenses"]:
        if lic["key"] == key:
            lic["status"] = "revoked"
            save_db(db)
            print(f"License {key} revoked for account {lic['account']}")
            return
    print(f"License {key} not found")


def main():
    parser = argparse.ArgumentParser(description="EA License Key Generator")
    parser.add_argument("--account", type=int, help="Deriv account number")
    parser.add_argument("--months", type=int, default=3, help="Subscription months (default: 3)")
    parser.add_argument("--expiry", type=str, help="Expiry date (YYYY.MM.DD)")
    parser.add_argument("--client", type=str, default="", help="Client name")
    parser.add_argument("--list", action="store_true", help="List all licenses")
    parser.add_argument("--revoke", type=str, help="Revoke a license key")

    args = parser.parse_args()

    if args.list:
        list_licenses()
        return

    if args.revoke:
        revoke_license(args.revoke)
        return

    if not args.account:
        # Interactive mode
        print("=" * 50)
        print("  EA LICENSE GENERATOR")
        print("=" * 50)
        print()

        account = int(input("  Account number: "))
        client = input("  Client name: ")
        months = int(input("  Months (3/6/12): ") or "3")

        key, expiry, entry = generate_license(account, months, client_name=client)
    else:
        key, expiry, entry = generate_license(
            args.account, args.months, args.expiry, args.client
        )

    print()
    print("=" * 50)
    print("  LICENSE GENERATED")
    print("=" * 50)
    print(f"  Account:  {entry['account']}")
    print(f"  Client:   {entry['client']}")
    print(f"  Key:      {key}")
    print(f"  Expiry:   {expiry}")
    print(f"  Months:   {entry['months']}")
    print()
    print("  Send to client:")
    print(f"  ----------------------------------------")
    print(f"  License Key:    {key}")
    print(f"  Account:        {entry['account']}")
    print(f"  Expiry Date:    {expiry}")
    print(f"  ----------------------------------------")
    print()
    print(f"  Client enters these 3 values in EA settings.")
    print("=" * 50)


if __name__ == "__main__":
    main()
