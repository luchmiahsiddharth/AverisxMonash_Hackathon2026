from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
from loader import Inbox

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

RESULTS = json.load(open("results.json"))
EMAILS = {e["email_id"]: e for e in Inbox("data").emails()}

@app.get("/api/emails")
def list_emails(category: str = None, status: str = None):
    out = []
    for eid, r in RESULTS.items():
        if category and r["category"] != category:
            continue
        if status and r.get("status") != status:
            continue
        out.append({"email_id": eid, "subject": EMAILS[eid]["subject"], **r})
    return out

@app.get("/api/emails/{email_id}")
def get_email(email_id: str):
    if email_id not in RESULTS:
        raise HTTPException(404, "not found")
    return {"email": EMAILS[email_id], "result": RESULTS[email_id]}

class ReviewCorrection(BaseModel):
    corrected_status: str
    notes: str = ""

REVIEWS = {}  # temporary — becomes Firebase later, not needed yet

@app.post("/api/emails/{email_id}/review")
def submit_review(email_id: str, correction: ReviewCorrection):
    REVIEWS[email_id] = correction.dict()
    return {"ok": True}