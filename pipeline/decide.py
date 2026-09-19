from .classify import classify_email
from .extract import extract_fields
from .compare import compare_documents

def process_email(email: dict, inbox) -> dict:
    category = classify_email(email)

    if category != "BL_COMPARISON":
        return {"category": category, "status": "OK", "review_reason": None,
                "has_defect": False, "defect_fields": []}

    attachments = email["attachments"]
    if len(attachments) != 2:
        return {"category": category, "status": "NEEDS_REVIEW",
                "review_reason": "missing_attachment", "has_defect": False, "defect_fields": []}

    si_path = next((a for a in attachments if "SI" in a), None)
    bl_path = next((a for a in attachments if "BL" in a), None)
    if not si_path or not bl_path:
        return {"category": category, "status": "NEEDS_REVIEW",
                "review_reason": "wrong_doc_type", "has_defect": False, "defect_fields": []}

    si_fields = extract_fields(inbox.read_text(si_path))
    bl_fields = extract_fields(inbox.read_text(bl_path))

    if si_fields is None or bl_fields is None:
        return {"category": category, "status": "NEEDS_REVIEW",
                "review_reason": "unreadable", "has_defect": False, "defect_fields": []}

    if any(v is None for v in si_fields.values()) or any(v is None for v in bl_fields.values()):
        return {"category": category, "status": "NEEDS_REVIEW",
                "review_reason": "missing_value", "has_defect": False, "defect_fields": []}

    mismatches = compare_documents(si_fields, bl_fields)
    if mismatches:
        return {"category": category, "status": "MISMATCH", "review_reason": None,
                "has_defect": True, "defect_fields": mismatches}

    return {"category": category, "status": "OK", "review_reason": None,
            "has_defect": False, "defect_fields": []}