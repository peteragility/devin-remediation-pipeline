#!/usr/bin/env bash
# Run the whole pipeline locally WITHOUT Docker.
#
# Useful behind a corporate TLS-inspection proxy (Zscaler/Netskope) that injects
# a self-signed root CA: such proxies break pip and HTTPS *inside* Docker
# containers, but the host already trusts the corporate CA, so running on the
# host "just works". Reads keys from .env (via python-dotenv in config.py).
#
# Starts: orchestrator loop + webhook (:8000) in the background, dashboard
# (:8501) in the foreground. Ctrl-C stops all three.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "No .venv found. Create it:  python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
mkdir -p data

echo "▶ orchestrator (loop) + webhook (:8000) starting in background…"
python -m src.orchestrator loop &
ORCH=$!
uvicorn src.webhook:app --host 0.0.0.0 --port 8000 --log-level warning &
WH=$!
trap 'echo; echo "stopping…"; kill "$ORCH" "$WH" 2>/dev/null || true' EXIT INT TERM

echo "▶ dashboard → http://localhost:8501   (Ctrl-C to stop everything)"
streamlit run dashboard/app.py
