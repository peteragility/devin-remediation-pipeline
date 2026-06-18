"""Seed the SQLite store from REAL run facts (fixtures/real_runs.json) so the
dashboard an evaluator sees shows real data — real session ids, real PR, the real
reviewer verdict, and time-to-PR measured from real timestamps — not simulator
output.

Usage:  python -m scripts.seed_demo
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import config
from src import store

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "real_runs.json")


def _epoch(iso: str | None) -> float | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def main() -> None:
    store.init()
    with open(os.path.abspath(FIXTURE)) as f:
        data = json.load(f)

    for run in data["runs"]:
        issue = {"number": run["number"], "title": run["title"], "html_url": run["html_url"]}
        fields = {k: v for k, v in run.items()
                  if k not in ("number", "title", "html_url", "dispatch_iso", "pr_iso", "reviewer_output")}
        if run.get("dispatch_iso"):
            fields["dispatch_ts"] = _epoch(run["dispatch_iso"])
        if run.get("pr_iso"):
            fields["pr_ts"] = _epoch(run["pr_iso"])
        if run.get("reviewer_output"):
            fields["reviewer_output"] = json.dumps(run["reviewer_output"])
        if run.get("pr_url"):
            fields["pr_commented"] = 1
        if run.get("reviewer_verdict"):
            fields["reviewer_commented"] = 1
        store.insert(issue, **fields)
        print(f"seeded #{run['number']:>2}  {run['handler']:<7}  {run.get('status','')}")

    print(f"\nSeeded {len(data['runs'])} runs into {config.DB_PATH}.")


if __name__ == "__main__":
    main()
