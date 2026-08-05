from copy import deepcopy

from backend.amr.financial_synthetic_snapshot import build_synthetic_snapshot
from tests.fixtures.synthetic_financial_authoritative_snapshot_cases import valid_snapshot_rows


def test_ready_snapshot_contains_full_contract_and_deterministic_hashes():
    rows = valid_snapshot_rows()
    first = build_synthetic_snapshot(rows)
    second = build_synthetic_snapshot(list(reversed(rows)))
    assert first.status == "ready"
    assert first.dataset_hash == second.dataset_hash
    assert first.manifest_hash == second.manifest_hash
    assert first.rows[0]["row_value_hash"]
    assert first.rows[0]["row_lineage"]["source_table"] == "synthetic_disclosure"


def test_snapshot_blocks_pit_violation_duplicate_and_broken_lineage_without_dropping():
    rows = valid_snapshot_rows()
    pit_bad = deepcopy(rows[0]); pit_bad["publish_date"] = "2024-06-01"
    duplicate = deepcopy(rows[0]); duplicate["source_record_id"] = "synthetic-src-duplicate"
    lineage_bad = deepcopy(rows[1]); lineage_bad["row_lineage"] = {}
    result = build_synthetic_snapshot([pit_bad, rows[0], duplicate, lineage_bad])
    assert result.status == "blocked"
    assert result.rows == ()
    assert {issue.code for issue in result.issues} == {"PIT_DATE_ORDER_VIOLATION", "DUPLICATE_PRIMARY_KEY", "LINEAGE_REFERENCE_MISSING"}


def test_snapshot_rejects_non_synthetic_input_and_mask_without_exclusion_reason():
    rows = valid_snapshot_rows()
    rows[0]["synthetic_test_only"] = False
    rows[1]["factor_sample_mask"] = False
    rows[1]["inclusion_or_exclusion_reason"] = "included"
    result = build_synthetic_snapshot(rows)
    assert result.status == "blocked"
    assert {issue.code for issue in result.issues} == {"NON_SYNTHETIC_INPUT_NOT_AUTHORIZED", "EXCLUSION_REASON_REQUIRED"}
