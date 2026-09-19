from dotenv import load_dotenv
load_dotenv()

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from loader import Inbox
from pipeline.decide import process_email

MAX_WORKERS = 5  # stays comfortably under Anthropic Tier 1's ~50 requests/minute

def main():
    inbox = Inbox("data")
    emails = list(inbox)
    results = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_id = {
            executor.submit(process_email, email, inbox): email["email_id"]
            for email in emails
        }
        done = 0
        for future in as_completed(future_to_id):
            eid = future_to_id[future]
            try:
                results[eid] = future.result()
            except Exception:
                # a repeatedly failing email shouldn't crash the whole run —
                # escalate it instead so you can look at it manually later
                results[eid] = {"category": "GENERAL", "status": "NEEDS_REVIEW",
                                 "review_reason": "unreadable", "has_defect": False, "defect_fields": []}
            done += 1
            print(f"[{done}/{len(emails)}] {eid}: {results[eid]['status']}")

    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDone — {len(results)} emails processed -> results.json")

if __name__ == "__main__":
    main()