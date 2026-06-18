"""Deterministic Devin simulator for credit-free, offline demos.

State is persisted to a JSON file next to the SQLite DB so the lifecycle survives
across separate processes (e.g. repeated `python -m src.orchestrator once`, or a
dispatch process + a dashboard process). Each session advances on successive
polls:  working -> working -> finished (with structured_output + a PR url).

Toggle with DEVIN_SIMULATE=true.
"""
from __future__ import annotations

import itertools
import json
import os
import threading
from typing import Any

import config

# Number of get_session() polls before a session reports "finished".
STEPS_TO_DONE = 2
_LOCK = threading.Lock()


def _state_path() -> str:
    return os.path.join(os.path.dirname(config.DB_PATH) or ".", "sim_state.json")


def _load() -> dict[str, Any]:
    try:
        with open(_state_path()) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seq": 0, "sessions": {}}


def _save(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_state_path()) or ".", exist_ok=True)
    with open(_state_path(), "w") as f:
        json.dump(state, f, indent=2)


def _snapshot(sess: dict[str, Any]) -> dict[str, Any]:
    done = sess["polls"] >= STEPS_TO_DONE
    status = "finished" if done else "working"
    issue = sess.get("issue_number", 0)
    structured = {
        "status": "done" if done else "fixing",
        "issue_number": issue,
        "root_cause": "Insecure pattern flagged by static analysis.",
        "files_changed": ["superset/utils/core.py", "tests/unit_tests/utils_test.py"],
        "fix_summary": "Applied the secure pattern and added a regression test.",
        "tests_run": done,
        "tests_passing": done,
        "confidence": "high",
        "pr_url": (
            f"https://github.com/{config.GITHUB_REPO or 'example/superset'}/pull/{9000 + issue}"
            if done
            else ""
        ),
    }
    out: dict[str, Any] = {
        "session_id": sess["session_id"],
        "status": status,
        "status_enum": status,
        "structured_output": structured,
        "acu_used": round(1.5 + 0.5 * (issue % 6), 2) if done else round(0.8 + 0.3 * (issue % 6), 2),
        "created_at": "2026-06-18T00:00:00Z",
        "updated_at": "2026-06-18T00:05:00Z",
    }
    if done:
        out["pull_request"] = {"url": structured["pr_url"]}
    return out


class Simulator:
    """File-backed so state persists across processes."""

    def create_session(self, prompt: str, *, tags=None, title=None) -> dict[str, Any]:
        tags = tags or []
        issue = next((t.split(":")[-1] for t in tags if t.startswith("issue:")), "0")
        with _LOCK:
            state = _load()
            state["seq"] += 1
            sid = f"devin-sim-{state['seq']:04d}"
            state["sessions"][sid] = {
                "session_id": sid,
                "title": title or "Simulated fix",
                "issue_number": int(issue) if issue.isdigit() else 0,
                "polls": 0,
            }
            _save(state)
        return {
            "session_id": sid,
            "url": f"https://app.devin.ai/sessions/{sid}",
            "is_new_session": True,
        }

    def get_session(self, session_id: str) -> dict[str, Any]:
        with _LOCK:
            state = _load()
            sess = state["sessions"].get(session_id)
            if not sess:
                return {
                    "session_id": session_id,
                    "status": "expired",
                    "status_enum": "expired",
                }
            sess["polls"] += 1
            _save(state)
            return _snapshot(sess)
