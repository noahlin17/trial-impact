"""Open Targets genetics feature ingestion.

The score returned here is from the **current Open Targets release**, not a
historical as-of snapshot. It is therefore only an approximation of a
point-in-time genetics feature and must be flagged as such by downstream
corpus-building code; this module does not hide that limitation. The function
returns ``None`` when the pair is absent rather than inventing a score.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen

API_URL = "https://api.platform.opentargets.org/api/v4/graphql"
Fetcher = Callable[..., Any]

QUERY = """
query GeneticAssociation($diseaseId: String!, $targetId: String!) {
  disease(efoId: $diseaseId) {
    associatedTargets(Bs: [$targetId], orderByScore: "score", page: {index: 0, size: 1}) {
      rows { score target { id } }
    }
  }
}
"""


def _default_fetcher(
    url: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    request = Request(url, data=data, headers=headers or {}, method="POST")
    with urlopen(request, timeout=30) as response:
        return response.read()


def _json_response(
    url: str,
    fetcher: Fetcher | None = None,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    raw = (fetcher or _default_fetcher)(url, data=data, headers=headers)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Open Targets response must be a JSON object")
    return parsed


def fetch_genetic_score(
    target_id: str,
    disease_id: str,
    *,
    fetcher: Fetcher | None = None,
) -> float | None:
    """Return the current-release association score for an ID pair.

    ``target_id`` is an Ensembl gene ID and ``disease_id`` is an EFO/MONDO ID.
    Both identifiers are required by the Open Targets GraphQL API. The result
    is suitable for ``TrialRecord.features["ot_genetic_score"]``.
    """
    if not target_id or not disease_id:
        return None
    body = json.dumps({
        "query": QUERY,
        "variables": {"targetId": target_id, "diseaseId": disease_id},
    }).encode("utf-8")
    payload = _json_response(
        API_URL,
        fetcher,
        data=body,
        headers={"content-type": "application/json", "accept": "application/json"},
    )
    data = payload.get("data", {})
    disease = data.get("disease") if isinstance(data, dict) else None
    associated = disease.get("associatedTargets") if isinstance(disease, dict) else None
    rows = associated.get("rows", []) if isinstance(associated, dict) else []
    if not isinstance(rows, list) or not rows:
        return None
    score = rows[0].get("score") if isinstance(rows[0], dict) else None
    if not isinstance(score, int | float):
        return None
    return min(max(float(score), 0.0), 1.0)
