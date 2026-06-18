"""Deterministic Devin simulator for credit-free, OFFLINE demos only.

It models both roles in the pipeline so the full loop (fixer PR -> reviewer
verdict -> merge gate) runs without an API key:
  - fixer    session:  working -> finished (+ PR + structured_output)
  - reviewer session:  working -> finished (+ verdict / recommendation)

State is persisted to JSON next to the DB so it survives across processes.
Note: time-to-PR on the dashboard is measured from the orchestrator's own
wall-clock (store dispatch_ts/pr_ts), NOT from anything this file returns — so
the latency metric is real even in simulate mode. Toggle: DEVIN_SIMULATE=true.
"""
from __future__ import annotations

import itertools
import json
import os
import threading
from typing import Any

import config

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


def _fixer_output(issue: int, done: bool) -> dict[str, Any]:
    return {
        "status": "done" if done else "fixing",
        "issue_number": issue,
        "root_cause": "Behavioral change in an upgraded dependency broke call-sites.",
        "files_changed": ["superset/constants.py", "tests/unit_tests/utils_test.py"],
        "fix_summary": "Adapted call-sites to the new API and added a regression test.",
        "tests_run": done,
        "tests_passing": done,
        "confidence": "high",
        "pr_url": (f"https://github.com/{config.GITHUB_REPO or 'example/superset'}/pull/{9000 + issue}"
                   if done else ""),
    }


def _reviewer_output(issue: int, done: bool) -> dict[str, Any]:
    return {
        "pr_number": 9000 + issue,
        "phase": "done" if done else "testing",
        "verdict": "approve" if done else None,
        "confidence": "high",
        "summary": "Independently re-ran the relevant tests; no missed cases found.",
        "missed_cases": [],
        "tests_run": done,
        "tests_passing": done,
        "security_ok": True,
        "recommendation": "auto_merge" if done else None,
    }


def _snapshot(sess: dict[str, Any]) -> dict[str, Any]:
    done = sess["polls"] >= STEPS_TO_DONE
    issue = sess.get("issue_number", 0)
    is_reviewer = sess.get("role") == "reviewer"
    so = _reviewer_output(issue, done) if is_reviewer else _fixer_output(issue, done)
    out: dict[str, Any] = {
        "session_id": sess["session_id"],
        "status": "finished" if done else "working",
        "status_enum": "finished" if done else "working",
        "structured_output": so,
    }
    if done and not is_reviewer:
        out["pull_request"] = {"url": so["pr_url"]}
    return out


class Simulator:
    def create_session(self, prompt: str, *, tags=None, title=None) -> dict[str, Any]:
        tags = tags or []
        role = "reviewer" if "role:reviewer" in tags else "fixer"
        issue = next((t.split(":")[-1] for t in tags if t.startswith("issue:")), "0")
        with _LOCK:
            state = _load()
            state["seq"] += 1
            sid = f"devin-sim-{role[:3]}-{state['seq']:04d}"
            state["sessions"][sid] = {
                "session_id": sid, "role": role,
                "issue_number": int(issue) if issue.isdigit() else 0, "polls": 0,
            }
            _save(state)
        return {"session_id": sid, "url": f"https://app.devin.ai/sessions/{sid}", "is_new_session": True}

    def get_session(self, session_id: str) -> dict[str, Any]:
        with _LOCK:
            state = _load()
            sess = state["sessions"].get(session_id)
            if not sess:
                return {"session_id": session_id, "status": "expired", "status_enum": "expired"}
            sess["polls"] += 1
            _save(state)
            return _snapshot(sess)
