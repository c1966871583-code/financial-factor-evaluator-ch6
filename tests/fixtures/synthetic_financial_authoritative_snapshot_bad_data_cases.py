"""Frozen adversarial inputs for the synthetic PRE-01 preflight gate."""

from copy import deepcopy

from tests.fixtures.synthetic_financial_authoritative_snapshot_cases import valid_snapshot_rows


def bad_snapshot_cases():
    rows = valid_snapshot_rows()
    missing = deepcopy(rows[0]); del missing["upstream_run_id"]
    future = deepcopy(rows[0]); future["publish_date"] = "2024-06-01"
    duplicate = deepcopy(rows[0]); duplicate["source_record_id"] = "conflicting-revision-source"
    bad_mask = deepcopy(rows[1]); bad_mask["factor_sample_mask"] = False; bad_mask["inclusion_or_exclusion_reason"] = "included"
    broken_lineage = deepcopy(rows[1]); broken_lineage["row_lineage"] = {}
    return {
        "missing_run_reference": ([missing], "MISSING_REQUIRED_FIELD"),
        "future_disclosure": ([future], "PIT_DATE_ORDER_VIOLATION"),
        "conflicting_primary_key": ([rows[0], duplicate], "DUPLICATE_PRIMARY_KEY"),
        "mask_reason_conflict": ([bad_mask], "EXCLUSION_REASON_REQUIRED"),
        "broken_lineage": ([broken_lineage], "LINEAGE_REFERENCE_MISSING"),
    }
