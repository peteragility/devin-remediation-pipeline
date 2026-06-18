"""Cost-aware routing — the "don't pay an agent for what a linter does for free" rule.

Every finding is classified before any Devin session is created:

  - codemod : trivial, mechanical, single-rule rewrites a linter autofixes
              deterministically for $0 (Bandit B113/B324/B506, bare-except E722).
              These NEVER go to Devin.
  - devin   : judgment work — dependency upgrades with breaking changes, call-site
              migrations, failing-test triage. This is where an autonomous agent
              earns its cost.

This routing decision is the architecture's answer to "why not just a codemod?":
we use a codemod for codemod-shaped work and reserve Devin for the rest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import config

# Mechanical rules a linter autofixes deterministically — route to a codemod.
CODEMOD_RULES = {"B113", "B324", "B506", "E722"}
_RULE_RE = re.compile(r"\b([BES]\d{3}|E722)\b")


@dataclass
class Route:
    handler: str       # 'codemod' | 'devin'
    risk_tier: str     # 'low' | 'high'  (auto-merge eligibility)
    rule_id: str       # e.g. 'B113', or '' if none
    finding_type: str  # 'security' | 'dependency' | 'code-quality'
    reason: str


def finding_type(issue: dict) -> str:
    labels = " ".join(l.get("name", "") for l in issue.get("labels", [])).lower()
    blob = f"{labels} {(issue.get('title') or '').lower()}"
    if "depend" in blob or "cve" in blob or "upgrade" in blob:
        return "dependency"
    if "security" in blob or "bandit" in blob or "vuln" in blob:
        return "security"
    return "code-quality"


def _rule_id(issue: dict) -> str:
    m = _RULE_RE.search(f"{issue.get('title','')} {issue.get('body','')}")
    if m:
        return m.group(1)
    if "bare except" in (issue.get("title", "") + issue.get("body", "")).lower():
        return "E722"
    return ""


def route(issue: dict) -> Route:
    ftype = finding_type(issue)
    rule = _rule_id(issue)

    # Dependency work always needs judgment (the upgrade may break call-sites).
    if ftype == "dependency":
        return Route("devin", "high", rule, ftype, "dependency upgrade — may break call-sites; needs judgment")

    # Trivial mechanical rules → codemod, $0.
    if rule in CODEMOD_RULES:
        return Route("codemod", "low", rule, ftype, f"{rule} is a deterministic linter autofix")

    # Everything else → Devin, and risk-tier by whether its rule is in the allowlist.
    risk = "low" if rule in config.LOW_RISK_RULES else "high"
    return Route("devin", risk, rule, ftype, "non-mechanical fix — needs an agent")
