"""Read-only adapter for the platform-owned ``ExposureBatch-v1`` contract.

This module deliberately contains no RQData or vendor-specific reader.  It
validates a supplied public exposure snapshot and performs an exact PIT join
for explicitly requested financial evaluation dates.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.amr.financial_fingerprint import (
    FINANCIAL_FINGERPRINT_CONTRACT_VERSION,
    canonicalize_financial_fingerprint,
)

EXPOSURE_BATCH_CONTRACT_VERSION = "ExposureBatch-v1"
EXPOSURE_ADAPTER_VERSION = "FIN-EXPOSURE-ADAPTER-v1.0"
_REQUIRED_COLUMNS = (
    "security_id",
    "start_date",
    "cancel_date",
    "industry_code",
    "industry_type",
    "total_market_cap",
    "market_cap_date",
)


@dataclass(frozen=True)
class FinancialExposureRecord:
    security_id: str
    evaluation_date: str
    industry_code: str | None
    industry_type: str | None
    total_market_cap: float | None
    log_market_cap: float | None
    start_date: str | None
    cancel_date: str | None
    source: str
    data_version: str
    industry_mapping_version: str
    snapshot_hash: str
    missing_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name) for name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class FinancialExposureAudit:
    gate_status: str
    requested_count: int
    matched_count: int
    missing_count: int
    duplicate_match_count: int
    future_fill_count: int
    source: str
    data_version: str
    industry_mapping_version: str
    snapshot_hash: str
    contract_version: str
    adapter_version: str
    content_hash: str
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "errors"
        }
        payload["errors"] = list(self.errors)
        return payload


@dataclass(frozen=True)
class FinancialExposureAdapterResult:
    records: tuple[FinancialExposureRecord, ...]
    audit: FinancialExposureAudit

    def lookup(self, evaluation_date: Any, security_id: Any) -> FinancialExposureRecord:
        key = (_date_iso(evaluation_date), _text(security_id, "security_id"))
        matches = [
            item
            for item in self.records
            if (item.evaluation_date, item.security_id) == key
        ]
        if len(matches) != 1:
            raise LookupError(f"expected one adapted exposure for {key}, found {len(matches)}")
        return matches[0]


def adapt_exposure_batch_v1(
    exposure_batch: Any,
    *,
    evaluation_keys: list[tuple[Any, Any]] | tuple[tuple[Any, Any], ...],
) -> FinancialExposureAdapterResult:
    """PIT-match one public exposure record per explicit date/security key."""
    errors: list[str] = []
    contract = getattr(exposure_batch, "schema_version", None)
    if contract != EXPOSURE_BATCH_CONTRACT_VERSION:
        errors.append(
            f"contract_version expected={EXPOSURE_BATCH_CONTRACT_VERSION} actual={contract}"
        )
    provenance = dict(getattr(exposure_batch, "provenance", {}) or {})
    metadata = {
        "source": provenance.get("source", getattr(exposure_batch, "source", None)),
        "data_version": provenance.get("data_version", getattr(exposure_batch, "version", None)),
        "industry_mapping_version": provenance.get("industry_mapping_version"),
        "snapshot_hash": provenance.get("snapshot_hash"),
    }
    for name, value in metadata.items():
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing required exposure metadata: {name}")
            metadata[name] = "missing"
    try:
        frame = exposure_batch.get_frame().copy(deep=True)
    except (AttributeError, TypeError, ValueError):
        frame = pd.DataFrame()
        errors.append("ExposureBatch-v1 must provide get_frame()")
    missing_columns = sorted(set(_REQUIRED_COLUMNS) - set(frame.columns))
    if missing_columns:
        errors.append(f"missing exposure columns: {','.join(missing_columns)}")

    normalized_keys = sorted(
        {(_date_iso(date), _text(security, "security_id")) for date, security in evaluation_keys}
    )
    records: list[FinancialExposureRecord] = []
    duplicate_count = 0
    if not missing_columns:
        frame = frame.loc[:, _REQUIRED_COLUMNS].copy(deep=True)
        for column in ("start_date", "cancel_date", "market_cap_date"):
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
        frame["security_id"] = frame["security_id"].map(str).str.strip()
        frame = frame.sort_values(
            ["security_id", "start_date", "cancel_date"], kind="stable"
        )
        for evaluation_date, security_id in normalized_keys:
            point = pd.Timestamp(evaluation_date)
            candidates = frame[
                (frame["security_id"] == security_id)
                & (frame["start_date"] <= point)
                & (point < frame["cancel_date"])
                & (frame["market_cap_date"] == point)
            ]
            if len(candidates) > 1:
                duplicate_count += 1
                errors.append(
                    f"duplicate PIT exposure match: {evaluation_date}/{security_id}"
                )
                continue
            if candidates.empty:
                reason = _missing_reason(frame, security_id, point)
                records.append(
                    _record(metadata, security_id, evaluation_date, missing_reason=reason)
                )
                continue
            row = candidates.iloc[0]
            industry_code = _optional_text(row["industry_code"])
            industry_type = _optional_text(row["industry_type"])
            market_cap = _positive_float(row["total_market_cap"])
            reason = None
            if industry_code is None or industry_type is None:
                reason = "MISSING_INDUSTRY"
            elif market_cap is None:
                reason = "MISSING_OR_NON_POSITIVE_MARKET_CAP"
            records.append(
                _record(
                    metadata,
                    security_id,
                    evaluation_date,
                    industry_code=industry_code,
                    industry_type=industry_type,
                    market_cap=market_cap,
                    start_date=row["start_date"].date().isoformat(),
                    cancel_date=row["cancel_date"].date().isoformat(),
                    missing_reason=reason,
                )
            )

    matched = sum(item.missing_reason is None for item in records)
    missing = sum(item.missing_reason is not None for item in records)
    payload = {
        "records": [item.to_dict() for item in records],
        "errors": errors,
        "requested_count": len(normalized_keys),
        "duplicate_match_count": duplicate_count,
        "metadata": metadata,
        "contract_version": EXPOSURE_BATCH_CONTRACT_VERSION,
        "adapter_version": EXPOSURE_ADAPTER_VERSION,
    }
    content_hash = _hash(payload)
    audit = FinancialExposureAudit(
        gate_status="blocked" if errors else "ready",
        requested_count=len(normalized_keys),
        matched_count=matched,
        missing_count=missing,
        duplicate_match_count=duplicate_count,
        future_fill_count=0,
        source=metadata["source"],
        data_version=metadata["data_version"],
        industry_mapping_version=metadata["industry_mapping_version"],
        snapshot_hash=metadata["snapshot_hash"],
        contract_version=EXPOSURE_BATCH_CONTRACT_VERSION,
        adapter_version=EXPOSURE_ADAPTER_VERSION,
        content_hash=content_hash,
        errors=tuple(errors),
    )
    return FinancialExposureAdapterResult(tuple(records), audit)


def _record(
    metadata: dict[str, str],
    security_id: str,
    evaluation_date: str,
    *,
    industry_code: str | None = None,
    industry_type: str | None = None,
    market_cap: float | None = None,
    start_date: str | None = None,
    cancel_date: str | None = None,
    missing_reason: str | None,
) -> FinancialExposureRecord:
    return FinancialExposureRecord(
        security_id=security_id,
        evaluation_date=evaluation_date,
        industry_code=industry_code,
        industry_type=industry_type,
        total_market_cap=market_cap,
        log_market_cap=math.log(market_cap) if market_cap is not None else None,
        start_date=start_date,
        cancel_date=cancel_date,
        source=metadata["source"],
        data_version=metadata["data_version"],
        industry_mapping_version=metadata["industry_mapping_version"],
        snapshot_hash=metadata["snapshot_hash"],
        missing_reason=missing_reason,
    )


def _missing_reason(frame: pd.DataFrame, security_id: str, point: pd.Timestamp) -> str:
    security = frame[frame["security_id"] == security_id]
    if security.empty:
        return "SECURITY_NOT_IN_EXPOSURE_BATCH"
    interval = security[
        (security["start_date"] <= point) & (point < security["cancel_date"])
    ]
    if interval.empty:
        return "NO_PIT_INDUSTRY_INTERVAL"
    return "NO_SAME_DATE_MARKET_CAP"


def _hash(value: Any) -> str:
    payload = json.dumps(
        {
            "canonicalization_contract_version": FINANCIAL_FINGERPRINT_CONTRACT_VERSION,
            "value": canonicalize_financial_fingerprint(value),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _date_iso(value: Any) -> str:
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise ValueError("evaluation_date must be valid")
    return parsed.date().isoformat()


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None
