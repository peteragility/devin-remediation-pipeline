# Autonomous Remediation Pipeline — Devin as a governed primitive

> Event-driven automation that clears an engineering team's **security & dependency
> backlog** on Apache Superset. Each `devin-fix` issue is picked up by the
> orchestrator, a Devin **fixer** session adapts the code and runs tests until green
> and opens a PR, a second Devin **reviewer** independently audits it, and a **merge
> gate** decides auto-merge vs. human. Everything is observable on a live dashboard.

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
editor where a human drives the session. They now have headless modes, so "only
Devin can run unattended" is **not** a claim we make.

The defensible claim is **operational**: Devin is purpose-built to run agents as
**governed fleet infrastructure**, and this system exercises exactly that layer:

- **Event → session API** with **structured-output contracts** — the orchestrator
  reads machine state, never scrapes prose.
- **Devin reviews Devin** — the reviewer's verdict is a *structured artifact* that
  programmatically **gates the merge** (not "an agent left a comment").
- **Org Knowledge** attached to every session — conventions live once in Devin and
  the whole fleet inherits them unattended.
- **Native cost governance** — Devin is priced per **ACU** (consumption, not seats or
  tokens), and every session carries an enforced ACU cap.
- **Idempotent, crash-safe, concurrency-capped dispatch** — the plumbing you need
  when no human is watching.

> You would never build a mission-control dashboard for an IDE copilot — a human is
> already watching. The fact that this fleet *needs* one is the proof it runs unattended.

---

## The pipeline

| Stage | What happens | Code |
|---|---|---|
| **Dispatch** | The loop polls open `devin-fix` issues and starts one Devin fixer session each (idempotent, ACU-capped, **Knowledge attached**) | `src/orchestrator.py` |
| **Fix** | Devin adapts the code, runs tests until green, opens a PR | `src/prompts.py` |
| **Review** | A second Devin independently audits the PR → structured verdict | `prompts.build_review_prompt`, `REVIEW_SCHEMA` |
| **Gate** | Auto-merge **only if** reviewer-approved AND tests green AND small diff; else hold for a human. **OFF by default.** | `Orchestrator._evaluate_gate` |
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
make seed                            # load the REAL run facts (6 Devin fixes + reviews) into the dashboard
docker compose up --build            # orchestrator loop + dashboard (:8501)
```
Open **http://localhost:8501**. The loop polls every 10s; because the DB is seeded,
it won't re-dispatch finished work — it just serves the live dashboard.

> **Offline (no keys / no ACUs):** `DEVIN_SIMULATE=true make seed && DEVIN_SIMULATE=true streamlit run dashboard/app.py`.
> In simulate mode the pipeline never writes to real GitHub.

---

## Demo flow (what the 5-minute walkthrough shows)

Pre-run everything (above) so nothing is waited on live. Have these tabs open:
**dashboard** (:8501), the fork's **Issues**, **PR #10**, the **reviewer's review** on
PR #10, and one **Devin session**.

1. **The fleet, at a glance** — the dashboard: every issue maps to the Devin session
   that fixed it and the PR it produced; the two judgment cases were independently
   reviewed and the gate held them for a human.
   *"One event kicked this off; a fleet of autonomous Devins cleared the backlog while
   I watched this screen. You'd never need this dashboard for a copilot — a human is
   already watching. Needing mission-control is the proof it runs unattended."*

2. **The event + architecture** — the fork's Issues (the backlog) and the diagram. A
   scan files the findings; the loop polls every 10s and dispatches Devin.

3. **Hero: autonomous breaking-change fix (PR #10)** — the thin issue ("upgrade and
   fix breakage") next to Devin's PR: it *discovered* PyJWT 2.13's 32-byte-key
   breaking change, fixed every short secret across 5 files, wrote a regression test,
   and ran tests until green. Unattended. A version-bumper opens a red PR here; a
   copilot needs a human at the keyboard.

4. **Devin reviews Devin** — the reviewer session's **Request Changes** on PR #10: it
   independently re-ran 83 tests and found a 6th short secret the fixer missed, so the
   gate **held the PR for a human**. Agents check agents; only clean work merges.

5. **Cost & governance** — Devin is priced per **ACU** (consumption, ~15 min each;
   not seats/tokens), each session ACU-capped. Auto-merge is **OFF by default** — both
   judgment PRs (#10 rejected, #12 approved) were **held for a human**; branch
   protection is the real platform gate.

6. **Why Devin + close** — the differentiation is the operational layer (session API,
   structured-verdict gating, org Knowledge, ACU governance): a backlog now measured
   in PRs and (with ACU filled in) dollars per fix.

### Optional live trigger (no extra setup)
With `docker compose up` running, create a new issue labelled `devin-fix` on the fork
(`gh issue create … --label devin-fix`). The loop picks it up within ~10s and a new
Devin session appears on the dashboard. Show the dispatch — don't wait the ~40 min
for the fix to finish on camera.

---

## Observability — and how the metrics stay honest

| Metric | Definition | Source |
|---|---|---|
| Time-to-PR | dispatch → PR, real wall-clock | orchestrator timestamps in SQLite |
| Success | PR opened **AND** tests independently green | `tests_passing` |
| Independently reviewed | PRs a second Devin audited | reviewer verdict |
| Gate decision | auto-merged / held-for-human | `_evaluate_gate` |
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
| `AUTOMERGE_ENABLED` | Auto-merge approved + green + small-diff PRs (**default OFF** — gate holds for a human) |
| `ACU_USD_RATE` / `ENG_HOUR_USD` | Cost + ROI conversion for the dashboard |
| `DEVIN_MAX_ACU` | Enforced per-session ACU cap |
| `POLL_INTERVAL` / `MAX_CONCURRENCY` / `MAX_RUN_AGE_SECONDS` / `MAX_ATTEMPTS` | Fleet + robustness controls |

The **real** merge gate in production is **GitHub branch protection** (required CI +
required review) — enforced by the platform, independent of this orchestrator.

---

## Repo layout
```
src/orchestrator.py  dispatch → reconcile → review → gate (crash-safe, retrying)
src/devin_client.py  Devin API wrapper (+ Knowledge), simulate hook
src/github_client.py issues / comments / PR status / merge
src/prompts.py       fixer + reviewer prompts and structured-output schemas
src/store.py         SQLite system-of-record
src/simulator.py     deterministic offline Devin (fixer + reviewer)
scripts/setup_knowledge.py   create the org Knowledge entry
scripts/scan_and_file.py     scan (Bandit + pip-audit) → file issues
scripts/seed_demo.py         load REAL run facts for the dashboard
dashboard/app.py     observability dashboard
fixtures/real_runs.json      real session ids, PRs, reviewer verdicts, timestamps
docs/architecture.png        architecture diagram
```

## Extending in a real engagement
- **Triggers:** today the loop polls GitHub; a webhook (or Snyk/CodeQL/Jira/ServiceNow
  scan-complete event) hitting the same dispatch path makes it real-time.
- **Trust ramp:** turn on `AUTOMERGE_ENABLED` after a baseline of human-approved Devin
  PRs; widen what's eligible as confidence grows.
- **Scale:** one config per repo; the dashboard already aggregates cost-per-fix and
  cycle time for leadership.
