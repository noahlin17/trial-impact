"""Client for the Devin API.

Wraps the two endpoints this service needs:

* ``POST /v1/sessions``       — create a simulation session.
* ``GET  /v1/sessions/{id}``  — poll a session's status and extract its result.

Each simulation session is expected to end by printing a single line beginning
with ``SIM_RESULT_JSON:`` (see ``app/simulation.py``). The client scans the
session transcript for that marker, parses the JSON, and normalises the session
onto our five-state model (queued / running / completed / failed /
needs_attention) so the rest of the application never sees Devin's raw status
strings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import requests

from . import db
from .simulation import RESULT_MARKER

_TIMEOUT_SECONDS = 30


@dataclass
class CreatedSession:
    session_id: str
    url: str


@dataclass
class SessionStatus:
    """Normalised view of a polled session."""

    raw_status: str
    mapped_status: str
    sim_result: dict[str, Any] | None
    error_message: str | None


class DevinClient:
    def __init__(self, api_key: str, api_base: str = "https://api.devin.ai/v1") -> None:
        self.api_base = api_base.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    # --- Create ---------------------------------------------------------------

    def create_session(
        self, *, prompt: str, title: str, tags: list[str] | None = None
    ) -> CreatedSession:
        """Create a new Devin session and return its id + web URL."""
        payload: dict[str, Any] = {"prompt": prompt, "title": title}
        if tags:
            payload["tags"] = tags

        resp = self._session.post(
            f"{self.api_base}/sessions", json=payload, timeout=_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        data = resp.json()
        return CreatedSession(session_id=data["session_id"], url=data.get("url", ""))

    # --- Poll -----------------------------------------------------------------

    def get_session(self, session_id: str) -> SessionStatus:
        """Fetch a session and normalise it into a :class:`SessionStatus`."""
        resp = self._session.get(
            f"{self.api_base}/sessions/{session_id}", timeout=_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        data = resp.json()

        raw_status = (data.get("status_enum") or data.get("status") or "").lower()
        sim_result = extract_sim_result(data)
        mapped = _map_status(raw_status, sim_result)

        error_message = None
        if mapped == db.STATUS_FAILED:
            if sim_result and sim_result.get("error"):
                error_message = f"Simulation error: {sim_result['error']}"
            else:
                error_message = f"Devin session ended in status '{raw_status}'"

        return SessionStatus(
            raw_status=raw_status,
            mapped_status=mapped,
            sim_result=sim_result,
            error_message=error_message,
        )


# Marker the simulation prints before its JSON result.
_MARKER_RE = re.compile(re.escape(RESULT_MARKER) + r"\s*")

# Message ``type``/``role`` values that echo *our own prompt* back — they must be
# skipped, because the prompt embeds an EXAMPLE SIM_RESULT_JSON line that would
# otherwise be mistaken for Devin's actual output.
_PROMPT_ECHO_TYPES = {"initial_user_message", "user_message", "user"}


def extract_sim_result(data: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the ``SIM_RESULT_JSON`` object out of a session payload.

    Two subtleties, both learned from a real Devin run:

    * The transcript includes our *own prompt* (the ``initial_user_message``),
      which embeds an EXAMPLE ``SIM_RESULT_JSON`` line. We skip prompt-echo
      messages so that example is never mistaken for Devin's real result.
    * Devin may print interim/partial markers; we take the **last** decodable
      marker across its output — its final answer.
    """
    # A structured field is the happy path if the API ever provides one.
    structured = data.get("structured_output")
    if isinstance(structured, dict) and _looks_like_result(structured):
        return structured

    # Ordered candidate texts: Devin's messages (excluding prompt echoes) first,
    # then any top-level output fields.
    text_parts: list[str] = []
    messages = data.get("messages")
    if isinstance(messages, list):
        for m in messages:
            if isinstance(m, dict):
                if (m.get("type") or m.get("role")) in _PROMPT_ECHO_TYPES:
                    continue
                content = m.get("message") or m.get("content") or m.get("text")
                if isinstance(content, str):
                    text_parts.append(content)
            elif isinstance(m, str):
                text_parts.append(m)
    for key in ("output", "result", "summary"):
        val = data.get(key)
        if isinstance(val, str):
            text_parts.append(val)

    blob = "\n".join(text_parts)
    # Decode the JSON after each marker; keep the LAST one that parses.
    result: dict[str, Any] | None = None
    for match in _MARKER_RE.finditer(blob):
        obj = _decode_first_object(blob[match.end():])
        if obj is not None:
            result = obj
    return result


def _looks_like_result(obj: dict[str, Any]) -> bool:
    return "binding_affinity_kcal_mol" in obj or "error" in obj or "kd_nM" in obj


def _decode_first_object(text: str) -> dict[str, Any] | None:
    """Decode the first complete JSON object at the start of ``text``."""
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


# Devin statuses that mean "this session is finished and will do no more work".
# NOTE: "blocked" is intentionally NOT here — it means the session is paused
# awaiting human input and may still resume and complete.
_TERMINAL_STATUSES = {"finished", "expired", "exit"}
# Statuses that unambiguously indicate failure.
_ERROR_STATUSES = {"error", "expired"}


def _map_status(raw_status: str, sim_result: dict[str, Any] | None) -> str:
    """Map a Devin status onto our five-state model.

    The deliverable is a parseable simulation result *without* an ``error`` field.

    1. ``error`` / ``expired``            -> **failed**.
    2. Terminal WITH a good result        -> **completed**.
    3. Terminal WITHOUT a good result     -> **failed**.
    4. ``blocked`` WITH a good result     -> **completed**.
    5. ``blocked`` WITHOUT a good result  -> **needs_attention** (alive, awaiting
       input — NOT a failure, so /poll won't escalate prematurely).
    6. Everything else                    -> **running**.
    """
    has_result = bool(sim_result) and not sim_result.get("error")

    if raw_status in _ERROR_STATUSES:
        return db.STATUS_FAILED

    if raw_status in _TERMINAL_STATUSES:
        return db.STATUS_COMPLETED if has_result else db.STATUS_FAILED

    if raw_status == "blocked":
        return db.STATUS_COMPLETED if has_result else db.STATUS_NEEDS_ATTENTION

    return db.STATUS_RUNNING
