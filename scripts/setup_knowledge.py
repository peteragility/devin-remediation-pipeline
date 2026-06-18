"""Create the org Knowledge entry every session in the fleet inherits.

This is the Devin-native primitive that makes the differentiation real: instead
of re-prompting each session, conventions live ONCE in Devin and every fixer +
reviewer session applies them unattended. Run once, then put the printed id in
.env as KNOWLEDGE_ID.

Usage:  python -m scripts.setup_knowledge
"""
from __future__ import annotations

from src.devin_client import DevinClient

NAME = "Apache Superset — remediation conventions"

TRIGGER = (
    "Apply when remediating issues or opening pull requests in the apache/superset "
    "repository (security findings, dependency upgrades, code-quality fixes)."
)

BODY = """\
When fixing issues in apache/superset:

- Run the relevant unit tests with `pytest tests/unit_tests/...`; do not run the
  full suite unless necessary. A change is not done until the relevant tests pass.
- Stay strictly in scope: fix only the reported issue; never refactor unrelated code.
- For DEPENDENCY UPGRADES: assume the new version may have behavioral/breaking
  changes. After bumping, search the ENTIRE codebase for affected call-sites,
  defaults, fixtures, and config — not just the obvious one — and adapt them all.
  Add a regression test that would fail on the old behavior.
- Open one focused PR per issue. The PR description must start with `Fixes #<n>`.
- Do not merge your own PR; an independent reviewer and a merge gate handle that.
"""


def main() -> None:
    client = DevinClient()
    existing = client.list_knowledge().get("knowledge", [])
    for k in existing:
        if k.get("name") == NAME:
            print(f"Knowledge already exists: id={k.get('id')}  (set KNOWLEDGE_ID in .env)")
            return
    created = client.create_knowledge(NAME, BODY, TRIGGER)
    print("Created Knowledge entry.")
    print(f"  id: {created.get('id')}")
    print("  -> add this to .env:  KNOWLEDGE_ID=" + str(created.get("id")))


if __name__ == "__main__":
    main()
