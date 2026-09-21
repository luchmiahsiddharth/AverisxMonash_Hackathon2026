"""
decide.py — Orchestrate classification, extraction, and comparison
for a single email and return the submission entry for it.

Output shape (one entry per email in submission.json):
    {
        "category":      one of BL_COMPARISON / SI_REQUEST / INVOICE_QUERY / GENERAL / SPAM,
        "status":        "OK" | "MISMATCH" | "NEEDS_REVIEW",
        "review_reason": None | "missing_attachment" | "unreadable" | "missing_value",
        "has_defect":    bool,
        "defect_fields": list[str],
    }

Decision flow (only BL_COMPARISON emails go past step 1):
    1. Not a BL comparison               -> OK
    2. No SI or no BL attachment         -> NEEDS_REVIEW / missing_attachment
    3. Extraction fails or raises        -> NEEDS_REVIEW / unreadable
    4. Any extracted field is None       -> NEEDS_REVIEW / missing_value
    5. SI and BL fields differ           -> MISMATCH (+ defect_fields)
    6. Otherwise                         -> OK
"""

from typing import Iterable, List, Optional

from .classify import classify_with_fallback
from .extract import extract_fields_from_attachment, FIELDS
from .compare import compare_documents


# ------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------

def _result(category: str,
            status: str = "OK",
            review_reason: Optional[str] = None,
            defect_fields: Optional[List[str]] = None) -> dict:
    """Build a submission entry. has_defect is derived, so it can never
    disagree with defect_fields."""
    defect_fields = list(defect_fields or [])
    return {
        "category": category,
        "status": status,
        "review_reason": review_reason,
        "has_defect": bool(defect_fields),
        "defect_fields": defect_fields,
    }


def _needs_review(category: str, reason: str) -> dict:
    return _result(category, status="NEEDS_REVIEW", review_reason=reason)


def _find_attachment(attachments: Iterable[str], tag: str) -> Optional[str]:
    """First attachment whose filename contains _SI. or _BL. (case-insensitive)."""
    marker = f"_{tag}."
    for a in attachments:
        if marker in a.upper():
            return a
    return None


def _has_missing_value(fields: dict) -> bool:
    return any(v is None for v in fields.values())


def _ordered(defects: Iterable[str]) -> List[str]:
    """De-duplicate and put defect fields in the canonical FIELDS order."""
    seen = set(defects)
    ordered = [f for f in FIELDS if f in seen]
    ordered += sorted(seen - set(FIELDS))  # anything unexpected goes last
    return ordered


# ------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------

def process_email(email: dict, inbox) -> dict:
    category = classify_with_fallback(email)

    # 1. Only BL comparisons need document work.
    if category != "BL_COMPARISON":
        return _result(category)

    # 2. Need both an SI and a BL to compare.
    attachments = email.get("attachments") or []
    si_path = _find_attachment(attachments, "SI")
    bl_path = _find_attachment(attachments, "BL")
    if not si_path or not bl_path:
        return _needs_review(category, "missing_attachment")

    # 3. Extract fields from both documents. A crash in one file must not
    #    take down the whole email, so treat it as unreadable.
    try:
        si_fields = extract_fields_from_attachment(inbox, si_path)
        bl_fields = extract_fields_from_attachment(inbox, bl_path)
    except Exception as e:
        print(f"[decide] extraction failed for {email.get('email_id')}: {e}")
        return _needs_review(category, "unreadable")

    if si_fields is None or bl_fields is None:
        return _needs_review(category, "unreadable")

    # 4. We can't call a match or a mismatch if a value wasn't found.
    if _has_missing_value(si_fields) or _has_missing_value(bl_fields):
        return _needs_review(category, "missing_value")

    # 5. Compare.
    try:
        mismatches = compare_documents(si_fields, bl_fields)
    except Exception as e:
        print(f"[decide] comparison failed for {email.get('email_id')}: {e}")
        return _needs_review(category, "unreadable")

    if mismatches:
        return _result(category, status="MISMATCH",
                       defect_fields=_ordered(mismatches))

    # 6. Everything matched.
    return _result(category)