"""
run_pipeline.py — Run the full pipeline on all emails and write submission.json.
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env")

from loader import Inbox
from pipeline.decide import process_email

DATA_ROOT = ROOT / "data"
OUTPUT = ROOT / "submission.json"


def main():
    inbox = Inbox(str(DATA_ROOT))
    emails = inbox.emails()
    print(f"Processing {len(emails)} emails...", flush=True)

    submission = {}
    for i, email in enumerate(emails, 1):
        eid = email["email_id"]
        try:
            submission[eid] = process_email(email, inbox)
        except Exception as e:
            print(f"  !! {eid} failed: {e}", flush=True)
            submission[eid] = {
                "category": "GENERAL",
                "status": "NEEDS_REVIEW",
                "review_reason": "unreadable",
                "defect_fields": [],
                "has_defect": False,
            }
        if i % 25 == 0:
            print(f"  ...{i}/{len(emails)}", flush=True)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(submission, f, indent=2)
    print(f"\nWrote {OUTPUT} with {len(submission)} entries", flush=True)


if __name__ == "__main__":
    main()
