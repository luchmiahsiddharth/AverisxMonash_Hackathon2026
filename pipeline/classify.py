"""
classify.py — Stage 1 email classifier.

Two-tier keyword design + a targeted LLM fallback, based on two things
observed from real testing against the ground truth:

1. Your rule-only run (81.7% accuracy) had ZERO cross-category false
   positives — every error fell through to GENERAL. That means specific
   phrases like "draft bill of lading" or "prepare shipping instruction"
   are safe to trust outright.

2. But two of the original keywords — bare "compare" and "please check" —
   are dangerously generic. Tested against plausible unrelated emails
   ("please check the attached price list", "can you compare these two
   carrier rates"), they misfire into BL_COMPARISON every time, just by
   accident of not appearing in this particular 520-email sample.

So: STRONG keywords (specific phrases) auto-decide with no LLM call.
WEAK keywords (generic single words) only ever produce a *hint* — they
get routed to Claude for a real decision instead of committing blindly.
Anything with no signal at all also goes to Claude. This keeps the fast,
free path for the ~70% of emails that are unambiguous, while removing
the false-positive risk on the generic terms without needing to hand-tune
an ever-growing exceptions list.
"""

import os
import time
import functools

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ============================================================
# Keyword tiers
# ============================================================

BL_STRONG = [
    "check the details", "confirm docs", "check docs",
    "to confirm docs", "to confirm doc", "confirm the details",
    "check and confirm", "draft bill of lading", "bill of lading",
    "review the bl", "bl details", "shipping documents",
]
BL_WEAK = ["compare", "please check"]  # too generic to trust alone — LLM confirms

SI_STRONG = [
    "prepare si", "new si", "create si", "issue shipping instruction",
    "make si", "shipping instruction request",
    "prepare shipping instruction", "create shipping instruction",
    "new shipping instruction", "request si", "shipping instruction",
]
SI_WEAK = []  # nothing generic enough here to need a weak tier yet

INVOICE_STRONG = [
    "thc", "local charge", "telex release", "freight invoice", "debit note",
]
INVOICE_WEAK = ["billed", "charges"]  # generic on their own — LLM confirms

SPAM_KEYWORDS = [
    "unsubscribe", "viagra", "winner", "claim prize", "click here",
    "bitcoin", "crypto", "casino", "limited time offer", "act now",
]

CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]


def _match(text, keywords):
    return any(kw in text for kw in keywords)


# ============================================================
# Stage A: rule-based classification, with a "trustworthy" flag
# ============================================================

def rule_classify(email: dict):
    """
    Returns (category_or_hint, is_strong).
    is_strong=True  -> safe to use directly, no LLM needed.
    is_strong=False -> category_or_hint is only a WEAK hint (may be None),
                       caller should confirm with the LLM.
    """
    subject = (email.get("subject") or "").lower()
    body = (email.get("body") or "").lower()
    text = f"{subject}\n{body}"
    attachments = email.get("attachments", [])

    has_si = any("_SI." in a for a in attachments)
    has_bl = any("_BL." in a for a in attachments)

    # --- strong signals: trust outright ---
    if has_si and has_bl:
        return "BL_COMPARISON", True
    if _match(text, SPAM_KEYWORDS):
        return "SPAM", True
    if _match(text, SI_STRONG):
        return "SI_REQUEST", True
    if _match(text, INVOICE_STRONG):
        return "INVOICE_QUERY", True
    if _match(text, BL_STRONG):
        return "BL_COMPARISON", True

    # --- weak signals: hint only, not to be trusted alone ---
    if _match(text, BL_WEAK):
        return "BL_COMPARISON", False
    if _match(text, INVOICE_WEAK):
        return "INVOICE_QUERY", False

    return None, False  # no signal at all


def classify(email: dict) -> str:
    """Rule-only classification (weak hints treated as the answer).
    Kept for quick local testing / comparing against your old script —
    use classify_with_fallback() for the safer hybrid behavior."""
    category, _ = rule_classify(email)
    return category or "GENERAL"


# ============================================================
# Stage B: Claude fallback — only called for weak hints or no signal
# ============================================================

SYSTEM_PROMPT = """You classify shipping-operations emails into exactly one category.
A keyword rule engine already looked at this email and could not confidently
decide, so do not expect exact phrases — look for paraphrases and intent.

- BL_COMPARISON: asks (directly or indirectly) to check/compare/confirm a
  Shipping Instruction (SI) against a draft Bill of Lading (BL).
- SI_REQUEST: asks to prepare/issue/update a Shipping Instruction.
- INVOICE_QUERY: asks about an invoice, payment, billing, or a charge.
- SPAM: unsolicited marketing, phishing, or junk.
- GENERAL: any other legitimate operational message that doesn't fit above
  — this is a real, correct answer, not a fallback to avoid.

Reply with ONLY the category name, nothing else."""


def with_retry(fn, max_retries=3, base_delay=1.5):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        last_err = None
        for attempt in range(max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_err = e
                time.sleep(base_delay * (2 ** attempt))
        raise last_err
    return wrapper


@with_retry
def _ai_classify(email: dict, hint: str = None) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    subject = email.get("subject") or ""
    body = (email.get("body") or "")[:2000]
    attachments = email.get("attachments") or []
    hint_line = f"\n\n(A keyword rule weakly suggested {hint}, but confirm independently.)" if hint else ""
    message = (
        f"Subject: {subject}\n\n"
        f"Body:\n{body}\n\n"
        f"Attachments: {', '.join(attachments) if attachments else 'none'}"
        f"{hint_line}"
    )

    resp = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    result = ""
    for block in resp.content:
        if hasattr(block, "text") and block.text:
            result = block.text.strip().upper()
            break
    for cat in CATEGORIES:
        if cat in result:
            return cat
    return "GENERAL"


def classify_with_fallback(email: dict) -> str:
    """Recommended entry point: trust strong rule matches, ask Claude to
    confirm weak hints and unmatched emails."""
    category, is_strong = rule_classify(email)
    if is_strong:
        return category

    try:
        return _ai_classify(email, hint=category)
    except Exception as e:
        print(f"[classify] Claude failed for {email.get('email_id')}: {e}")
        return category or "GENERAL"  # fall back to the weak hint, or GENERAL