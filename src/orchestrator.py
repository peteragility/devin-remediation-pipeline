"""The orchestrator: the brain that turns issue events into managed Devin
sessions and reconciles their outcomes back to GitHub + the datastore.

  dispatch()  : new labelled issues  -> Devin sessions  (idempotent, capped)
  reconcile() : in-flight sessions    -> status / PR / structured_output
  loop()      : run both forever on POLL_INTERVAL

Run:  python -m src.orchestrator [dispatch|reconcile|loop|once]
"""
from __future__ import annotations

import argparse
import logging
import time

import config
from src import prompts, store
from src.devin_client import DevinClient
from src.github_client import GitHubClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(self):
        self.devin = DevinClient()
        self.gh = GitHubClient()
        store.init()

    # ── event -> Devin session ──────────────────────────────────────────────────
    def dispatch_one(self, issue: dict) -> bool:
        """Dispatch a single issue to a Devin session. Idempotent and
        concurrency-capped. Returns True iff a new session was created.

        Used by both the scheduled scan path (dispatch) and the real-time
        GitHub webhook receiver (src/webhook.py)."""
        num = issue["number"]
        if store.has_run(num):
            return False  # idempotency: never double-dispatch
        if store.active_count() >= config.MAX_CONCURRENCY:
            log.info("Concurrency cap (%d) reached; deferring #%s.", config.MAX_CONCURRENCY, num)
            return False
        try:
            session = self.devin.create_session(
                prompts.build_prompt(issue, config.GITHUB_REPO),
                structured_output_schema=prompts.STRUCTURED_OUTPUT_SCHEMA,
                tags=prompts.session_tags(issue),
                title=prompts.session_title(issue),
            )
            store.insert_dispatch(issue, session, _finding_type(issue))
            log.info(
                "Dispatched #%s -> %s (%s)",
                num,
                session.get("session_id"),
                session.get("url"),
            )
            return True
        except Exception as e:  # noqa: BLE001 - surface, keep going
            log.exception("Failed to dispatch #%s: %s", num, e)
            return False

    def dispatch(self) -> int:
        issues = self.gh.list_open_issues(config.TARGET_LABEL)
        log.info("Found %d open issue(s) labelled '%s'", len(issues), config.TARGET_LABEL)
        return sum(1 for issue in issues if self.dispatch_one(issue))

    # ── Devin session -> outcome ────────────────────────────────────────────────
    def reconcile(self) -> int:
        runs = store.runs_needing_poll()
        updated = 0
        for run in runs:
            num = run["issue_number"]
            sid = run["session_id"]
            try:
                session = self.devin.get_session(sid)
                status = self.devin.status_of(session)
                store.update_from_session(num, status, session)
                updated += 1

                pr_url = self.devin.pr_url_of(session) or (
                    (session.get("structured_output") or {}).get("pr_url")
                )
                if pr_url and not run["pr_commented"]:
                    self._comment_pr(num, pr_url, session)

                if status in config.TERMINAL_STATES:
                    log.info("#%s reached terminal state '%s'", num, status)
                elif status in config.ATTENTION_STATES:
                    reason = (session.get("structured_output") or {}).get(
                        "blocked_reason", "(no reason given)"
                    )
                    log.warning("#%s is BLOCKED: %s", num, reason)
            except Exception as e:  # noqa: BLE001
                log.exception("Reconcile failed for #%s: %s", num, e)
                store.record_error(num, str(e))
        return updated

    def _comment_pr(self, issue_number: int, pr_url: str, session: dict) -> None:
        so = session.get("structured_output") or {}
        body = (
            f"🤖 **Devin opened a fix:** {pr_url}\n\n"
            f"- **Root cause:** {so.get('root_cause', 'n/a')}\n"
            f"- **Summary:** {so.get('fix_summary', 'n/a')}\n"
            f"- **Tests passing:** {so.get('tests_passing', 'n/a')}  ·  "
            f"**Confidence:** {so.get('confidence', 'n/a')}\n\n"
            f"_Awaiting human review — Devin does not self-merge._"
        )
        self.gh.comment(issue_number, body)
        self.gh.add_labels(issue_number, ["devin-pr-open"])
        store.mark_commented(issue_number)
        log.info("#%s commented with PR %s", issue_number, pr_url)

    # ── loops ────────────────────────────────────────────────────────────────────
    def once(self) -> None:
        self.dispatch()
        self.reconcile()

    def loop(self) -> None:
        log.info("Entering loop (interval=%ss). Ctrl-C to stop.", config.POLL_INTERVAL)
        while True:
            try:
                self.dispatch()
                self.reconcile()
            except Exception as e:  # noqa: BLE001
                log.exception("Loop iteration error: %s", e)
            time.sleep(config.POLL_INTERVAL)


def _finding_type(issue: dict) -> str:
    """Derive a coarse finding category from issue labels/title for analytics."""
    names = " ".join(l.get("name", "") for l in issue.get("labels", [])).lower()
    title = (issue.get("title") or "").lower()
    blob = f"{names} {title}"
    if "depend" in blob or "cve" in blob or "upgrade" in blob:
        return "dependency"
    if "security" in blob or "bandit" in blob or "vuln" in blob:
        return "security"
    return "code-quality"


def main() -> None:
    ap = argparse.ArgumentParser(description="Devin remediation orchestrator")
    ap.add_argument(
        "command",
        nargs="?",
        default="loop",
        choices=["dispatch", "reconcile", "once", "loop"],
    )
    args = ap.parse_args()
    orch = Orchestrator()
    getattr(orch, args.command)()


if __name__ == "__main__":
    main()
