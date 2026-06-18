"""Issue producer = the EVENT SOURCE.

Runs security/dependency scanners against a local Superset checkout, converts
findings into GitHub issues labelled `devin-fix`, and exits. The orchestrator
then picks those issues up. If no checkout is configured (SUPERSET_PATH unset)
or the scanners aren't installed, falls back to fixtures/findings.json so the
demo always has issues to remediate.

Usage:
  python -m scripts.scan_and_file            # scan SUPERSET_PATH or use fixtures
  python -m scripts.scan_and_file --dry-run  # print issues, don't create them
  python -m scripts.scan_and_file --limit 3  # cap number of issues filed
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from typing import Any

import config
from src.github_client import GitHubClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("scan")


def _bandit_findings(path: str) -> list[dict[str, Any]]:
    """Run Bandit JSON and collapse to one issue per rule id (deduped)."""
    try:
        proc = subprocess.run(
            ["bandit", "-r", path, "-f", "json", "-q"],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("Bandit unavailable/failed (%s); skipping.", e)
        return []
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return []

    by_rule: dict[str, dict[str, Any]] = {}
    for r in data.get("results", []):
        rid = r.get("test_id", "B???")
        entry = by_rule.setdefault(
            rid,
            {
                "title": f"[security] {r.get('test_name', rid)} ({rid})",
                "finding_type": "security",
                "locations": [],
                "issue_text": r.get("issue_text", ""),
            },
        )
        entry["locations"].append(f"{r.get('filename')}:{r.get('line_number')}")

    findings = []
    for rid, e in by_rule.items():
        locs = "\n".join(f"- `{l}`" for l in e["locations"][:25])
        findings.append(
            {
                "title": e["title"],
                "finding_type": "security",
                "body": (
                    f"## Finding ({rid})\n{e['issue_text']}\n\n"
                    f"## Locations\n{locs}\n\n"
                    "## Acceptance criteria\n- Apply the secure pattern.\n"
                    "- Add/extend a test.\n- The Bandit rule no longer fires.\n\n"
                    "_Source: Bandit static analysis._"
                ),
            }
        )
    return findings


def _pip_audit_findings(path: str) -> list[dict[str, Any]]:
    req = os.path.join(path, "requirements", "base.txt")
    if not os.path.exists(req):
        req = os.path.join(path, "requirements.txt")
    if not os.path.exists(req):
        return []
    try:
        proc = subprocess.run(
            ["pip-audit", "-r", req, "-f", "json"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        data = json.loads(proc.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        log.warning("pip-audit unavailable/failed (%s); skipping.", e)
        return []

    findings = []
    for dep in data.get("dependencies", []):
        for v in dep.get("vulns", []):
            findings.append(
                {
                    "title": f"[dependency] {dep['name']} {dep.get('version','')} — {v.get('id')}",
                    "finding_type": "dependency",
                    "body": (
                        f"## Finding\n`{dep['name']}=={dep.get('version','')}` is affected "
                        f"by **{v.get('id')}**.\n\n{v.get('description','')}\n\n"
                        f"Fix versions: {', '.join(v.get('fix_versions', [])) or 'see advisory'}\n\n"
                        "## Acceptance criteria\n- Bump to a non-vulnerable version.\n"
                        "- Fix any breakage so tests pass.\n- pip-audit no longer reports it.\n\n"
                        "_Source: pip-audit._"
                    ),
                }
            )
    return findings


def collect_findings() -> list[dict[str, Any]]:
    path = os.getenv("SUPERSET_PATH", "")
    if path and os.path.isdir(path):
        log.info("Scanning %s ...", path)
        findings = _bandit_findings(path) + _pip_audit_findings(path)
        if findings:
            return findings
        log.warning("No findings from scanners; falling back to fixtures.")
    else:
        log.info("SUPERSET_PATH not set/found; using fixtures/findings.json.")

    fx = os.path.join(os.path.dirname(__file__), "..", "fixtures", "findings.json")
    with open(os.path.abspath(fx)) as f:
        return json.load(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = ap.parse_args()

    findings = collect_findings()
    if args.limit:
        findings = findings[: args.limit]
    log.info("Collected %d finding(s).", len(findings))

    if args.dry_run:
        for f in findings:
            print(f"\n=== {f['title']} ===\n{f['body'][:300]}...")
        return

    gh = GitHubClient()
    gh.ensure_label(config.TARGET_LABEL, desc="Remediate this issue with Devin")
    for f in findings:
        issue = gh.create_issue(
            f["title"],
            f["body"],
            labels=[config.TARGET_LABEL, f.get("finding_type", "code-quality")],
        )
        log.info("Filed #%s: %s", issue["number"], f["title"])


if __name__ == "__main__":
    main()
