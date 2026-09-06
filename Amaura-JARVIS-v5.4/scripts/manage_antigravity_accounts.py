#!/usr/bin/env python3
"""Antigravity Multi-Account Pool & Auto-Rotator for JARVIS."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ACTIVE_ACCOUNTS = Path.home() / ".gemini" / "google_accounts.json"

PRO_EMAILS = {"sshashvat810@gmail.com", "akshat92008singh@gmail.com"}


def get_current_state() -> Dict[str, Any]:
    if not ACTIVE_ACCOUNTS.is_file():
        return {"active": "", "old": []}
    try:
        with open(ACTIVE_ACCOUNTS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active": "", "old": []}


def save_state(active: str, old: List[str]) -> None:
    # Deduplicate old while preserving order
    deduped_old = []
    for o in old:
        if o and o != active and o not in deduped_old:
            deduped_old.append(o)
    payload = {"active": active, "old": deduped_old}
    with open(ACTIVE_ACCOUNTS, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def list_accounts() -> List[Dict[str, Any]]:
    """Lists all accounts known to Google Antigravity."""
    state = get_current_state()
    active = state.get("active", "").strip()
    old = state.get("old", [])

    all_emails = []
    if active:
        all_emails.append(active)
    for email in old:
        if email and email not in all_emails:
            all_emails.append(email)

    results = []
    for email in all_emails:
        is_pro = email in PRO_EMAILS or "92008" in email or "810" in email
        results.append({
            "email": email,
            "is_active": (email == active),
            "is_pro": is_pro,
        })
    return results


def switch_to_account(target_email: str) -> bool:
    """Switches the active Google Antigravity account."""
    accounts = list_accounts()
    matches = [a for a in accounts if target_email.lower() in a["email"].lower()]
    if not matches:
        return False
    new_active = matches[0]["email"]
    state = get_current_state()
    curr_active = state.get("active", "")
    old = state.get("old", [])
    if curr_active and curr_active != new_active and curr_active not in old:
        old.insert(0, curr_active)
    if new_active in old:
        old.remove(new_active)
    save_state(new_active, old)
    return True


def rotate_to_next_account(exclude_current: bool = True) -> Optional[str]:
    """Rotates to the next account in the pool (prioritizing Pro accounts)."""
    accounts = list_accounts()
    if not accounts:
        return None
    state = get_current_state()
    curr_active = state.get("active", "")

    candidates = [a for a in accounts if a["email"] != curr_active] if exclude_current else accounts
    if not candidates:
        return None

    # Prioritize Pro accounts first
    candidates.sort(key=lambda a: not a.get("is_pro", False))
    next_email = candidates[0]["email"]
    switch_to_account(next_email)
    return next_email


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Antigravity Multi-Account Manager")
    parser.add_argument("action", choices=["status", "switch", "rotate"], nargs="?", default="status")
    parser.add_argument("--email", "-e", help="Account email for switch")

    args = parser.parse_args()
    if args.action == "status":
        accs = list_accounts()
        print(f"Total Accounts in Pool: {len(accs)}")
        for a in accs:
            marker = " [ACTIVE]" if a["is_active"] else ""
            pro_badge = " (GOOGLE AI PRO)" if a["is_pro"] else ""
            print(f" - {a['email']}{pro_badge}{marker}")
    elif args.action == "switch":
        if not args.email:
            print("Error: --email required to switch")
            sys.exit(1)
        if switch_to_account(args.email):
            print(f"Switched active account to: {args.email}")
        else:
            print(f"Account not found: {args.email}")
            sys.exit(1)
    elif args.action == "rotate":
        next_email = rotate_to_next_account()
        if next_email:
            print(f"Rotated active account to: {next_email}")
        else:
            print("No other accounts available to rotate to")
