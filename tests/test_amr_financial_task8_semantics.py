from __future__ import annotations

import json
from dataclasses import replace

import pytest

from backend.amr.financial_task8_semantics import (
    get_financial_task8_value_semantics,
    serialize_financial_task8_value_semantics,
    validate_financial_task8_value_semantics,
)


def test_confirmed_semantics_are_exactly_frozen():
    semantics = get_financial_task8_value_semantics()
    assert semantics.raw_value_field == "raw_pit_factor_value"
    assert semantics.evaluation_value_field == "evaluation_factor_value"
    assert semantics.neutralized_value_status == "not_available_not_substitutable"
    assert semantics.financial_frequency == "quarterly"
    assert semantics.evaluation_contexts == ("M:20D",)
    assert semantics.sample_key == ("evaluation_date", "code", "factor_id")
    assert semantics.common_sample_period_count == 18
    assert semantics.common_sample_row_count_per_combination == 900
    assert semantics.missing_value_policy == "no_zero_fill_record_isolated_or_fail_closed"
    assert semantics.stale_value_policy == "effective_date_lte_evaluation_date_no_freshness_claim"
    assert semantics.direction_policy == "original_direction_only_no_posthoc_flip"


@pytest.mark.parametrize(
    "field,value",
    [
        ("neutralized_value_status", "synthetic_residual"),
        ("evaluation_contexts", ("M:5D",)),
        ("common_sample_row_count_per_combination", 0),
        ("direction_policy", "best_direction_after_evaluation"),
    ],
)
def test_semantic_drift_fails_closed(field, value):
    changed = replace(get_financial_task8_value_semantics(), **{field: value})
    with pytest.raises(ValueError, match="confirmed policy"):
        validate_financial_task8_value_semantics(changed)


def test_serialization_is_deterministic_and_carries_a_content_hash():
    first = serialize_financial_task8_value_semantics()
    second = serialize_financial_task8_value_semantics()
    payload = json.loads(first)
    assert first == second
    assert len(payload["content_hash"]) == 64
    assert payload["production_status"] == "not production ready"
    assert "P05CandidateHandoffPackage" not in first
