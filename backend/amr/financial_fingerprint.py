"""Cross-platform canonical values for frozen financial fingerprints.

The v2 contract deliberately separates hashing representation from research
values.  It prevents libm/BLAS last-bit differences and pandas/numpy scalar
types from changing an otherwise identical fingerprint.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

FINANCIAL_FINGERPRINT_CONTRACT_VERSION = "FIN-FINGERPRINT-v2.0"
FINANCIAL_FINGERPRINT_FLOAT_DECIMALS = 12


def canonicalize_financial_fingerprint(
    value: Any,
    *,
    float_decimals: int = FINANCIAL_FINGERPRINT_FLOAT_DECIMALS,
) -> Any:
    """Return a stable JSON-compatible representation under the v2 contract."""
    if not isinstance(float_decimals, int) or not 0 <= float_decimals <= 15:
        raise ValueError("float_decimals must be an integer from 0 through 15")
    if isinstance(value, Mapping):
        return {
            str(key): canonicalize_financial_fingerprint(
                item, float_decimals=float_decimals
            )
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [
            canonicalize_financial_fingerprint(
                item, float_decimals=float_decimals
            )
            for item in value
        ]
    if isinstance(value, Enum):
        return canonicalize_financial_fingerprint(
            value.value, float_decimals=float_decimals
        )
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number):
            return None
        if math.isinf(number):
            return "Infinity" if number > 0 else "-Infinity"
        rounded = round(number, float_decimals)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat(timespec="microseconds")
        return value.astimezone(UTC).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    if isinstance(value, np.generic):
        return canonicalize_financial_fingerprint(
            value.item(), float_decimals=float_decimals
        )
    raise TypeError(
        f"unsupported financial fingerprint type: {type(value).__name__}"
    )
