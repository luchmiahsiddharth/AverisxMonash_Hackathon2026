from dotenv import load_dotenv
load_dotenv()

import json
from loader import Inbox
from pipeline.decide import process_email

def main():
    inbox = Inbox("data")
    results = {}
    for email in inbox:
        result = process_email(email, inbox)
        results[email["email_id"]] = result
        print(f"{email['email_id']}: {result['status']}")
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDone — {len(results)} emails processed -> results.json")

if __name__ == "__main__":
    main()