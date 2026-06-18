# Autonomous Remediation Pipeline — powered by Devin

> Event-driven automation that clears an engineering team's **security & dependency
> backlog** on Apache Superset. A scan files issues → an orchestrator dispatches a
> **Devin session per issue** → Devin fixes the code, runs tests, and opens a PR →
> status flows back to the issue and a **live observability dashboard**. Humans only
> review PRs.

Built for the Cognition take-home. Optimised for a *working end-to-end demo*.

---

## Why this matters (the pitch)

Every engineering org carries a backlog of security findings and dependency
upgrades that never gets cleared — it's low-status toil that loses to feature work
every sprint. Tools like Dependabot/Renovate can *bump a version*, but they can't
**fix the breakage the bump causes, adapt the calling code, or repair the tests.**

Devin closes that loop. This system treats Devin as a **fleet primitive**: N
findings become N autonomous engineers working in parallel, each producing a
review-ready PR with passing tests — observable end-to-end by an engineering leader.

---

## Architecture

```
   EVENT SOURCE                 ORCHESTRATOR (brain)              OBSERVABILITY
 ┌───────────────┐          ┌───────────────────────┐         ┌──────────────┐
 │ scan_and_file │  issues  │ dispatch():           │ Devin   │  Streamlit   │
 │ Bandit +      ├─────────▶│  issue -> POST        ├────────▶│  dashboard   │
 │ pip-audit     │ (GitHub  │  /v1/sessions         │ v1 API  │ KPIs + table │
 │  └ fixtures   │  labels) │  (idempotent, ACU-cap)│         │ MTTR · ACU · │
 └───────────────┘          │ reconcile():          │◀────────┤ success rate │
        ▲                   │  GET /v1/sessions/{id}│  poll   └──────┬───────┘
        │ (also: GitHub     │  -> status + PR +     │                │
        │  webhook in prod) │     structured_output │         reads  │ SQLite
        │                   │  -> comment issue     │◀───────────────┘ (system
        └───────────────────┤  -> persist (SQLite)  │                  of record)
          PR link back      └───────────────────────┘
```

### Key design decisions (the "How")
1. **Devin as a fleet, not a call.** One session per issue, dispatched in
   parallel, each tracked independently. → `src/orchestrator.py`
2. **Structured-output contract.** Each session is given a JSON Schema
   (`structured_output_schema`) so its result is *machine-readable*
   (`status, root_cause, files_changed, tests_passing, pr_url, confidence`) — the
   orchestrator never scrapes prose. → `src/prompts.py`
3. **Idempotency & concurrency caps.** `idempotent=true` + an issue→session map in
   SQLite means re-running never double-dispatches; `MAX_CONCURRENCY` bounds
   in-flight work. → `src/store.py`
4. **Cost governance.** `max_acu_limit` caps spend per session; ACU spend is
   surfaced on the dashboard. A VP cares this can't run away.
5. **Human-in-the-loop.** Devin opens PRs; it never self-merges.
6. **Poll-based reconciler.** Devin can't be forced to push updates, so we poll
   `GET /v1/sessions/{id}` every `POLL_INTERVAL`s over a clean state machine
   (`working → finished/blocked/expired`).

---

## Quickstart

### Option A — fully offline demo (no keys, no ACUs)
Proves the whole loop using a built-in Devin simulator + fixture issues.
```bash
pip install -r requirements.txt
DEVIN_SIMULATE=true python -m src.orchestrator once   # dispatch (sim sessions)
DEVIN_SIMULATE=true python -m src.orchestrator once   # reconcile -> PRs appear
DEVIN_SIMULATE=true streamlit run dashboard/app.py     # open http://localhost:8501
```
(or just `make sim-demo`)

### Option B — live, with Docker (recommended for the real demo)
```bash
cp .env.example .env        # fill in DEVIN_API_KEY, GITHUB_TOKEN, GITHUB_REPO
make scan                   # EVENT: file issues into your fork (or use fixtures)
docker compose up --build   # orchestrator loop + dashboard at :8501
```
Open **http://localhost:8501** and watch issues move working → PR opened.

### Option C — live, local (no Docker)
```bash
cp .env.example .env && pip install -r requirements.txt
make scan                   # file issues
make loop                   # orchestrator in one terminal
make dashboard              # dashboard in another
```

---

## How each deliverable maps

| Challenge requirement | Where |
|---|---|
| **Triggered by an event** | `scripts/scan_and_file.py` (scan → issues). Webhook path documented under *Extending*. |
| **Programmatically manage Devin sessions** | `src/devin_client.py` + `src/orchestrator.py` (create, poll, comment, steer) |
| **Observable outputs** | GitHub PRs + issue comments; Streamlit dashboard (`dashboard/app.py`) |
| **Observability / analytics** | KPIs: throughput, success rate, MTTR, ACU spend, status & finding-type breakdown |
| **Dockerised** | `Dockerfile` + `docker-compose.yml` (orchestrator + dashboard, shared volume) |
| **Forked Superset + issues** | `make scan` files them; fixtures in `fixtures/findings.json` |

---

## Configuration (`.env`)

| Var | Purpose |
|---|---|
| `DEVIN_API_KEY` | Devin API key (`apk_…`) |
| `DEVIN_MAX_ACU` | Per-session ACU ceiling (cost guard) |
| `DEVIN_SIMULATE` | `true` = run against the offline simulator |
| `GITHUB_TOKEN` / `GITHUB_REPO` | `repo`-scoped token + your `user/superset` fork |
| `TARGET_LABEL` | Issue label that triggers remediation (default `devin-fix`) |
| `POLL_INTERVAL` / `MAX_CONCURRENCY` | Reconcile cadence + in-flight cap |
| `SUPERSET_PATH` | Local Superset checkout to scan (optional; else fixtures) |

---

## Repo layout
```
src/devin_client.py    Devin v1 API wrapper (+ simulate hook)
src/github_client.py   GitHub issues/comments/labels (+ fixture fallback)
src/prompts.py         Scoped prompt + structured-output JSON Schema
src/orchestrator.py    dispatch / reconcile / loop  (the brain)
src/store.py           SQLite system-of-record
src/simulator.py       Deterministic offline Devin
scripts/scan_and_file.py   Event source: Bandit/pip-audit -> GitHub issues
dashboard/app.py       Streamlit observability dashboard
fixtures/findings.json Sample findings (offline + fallback)
```

---

## Extending in a real customer engagement (the "When")
- **Webhook trigger**: replace polling with a GitHub `issues`/`push` webhook (or
  ServiceNow/Jira/CodeQL/Snyk) hitting a small FastAPI receiver → same dispatch path.
- **Severity routing**: auto-merge low-risk fixes that pass CI above a confidence
  threshold; escalate the rest to a named reviewer.
- **CI gating**: block the comment-back until the PR's checks go green.
- **Multi-repo / fleet**: one config per repo; the dashboard already aggregates.
- **Devin telemetry**: enrich KPIs from Devin's own consumption/metrics API
  (`/v3/.../consumption/*`, `/metrics/prs`) for true cost-per-fix reporting.

---

_Devin opens PRs; humans merge. Nothing here self-merges._
