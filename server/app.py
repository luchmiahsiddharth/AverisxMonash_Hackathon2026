from pathlib import Path
import json
import sys

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.decide import process_email
from pipeline.extract import extract_fields_from_attachment
from pipeline.loader import Inbox

app = FastAPI(title="SDOC Verifier")

SUBMISSION = json.loads((ROOT / "submission.json").read_text())
EMAILS = json.loads((ROOT / "data/emails_meta.json").read_text())
EMAIL_INDEX = {e["email_id"]: e for e in EMAILS}

# Persist human reviews to a small JSON file
REVIEWS_PATH = ROOT / "data" / "reviews.json"
if REVIEWS_PATH.exists():
    REVIEWS = json.loads(REVIEWS_PATH.read_text())
else:
    REVIEWS = {}

app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "frontend/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/emails")
def list_emails(category: str | None = None, status: str | None = None):
    """Return the email list, with result merged in, so the frontend has
    everything it needs in one call."""
    out = []
    for e in EMAILS:
        r = SUBMISSION.get(e["email_id"], {})
        row = {
            "email_id": e["email_id"],
            "subject": e.get("subject", ""),
            "category": r.get("category", "GENERAL"),
            "status": r.get("status", "OK"),
            "has_defect": r.get("has_defect", False),
            "defect_fields": r.get("defect_fields", []),
            "review_reason": r.get("review_reason"),
        }
        if category and row["category"] != category:
            continue
        if status and row["status"] != status:
            continue
        out.append(row)
    return out


@app.get("/api/emails/{email_id}")
def get_email(email_id: str):
    if email_id not in EMAIL_INDEX:
        raise HTTPException(404, "email not found")
    email = EMAIL_INDEX[email_id]
    result = SUBMISSION.get(email_id, {})
    return {"email": email, "result": result}


class ReviewBody(BaseModel):
    corrected_status: str
    notes: str = ""


@app.post("/api/emails/{email_id}/review")
def submit_review(email_id: str, body: ReviewBody):
    if email_id not in EMAIL_INDEX:
        raise HTTPException(404, "email not found")
    REVIEWS[email_id] = {
        "corrected_status": body.corrected_status,
        "notes": body.notes,
    }
    REVIEWS_PATH.write_text(json.dumps(REVIEWS, indent=2))
    return {"ok": True, "review": REVIEWS[email_id]}


@app.post("/api/process/{email_id}")
def process_live(email_id: str):
    if email_id not in EMAIL_INDEX:
        raise HTTPException(404, "email not found")
    inbox = Inbox(str(ROOT / "data"))
    try:
        return process_email(EMAIL_INDEX[email_id], inbox)
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/emails/{email_id}/fields")
def get_fields(email_id: str):
    if email_id not in EMAIL_INDEX:
        raise HTTPException(404, "email not found")
    email = EMAIL_INDEX[email_id]
    attachments = email.get("attachments", [])

    si_path = next((a for a in attachments if "SI" in a), None)
    bl_path = next((a for a in attachments if "BL" in a), None)

    if not si_path or not bl_path:
        return {"si": None, "bl": None, "mismatches": []}

    inbox = Inbox(str(ROOT / "data"))
    si_fields = extract_fields_from_attachment(inbox, si_path)
    bl_fields = extract_fields_from_attachment(inbox, bl_path)

    return {"si": si_fields, "bl": bl_fields}