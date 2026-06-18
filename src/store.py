"""SQLite system-of-record. One row per issue (the unit of work). Single source
of truth shared by the orchestrator (writer) and the dashboard (reader).

A generic update(issue_number, **fields) keeps the surface small. Timestamps are
real wall-clock so the dashboard's time-to-PR is a measured latency, not a value
echoed back from Devin."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Optional

import config

# Whitelisted columns (also guards the dynamic UPDATE against injection).
COLUMNS = [
    "issue_number", "issue_title", "issue_url", "finding_type", "rule_id",
    "handler", "risk_tier", "status", "attempts",
    "session_id", "devin_url", "pr_url", "tests_passing", "confidence",
    "structured_output", "pr_commented",
    "reviewer_session_id", "reviewer_url", "reviewer_verdict",
    "reviewer_recommendation", "reviewer_output", "reviewer_commented",
    "automerge_decision", "merged_at",
    "acu_used", "error",
    "dispatch_ts", "pr_ts", "created_at", "updated_at",
]

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS runs (
    issue_number            INTEGER PRIMARY KEY,
    issue_title             TEXT,
    issue_url               TEXT,
    finding_type            TEXT,
    rule_id                 TEXT,
    handler                 TEXT,      -- 'devin' | 'codemod'
    risk_tier               TEXT,      -- 'low' | 'high'
    status                  TEXT,      -- routing|codemod_done|dispatching|working|finished|expired|blocked|error
    attempts                INTEGER DEFAULT 0,
    session_id              TEXT,
    devin_url               TEXT,
    pr_url                  TEXT,
    tests_passing           INTEGER,
    confidence              TEXT,
    structured_output       TEXT,
    pr_commented            INTEGER DEFAULT 0,
    reviewer_session_id     TEXT,
    reviewer_url            TEXT,
    reviewer_verdict        TEXT,      -- approve | request_changes | comment
    reviewer_recommendation TEXT,      -- auto_merge | human_review | block
    reviewer_output         TEXT,
    reviewer_commented      INTEGER DEFAULT 0,
    automerge_decision      TEXT,      -- merged | held_for_human | ineligible | disabled
    merged_at               REAL,
    acu_used                REAL,
    error                   TEXT,
    dispatch_ts             REAL,
    pr_ts                   REAL,
    created_at              REAL,
    updated_at              REAL
);
"""

# Statuses that need no further polling.
TERMINAL = set(config.TERMINAL_STATES) | {"codemod_done"}
# Statuses that count against the in-flight Devin concurrency budget.
ACTIVE = {"dispatching", "working"}


def _now() -> float:
    return time.time()


@contextmanager
def _conn():
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


def has_run(issue_number: int) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM runs WHERE issue_number=?", (issue_number,)).fetchone() is not None


def active_count() -> int:
    """In-flight Devin sessions (fixer or reviewer dispatching/working)."""
    qs = ",".join("?" * len(ACTIVE))
    with _conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM runs WHERE status IN ({qs})", tuple(ACTIVE)).fetchone()[0]


def insert(issue: dict, **fields) -> None:
    base = {
        "issue_number": issue["number"],
        "issue_title": issue.get("title"),
        "issue_url": issue.get("html_url", ""),
        "attempts": 0,
        "pr_commented": 0,
        "reviewer_commented": 0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    base.update(fields)
    cols = [k for k in base if k in COLUMNS]
    with _conn() as c:
        c.execute(
            f"INSERT OR REPLACE INTO runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            tuple(base[k] for k in cols),
        )


def update(issue_number: int, **fields) -> None:
    fields["updated_at"] = _now()
    cols = [k for k in fields if k in COLUMNS]
    if not cols:
        return
    with _conn() as c:
        c.execute(
            f"UPDATE runs SET {','.join(f'{k}=?' for k in cols)} WHERE issue_number=?",
            (*[fields[k] for k in cols], issue_number),
        )


def bump_attempts(issue_number: int) -> int:
    with _conn() as c:
        c.execute("UPDATE runs SET attempts=attempts+1, updated_at=? WHERE issue_number=?", (_now(), issue_number))
        return c.execute("SELECT attempts FROM runs WHERE issue_number=?", (issue_number,)).fetchone()[0]


def apply_session(issue_number: int, status: str, session: dict, *, which: str = "fixer") -> Optional[str]:
    """Fold a Devin session payload into the row. Returns a newly-observed PR url
    (fixer only) the first time one appears, else None."""
    so = session.get("structured_output") or {}
    pr_url = None
    pr = session.get("pull_request")
    if isinstance(pr, dict):
        pr_url = pr.get("url")
    pr_url = pr_url or so.get("pr_url") or None

    if which == "fixer":
        row = get(issue_number) or {}
        fresh_pr = pr_url if (pr_url and not row.get("pr_url")) else None
        fields = {
            "status": status,
            "structured_output": json.dumps(so),
            "confidence": so.get("confidence"),
            "tests_passing": None if so.get("tests_passing") is None else int(bool(so.get("tests_passing"))),
        }
        if pr_url:
            fields["pr_url"] = pr_url
        if fresh_pr:
            fields["pr_ts"] = _now()
        update(issue_number, **fields)
        return fresh_pr

    # reviewer
    update(
        issue_number,
        reviewer_verdict=so.get("verdict"),
        reviewer_recommendation=so.get("recommendation"),
        reviewer_output=json.dumps(so),
    )
    return None


def get(issue_number: int) -> Optional[dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT * FROM runs WHERE issue_number=?", (issue_number,)).fetchone()
        return dict(row) if row else None


def all_runs() -> list[dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY issue_number")]


def fixers_to_poll() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM runs WHERE session_id IS NOT NULL AND status IN ('dispatching','working')"
        ).fetchall()
        return [dict(r) for r in rows]


def prs_needing_reviewer() -> list[dict[str, Any]]:
    """Devin PRs that are open but have no reviewer session yet."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM runs WHERE handler='devin' AND pr_url IS NOT NULL "
            "AND reviewer_session_id IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]


def reviewers_to_poll() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM runs WHERE reviewer_session_id IS NOT NULL AND reviewer_verdict IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]
