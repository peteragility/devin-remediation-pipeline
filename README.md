# Autonomous Remediation Pipeline — Devin as a governed primitive

> Event-driven automation that clears an engineering team's **security & dependency
> backlog** on Apache Superset. Findings are **routed** (trivial → a $0 codemod;
> judgment → Devin), each Devin **fixer** session adapts code and runs tests until
> green and opens a PR, a second Devin **reviewer** independently audits it, and a
> risk-tiered **merge gate** decides auto-merge vs. human. Everything is observable
> on a live dashboard.

Built for the Cognition take-home. The repo, the claims, and the demo all describe
the **same** system — nothing here is narrated-but-unbuilt.

![Architecture](docs/architecture.png)

---

## Why this matters

Every engineering org carries a backlog of security findings and dependency
upgrades that never gets cleared — it's low-status toil that loses to feature work
every sprint. This pipeline clears it autonomously and shows a leader, on one
screen, that it's working.

## Why Devin, and not an interactive copilot (the honest version)

Claude Code, Codex, and Cursor are **interactive copilots** — an AI in a developer's
editor where a human drives the session. Their unit of work is *"a developer
session."* They now have headless modes, so "only Devin can run unattended" is **not**
a claim we make.

The defensible claim is **operational**: Devin is purpose-built to run agents as
**governed fleet infrastructure**, and this system exercises exactly that layer:

- **Event → session API** with **structured-output contracts** — the orchestrator
  reads machine state, never scrapes prose.
- **Devin reviews Devin** — the reviewer's verdict is a *structured artifact* that
  programmatically **gates the merge** (not "an agent left a comment").
- **Org Knowledge** attached to every session — conventions live once in Devin and
  the whole fleet inherits them unattended.
- **Native cost governance** — an enforced per-session ACU cap.
- **Idempotent, crash-safe, concurrency-capped dispatch** — the plumbing you need
  when no human is watching.

> You would never build a mission-control dashboard for an IDE copilot — a human is
> already watching. The fact that this fleet *needs* one is the proof it runs unattended.

And the **router** is the cost-aware answer to "why not just a codemod?": we *use* a
codemod for codemod-shaped work (Bandit B113/B324/B506, bare-except) for $0, and
reserve Devin for the judgment cases a rules engine can't touch.

---

## The pipeline

| Stage | What happens | Code |
|---|---|---|
| **Route** | Each finding → `codemod` ($0) or `devin` (judgment) + a risk tier | `src/router.py` |
| **Fix** | Devin session (idempotent, ACU-capped, **Knowledge attached**) adapts code, runs tests until green, opens a PR | `src/orchestrator.py`, `src/prompts.py` |
| **Review** | A second Devin independently audits the PR → structured verdict | `prompts.build_review_prompt`, `REVIEW_SCHEMA` |
| **Gate** | Auto-merge **only if** reviewer-approved AND tests green AND low-risk AND small diff; else hold for a human. **OFF by default.** | `Orchestrator._evaluate_gate` |
| **Observe** | Every step persisted; KPIs on a live dashboard | `src/store.py`, `dashboard/app.py` |

The hero case is real: **PR #10** upgraded PyJWT for a CVE, *discovered* the new
32-byte-HMAC breaking change, fixed every short secret across 5 files, and wrote a
regression test — then the **reviewer Devin found a 6th secret the fixer missed** and
correctly withheld approval. The gate held it for a human. That's the safety
mechanism working, on the record.

---

## Setup

```bash
cp .env.example .env                 # fill DEVIN_API_KEY, GITHUB_TOKEN, GITHUB_REPO
python -m scripts.setup_knowledge    # one-time: create org Knowledge -> paste id into .env as KNOWLEDGE_ID
make seed                            # load the REAL run facts (PR #10 + reviewer verdict) into the dashboard
docker compose up --build            # orchestrator loop + dashboard (:8501) + webhook (:8000)
```
Open **http://localhost:8501**. The orchestrator loop now autonomously carries any
in-flight work through fix → review → gate; the dashboard reflects it live.

> **Offline (no keys / no ACUs):** `DEVIN_SIMULATE=true make seed && DEVIN_SIMULATE=true streamlit run dashboard/app.py`.
> In simulate mode the pipeline never writes to real GitHub.

---

## Demo flow (what the 5-minute walkthrough shows)

Pre-run everything (above) so nothing is waited on live. Have five tabs open:
**dashboard** (:8501), the fork's **Issues**, **PR #10**, the **reviewer's review** on
PR #10, and one **Devin session**.

1. **The fleet, at a glance** — the dashboard. One event produced a backlog of
   remediations: a router split them into a `$0 codemod` lane and a `Devin` lane;
   each Devin PR was independently reviewed; the gate decided merge vs. human.
   *"You'd never build mission-control for an IDE copilot — a human is already
   watching. This dashboard existing is the proof the fleet runs unattended."*

2. **The event + architecture** — the fork's Issues (the backlog) and the diagram.
   A scan or webhook drops findings in; everything downstream is automatic.

3. **Hero: autonomous breaking-change fix (PR #10)** — the thin issue ("upgrade and
   fix breakage") next to Devin's PR: it *discovered* PyJWT 2.13's 32-byte-key
   breaking change, fixed every short secret across 5 files, wrote a regression
   test, and ran tests until green. Unattended. A version-bumper opens a red PR
   here; a copilot needs a human at the keyboard.

4. **Devin reviews Devin** — the reviewer session's **Request Changes** on PR #10:
   it independently re-ran 83 tests and found a 6th short secret the fixer missed,
   so the gate **held the PR for a human**. Agents check agents; only clean work
   clears the gate.

5. **Routing + trust-ramp** — back on the dashboard: the trivial Bandit fixes went
   to the codemod for `$0`; Devin was spent only on the judgment cases (the
   dependency upgrade and a `datetime.utcnow()` deprecation migration). Auto-merge
   is OFF by default; the trust-ramp earns it per-rule.

6. **Why Devin + close** — the differentiation is the operational layer (session
   API, structured-verdict gating, org Knowledge, ACU governance), and the close is
   the dashboard's cost-per-fix: a backlog now measured in PRs and dollars per fix.

### Optional live trigger (real-time event, low risk)
With the webhook running, label any issue `devin-fix` on camera and watch it appear
on the dashboard and dispatch within seconds — then cut back to the pre-run results
(don't wait the ~40 min for a fix to complete on camera).

---

## Observability — and how the metrics stay honest

| Metric | Definition | Source |
|---|---|---|
| Time-to-PR | dispatch → PR, real wall-clock | orchestrator timestamps in SQLite |
| Success | PR opened **AND** tests independently green | `tests_passing` |
| Reviewer-audited | PRs a second Devin reviewed | reviewer verdict |
| Gate decision | auto-merged / held-for-human / codemod | `_evaluate_gate` |
| Cost / fix | ACU × `ACU_USD_RATE` | **ACU read from the Devin console** into `fixtures/real_runs.json` |

Per-session ACU is **not exposed by the session API on this tier**, so it is read
from Devin's consumption console and entered as real numbers — never guessed. The
enforced `max_acu_limit` is the live cost-governance primitive.

---

## Configuration (`.env`)

| Var | Purpose |
|---|---|
| `DEVIN_API_KEY` | Devin API key (`apk_…`) |
| `GITHUB_TOKEN` / `GITHUB_REPO` | `repo`-scoped token + your `user/superset` fork |
| `KNOWLEDGE_ID` | Org Knowledge entry attached to every session (`scripts/setup_knowledge.py`) |
| `REVIEWER_ENABLED` | Dispatch a reviewer Devin per PR (default on) |
| `AUTOMERGE_ENABLED` | Risk-tiered auto-merge (**default OFF** — gate routes to human) |
| `LOW_RISK_RULES` | Rule ids eligible for auto-merge (deps never qualify) |
| `ACU_USD_RATE` / `ENG_HOUR_USD` | Cost + ROI conversion for the dashboard |
| `DEVIN_MAX_ACU` | Enforced per-session ACU cap |
| `MAX_CONCURRENCY` / `POLL_INTERVAL` / `MAX_RUN_AGE_SECONDS` / `MAX_ATTEMPTS` | Fleet + robustness controls |

The **real** merge gate in production is **GitHub branch protection** (required CI +
required review) — enforced by the platform, independent of this orchestrator.

---

## Repo layout
```
src/router.py        cost-aware routing (codemod vs Devin)
src/orchestrator.py  route → dispatch → reconcile → review → gate (crash-safe, retrying)
src/devin_client.py  Devin API wrapper (+ Knowledge), simulate hook
src/github_client.py issues / comments / PR status / merge
src/prompts.py       fixer + reviewer prompts and structured-output schemas
src/store.py         SQLite system-of-record
src/webhook.py       real-time GitHub issue trigger (FastAPI)
src/simulator.py     deterministic offline Devin (fixer + reviewer)
scripts/setup_knowledge.py   create the org Knowledge entry
scripts/scan_and_file.py     scan → file issues (batch event source)
scripts/seed_demo.py         load REAL run facts for the dashboard
dashboard/app.py     observability dashboard
fixtures/real_runs.json      real session ids, PR, reviewer verdict, ACU
docs/architecture.png        architecture diagram
```

## Extending in a real engagement
- **Triggers:** the GitHub webhook is built; the same receiver extends to
  Snyk/CodeQL/Jira/ServiceNow scan-complete events.
- **Trust ramp:** enable `AUTOMERGE_ENABLED` per-rule after a baseline of
  human-approved Devin PRs; widen the low-risk allowlist as confidence grows.
- **Scale:** one config per repo; the dashboard already aggregates cost-per-fix and
  cycle time for leadership.
