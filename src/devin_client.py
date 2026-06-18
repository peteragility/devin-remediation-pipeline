"""Thin, well-typed wrapper around the Devin v1 API.

Endpoints used (https://docs.devin.ai/api-reference):
  POST   /v1/sessions                  -> create a session
  GET    /v1/sessions/{session_id}     -> poll status + structured_output + PR
  POST   /v1/sessions/{session_id}/messages  -> steer / unblock

A SIMULATE mode returns recorded fixtures so the whole pipeline can be
demoed without burning Agent Compute Units (ACUs).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests

import config

log = logging.getLogger("devin")


class DevinClient:
    def __init__(
        self,
        api_key: str = config.DEVIN_API_KEY,
        base_url: str = config.DEVIN_API_BASE,
        simulate: bool = config.DEVIN_SIMULATE,
    ):
        self.base_url = base_url.rstrip("/")
        self.simulate = simulate
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )
        if simulate:
            from src import simulator  # lazy import; only needed in sim mode

            self._sim = simulator.Simulator()
        else:
            self._sim = None
            if not api_key:
                raise RuntimeError(
                    "DEVIN_API_KEY is empty. Set it in .env or use DEVIN_SIMULATE=true."
                )

    # ── create ────────────────────────────────────────────────────────────────
    def create_session(
        self,
        prompt: str,
        *,
        structured_output_schema: Optional[dict] = None,
        tags: Optional[list[str]] = None,
        title: Optional[str] = None,
        max_acu_limit: int = config.DEVIN_MAX_ACU,
        idempotent: bool = True,
    ) -> dict[str, Any]:
        """Returns at least: {session_id, url, is_new_session}."""
        if self._sim:
            return self._sim.create_session(prompt, tags=tags, title=title)

        body: dict[str, Any] = {
            "prompt": prompt,
            "idempotent": idempotent,
            "max_acu_limit": max_acu_limit,
        }
        if structured_output_schema:
            body["structured_output_schema"] = structured_output_schema
        if tags:
            body["tags"] = tags
        if title:
            body["title"] = title

        r = self._session.post(f"{self.base_url}/sessions", json=body, timeout=60)
        r.raise_for_status()
        return r.json()

    # ── poll ──────────────────────────────────────────────────────────────────
    def get_session(self, session_id: str) -> dict[str, Any]:
        if self._sim:
            return self._sim.get_session(session_id)

        r = self._session.get(f"{self.base_url}/sessions/{session_id}", timeout=60)
        r.raise_for_status()
        return r.json()

    # ── steer ─────────────────────────────────────────────────────────────────
    def send_message(self, session_id: str, message: str) -> dict[str, Any]:
        if self._sim:
            return {"ok": True}

        r = self._session.post(
            f"{self.base_url}/sessions/{session_id}/messages",
            json={"message": message},
            timeout=60,
        )
        r.raise_for_status()
        return r.json() if r.text else {"ok": True}

    # ── convenience ─────────────────────────────────────────────────────────────
    @staticmethod
    def status_of(session: dict) -> str:
        """Normalise the status field across API shapes."""
        return (session.get("status_enum") or session.get("status") or "unknown").lower()

    @staticmethod
    def pr_url_of(session: dict) -> Optional[str]:
        pr = session.get("pull_request")
        if isinstance(pr, dict):
            return pr.get("url")
        return None

    @staticmethod
    def acu_of(session: dict) -> Optional[float]:
        """Best-effort ACU read; field naming varies, so check a few keys."""
        for k in ("acu_used", "acus_used", "acu", "compute_units_used"):
            if session.get(k) is not None:
                try:
                    return float(session[k])
                except (TypeError, ValueError):
                    pass
        return None
