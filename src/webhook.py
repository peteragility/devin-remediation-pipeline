"""FastAPI receiver for the REAL-TIME event trigger.

A GitHub `issues` webhook (opened / labeled / reopened) fires an *instant* Devin
dispatch, instead of waiting for the next scheduled scan or poll. This is the
production-shaped trigger; the scheduled scan in scripts/scan_and_file.py is the
batch equivalent. Both funnel into the same Orchestrator.dispatch_one().

Security: the payload HMAC-SHA256 signature is verified whenever
GITHUB_WEBHOOK_SECRET is set (recommended). Reconciliation (polling sessions and
commenting PRs back) is still handled by the orchestrator loop service.

Run locally:
  uvicorn src.webhook:app --host 0.0.0.0 --port 8000 --reload
Expose for GitHub (dev):
  ngrok http 8000   # then point a repo webhook at  https://<ngrok>/webhook/github
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request

import config
from src import store
from src.orchestrator import Orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("webhook")

app = FastAPI(title="Devin Remediation Webhook")
_orch: Optional[Orchestrator] = None


def _orchestrator() -> Orchestrator:
    global _orch
    if _orch is None:
        _orch = Orchestrator()
    return _orch


def _verify_signature(body: bytes, signature: Optional[str]) -> None:
    secret = config.GITHUB_WEBHOOK_SECRET
    if not secret:
        log.warning("GITHUB_WEBHOOK_SECRET unset — skipping verification (dev only).")
        return
    if not signature:
        raise HTTPException(status_code=401, detail="missing X-Hub-Signature-256")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="bad signature")


@app.get("/health")
def health():
    store.init()
    return {
        "ok": True,
        "mode": "simulate" if config.DEVIN_SIMULATE else "live",
        "repo": config.GITHUB_REPO,
        "target_label": config.TARGET_LABEL,
    }


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None),
    x_github_event: Optional[str] = Header(default=None),
):
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)
    payload = await request.json()

    if x_github_event == "ping":
        return {"ok": True, "pong": True}
    if x_github_event != "issues":
        return {"ok": True, "ignored": f"event={x_github_event}"}

    action = payload.get("action")
    issue = payload.get("issue") or {}
    labels = [l.get("name") for l in issue.get("labels", [])]

    if action not in ("opened", "labeled", "reopened"):
        return {"ok": True, "ignored": f"action={action}"}
    if config.TARGET_LABEL not in labels:
        return {"ok": True, "ignored": "target-label-not-present"}

    dispatched = _orchestrator().dispatch_one(issue)
    log.info(
        "Webhook issue #%s action=%s -> dispatched=%s",
        issue.get("number"),
        action,
        dispatched,
    )
    return {"ok": True, "issue": issue.get("number"), "dispatched": dispatched}
