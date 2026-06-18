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
- One issue, one focused PR. Open the PR; do NOT merge it yourself — an
  independent reviewer and a merge gate handle that.
- Follow the repository's existing conventions and any org knowledge provided to you.
- If you become blocked (missing access, ambiguous requirement, failing
  environment), set structured_output.status = "blocked" with a clear
  blocked_reason and stop rather than guessing.

# Progress reporting (important)
Maintain your structured output continuously. Update it IMMEDIATELY whenever you
change phase or complete a requirement, and set status="done" with the pr_url
populated once the PR is open. This output is read by an automated dashboard.
"""


def session_tags(issue: dict) -> list[str]:
    return ["superset-remediation", "role:fixer", f"issue:{issue['number']}", config.TARGET_LABEL]


def session_title(issue: dict) -> str:
    return f"Fix #{issue['number']}: {issue['title']}"[:120]


# ── Reviewer-Devin: a second session independently audits the fixer's PR ─────────
# The value is not "an agent reviewed an agent" (commodity) — it's that the verdict
# is a STRUCTURED ARTIFACT the orchestrator reads to gate the merge.
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "pr_number": {"type": "integer"},
        "phase": {"type": "string", "enum": ["analyzing", "searching", "testing", "posting_review", "done", "blocked"]},
        "verdict": {"type": "string", "enum": ["approve", "request_changes", "comment"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "summary": {"type": "string"},
        "missed_cases": {"type": "array", "items": {"type": "string"}},
        "tests_run": {"type": "boolean"},
        "tests_passing": {"type": "boolean"},
        "security_ok": {"type": "boolean"},
        "recommendation": {"type": "string", "enum": ["auto_merge", "human_review", "block"]},
        "review_posted_url": {"type": "string"},
    },
    "required": ["phase"],
}


def build_review_prompt(issue: dict, pr_url: str, repo: str) -> str:
    number = issue["number"]
    return f"""You are a senior staff engineer performing an INDEPENDENT, adversarial code review of a pull request that was authored by ANOTHER autonomous Devin agent. Verify the work; do not trust it.

Repository: {repo}
Pull request: {pr_url}  (remediates issue #{number}: {issue.get('title','')})

Do the following:
1. Confirm the change actually and fully resolves the issue it claims to fix.
2. Search the WHOLE codebase for any related cases the original author may have MISSED (other call-sites, other files, similar patterns) — this is the most valuable thing you can do.
3. Check out the PR branch and RUN ONLY THE TESTS RELEVANT to the change. Report pass/fail.
4. Assess test adequacy, security, and any behavioral regression.

Then POST a real review on the GitHub PR: approve, or request changes with specific, line-referenced comments.

Maintain your structured output continuously. Set recommendation = "auto_merge" ONLY if you independently verified the tests pass AND found no missed cases AND the change is low-risk."""


def reviewer_tags(issue: dict) -> list[str]:
    return ["superset-remediation", "role:reviewer", f"issue:{issue['number']}"]


def reviewer_title(issue: dict) -> str:
    return f"Review fix for #{issue['number']}: {issue.get('title','')}"[:120]
