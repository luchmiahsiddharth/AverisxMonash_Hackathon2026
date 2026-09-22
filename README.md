# SDOC Hackathon 2026 — Shipping Document Verification Pipeline

**Team:** MauCoderz
**Event:** Averis x Monash Hackathon 2026

## Overview

This pipeline automates the review of shipping-operations emails. For each
email it:

1. **Classifies** the email into one of five categories
   (`BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, `SPAM`).
2. If the email is a **BL_COMPARISON**, **extracts** the key fields from its
   Shipping Instruction (SI) and Bill of Lading (BL) attachments.
3. **Compares** the two sets of fields for discrepancies.
4. **Decides** a final status for the email — `OK`, `MISMATCH`, or
   `NEEDS_REVIEW` — with a reason if it needs a human to look at it.

The output is `submission.json`, one entry per email, scored against
`ground_truth.json` with `reference/score_cli.py`.

## Architecture

```
email ──► classify.py ──► category
                            │
              not BL_COMPARISON ──► OK
                            │
                     BL_COMPARISON
                            │
            find SI + BL attachments ──(missing)──► NEEDS_REVIEW: missing_attachment
                            │
                extract.py (SI + BL fields) ──(fails)──► NEEDS_REVIEW: unreadable
                            │
                any field missing? ──(yes)──► NEEDS_REVIEW: missing_value
                            │
                compare.py ──► mismatched fields
                            │
                   none: OK        some: MISMATCH (+ defect_fields)
```

`decide.py` orchestrates the whole flow above for a single email;
`run_pipeline.py` runs it over every email in the inbox and writes the
submission file.

## Project structure

```
.
├── pipeline/
│   ├── loader.py       # Inbox access — local files or the HTTP server
│   ├── classify.py     # Stage 1: email classification (rules + LLM fallback)
│   ├── extract.py      # Stage 2: field extraction from SI/BL attachments
│   ├── compare.py      # Stage 3: SI-vs-BL field comparison
│   ├── decide.py        # Stage 4: orchestration + final decision per email
│   ├── pools.py         # Entity pools (ports, shippers, customers) used by compare.py
│   ├── retry.py         # Shared exponential-backoff retry decorator
│   └── run_pipeline.py  # Entry point — runs the full pipeline, writes submission.json
├── server/
│   ├── main.py           # FastAPI review dashboard backend
│   ├── make_bundle.py
│   ├── make_docker_bundle.py
│   └── Dockerfile
├── reference/
│   ├── score_cli.py     # Scores a submission against ground_truth.json
│   └── scoring.py
├── data/                 # Email inbox + attachments (not committed if large)
├── ground_truth.json
├── sample_submission.json
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

1. **Clone the repo and create a virtual environment**
   ```bash
   git clone <repo-url>
   cd AverisxMonash_Hackathon2026
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # macOS/Linux
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your API key**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your key:
   ```
   ANTHROPIC_API_KEY=your-key-here
   ```
   Required for the LLM fallback in `classify.py` and the extraction
   fallback in `extract.py`.

## Running the pipeline

```bash
python pipeline/run_pipeline.py
```

This processes every email in `data/` and writes `submission.json` to the
project root. Progress is printed every 25 emails.

## Scoring

```bash
python reference/score_cli.py --submission submission.json --ground-truth ground_truth.json
```

(Run `python reference/score_cli.py --help` to confirm the exact flags —
check `reference/score_cli.py` if this differs.)

## Current results

| Metric | Score |
|---|---|
| Stage 1 — classification accuracy | 0.977 |
| Stage 1 — macro-F1 | 0.969 |
| Stage 3 — defect recall | 0.717 |
| Stage 3 — defect precision | 0.393 |
| End-to-end defect capture | *(update after latest run)* |
| **Final score** | *(update after latest run)* |

## Known limitations / future work

- `SI_REQUEST` classification has some false positives from a broad keyword
  match; `GENERAL` recall is correspondingly lower than the other categories.
- Attachment matching relies on `_SI.` / `_BL.` in the filename; emails with
  different naming conventions are escalated to `NEEDS_REVIEW`.
- See `pipeline/decide.py` and `pipeline/classify.py` docstrings for the
  detailed per-stage design notes and challenges.

## Team

- *Siddharth Luchmiah*
- *Kamya Seeburn*
- *Rowan Dodin*
- *Yashvin Buchaya*
- *Yeshika Buchaya*