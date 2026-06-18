"""SQLite system-of-record. Single source of truth shared by the orchestrator
(writer) and the dashboard (reader). One row per remediation run."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Optional

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    issue_number      INTEGER PRIMARY KEY,
    issue_title       TEXT,
    issue_url         TEXT,
    finding_type      TEXT,
    session_id        TEXT,
    devin_url         TEXT,
    status            TEXT,            -- normalised Devin status_enum
    pr_url            TEXT,
    confidence        TEXT,
    tests_passing     INTEGER,         -- 0/1/NULL
    acu_used          REAL,
    structured_output TEXT,            -- raw JSON
    pr_commented      INTEGER DEFAULT 0,
    error             TEXT,
    created_at        REAL,
    updated_at        REAL
);
"""


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
        return c.execute(
            "SELECT 1 FROM runs WHERE issue_number=?", (issue_number,)
        ).fetchone() is not None


def active_count() -> int:
    placeholders = ",".join("?" * len(config.TERMINAL_STATES))
    with _conn() as c:
        return c.execute(
            f"SELECT COUNT(*) FROM runs WHERE status NOT IN ({placeholders})",
            tuple(config.TERMINAL_STATES),
        ).fetchone()[0]


def insert_dispatch(issue: dict, session: dict, finding_type: str) -> None:
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO runs
               (issue_number, issue_title, issue_url, finding_type, session_id,
                devin_url, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                issue["number"],
                issue["title"],
                issue.get("html_url", ""),
                finding_type,
                session.get("session_id"),
                session.get("url", ""),
                "working",
                _now(),
                _now(),
            ),
        )


def update_from_session(issue_number: int, status: str, session: dict) -> None:
    so = session.get("structured_output") or {}
    pr_url = None
    pr = session.get("pull_request")
    if isinstance(pr, dict):
        pr_url = pr.get("url")
    pr_url = pr_url or so.get("pr_url") or None
    tests = so.get("tests_passing")
    acu = None
    for k in ("acu_used", "acus_used", "acu", "compute_units_used"):
        if session.get(k) is not None:
            acu = session[k]
            break

    with _conn() as c:
        c.execute(
            """UPDATE runs SET status=?, pr_url=COALESCE(?, pr_url),
               confidence=?, tests_passing=?, acu_used=COALESCE(?, acu_used),
               structured_output=?, updated_at=? WHERE issue_number=?""",
            (
                status,
                pr_url,
                so.get("confidence"),
                (None if tests is None else int(bool(tests))),
                acu,
                json.dumps(so),
                _now(),
                issue_number,
            ),
        )


def mark_commented(issue_number: int) -> None:
    with _conn() as c:
        c.execute("UPDATE runs SET pr_commented=1 WHERE issue_number=?", (issue_number,))


def record_error(issue_number: int, msg: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE runs SET status='error', error=?, updated_at=? WHERE issue_number=?",
            (msg, _now(), issue_number),
        )


def all_runs() -> list[dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY issue_number")]


def runs_needing_poll() -> list[dict[str, Any]]:
    placeholders = ",".join("?" * len(config.TERMINAL_STATES))
    with _conn() as c:
        rows = c.execute(
            f"""SELECT * FROM runs
                WHERE session_id IS NOT NULL
                  AND status NOT IN ({placeholders})
                  AND status != 'error'""",
            tuple(config.TERMINAL_STATES),
        ).fetchall()
        return [dict(r) for r in rows]


def get_run(issue_number: int) -> Optional[dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT * FROM runs WHERE issue_number=?", (issue_number,)).fetchone()
        return dict(row) if row else None
