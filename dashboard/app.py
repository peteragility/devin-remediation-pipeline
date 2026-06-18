"""Observability dashboard — mission control for a fleet of autonomous Devins.

Answers the VP's question "how would I know this is working?" Each issue maps to
the Devin session that fixed it and the PR it produced; the two judgment cases were
also independently reviewed by a second Devin and held by the merge gate.

Honest metrics:
  - time-to-PR : measured from the orchestrator's wall-clock (dispatch -> PR)
  - success    : PR opened AND tests independently green
  - cost       : Devin is priced per ACU (consumption), read from the Devin console

You would never build this for an IDE copilot — a human is already watching. The
fact the fleet NEEDS mission control is the proof it runs unattended.

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
store.init()

st.title("🤖 Autonomous Remediation Pipeline — Apache Superset")
st.caption(
    f"repo `{config.GITHUB_REPO or '(set GITHUB_REPO)'}` · label `{config.TARGET_LABEL}` · "
    f"{'SIMULATE' if config.DEVIN_SIMULATE else 'LIVE'} mode · "
    f"auto-merge **{'ON' if config.AUTOMERGE_ENABLED else 'OFF (every PR held for a human)'}** · "
    f"polls every {config.POLL_INTERVAL}s"
)

with st.expander("💰 How Devin is priced (and what 'cost' means here)"):
    st.markdown(
        f"""
Devin is **consumption-priced in ACUs (Agent Compute Units)** — roughly **~15 min of
agent work each** — **not per-seat and not per-token**. Each session here is capped at
**{config.DEVIN_MAX_ACU} ACU** (`max_acu_limit`), an enforced spend ceiling.

The cost tiles read **real ACU from the Devin consumption console** (the session API on
this tier doesn't expose it) and convert at **${config.ACU_USD_RATE}/ACU**. Where ACU
hasn't been entered yet they show `—` rather than a guessed number.
"""
    )

_STATUS = {"working": "🟡", "dispatching": "🟡", "finished": "🟢",
           "blocked": "🟠", "error": "🔴", "expired": "⚫"}
_GATE = {"merged": "✅ auto-merged", "held_for_human": "🛑 held for human",
         "disabled": "🛑 human (gate off)"}


@st.fragment(run_every=config.POLL_INTERVAL)
def live_view() -> None:
    runs = store.all_runs()
    if not runs:
        st.info("No runs yet. `python -m scripts.seed_demo` (real data) or run the orchestrator.")
        return
    df = pd.DataFrame(runs)

    def colv(name, default=None):
        return df[name] if name in df else pd.Series([default] * len(df))

    has_pr = colv("pr_url").notna()
    green = colv("tests_passing") == 1
    reviewed = colv("reviewer_verdict").notna()
    total = len(df)
    prs = int(has_pr.sum())
    success = int((has_pr & green).sum())
    success_rate = round(100 * success / total) if total else 0

    cyc = df.dropna(subset=["dispatch_ts", "pr_ts"]) if {"dispatch_ts", "pr_ts"} <= set(df.columns) else df.iloc[0:0]
    ttp = f"{((cyc['pr_ts'] - cyc['dispatch_ts']) / 60).mean():.0f} min" if not cyc.empty else "—"

    acu_total = float(colv("acu_used").fillna(0).sum())
    cost_per_fix = f"${acu_total * config.ACU_USD_RATE / prs:,.0f}" if (acu_total > 0 and prs) else "—"

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Issues fixed by Devin", total)
    c2.metric("PRs opened", prs)
    c3.metric("Independently reviewed", int(reviewed.sum()), help="PRs a second Devin audited")
    c4.metric("Success (PR + green tests)", f"{success_rate}%")
    c5.metric("Time-to-PR", ttp, help="agent cycle time: dispatch → PR (real wall-clock)")
    c6.metric("Cost / fix", cost_per_fix, help=f"ACU × ${config.ACU_USD_RATE}; cap {config.DEVIN_MAX_ACU} ACU/session")

    held = int((colv("automerge_decision").isin(["held_for_human", "disabled"])).sum())
    st.caption(
        f"💡 Every fix is an autonomous Devin session that opened a PR. The two judgment "
        f"cases were independently reviewed by a second Devin; the merge gate **held {held} "
        f"PR(s) for a human** (auto-merge is off by default — branch protection is the real gate)."
    )

    st.subheader("Issue → Devin session → PR")

    def fmt(r):
        return {
            "Issue": f"#{r['issue_number']}",
            "Title": (r.get("issue_title") or "")[:60],
            "Type": r.get("finding_type") or "",
            "Status": f"{_STATUS.get(r.get('status'), '⚪')} {r.get('status', '')}",
            "Tests": {1: "✅", 0: "❌"}.get(r.get("tests_passing"), "—"),
            "Reviewer": r.get("reviewer_verdict") or "—",
            "Gate": _GATE.get(r.get("automerge_decision"), r.get("automerge_decision") or "—"),
            "ACU": r.get("acu_used") if r.get("acu_used") is not None else "—",
            "Devin session": r.get("devin_url") or "",
            "PR": r.get("pr_url") or "",
        }

    st.dataframe(
        pd.DataFrame([fmt(r) for r in runs]),
        use_container_width=True, hide_index=True,
        column_config={
            "Devin session": st.column_config.LinkColumn("Devin session", display_text="open ↗"),
            "PR": st.column_config.LinkColumn("PR", display_text="open ↗"),
        },
    )
    st.caption(f"Updated {time.strftime('%H:%M:%S')} · live, refreshes every {config.POLL_INTERVAL}s")


live_view()
