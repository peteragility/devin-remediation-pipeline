"""Central config loaded from environment (.env in dev, real env in Docker)."""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# Devin
DEVIN_API_KEY = os.getenv("DEVIN_API_KEY", "")
DEVIN_API_BASE = os.getenv("DEVIN_API_BASE", "https://api.devin.ai/v1").rstrip("/")
DEVIN_MAX_ACU = int(os.getenv("DEVIN_MAX_ACU", "10"))
DEVIN_SIMULATE = _bool("DEVIN_SIMULATE")

# GitHub
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
TARGET_LABEL = os.getenv("TARGET_LABEL", "devin-fix")
# Shared secret for verifying GitHub webhook payloads (HMAC-SHA256). Optional in
# dev; strongly recommended in any shared/exposed deployment.
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

# Orchestrator
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "20"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "5"))
DB_PATH = os.getenv("DB_PATH", "data/pipeline.db")

# Terminal Devin states (no further polling needed).
TERMINAL_STATES = {"finished", "expired"}
# States that need a human nudge (surfaced on the dashboard).
ATTENTION_STATES = {"blocked"}
