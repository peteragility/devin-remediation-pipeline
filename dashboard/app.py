"""Observability dashboard — answers the VP's question:
"If I were an engineering leader, how would I know this is working?"

Reads the SQLite system-of-record (read-only) and renders live KPIs:
throughput, success rate, mean-time-to-remediation (MTTR), ACU spend, and a
per-issue run table with links to the live Devin session and the resulting PR.

Run:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# Make project root importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from src import store  # noqa: E402

st.set_page_config(page_title="Devin Remediation Pipeline", page_icon="🤖", layout="wide")

# Auto-refresh every 10s so the Loom shows live movement.
st.markdown(
    "<meta http-equiv='refresh' content='10'>", unsafe_allow_html=True
)

st.title("🤖 Autonomous Remediation Pipeline — Apache Superset")
st.caption(
    f"Repo `{config.GITHUB_REPO or '(set GITHUB_REPO)'}`  ·  label `{config.TARGET_LABEL}`  ·  "
    f"{'SIMULATE' if config.DEVIN_SIMULATE else 'LIVE'} mode  ·  refreshes every 10s"
)

store.init()
runs = store.all_runs()

if not runs:
    st.info("No runs yet. File issues (`scripts.scan_and_file`) and start the orchestrator.")
    st.stop()

df = pd.DataFrame(runs)

# ── KPIs ───────────────────────────────────────────────────────────────────────
terminal = config.TERMINAL_STATES
total = len(df)
active = int((~df["status"].isin(terminal) & (df["status"] != "error")).sum())
with_pr = int(df["pr_url"].notna().sum())
finished = int((df["status"] == "finished").sum())
errors = int((df["status"] == "error").sum())
success_rate = round(100 * with_pr / total) if total else 0

# MTTR over runs that produced a PR (created_at -> updated_at).
done = df[df["pr_url"].notna()].copy()
mttr = "—"
if not done.empty:
    mins = (done["updated_at"] - done["created_at"]) / 60.0
    mttr = f"{mins.mean():.1f} min"

acu_total = float(df["acu_used"].fillna(0).sum())

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total issues", total)
c2.metric("In flight", active)
c3.metric("PRs opened", with_pr)
c4.metric("Success rate", f"{success_rate}%")
c5.metric("MTTR", mttr)
c6.metric("ACU spent", f"{acu_total:.1f}")

st.divider()

# ── breakdowns ──────────────────────────────────────────────────────────────────
left, right = st.columns([1, 1])
with left:
    st.subheader("By status")
    st.bar_chart(df["status"].value_counts())
with right:
    st.subheader("By finding type")
    if "finding_type" in df:
        st.bar_chart(df["finding_type"].fillna("unknown").value_counts())

st.divider()

# ── run table ───────────────────────────────────────────────────────────────────
st.subheader("Remediation runs")

_STATUS_ICON = {
    "working": "🟡",
    "finished": "🟢",
    "blocked": "🟠",
    "error": "🔴",
    "expired": "⚫",
}


def _fmt(row):
    so = {}
    try:
        so = json.loads(row.get("structured_output") or "{}")
    except json.JSONDecodeError:
        pass
    return {
        "Issue": f"#{row['issue_number']}",
        "Title": (row.get("issue_title") or "")[:60],
        "Type": row.get("finding_type") or "",
        "Status": f"{_STATUS_ICON.get(row['status'], '⚪')} {row['status']}",
        "Tests": {1: "✅", 0: "❌"}.get(row.get("tests_passing"), "—"),
        "Conf.": row.get("confidence") or so.get("confidence") or "—",
        "ACU": row.get("acu_used") if row.get("acu_used") is not None else "—",
        "Devin": row.get("devin_url") or "",
        "PR": row.get("pr_url") or "",
    }


table = pd.DataFrame([_fmt(r) for r in runs])
st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Devin": st.column_config.LinkColumn("Devin session", display_text="open ↗"),
        "PR": st.column_config.LinkColumn("Pull request", display_text="open ↗"),
    },
)

st.caption(f"Last updated {time.strftime('%H:%M:%S')}  ·  DB: {config.DB_PATH}")
