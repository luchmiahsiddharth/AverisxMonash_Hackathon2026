# SDOC Hackathon

A Python workspace for classifying shipping-document emails and comparing
shipping instructions with draft bills of lading.

## Setup

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The participant dataset is under `data/`. The protected `ground_truth.json` is
kept at the project root for local scoring and is not served by the API unless
explicitly enabled.

## Run the starter pipeline

```powershell
python -m pipeline.run_pipeline
```

## Run the scoring server

```powershell
uvicorn server.main:app --reload
```

For the organizer Docker distribution:

```powershell
docker compose up --build
```

The pipeline stages live in `pipeline/`; the HTTP service and scoring helpers
live in `server/`.