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
        knowledge_ids: Optional[list[str]] = None,
        playbook_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a Devin session. Returns at least {session_id, url, is_new_session}.

        knowledge_ids / playbook_id attach Devin-native org context so every
        session in the fleet inherits the same conventions unattended."""
        # Fall back to the org-wide defaults so the whole fleet shares context.
        if knowledge_ids is None and config.KNOWLEDGE_ID:
            knowledge_ids = [config.KNOWLEDGE_ID]
        if playbook_id is None and config.PLAYBOOK_ID:
            playbook_id = config.PLAYBOOK_ID

        if self._sim:
            return self._sim.create_session(prompt, tags=tags, title=title)

        body: dict[str, Any] = {
            "prompt": prompt,
            "idempotent": idempotent,
            "max_acu_limit": max_acu_limit,  # enforced per-session cost cap
        }
        if structured_output_schema:
            body["structured_output_schema"] = structured_output_schema
        if tags:
            body["tags"] = tags
        if title:
            body["title"] = title
        if knowledge_ids:
            body["knowledge_ids"] = knowledge_ids
        if playbook_id:
            body["playbook_id"] = playbook_id

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

    # Note: per-session ACU is intentionally NOT read here — the session API on
    # this tier does not expose it. Cost is sourced from the Devin consumption
    # console (see fixtures/real_runs.json) rather than guessed.

    # ── Knowledge (Devin-native org context) ────────────────────────────────────
    def create_knowledge(self, name: str, body: str, trigger_description: str) -> dict[str, Any]:
        """Create an org Knowledge entry. Attach its id to sessions so the whole
        fleet inherits the same conventions without re-prompting."""
        if self._sim:
            return {"id": "knowledge-sim-001", "name": name}
        r = self._session.post(
            f"{self.base_url}/knowledge",
            json={"name": name, "body": body, "trigger_description": trigger_description},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def list_knowledge(self) -> dict[str, Any]:
        if self._sim:
            return {"knowledge": [], "folders": []}
        r = self._session.get(f"{self.base_url}/knowledge", timeout=30)
        r.raise_for_status()
        return r.json()
