from __future__ import annotations

import copy
from typing import ClassVar

import pandas as pd

from backend.amr.financial_exposure_adapter import adapt_exposure_batch_v1


class ExposureBatchStub:
    schema_version = "ExposureBatch-v1"
    source = "platform-exposure-service"
    version = "exposure-data-2024-01"
    provenance: ClassVar[dict[str, str]] = {
        "source": source,
        "data_version": version,
        "industry_mapping_version": "citics-pit-v3",
        "snapshot_hash": "a" * 64,
    }

    def __init__(self, rows):
        self._frame = pd.DataFrame(rows)

    def get_frame(self):
        return self._frame.copy(deep=True)


def _rows():
    return [
        {
            "security_id": "000001.SZ",
            "start_date": "2020-01-01",
            "cancel_date": "2025-01-01",
            "industry_code": "BANK",
            "industry_type": "BANK",
            "total_market_cap": 250_000_000_000.0,
            "market_cap_date": "2024-01-31",
        },
        {
            "security_id": "000002.SZ",
            "start_date": "2020-01-01",
            "cancel_date": "2025-01-01",
            "industry_code": "REAL_ESTATE",
            "industry_type": "NON_FINANCIAL",
            "total_market_cap": 25_000_000_000.0,
            "market_cap_date": "2024-01-31",
        },
    ]


def test_consumes_public_contract_with_exact_pit_and_version_metadata():
    result = adapt_exposure_batch_v1(
        ExposureBatchStub(_rows()),
        evaluation_keys=(("2024-01-31", "000001.SZ"), ("2024-01-31", "000002.SZ")),
    )
    assert result.audit.gate_status == "ready"
    assert result.audit.matched_count == 2
    assert result.audit.future_fill_count == 0
    bank = result.lookup("2024-01-31", "000001.SZ")
    assert bank.industry_type == "BANK"
    assert bank.total_market_cap == 250_000_000_000.0
    assert bank.log_market_cap is not None
    assert bank.industry_mapping_version == "citics-pit-v3"
    assert bank.snapshot_hash == "a" * 64


def test_missing_same_date_market_cap_is_recorded_without_forward_fill():
    result = adapt_exposure_batch_v1(
        ExposureBatchStub(_rows()),
        evaluation_keys=(("2024-02-01", "000001.SZ"),),
    )
    record = result.lookup("2024-02-01", "000001.SZ")
    assert record.total_market_cap is None
    assert record.missing_reason == "NO_SAME_DATE_MARKET_CAP"
    assert result.audit.future_fill_count == 0


def test_overlapping_industry_intervals_fail_closed():
    rows = _rows()
    duplicate = copy.deepcopy(rows[0])
    duplicate["industry_code"] = "DUPLICATE"
    rows.append(duplicate)
    result = adapt_exposure_batch_v1(
        ExposureBatchStub(rows),
        evaluation_keys=(("2024-01-31", "000001.SZ"),),
    )
    assert result.audit.gate_status == "blocked"
    assert result.audit.duplicate_match_count == 1
    assert any("duplicate PIT exposure" in error for error in result.audit.errors)
