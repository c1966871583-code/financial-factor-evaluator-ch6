from __future__ import annotations

from dataclasses import replace

import pytest

from backend.amr.financial_task8_numeric_extraction import (
    extract_financial_task8_approved_numeric_datasets,
    serialize_financial_task8_numeric_extraction,
)
from tests.fixtures.synthetic_financial_task8_numeric_cases import make_batches


def test_extracts_all_approved_candidates_deterministically_without_evaluation():
    first = extract_financial_task8_approved_numeric_datasets(make_batches())
    second = extract_financial_task8_approved_numeric_datasets(make_batches())
    assert [item.candidate_id for item in first.extractions] == ["VQ", "QG", "CASHQ"]
    assert all(item.row_count == 900 and item.period_count == 18 for item in first.extractions)
    assert first.production_status == "not production ready"
    assert serialize_financial_task8_numeric_extraction(first) == serialize_financial_task8_numeric_extraction(second)


@pytest.mark.parametrize("mutation,match", [
    ("definition", "definition hash drift"), ("sample", "sample fingerprint drift"),
    ("neutralized", "forbidden numeric-extraction columns"), ("pit", "PIT violation"),
    ("row_count", "requires exactly"),
])
def test_drift_or_unapproved_fields_fail_closed(mutation, match):
    batches = list(make_batches())
    target = batches[0]
    rows = target.get_rows()
    if mutation == "definition":
        batches[0] = replace(target, candidate_definition_hash="0" * 64)
    elif mutation == "sample":
        batches[0] = replace(target, declared_sample_fingerprint="0" * 64)
    elif mutation == "neutralized":
        rows["neutralized_value"] = 1.0
        batches[0] = replace(target, _rows=rows)
    elif mutation == "pit":
        rows.loc[0, "effective_date"] = "2099-01-01"
        batches[0] = replace(target, _rows=rows)
    else:
        batches[0] = replace(target, _rows=rows.iloc[:-1])
    with pytest.raises(ValueError, match=match):
        extract_financial_task8_approved_numeric_datasets(tuple(batches))


def test_runtime_input_mutation_cannot_change_extracted_rows():
    batches = make_batches()
    result = extract_financial_task8_approved_numeric_datasets(batches)
    rows = batches[0].get_rows()
    rows.loc[0, "raw_pit_factor_value"] = 999.0
    assert result.extractions[0].rows[0]["raw_pit_factor_value"] != 999.0
