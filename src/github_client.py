"""Minimal GitHub REST client (issues, comments, labels) using `requests`.

Kept dependency-light on purpose. In SIMULATE mode with no token, falls back to
reading fixtures/findings.json so the dashboard has issues to show offline.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import requests

import config

log = logging.getLogger("github")
API = "https://api.github.com"


class GitHubClient:
    def __init__(
        self,
        token: str = config.GITHUB_TOKEN,
        repo: str = config.GITHUB_REPO,
        simulate: bool = config.DEVIN_SIMULATE,
    ):
        self.repo = repo
        # In simulate mode (or with no token) NEVER write to real GitHub — read
        # fixtures and log would-be writes. Prevents offline demos from polluting
        # the live repo.
        self.simulate = simulate or not token
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    # ── read ────────────────────────────────────────────────────────────────────
    def list_open_issues(self, label: str = config.TARGET_LABEL) -> list[dict[str, Any]]:
        """Open issues carrying `label`. Pull requests are filtered out."""
        if self.simulate:
            return self._fixture_issues(label)

        out: list[dict[str, Any]] = []
        page = 1
        while True:
            r = self._session.get(
                f"{API}/repos/{self.repo}/issues",
                params={"labels": label, "state": "open", "per_page": 100, "page": page},
                timeout=30,
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            out.extend(i for i in batch if "pull_request" not in i)
            page += 1
        return out

    # ── write ───────────────────────────────────────────────────────────────────
    def create_issue(
        self, title: str, body: str, labels: Optional[list[str]] = None
    ) -> dict[str, Any]:
        r = self._session.post(
            f"{API}/repos/{self.repo}/issues",
            json={"title": title, "body": body, "labels": labels or []},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def comment(self, issue_number: int, body: str) -> dict[str, Any]:
        if self.simulate:
            log.info("[sim] comment on #%s: %s", issue_number, body.splitlines()[0])
            return {"ok": True}
        r = self._session.post(
            f"{API}/repos/{self.repo}/issues/{issue_number}/comments",
            json={"body": body},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def add_labels(self, issue_number: int, labels: list[str]) -> None:
        if self.simulate:
            return
        r = self._session.post(
            f"{API}/repos/{self.repo}/issues/{issue_number}/labels",
            json={"labels": labels},
            timeout=30,
        )
        r.raise_for_status()

    # ── pull requests (for the auto-merge gate) ────────────────────────────────────
    def get_pr(self, number: int) -> dict[str, Any]:
        if self.simulate:
            return {"state": "open", "mergeable": True, "mergeable_state": "clean",
                    "additions": 12, "deletions": 3, "changed_files": 2}
        r = self._session.get(f"{API}/repos/{self.repo}/pulls/{number}", timeout=30)
        r.raise_for_status()
        return r.json()

    def merge_pr(self, number: int, method: str = "squash") -> dict[str, Any]:
        if self.simulate:
            log.info("[sim] merge PR #%s (%s)", number, method)
            return {"merged": True}
        r = self._session.put(
            f"{API}/repos/{self.repo}/pulls/{number}/merge",
            json={"merge_method": method},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def pr_number_from_url(url: str) -> Optional[int]:
        m = re.search(r"/pull/(\d+)", url or "")
        return int(m.group(1)) if m else None

    def ensure_label(self, name: str, color: str = "5319e7", desc: str = "") -> None:
        if self.simulate:
            return
        r = self._session.post(
            f"{API}/repos/{self.repo}/labels",
            json={"name": name, "color": color, "description": desc},
            timeout=30,
        )
        if r.status_code not in (201, 422):  # 422 = already exists
            r.raise_for_status()

    # ── fixtures (offline) ────────────────────────────────────────────────────────
    def _fixture_issues(self, label: str) -> list[dict[str, Any]]:
        path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "findings.json")
        with open(os.path.abspath(path)) as f:
            findings = json.load(f)
        return [
            {
                "number": 1000 + i,
                "title": f["title"],
                "body": f["body"],
                "labels": [{"name": label}],
                "html_url": f"https://github.com/{self.repo}/issues/{1000 + i}",
            }
            for i, f in enumerate(findings, start=1)
        ]
