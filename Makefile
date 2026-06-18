.PHONY: install scan dispatch reconcile once loop dashboard up down logs sim-demo

install:        ## install python deps into the current environment
	pip install -r requirements.txt

knowledge:      ## one-time: create the org Knowledge entry (prints id for .env)
	python -m scripts.setup_knowledge

seed:           ## load REAL run facts into the dashboard DB (no waiting)
	python -m scripts.seed_demo

scan:           ## EVENT SOURCE: scan repo (or fixtures) -> file GitHub issues
	python -m scripts.scan_and_file

scan-dry:       ## preview the issues that would be filed
	python -m scripts.scan_and_file --dry-run

dispatch:       ## one pass: labelled issues -> Devin sessions
	python -m src.orchestrator dispatch

reconcile:      ## one pass: poll sessions -> update store + comment PRs
	python -m src.orchestrator reconcile

once:           ## one dispatch + reconcile pass
	python -m src.orchestrator once

loop:           ## run the orchestrator continuously
	python -m src.orchestrator loop

webhook:        ## run the FastAPI webhook receiver (real-time trigger)
	uvicorn src.webhook:app --host 0.0.0.0 --port 8000 --reload

dashboard:      ## launch the Streamlit dashboard locally
	streamlit run dashboard/app.py

up:             ## docker: build + run orchestrator + dashboard
	docker compose up --build

down:           ## docker: stop + remove
	docker compose down

logs:           ## docker: tail orchestrator logs
	docker compose logs -f orchestrator

sim-demo:       ## fully offline end-to-end demo (no API keys / no ACUs)
	DEVIN_SIMULATE=true python -m src.orchestrator once
	DEVIN_SIMULATE=true python -m src.orchestrator once
	@echo "Now run:  DEVIN_SIMULATE=true make dashboard"
