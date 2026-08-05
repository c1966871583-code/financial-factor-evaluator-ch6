from __future__ import annotations

import json
from dataclasses import replace

import pytest

from backend.amr.financial_task8_handoff_schema import (
    P05_FORBIDDEN_SELECTION_FIELDS,
    P05_HANDOFF_PACKAGE_FIELDS,
    P05_HANDOFF_SCHEMA_VERSION,
    get_p05_candidate_handoff_schema,
    serialize_p05_candidate_handoff_schema,
)


def test_schema_freezes_required_p05_fields_without_a_package_instance():
    schema = get_p05_candidate_handoff_schema()
    assert schema.schema_version == P05_HANDOFF_SCHEMA_VERSION
    assert schema.fields == P05_HANDOFF_PACKAGE_FIELDS
    assert schema.production_status == "not production ready"
    assert set(P05_FORBIDDEN_SELECTION_FIELDS).isdisjoint(schema.fields)
    assert "candidate_id" in schema.required_nonempty_fields
    assert len(schema.semantic_policy_content_hash) == 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "P05CandidateHandoffPackage-v2.0"),
        ("fields", P05_HANDOFF_PACKAGE_FIELDS + ("selected_candidate",)),
        ("production_status", "production ready"),
    ],
)
def test_schema_drift_fails_closed(field, value):
    changed = replace(get_p05_candidate_handoff_schema(), **{field: value})
    with pytest.raises(ValueError, match="frozen contract"):
        serialize_p05_candidate_handoff_schema(changed)


def test_schema_serialization_is_deterministic_and_content_addressed():
    first = serialize_p05_candidate_handoff_schema()
    second = serialize_p05_candidate_handoff_schema()
    payload = json.loads(first)
    assert first == second
    assert len(payload["content_hash"]) == 64
    assert "row_count" in payload["fields"]
    assert "P05CandidateHandoffPackage" not in payload.get("candidate_id", "")
