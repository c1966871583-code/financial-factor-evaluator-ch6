from copy import deepcopy

from backend.amr.financial_synthetic_snapshot import build_synthetic_snapshot
from tests.fixtures.synthetic_financial_authoritative_snapshot_bad_data_cases import bad_snapshot_cases


def test_every_frozen_bad_data_case_blocks_without_mutating_input():
    for case_id, (records, expected_code) in bad_snapshot_cases().items():
        before = deepcopy(records)
        first = build_synthetic_snapshot(records)
        second = build_synthetic_snapshot(records)
        assert first.status == "blocked", case_id
        assert first.rows == (), case_id
        assert expected_code in {issue.code for issue in first.issues}, case_id
        assert first.issues == second.issues, case_id
        assert records == before, case_id
