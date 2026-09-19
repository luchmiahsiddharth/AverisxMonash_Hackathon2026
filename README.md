# SDOC Hackathon

## Setup
1. python3 -m venv venv && source venv/bin/activate
2. pip install -r requirements.txt
3. cp .env.example .env, then add your real API key

## Run the pipeline
python3 -m pipeline.run_pipeline
→ creates results.json

## Score it locally
python3 reference/score_cli.py results.json --ground-truth ground_truth.json

## Run the server
python3 -m uvicorn server.main:app --reload --port 8000

## Open the dashboard
Open frontend/index.html in a browser (server must already be running)