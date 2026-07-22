"""ClinicalTrials.gov API v2 feature and metadata ingestion.

This loader never derives an outcome from registry status, completion, or results
fields. Every mapped row has ``outcome="unknown"`` and an outcome source that
requires human adjudication. ``feature_as_of`` is conservatively set to the
registry posting date, so registry metadata cannot leak a later update into a
point-in-time feature row.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from ..schema import UNKNOWN, TrialRecord

API_URL = "https://clinicaltrials.gov/api/v2/studies"
Fetcher = Callable[..., Any]


def _parse_ct_date(value: str | None) -> date | None:
    """Parse CT.gov's YYYY, YYYY-MM, or YYYY-MM-DD date forms conservatively."""
    if not value:
        return None
    parts = value.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def _date_struct(module: dict[str, Any], *keys: str) -> date | None:
    for key in keys:
        raw = module.get(key)
        if isinstance(raw, dict) and raw.get("type") == "ACTUAL":
            parsed = _parse_ct_date(raw.get("date"))
            if parsed is not None:
                return parsed
    return None


def _names(interventions: Any, *, drug_only: bool) -> list[str]:
    if not isinstance(interventions, list):
        return []
    selected = [
        item.get("name", "").strip()
        for item in interventions
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item.get("name", "").strip()
        and (not drug_only or item.get("type") == "DRUG")
    ]
    return selected


def _explicit_target(protocol: dict[str, Any], interventions: Any) -> str:
    for module_name in ("armsInterventionsModule", "identificationModule"):
        module = protocol.get(module_name)
        if isinstance(module, dict):
            for key in ("target", "targetName", "targetSymbol"):
                value = module.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    if isinstance(interventions, list):
        for item in interventions:
            if not isinstance(item, dict):
                continue
            for key in ("target", "targetName", "targetSymbol"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def to_trial_record(study_json: dict[str, Any]) -> TrialRecord:
    """Map one CT.gov study object to a leakage-safe, unresolved trial record."""
    protocol = study_json.get("protocolSection", study_json)
    if not isinstance(protocol, dict):
        raise ValueError("ClinicalTrials.gov study must contain an object protocolSection")

    identification = protocol.get("identificationModule") or {}
    status = protocol.get("statusModule") or {}
    sponsor_module = protocol.get("sponsorCollaboratorsModule") or {}
    conditions_module = protocol.get("conditionsModule") or {}
    design_module = protocol.get("designModule") or {}
    interventions_module = protocol.get("armsInterventionsModule") or {}
    if not all(isinstance(value, dict) for value in (
        identification,
        status,
        sponsor_module,
        conditions_module,
        design_module,
        interventions_module,
    )):
        raise ValueError("ClinicalTrials.gov study modules must be objects")

    registered = _parse_ct_date(
        (status.get("studyFirstPostDateStruct") or {}).get("date")
    )
    if registered is None:
        registered = _parse_ct_date(status.get("studyFirstSubmitDate"))
    trial_id = str(identification.get("nctId") or "").strip()
    if not trial_id or registered is None:
        raise ValueError("ClinicalTrials.gov study requires nctId and registration date")

    interventions = interventions_module.get("interventions", [])
    drug_names = _names(interventions, drug_only=True)
    all_names = _names(interventions, drug_only=False)
    sponsor = sponsor_module.get("leadSponsor") or {}
    phases = design_module.get("phases") or []
    conditions = conditions_module.get("conditions") or []
    phase = ", ".join(str(item) for item in phases) if phases else "unknown"
    indication = "; ".join(str(item) for item in conditions) if conditions else ""

    return TrialRecord(
        trial_id=trial_id,
        sponsor=str(sponsor.get("name") or "") if isinstance(sponsor, dict) else "",
        phase=phase,
        indication=indication,
        drug="; ".join(drug_names or all_names),
        target=_explicit_target(protocol, interventions),
        registered_date=registered,
        feature_as_of=registered,
        outcome=UNKNOWN,
        outcome_source="ctgov-registry: outcome not adjudicated",
        readout_date=_date_struct(
            status,
            "resultsFirstPostDateStruct",
            "completionDateStruct",
            "primaryCompletionDateStruct",
        ),
    )


def _default_fetcher(
    url: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    with urlopen(url, data=data, timeout=30) as response:
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
        raise ValueError("ClinicalTrials.gov response must be a JSON object")
    return parsed


def fetch_trials(
    query: str = "",
    *,
    page_size: int = 100,
    max_pages: int | None = None,
    fetcher: Fetcher | None = None,
) -> list[TrialRecord]:
    """Fetch CT.gov studies and map them without creating outcome labels."""
    if page_size < 1:
        raise ValueError("page_size must be positive")
    records: list[TrialRecord] = []
    page_token: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"pageSize": page_size}
        if query:
            params["query.term"] = query
        if page_token:
            params["pageToken"] = page_token
        payload = _json_response(
            f"{API_URL}?{urlencode(params)}",
            fetcher,
            headers={"accept": "application/json"},
        )
        studies = payload.get("studies") or []
        records.extend(to_trial_record(study) for study in studies)
        pages += 1
        page_token = payload.get("nextPageToken")
        if not page_token or (max_pages is not None and pages >= max_pages):
            return records
