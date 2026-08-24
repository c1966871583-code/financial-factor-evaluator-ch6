from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from backend.amr.financial_fingerprint import (
    FINANCIAL_FINGERPRINT_CONTRACT_VERSION,
    canonicalize_financial_fingerprint,
)


def test_v2_normalizes_python_numpy_and_pandas_scalars():
    assert FINANCIAL_FINGERPRINT_CONTRACT_VERSION == "FIN-FINGERPRINT-v2.0"
    assert canonicalize_financial_fingerprint(np.int64(3)) == 3
    assert canonicalize_financial_fingerprint(np.float64(1.25)) == 1.25
    assert canonicalize_financial_fingerprint(np.bool_(True)) is True
    assert canonicalize_financial_fingerprint(pd.NA) is None


def test_v2_floats_have_fixed_precision_and_special_value_rules():
    assert canonicalize_financial_fingerprint(1.12345678901249) == 1.123456789012
    assert canonicalize_financial_fingerprint(-0.0) == 0.0
    assert canonicalize_financial_fingerprint(float("nan")) is None
    assert canonicalize_financial_fingerprint(float("inf")) == "Infinity"
    assert canonicalize_financial_fingerprint(float("-inf")) == "-Infinity"


def test_v2_allows_a_versioned_consumer_precision():
    value = {"nested": [1.123456789049]}
    assert canonicalize_financial_fingerprint(
        value, float_decimals=10
    ) == {"nested": [1.123456789]}
    with pytest.raises(ValueError):
        canonicalize_financial_fingerprint(value, float_decimals=16)


def test_v2_dates_and_mapping_order_are_canonical():
    utc = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    assert canonicalize_financial_fingerprint(utc) == "2024-01-01T00:00:00.000000Z"
    first = canonicalize_financial_fingerprint({"b": 2, "a": 1})
    second = canonicalize_financial_fingerprint({"a": 1, "b": 2})
    assert first == second == {"a": 1, "b": 2}
