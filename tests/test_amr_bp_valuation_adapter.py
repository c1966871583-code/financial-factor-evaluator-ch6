"""Tests for explicit BP valuation-date evidence adaptation."""

from __future__ import annotations

import copy
import hashlib
import json

import pandas as pd
import pytest

from backend.amr.bp_valuation_adapter import (
    BPValuationAdapterErrorCode,
    BPValuationBindingError,
    adapt_bp_valuation_rows,
    bind_bp_valuation_to_path_b_records,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _valuation_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "evaluation_date": "2025-06-30",
                "provider_date": "2025-06-30",
                "code": "000001.XSHE",
                "factor_id": "BP",
                "market_cap": 200.0,
                "book_to_market_ratio_lf": 0.55,
                "provider": "RQData",
                "provider_endpoint": "rqdatac.get_factor",
                "provider_field": "book_to_market_ratio_lf",
                "source_record_reference": "isr-bp-1",
                "source_input_hash": _hash("bp-1"),
                "valuation_policy_version": "1.0",
            }
        ]
    )


def _path_b_records() -> list[dict]:
    return [
        {
            "evaluation_date": "2025-06-30",
            "code": "000001.XSHE",
            "factor_id": "ROE",
            "formula_inputs": {
                "parent_net_profit_ttm": 10.0,
                "average_parent_equity": 50.0,
            },
        },
        {
            "evaluation_date": "2025-06-30",
            "code": "000001.XSHE",
            "factor_id": "BP",
            "formula_inputs": {"parent_equity": 110.0, "market_cap": 200.0},
        },
    ]


def _codes(result) -> set[str]:
    return {item.code for item in result.issues}


def test_explicit_provider_date_is_adapted_to_market_cap_as_of():
    result = adapt_bp_valuation_rows(_valuation_frame())
    assert result.status == "READY"
    observation = result.get("2025-06-30", "000001.XSHE")
    assert observation.market_cap_as_of == observation.evaluation_date
    assert observation.market_cap == 200.0
    assert observation.provider == "RQData"
    json.dumps(result.to_dict(), sort_keys=True, allow_nan=False)


def test_row_order_does_not_change_content_hash():
    frame = pd.concat(
        [
            _valuation_frame(),
            _valuation_frame().assign(
                code="000002.XSHE",
                source_record_reference="isr-bp-2",
                source_input_hash=_hash("bp-2"),
            ),
        ],
        ignore_index=True,
    )
    forward = adapt_bp_valuation_rows(frame)
    reverse = adapt_bp_valuation_rows(frame.iloc[::-1].reset_index(drop=True))
    assert forward.content_hash == reverse.content_hash
    assert forward.to_dict() == reverse.to_dict()


def test_date_mismatch_fails_closed_without_observations():
    frame = _valuation_frame().assign(provider_date="2025-06-27")
    result = adapt_bp_valuation_rows(frame)
    assert result.status == "BLOCKED"
    assert result.observations == ()
    assert "VALUATION_DATE_MISMATCH" in _codes(result)


@pytest.mark.parametrize("market_cap", [None, 0.0, -1.0, float("nan")])
def test_invalid_market_cap_fails_closed(market_cap):
    frame = _valuation_frame()
    frame.loc[0, "market_cap"] = market_cap
    result = adapt_bp_valuation_rows(frame)
    assert result.status == "BLOCKED"
    assert "INVALID_MARKET_CAP" in _codes(result)


def test_duplicate_key_fails_closed():
    frame = pd.concat([_valuation_frame(), _valuation_frame()], ignore_index=True)
    result = adapt_bp_valuation_rows(frame)
    assert result.status == "BLOCKED"
    assert "DUPLICATE_VALUATION_KEY" in _codes(result)


def test_binding_adds_explicit_evidence_without_mutating_inputs():
    valuation = adapt_bp_valuation_rows(_valuation_frame())
    records = _path_b_records()
    before = copy.deepcopy(records)
    bound = bind_bp_valuation_to_path_b_records(records, valuation)
    assert records == before
    bp = next(item for item in bound if item["factor_id"] == "BP")
    roe = next(item for item in bound if item["factor_id"] == "ROE")
    assert bp["market_cap_as_of"] == "2025-06-30"
    assert bp["valuation_source_reference"] == "isr-bp-1"
    assert bp["valuation_input_hash"] == _hash("bp-1")
    assert bp["valuation_policy_version"] == "1.0"
    assert len(bp["valuation_adapter_content_hash"]) == 64
    assert "market_cap_as_of" not in roe


def test_binding_rejects_market_cap_difference():
    valuation = adapt_bp_valuation_rows(_valuation_frame())
    records = _path_b_records()
    records[1]["formula_inputs"]["market_cap"] = 201.0
    with pytest.raises(BPValuationBindingError) as exc_info:
        bind_bp_valuation_to_path_b_records(records, valuation)
    assert (
        exc_info.value.code == BPValuationAdapterErrorCode.BP_MARKET_CAP_MISMATCH.value
    )


def test_binding_requires_exact_bp_coverage():
    valuation = adapt_bp_valuation_rows(_valuation_frame())
    with pytest.raises(BPValuationBindingError) as exc_info:
        bind_bp_valuation_to_path_b_records([], valuation)
    assert exc_info.value.code == BPValuationAdapterErrorCode.BP_COVERAGE_MISMATCH.value
