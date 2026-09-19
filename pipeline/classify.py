import anthropic
from .retry import with_retry

client = anthropic.Anthropic()

CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]

SYSTEM_PROMPT = """You sort emails in a shipping operations inbox into exactly one category:

- BL_COMPARISON: asks to check/compare/confirm a Shipping Instruction (SI) against a draft Bill of Lading (BL)
- SI_REQUEST: asks to prepare a NEW shipping instruction (not a check of an existing one)
- INVOICE_QUERY: asks about an invoice, payment, or charge
- GENERAL: any other operational message (updates, scheduling, greetings)
- SPAM: unsolicited marketing or irrelevant junk

Reply with ONLY the category name. Nothing else."""

@with_retry()
def classify_email(email: dict) -> str:
    message = f"Subject: {email['subject']}\n\nBody:\n{email['body']}"
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=20,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    category = response.content[0].text.strip()
    return category if category in CATEGORIES else "GENERAL"