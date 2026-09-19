"""Command-line entry point for the participant pipeline."""

import json
from pathlib import Path

from loader import Inbox


def run(source="data"):
    inbox = Inbox(source)
    return {
        email["email_id"]: {
            "category": "GENERAL",
            "status": None,
            "review_reason": None,
            "has_defect": False,
            "defect_fields": [],
        }
        for email in inbox
    }


if __name__ == "__main__":
    output = Path("submission.json")
    output.write_text(json.dumps(run(), indent=2) + "\n")
    print(f"Wrote {output}")