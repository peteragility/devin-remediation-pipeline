"""Prompt + structured-output contract that turns a GitHub issue into a
machine-trackable Devin remediation session.

The structured_output_schema is the key design choice: it forces Devin's result
into a JSON shape the orchestrator can read programmatically, instead of
scraping prose. This is what makes Devin a *primitive* rather than a chatbot.
"""
from __future__ import annotations

import config

# JSON Schema (Draft 7) describing Devin's "notepad" for each remediation.
STRUCTURED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["analyzing", "fixing", "testing", "pr_open", "blocked", "done"],
            "description": "Current phase of the remediation.",
        },
        "issue_number": {"type": "integer"},
        "root_cause": {"type": "string", "description": "One-line root cause."},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "fix_summary": {"type": "string"},
        "tests_run": {"type": "boolean"},
        "tests_passing": {"type": "boolean"},
        "pr_url": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "blocked_reason": {"type": "string"},
    },
    "required": ["status"],
}


def build_prompt(issue: dict, repo: str) -> str:
    number = issue["number"]
    title = issue["title"]
    body = issue.get("body") or ""

    return f"""You are remediating a single, well-scoped issue in the repository `{repo}`.

# Issue #{number}: {title}

{body}

# Your task
1. Reproduce / locate the problem described above in the codebase.
2. Implement a minimal, correct fix. Stay strictly in scope — do NOT refactor
   unrelated code or bundle other changes.
3. Add or update a test that proves the fix, and run the relevant test + lint
   suite so the change is green.
4. Open a pull request against the default branch. The PR description MUST start
   with "Fixes #{number}" so it links the issue, and summarise the change.

# Guardrails
- One issue, one focused PR. Do not merge it — a human will review.
- If you become blocked (missing access, ambiguous requirement, failing
  environment), set structured_output.status = "blocked" with a clear
  blocked_reason and stop rather than guessing.

# Progress reporting (important)
Maintain your structured output continuously. Update it IMMEDIATELY whenever you
change phase or complete a requirement, and set status="done" with the pr_url
populated once the PR is open. This output is read by an automated dashboard.
"""


def session_tags(issue: dict) -> list[str]:
    return ["superset-remediation", f"issue:{issue['number']}", config.TARGET_LABEL]


def session_title(issue: dict) -> str:
    return f"Fix #{issue['number']}: {issue['title']}"[:120]
