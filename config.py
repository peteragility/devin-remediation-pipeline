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

# Orchestrator
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "5"))
DB_PATH = os.getenv("DB_PATH", "data/pipeline.db")
# Hung-session guard: a session in flight longer than this is marked 'expired'.
MAX_RUN_AGE_SECONDS = int(os.getenv("MAX_RUN_AGE_SECONDS", str(2 * 60 * 60)))
# Transient poll/dispatch errors are retried up to this many times before giving up.
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))

# Terminal Devin states (no further polling needed).
TERMINAL_STATES = {"finished", "expired"}
# States that need a human nudge (surfaced on the dashboard).
ATTENTION_STATES = {"blocked"}

# Reviewer-Devin (a second session reviews the fixer's PR).
REVIEWER_ENABLED = _bool("REVIEWER_ENABLED", "true")

# Auto-merge. OFF by default — by default every PR is held for a human, and GitHub
# branch protection is the real platform-enforced gate. When enabled, a PR merges
# only if the reviewer Devin approved AND tests are green AND the diff is small.
AUTOMERGE_ENABLED = _bool("AUTOMERGE_ENABLED", "false")
# Auto-merge diff guardrails: anything larger always escalates to a human.
MAX_AUTOMERGE_FILES = int(os.getenv("MAX_AUTOMERGE_FILES", "5"))
MAX_AUTOMERGE_LINES = int(os.getenv("MAX_AUTOMERGE_LINES", "80"))

# Devin-native primitives. A Knowledge entry attached to every session gives the
# whole fleet shared org context unattended (see scripts/setup_knowledge.py).
KNOWLEDGE_ID = os.getenv("KNOWLEDGE_ID", "")
PLAYBOOK_ID = os.getenv("PLAYBOOK_ID", "")

# Cost reporting. Per-session ACU is read from the Devin consumption console (the
# session API on this tier does not expose it) and recorded in fixtures/real_runs.json.
# This rate converts ACU -> USD for the dashboard's $/fix tile.
ACU_USD_RATE = float(os.getenv("ACU_USD_RATE", "2.25"))
# Defensible engineer-hour baseline for the ROI tile (a senior-eng hour, fully loaded).
ENG_HOUR_USD = float(os.getenv("ENG_HOUR_USD", "120"))
