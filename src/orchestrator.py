"""The orchestrator: turns issue events into managed Devin work and reconciles
outcomes back to GitHub + the datastore.

Pipeline per issue:
  route()        cost-aware: trivial -> codemod ($0), judgment -> Devin
  dispatch       Devin fixer session (idempotent, ACU-capped, org-Knowledge attached)
  reconcile      poll fixer -> on PR, dispatch a reviewer Devin -> poll reviewer
  gate           risk-tiered auto-merge (OFF by default) on reviewer-approve +
                 green + low-risk; otherwise hold for a human

Run:  python -m src.orchestrator [dispatch|reconcile|once|loop]
"""
from __future__ import annotations

import argparse
import json
import logging
import time

import config
from src import prompts, router, store
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

    # ── routing + dispatch ──────────────────────────────────────────────────────
    def dispatch(self) -> int:
        issues = self.gh.list_open_issues(config.TARGET_LABEL)
        log.info("Found %d open issue(s) labelled '%s'", len(issues), config.TARGET_LABEL)
        dispatched = 0
        for issue in issues:
            row = store.get(issue["number"])
            if row is None:
                dispatched += int(bool(self._intake(issue)))
            elif row["status"] == "dispatching" and not row["session_id"] and row["attempts"] < config.MAX_ATTEMPTS:
                # crash/transient recovery: a row exists but the API call never landed.
                dispatched += int(bool(self._attempt_dispatch(issue, router.route(issue))))
        return dispatched

    def dispatch_one(self, issue: dict) -> bool:
        """Single-issue entry used by the real-time webhook receiver."""
        if store.has_run(issue["number"]):
            return False
        return bool(self._intake(issue))

    def _intake(self, issue: dict):
        r = router.route(issue)
        if r.handler == "codemod":
            # Trivial, deterministic — a linter handles it for $0. Never spend an agent.
            store.insert(
                issue, handler="codemod", risk_tier=r.risk_tier, finding_type=r.finding_type,
                rule_id=r.rule_id, status="codemod_done", acu_used=0.0,
                automerge_decision="codemod", structured_output=json.dumps({"routed": r.reason}),
            )
            log.info("Routed #%s -> codemod ($0): %s", issue["number"], r.reason)
            return False
        return self._attempt_dispatch(issue, r)

    def _attempt_dispatch(self, issue: dict, r: router.Route) -> bool:
        num = issue["number"]
        # Write the row BEFORE the API call so a crash mid-create is recoverable
        # (no orphaned, paid-for session that we forget about).
        if store.get(num) is None:
            store.insert(issue, handler="devin", risk_tier=r.risk_tier,
                         finding_type=r.finding_type, rule_id=r.rule_id, status="dispatching")
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
            store.update(num, status="working", session_id=session.get("session_id"),
                         devin_url=session.get("url", ""), dispatch_ts=time.time(), error=None)
            log.info("Dispatched #%s -> %s (%s)", num, session.get("session_id"), session.get("url"))
            return True
        except Exception as e:  # noqa: BLE001
            attempts = store.bump_attempts(num)
            if attempts >= config.MAX_ATTEMPTS:
                store.update(num, status="error", error=str(e))
                log.error("Dispatch of #%s failed permanently after %d attempts: %s", num, attempts, e)
            else:
                log.warning("Dispatch of #%s failed (attempt %d), will retry: %s", num, attempts, e)
            return False

    # ── reconcile ───────────────────────────────────────────────────────────────
    def reconcile(self) -> None:
        for row in store.fixers_to_poll():
            self._poll_fixer(row)
        if config.REVIEWER_ENABLED:
            for row in store.prs_needing_reviewer():
                self._dispatch_reviewer(row)
        for row in store.reviewers_to_poll():
            self._poll_reviewer(row)

    def _poll_fixer(self, row: dict) -> None:
        num, sid = row["issue_number"], row["session_id"]
        if row["dispatch_ts"] and time.time() - row["dispatch_ts"] > config.MAX_RUN_AGE_SECONDS:
            store.update(num, status="expired", error="exceeded MAX_RUN_AGE")
            self.gh.add_labels(num, ["needs-human"])
            log.warning("#%s expired (exceeded max run age)", num)
            return
        try:
            session = self.devin.get_session(sid)
        except Exception as e:  # noqa: BLE001 — transient: retry, do NOT strand
            attempts = store.bump_attempts(num)
            if attempts >= config.MAX_ATTEMPTS:
                store.update(num, status="error", error=str(e))
                log.error("#%s poll failed permanently: %s", num, e)
            else:
                log.warning("#%s poll failed (attempt %d), will retry: %s", num, attempts, e)
            return

        status = self.devin.status_of(session)
        fresh_pr = store.apply_session(num, status, session, which="fixer")
        if fresh_pr and not row["pr_commented"]:
            self._comment_pr_opened(num, fresh_pr, session)
        if status == "blocked":
            self.gh.add_labels(num, ["needs-human"])
            reason = (session.get("structured_output") or {}).get("blocked_reason", "(no reason)")
            log.warning("#%s BLOCKED: %s", num, reason)
        elif status in config.TERMINAL_STATES:
            log.info("#%s fixer terminal: %s", num, status)

    def _dispatch_reviewer(self, row: dict) -> None:
        if store.active_count() >= config.MAX_CONCURRENCY:
            return
        num = row["issue_number"]
        issue = {"number": num, "title": row["issue_title"]}
        try:
            session = self.devin.create_session(
                prompts.build_review_prompt(issue, row["pr_url"], config.GITHUB_REPO),
                structured_output_schema=prompts.REVIEW_SCHEMA,
                tags=prompts.reviewer_tags(issue),
                title=prompts.reviewer_title(issue),
            )
            store.update(num, reviewer_session_id=session.get("session_id"),
                         reviewer_url=session.get("url", ""))
            log.info("#%s reviewer dispatched -> %s", num, session.get("session_id"))
        except Exception as e:  # noqa: BLE001
            log.warning("#%s reviewer dispatch failed: %s", num, e)

    def _poll_reviewer(self, row: dict) -> None:
        num, rid = row["issue_number"], row["reviewer_session_id"]
        try:
            session = self.devin.get_session(rid)
        except Exception as e:  # noqa: BLE001
            log.warning("#%s reviewer poll failed: %s", num, e)
            return
        store.apply_session(num, self.devin.status_of(session), session, which="reviewer")
        so = session.get("structured_output") or {}
        if so.get("verdict"):  # reviewer reached a decision -> run the merge gate
            self._gate(num)

    # ── merge gate ──────────────────────────────────────────────────────────────
    def _gate(self, num: int) -> None:
        row = store.get(num)
        decision, reason = self._evaluate_gate(row)
        store.update(num, automerge_decision=decision)

        if decision == "merged":
            pr_num = self.gh.pr_number_from_url(row["pr_url"])
            try:
                self.gh.merge_pr(pr_num)
                store.update(num, merged_at=time.time())
                log.info("#%s AUTO-MERGED PR #%s (%s)", num, pr_num, reason)
            except Exception as e:  # noqa: BLE001
                store.update(num, automerge_decision="held_for_human", error=f"merge failed: {e}")
                decision, reason = "held_for_human", f"merge call failed: {e}"
        else:
            self.gh.add_labels(num, ["awaiting-human"])

        if not row["reviewer_commented"]:
            self._comment_gate(num, row, decision, reason)

    def _evaluate_gate(self, row: dict) -> tuple[str, str]:
        if not config.AUTOMERGE_ENABLED:
            return "disabled", "auto-merge disabled by default — routed to human review"
        if row["risk_tier"] != "low" or (row["rule_id"] or "") not in config.LOW_RISK_RULES:
            return "held_for_human", "high-risk change (e.g. dependency / judgment) — never auto-merged"
        if row["reviewer_verdict"] != "approve":
            return "held_for_human", f"reviewer verdict = {row['reviewer_verdict']}"
        ro = json.loads(row.get("reviewer_output") or "{}")
        if not ro.get("tests_passing"):
            return "held_for_human", "tests not independently confirmed green"
        pr = self.gh.get_pr(self.gh.pr_number_from_url(row["pr_url"]))
        if pr.get("changed_files", 0) > config.MAX_AUTOMERGE_FILES or \
           (pr.get("additions", 0) + pr.get("deletions", 0)) > config.MAX_AUTOMERGE_LINES:
            return "held_for_human", "diff exceeds auto-merge size guardrail"
        return "merged", "low-risk, reviewer-approved, tests green, small diff"

    # ── GitHub comments ─────────────────────────────────────────────────────────
    def _comment_pr_opened(self, num: int, pr_url: str, session: dict) -> None:
        so = session.get("structured_output") or {}
        body = (
            f"🤖 **Devin opened a fix:** {pr_url}\n\n"
            f"- **Root cause:** {so.get('root_cause', 'n/a')}\n"
            f"- **Summary:** {so.get('fix_summary', 'n/a')}\n"
            f"- **Tests passing (per Devin):** {so.get('tests_passing', 'n/a')} · "
            f"**Confidence:** {so.get('confidence', 'n/a')}\n\n"
            f"_An independent reviewer Devin will now audit this PR before any merge._"
        )
        self.gh.comment(num, body)
        self.gh.add_labels(num, ["devin-pr-open"])
        store.update(num, pr_commented=1)
        log.info("#%s commented PR %s", num, pr_url)

    def _comment_gate(self, num: int, row: dict, decision: str, reason: str) -> None:
        ro = json.loads(row.get("reviewer_output") or "{}")
        missed = ro.get("missed_cases") or []
        icon = {"merged": "✅", "held_for_human": "🛑", "disabled": "🛑", "codemod": "⚡"}.get(decision, "•")
        body = (
            f"{icon} **Merge gate: `{decision}`** — {reason}\n\n"
            f"- **Reviewer verdict:** {row.get('reviewer_verdict', 'n/a')} "
            f"(recommendation: {row.get('reviewer_recommendation', 'n/a')})\n"
            f"- **Risk tier:** {row.get('risk_tier', 'n/a')}\n"
        )
        if missed:
            body += "- **Reviewer found missed cases:**\n" + "".join(f"    - {m}\n" for m in missed[:5])
        self.gh.comment(num, body)
        store.update(num, reviewer_commented=1)
        log.info("#%s gate=%s (%s)", num, decision, reason)

    # ── loops ────────────────────────────────────────────────────────────────────
    def once(self) -> None:
        self.dispatch()
        self.reconcile()

    def loop(self) -> None:
        log.info("Loop start (interval=%ss, automerge=%s, reviewer=%s).",
                 config.POLL_INTERVAL, config.AUTOMERGE_ENABLED, config.REVIEWER_ENABLED)
        while True:
            try:
                self.dispatch()
                self.reconcile()
            except Exception as e:  # noqa: BLE001
                log.exception("Loop iteration error: %s", e)
            time.sleep(config.POLL_INTERVAL)


def main() -> None:
    ap = argparse.ArgumentParser(description="Devin remediation orchestrator")
    ap.add_argument("command", nargs="?", default="loop",
                    choices=["dispatch", "reconcile", "once", "loop"])
    args = ap.parse_args()
    getattr(Orchestrator(), args.command)()


if __name__ == "__main__":
    main()
