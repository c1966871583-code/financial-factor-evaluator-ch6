"""Explicit adapter from frozen valuation rows to BP Path-B inputs.

The adapter does not query a provider and does not infer a market date.  It
normalizes the provider date as ``market_cap_as_of``, proves that it equals the
evaluation date, and binds the resulting evidence to prepared BP records.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

import pandas as pd

BP_VALUATION_ADAPTER_SCHEMA_VERSION = "BPValuationAdapter-v1.0"
BP_VALUATION_OBSERVATION_SCHEMA_VERSION = "BPValuationObservation-v1.0"
BP_VALUATION_ADAPTER_POLICY_VERSION = "BP-VALUATION-ADAPTER-POLICY-v1.0"


class BPValuationAdapterStatus(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class BPValuationAdapterErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    INVALID_FACTOR_ID = "INVALID_FACTOR_ID"
    INVALID_PROVIDER = "INVALID_PROVIDER"
    INVALID_DATE = "INVALID_DATE"
    VALUATION_DATE_MISMATCH = "VALUATION_DATE_MISMATCH"
    INVALID_MARKET_CAP = "INVALID_MARKET_CAP"
    DUPLICATE_VALUATION_KEY = "DUPLICATE_VALUATION_KEY"
    INVALID_SOURCE_REFERENCE = "INVALID_SOURCE_REFERENCE"
    INVALID_SOURCE_HASH = "INVALID_SOURCE_HASH"
    BP_COVERAGE_MISMATCH = "BP_COVERAGE_MISMATCH"
    BP_MARKET_CAP_MISMATCH = "BP_MARKET_CAP_MISMATCH"


class BPValuationBindingError(ValueError):
    def __init__(self, code: BPValuationAdapterErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code.value


@dataclass(frozen=True)
class BPValuationAdapterIssue:
    code: str
    message: str
    row_number: int | None = None
    record_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "row_number": self.row_number,
            "record_key": self.record_key,
        }


@dataclass(frozen=True)
class BPValuationObservation:
    evaluation_date: str
    market_cap_as_of: str
    code: str
    market_cap: float
    provider: str
    provider_endpoint: str
    provider_field: str
    source_record_reference: str
    source_input_hash: str
    valuation_policy_version: str
    book_to_market_ratio_lf: float | None
    schema_version: str = BP_VALUATION_OBSERVATION_SCHEMA_VERSION

    @property
    def key(self) -> tuple[str, str]:
        return (self.evaluation_date, self.code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evaluation_date": self.evaluation_date,
            "market_cap_as_of": self.market_cap_as_of,
            "code": self.code,
            "market_cap": self.market_cap,
            "provider": self.provider,
            "provider_endpoint": self.provider_endpoint,
            "provider_field": self.provider_field,
            "source_record_reference": self.source_record_reference,
            "source_input_hash": self.source_input_hash,
            "valuation_policy_version": self.valuation_policy_version,
            "book_to_market_ratio_lf": self.book_to_market_ratio_lf,
        }


@dataclass(frozen=True)
class BPValuationAdapterResult:
    observations: tuple[BPValuationObservation, ...]
    status: str
    issues: tuple[BPValuationAdapterIssue, ...]
    input_row_count: int
    content_hash: str
    schema_version: str = BP_VALUATION_ADAPTER_SCHEMA_VERSION
    policy_version: str = BP_VALUATION_ADAPTER_POLICY_VERSION

    def get(self, evaluation_date: Any, code: Any) -> BPValuationObservation:
        key = (_date_text(evaluation_date, "evaluation_date"), _text(code, "code"))
        matches = [item for item in self.observations if item.key == key]
        if len(matches) != 1:
            raise LookupError(f"expected one BP valuation observation for {key}")
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "status": self.status,
            "input_row_count": self.input_row_count,
            "content_hash": self.content_hash,
            "observations": [item.to_dict() for item in self.observations],
            "issues": [item.to_dict() for item in self.issues],
        }


_REQUIRED_COLUMNS = (
    "evaluation_date",
    "provider_date",
    "code",
    "factor_id",
    "market_cap",
    "provider",
    "provider_endpoint",
    "provider_field",
    "source_record_reference",
    "source_input_hash",
    "valuation_policy_version",
)


def adapt_bp_valuation_rows(
    frame: pd.DataFrame,
    *,
    expected_provider: str = "RQData",
    expected_provider_endpoint: str = "rqdatac.get_factor",
    expected_provider_field: str = "book_to_market_ratio_lf",
) -> BPValuationAdapterResult:
    """Normalize a frozen valuation frame without inferring missing dates."""

    if not isinstance(frame, pd.DataFrame):
        return _blocked(
            0,
            BPValuationAdapterIssue(
                BPValuationAdapterErrorCode.INVALID_INPUT.value,
                "frame must be a pandas DataFrame",
            ),
        )
    raw = frame.copy(deep=True)
    missing = [name for name in _REQUIRED_COLUMNS if name not in raw.columns]
    if missing:
        return _blocked(
            len(raw),
            BPValuationAdapterIssue(
                BPValuationAdapterErrorCode.REQUIRED_FIELD_MISSING.value,
                f"missing required columns: {','.join(missing)}",
            ),
        )

    observations: list[BPValuationObservation] = []
    issues: list[BPValuationAdapterIssue] = []
    for row_number, (_, row) in enumerate(raw.iterrows()):
        try:
            evaluation_date = _date_text(row["evaluation_date"], "evaluation_date")
            market_cap_as_of = _date_text(row["provider_date"], "provider_date")
            code = _text(row["code"], "code")
            factor_id = _text(row["factor_id"], "factor_id")
            provider = _text(row["provider"], "provider")
            endpoint = _text(row["provider_endpoint"], "provider_endpoint")
            provider_field = _text(row["provider_field"], "provider_field")
            source_reference = _text(
                row["source_record_reference"], "source_record_reference"
            )
            source_hash = _sha256_text(row["source_input_hash"], "source_input_hash")
            policy_version = _text(
                row["valuation_policy_version"], "valuation_policy_version"
            )
            market_cap = _positive_finite(row["market_cap"], "market_cap")
            provider_bp = _optional_finite(row.get("book_to_market_ratio_lf"))
        except ValueError as exc:
            issues.append(
                BPValuationAdapterIssue(
                    _code_for_value_error(str(exc)).value,
                    str(exc),
                    row_number,
                )
            )
            continue
        key = f"{evaluation_date}|{code}"
        if factor_id != "BP":
            issues.append(
                BPValuationAdapterIssue(
                    BPValuationAdapterErrorCode.INVALID_FACTOR_ID.value,
                    "factor_id must be BP",
                    row_number,
                    key,
                )
            )
        elif (
            provider != expected_provider
            or endpoint != expected_provider_endpoint
            or provider_field != expected_provider_field
        ):
            issues.append(
                BPValuationAdapterIssue(
                    BPValuationAdapterErrorCode.INVALID_PROVIDER.value,
                    "provider identity differs from the configured source",
                    row_number,
                    key,
                )
            )
        elif market_cap_as_of != evaluation_date:
            issues.append(
                BPValuationAdapterIssue(
                    BPValuationAdapterErrorCode.VALUATION_DATE_MISMATCH.value,
                    "provider_date must equal evaluation_date",
                    row_number,
                    key,
                )
            )
        else:
            observations.append(
                BPValuationObservation(
                    evaluation_date=evaluation_date,
                    market_cap_as_of=market_cap_as_of,
                    code=code,
                    market_cap=market_cap,
                    provider=provider,
                    provider_endpoint=endpoint,
                    provider_field=provider_field,
                    source_record_reference=source_reference,
                    source_input_hash=source_hash,
                    valuation_policy_version=policy_version,
                    book_to_market_ratio_lf=provider_bp,
                )
            )

    keys = [item.key for item in observations]
    duplicate_keys = sorted({key for key in keys if keys.count(key) > 1})
    for key in duplicate_keys:
        issues.append(
            BPValuationAdapterIssue(
                BPValuationAdapterErrorCode.DUPLICATE_VALUATION_KEY.value,
                "valuation key must be unique",
                record_key="|".join(key),
            )
        )
    if issues:
        return _blocked_many(len(raw), issues)

    ordered = tuple(sorted(observations, key=lambda item: item.key))
    return BPValuationAdapterResult(
        observations=ordered,
        status=BPValuationAdapterStatus.READY.value,
        issues=(),
        input_row_count=len(raw),
        content_hash=_content_hash(ordered),
    )


def bind_bp_valuation_to_path_b_records(
    records: Iterable[Mapping[str, Any]],
    valuation: BPValuationAdapterResult,
) -> list[dict[str, Any]]:
    """Bind explicit valuation evidence to prepared records, without mutation."""

    if not isinstance(valuation, BPValuationAdapterResult):
        raise TypeError("valuation must be BPValuationAdapterResult")
    if valuation.status != BPValuationAdapterStatus.READY.value:
        raise BPValuationBindingError(
            BPValuationAdapterErrorCode.INVALID_INPUT,
            "valuation adapter result is not ready",
        )
    try:
        copied = [copy.deepcopy(dict(record)) for record in records]
    except (TypeError, ValueError) as exc:
        raise TypeError("records must be an iterable of mappings") from exc

    bp_records = [record for record in copied if record.get("factor_id") == "BP"]
    try:
        bp_keys = {
            (
                _date_text(record.get("evaluation_date"), "evaluation_date"),
                _text(record.get("code"), "code"),
            )
            for record in bp_records
        }
    except ValueError as exc:
        raise BPValuationBindingError(
            BPValuationAdapterErrorCode.INVALID_INPUT, str(exc)
        ) from exc
    valuation_keys = {item.key for item in valuation.observations}
    if bp_keys != valuation_keys or len(bp_records) != len(bp_keys):
        raise BPValuationBindingError(
            BPValuationAdapterErrorCode.BP_COVERAGE_MISMATCH,
            "BP records and valuation observations must have exact one-to-one coverage",
        )

    by_key = {item.key: item for item in valuation.observations}
    for record in bp_records:
        key = (
            _date_text(record["evaluation_date"], "evaluation_date"),
            _text(record["code"], "code"),
        )
        observation = by_key[key]
        inputs = record.get("formula_inputs")
        if not isinstance(inputs, Mapping) or "market_cap" not in inputs:
            raise BPValuationBindingError(
                BPValuationAdapterErrorCode.REQUIRED_FIELD_MISSING,
                "BP formula_inputs.market_cap is required",
            )
        try:
            prepared_market_cap = _positive_finite(inputs["market_cap"], "market_cap")
        except ValueError as exc:
            raise BPValuationBindingError(
                BPValuationAdapterErrorCode.INVALID_MARKET_CAP, str(exc)
            ) from exc
        if prepared_market_cap != observation.market_cap:
            raise BPValuationBindingError(
                BPValuationAdapterErrorCode.BP_MARKET_CAP_MISMATCH,
                "prepared BP market_cap differs from frozen valuation evidence",
            )
        record["formula_inputs"] = dict(inputs)
        record["formula_inputs"]["market_cap"] = observation.market_cap
        record["market_cap_as_of"] = observation.market_cap_as_of
        record["valuation_source_reference"] = observation.source_record_reference
        record["valuation_input_hash"] = observation.source_input_hash
        record["valuation_policy_version"] = observation.valuation_policy_version
        record["valuation_adapter_content_hash"] = valuation.content_hash
    return copied


def _blocked(
    row_count: int, issue: BPValuationAdapterIssue
) -> BPValuationAdapterResult:
    return _blocked_many(row_count, (issue,))


def _blocked_many(
    row_count: int, issues: Iterable[BPValuationAdapterIssue]
) -> BPValuationAdapterResult:
    ordered_issues = tuple(issues)
    return BPValuationAdapterResult(
        observations=(),
        status=BPValuationAdapterStatus.BLOCKED.value,
        issues=ordered_issues,
        input_row_count=row_count,
        content_hash=_hash_payload(
            "blocked", [item.to_dict() for item in ordered_issues]
        ),
    )


def _content_hash(observations: tuple[BPValuationObservation, ...]) -> str:
    return _hash_payload("ready", [item.to_dict() for item in observations])


def _hash_payload(status: str, payload: Any) -> str:
    canonical = json.dumps(
        {
            "schema_version": BP_VALUATION_ADAPTER_SCHEMA_VERSION,
            "policy_version": BP_VALUATION_ADAPTER_POLICY_VERSION,
            "status": status,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _text(value: Any, field_name: str) -> str:
    if value is None or pd.isna(value):
        raise ValueError(f"{field_name} is required")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _date_text(value: Any, field_name: str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    normalized = _text(value, field_name)
    try:
        parsed = date.fromisoformat(normalized[:10])
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc
    if normalized not in {parsed.isoformat(), f"{parsed.isoformat()} 00:00:00"}:
        try:
            timestamp = pd.Timestamp(normalized)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an ISO date") from exc
        if timestamp.time() != datetime.min.time():
            raise ValueError(f"{field_name} must not contain an intraday time")
    return parsed.isoformat()


def _positive_finite(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field_name} must be finite and positive")
    return number


def _optional_finite(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("book_to_market_ratio_lf must be finite when supplied")
    return number


def _sha256_text(value: Any, field_name: str) -> str:
    normalized = _text(value, field_name).lower()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return normalized


def _code_for_value_error(message: str) -> BPValuationAdapterErrorCode:
    if "date" in message:
        return BPValuationAdapterErrorCode.INVALID_DATE
    if "market_cap" in message:
        return BPValuationAdapterErrorCode.INVALID_MARKET_CAP
    if "source_record_reference" in message:
        return BPValuationAdapterErrorCode.INVALID_SOURCE_REFERENCE
    if "source_input_hash" in message:
        return BPValuationAdapterErrorCode.INVALID_SOURCE_HASH
    return BPValuationAdapterErrorCode.REQUIRED_FIELD_MISSING
