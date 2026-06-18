"""Observability dashboard — mission control for a fleet of autonomous agents.

Answers the VP's question: "how would I know this is working?" Every metric is
honest about its source:
  - time-to-PR  : measured from the orchestrator's own wall-clock (dispatch -> PR)
  - success     : PR opened AND tests independently green (not "a PR exists")
  - ACU / $     : per-session ACU is read from the Devin consumption console
                  (the session API on this tier doesn't expose it) and recorded
                  in fixtures/real_runs.json — never guessed.

You would never build this for an IDE copilot — a human is already watching. The
fact that the fleet NEEDS mission control is the proof it runs unattended.

Run:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from src import store  # noqa: E402

st.set_page_config(page_title="Devin Remediation Pipeline", page_icon="🤖", layout="wide")
st.markdown("<meta http-equiv='refresh' content='10'>", unsafe_allow_html=True)

st.title("🤖 Autonomous Remediation Pipeline — Apache Superset")
st.caption(
    f"repo `{config.GITHUB_REPO or '(set GITHUB_REPO)'}` · label `{config.TARGET_LABEL}` · "
    f"{'SIMULATE' if config.DEVIN_SIMULATE else 'LIVE'} mode · "
    f"auto-merge **{'ON' if config.AUTOMERGE_ENABLED else 'OFF (gate routes to human)'}** · refreshes 10s"
)

store.init()
runs = store.all_runs()
if not runs:
    st.info("No runs yet. Seed the demo (`python -m scripts.seed_demo`) or run the orchestrator.")
    st.stop()

df = pd.DataFrame(runs)


def col(name, default=None):
    return df[name] if name in df else pd.Series([default] * len(df))


is_devin = col("handler") == "devin"
is_codemod = col("handler") == "codemod"
has_pr = col("pr_url").notna()
green = col("tests_passing") == 1
reviewed = col("reviewer_verdict").notna()

total = len(df)
devin_n = int(is_devin.sum())
codemod_n = int(is_codemod.sum())
prs = int(has_pr.sum())
success = int((has_pr & green).sum())
success_rate = round(100 * success / devin_n) if devin_n else 0

# time-to-PR (agent cycle time) from REAL wall-clock dispatch -> PR.
cyc = df.dropna(subset=["dispatch_ts", "pr_ts"]) if {"dispatch_ts", "pr_ts"} <= set(df.columns) else df.iloc[0:0]
ttp = f"{((cyc['pr_ts'] - cyc['dispatch_ts']) / 60).mean():.0f} min" if not cyc.empty else "—"

acu_total = float(col("acu_used").fillna(0).sum())
usd_total = acu_total * config.ACU_USD_RATE
usd_per_fix = (usd_total / prs) if prs else 0.0

# ── KPI tiles ───────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Issues handled", total, help=f"{devin_n} by Devin · {codemod_n} by codemod ($0)")
c2.metric("Devin PRs", prs)
c3.metric("Success (PR + green tests)", f"{success_rate}%", help="PR opened AND tests independently green")
c4.metric("Time-to-PR", ttp, help="agent cycle time: dispatch → PR (real wall-clock)")
c5.metric("Reviewer-audited", int(reviewed.sum()), help="PRs a second Devin independently reviewed")
c6.metric("Cost / fix", f"${usd_per_fix:,.0f}", help=f"{acu_total:.0f} ACU × ${config.ACU_USD_RATE}/ACU (from Devin console)")

# ── ROI strip (clearly illustrative) ──────────────────────────────────────────────
hours_saved = devin_n * 4  # ~half a day of senior-eng triage per judgment fix
baseline_usd = hours_saved * config.ENG_HOUR_USD
st.caption(
    f"💡 **ROI (illustrative):** {devin_n} judgment fixes ≈ {hours_saved} senior-eng hours "
    f"(~${baseline_usd:,.0f} at ${config.ENG_HOUR_USD}/hr) of toil, delivered for ~${usd_total:,.0f} in ACU. "
    f"Trivial lint findings were routed to a codemod for $0 — Devin is reserved for judgment work."
)

st.divider()
left, right = st.columns(2)
with left:
    st.subheader("Routing — who handled what")
    st.bar_chart(col("handler").fillna("?").value_counts())
with right:
    st.subheader("Merge gate decisions")
    st.bar_chart(col("automerge_decision").fillna("pending").value_counts())

st.divider()
st.subheader("Remediation runs")

_STATUS = {"working": "🟡", "dispatching": "🟡", "finished": "🟢", "codemod_done": "⚡",
           "blocked": "🟠", "error": "🔴", "expired": "⚫"}
_GATE = {"merged": "✅ auto-merged", "held_for_human": "🛑 held for human",
         "disabled": "🛑 human (gate off)", "codemod": "⚡ codemod $0"}


def fmt(r):
    return {
        "Issue": f"#{r['issue_number']}",
        "Title": (r.get("issue_title") or "")[:52],
        "Handler": r.get("handler") or "",
        "Type": r.get("finding_type") or "",
        "Status": f"{_STATUS.get(r.get('status'), '⚪')} {r.get('status', '')}",
        "Tests": {1: "✅", 0: "❌"}.get(r.get("tests_passing"), "—"),
        "Reviewer": r.get("reviewer_verdict") or "—",
        "Gate": _GATE.get(r.get("automerge_decision"), r.get("automerge_decision") or "—"),
        "ACU": r.get("acu_used") if r.get("acu_used") is not None else "—",
        "Devin": r.get("devin_url") or "",
        "PR": r.get("pr_url") or "",
    }


st.dataframe(
    pd.DataFrame([fmt(r) for r in runs]),
    use_container_width=True, hide_index=True,
    column_config={
        "Devin": st.column_config.LinkColumn("Devin", display_text="open ↗"),
        "PR": st.column_config.LinkColumn("PR", display_text="open ↗"),
    },
)
st.caption(f"Updated {time.strftime('%H:%M:%S')} · DB {config.DB_PATH} · "
           "ACU/$ sourced from Devin consumption console (fixtures/real_runs.json), not estimated.")
