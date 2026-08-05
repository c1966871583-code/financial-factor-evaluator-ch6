"""Approved synthetic-only numeric rows for FIN-HO-8-B2 tests."""

from __future__ import annotations

import hashlib

import pandas as pd

from backend.amr.financial_p3_combinations import get_fin24_combination_definitions
from backend.amr.financial_p3_info_gain_contract import build_financial_p3_info_gain_contract
from backend.amr.financial_task8_numeric_extraction import ApprovedNumericCandidateBatch
from tests.fixtures.synthetic_financial_p3_combination_cases import evaluation_dates


def make_batches() -> tuple[ApprovedNumericCandidateBatch, ...]:
    definitions = {item.combination_id: item for item in get_fin24_combination_definitions()}
    samples = {item.combo_id: item for item in build_financial_p3_info_gain_contract().common_sample_references}
    batches = []
    for ordinal, candidate_id in enumerate(("VQ", "QG", "CASHQ"), start=1):
        rows = []
        for date_index, evaluation_date in enumerate(evaluation_dates()):
            effective_date = (pd.Timestamp(evaluation_date) - pd.Timedelta(days=5)).date().isoformat()
            for security_index in range(50):
                raw = ordinal * 10.0 + date_index * 0.1 + security_index * 0.01
                rows.append({
                    "evaluation_date": evaluation_date, "code": f"S{security_index:03d}",
                    "factor_id": candidate_id, "raw_pit_factor_value": raw,
                    "evaluation_factor_value": raw / 10.0,
                    "effective_date": effective_date,
                    "source_record_id": f"frozen-{candidate_id}-{date_index}-{security_index}",
                    "source_content_hash": hashlib.sha256(f"{candidate_id}|{date_index}|{security_index}".encode()).hexdigest(),
                })
        batches.append(ApprovedNumericCandidateBatch(
            candidate_id=candidate_id, candidate_definition_hash=definitions[candidate_id].content_hash,
            declared_sample_fingerprint=samples[candidate_id].common_sample_fingerprint,
            _rows=pd.DataFrame.from_records(rows),
            provenance={"approved_dataset": "frozen_synthetic_common_sample", "synthetic_test_only": True},
        ))
    return tuple(batches)
