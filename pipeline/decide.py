"""
decide.py — Orchestrate the classification, extraction, and comparison
for a single email.
"""

from .classify import classify_with_fallback
from .extract import extract_fields_from_attachment
from .compare import compare_documents


def process_email(email: dict, inbox) -> dict:
    category = classify_with_fallback(email)

    if category != "BL_COMPARISON":
        return {
            "category": category,
            "status": "OK",
            "review_reason": None,
            "has_defect": False,
            "defect_fields": [],
        }

    attachments = email.get("attachments", [])

    si_path = next((a for a in attachments if "_SI." in a), None)
    bl_path = next((a for a in attachments if "_BL." in a), None)

    if not si_path or not bl_path:
        return {
            "category": category,
            "status": "NEEDS_REVIEW",
            "review_reason": "missing_attachment",
            "has_defect": False,
            "defect_fields": [],
        }

    si_fields = extract_fields_from_attachment(inbox, si_path)
    bl_fields = extract_fields_from_attachment(inbox, bl_path)

    if si_fields is None or bl_fields is None:
        return {
            "category": category,
            "status": "NEEDS_REVIEW",
            "review_reason": "unreadable",
            "has_defect": False,
            "defect_fields": [],
        }

    if any(v is None for v in si_fields.values()) or any(v is None for v in bl_fields.values()):
        return {
            "category": category,
            "status": "NEEDS_REVIEW",
            "review_reason": "missing_value",
            "has_defect": False,
            "defect_fields": [],
        }

    mismatches = compare_documents(si_fields, bl_fields)
    if mismatches:
        return {
            "category": category,
            "status": "MISMATCH",
            "review_reason": None,
            "has_defect": True,
            "defect_fields": mismatches,
        }

    return {
        "category": category,
        "status": "OK",
        "review_reason": None,
        "has_defect": False,
        "defect_fields": [],
    }
