"""Offline tests for the Tier-1 feature and metadata ingesters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tier1.ingest.ctgov import to_trial_record
from tier1.ingest.opentargets import fetch_genetic_score
from tier1.schema import UNKNOWN
from tier1.splits import assert_no_leakage

FIXTURES = Path(__file__).parents[1] / "tier1" / "fixtures"


def _load(name: str) -> dict[str, Any]:
    with (FIXTURES / name).open() as fh:
        return json.load(fh)


def test_ctgov_mapper_preserves_metadata_and_never_labels_outcome() -> None:
    record = to_trial_record(_load("ctgov_study_sample.json"))

    assert record.trial_id == "NCT01991535"
    assert record.sponsor.startswith("Fundació Institut")
    assert record.phase == "NA"
    assert record.indication == (
        "Neuromuscular Disorders; Chest Wall Disorders; "
        "Obesity Hypoventilation Syndrome (OHS)"
    )
    assert record.drug == (
        "Spontaneous Ventilation Mode; Controlled Ventilation Mode; "
        "Simulator Ventilation Mode"
    )
    assert record.target == ""
    assert record.registered_date.isoformat() == "2013-11-25"
    assert record.feature_as_of == record.registered_date
    assert record.outcome == UNKNOWN
    assert record.outcome_source == "ctgov-registry: outcome not adjudicated"
    assert record.readout_date is None
    assert_no_leakage([record])


def test_ctgov_mapper_degrades_optional_fields_to_empty_values() -> None:
    record = to_trial_record({
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000000"},
            "statusModule": {"studyFirstSubmitDate": "2020"},
        }
    })

    assert record.sponsor == ""
    assert record.phase == "unknown"
    assert record.indication == ""
    assert record.drug == ""
    assert record.target == ""
    assert record.registered_date.isoformat() == "2020-01-01"
    assert record.outcome == UNKNOWN
    assert_no_leakage([record])


def test_opentargets_score_uses_canned_fixture_and_is_bounded() -> None:
    fixture = _load("opentargets_genetics_sample.json")

    def canned_fetcher(
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        assert "opentargets.org" in url
        assert data is not None
        assert headers is not None
        return fixture

    score = fetch_genetic_score(
        "ENSG00000146648",
        "MONDO_0007254",
        fetcher=canned_fetcher,
    )

    assert score == 0.7560462218494006
    assert 0.0 <= score <= 1.0


def test_opentargets_missing_pair_returns_none_without_network() -> None:
    def empty_fetcher(
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {"data": {"disease": None}}

    assert fetch_genetic_score("ENSG_missing", "MONDO_missing", fetcher=empty_fetcher) is None
    assert fetch_genetic_score("", "MONDO_missing", fetcher=empty_fetcher) is None
