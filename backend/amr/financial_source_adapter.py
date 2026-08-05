"""FIN-R1A: controlled financial source records to ``FinancialBatch``.

Only already-computed factor values are accepted.  The adapter never evaluates
formula or code text, never loads data, and never publishes a partial batch.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping

import pandas as pd

from .evaluation_input_contract import (
    EvaluationInputContractError,
    FactorType,
    FinancialBatch,
    ValueScope,
)
from .financial_timing import (
    REVISION_EFFECTIVE_DATE_INVALID,
    FinancialTimingObservation,
    FinancialTimingPolicy,
    TimingAudit,
    evaluate_financial_timing,
)


_REQUIRED_FIELDS = frozenset(
    {
        "code",
        "report_period",
        "publish_date",
        "factor_value",
        "statement_version",
        "source_record_id",
    }
)
_DYNAMIC_FORMULA_FIELDS = frozenset(
    {"formula", "factor_formula", "expression", "code_text", "executable_code"}
)


@dataclass(frozen=True)
class FinancialSourceIssue:
    code: str
    message: str
    field_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", copy.deepcopy(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_name": self.field_name,
            "details": copy.deepcopy(self.details),
        }


@dataclass(frozen=True)
class FinancialSourceGateResult:
    overall_status: str
    errors: tuple[FinancialSourceIssue, ...] = ()
    warnings: tuple[FinancialSourceIssue, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", copy.deepcopy(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "evidence": copy.deepcopy(self.evidence),
        }


@dataclass(frozen=True)
class FinancialSourceAdaptationResult:
    factor_id: str
    batch: FinancialBatch | None
    timing_audits: tuple[TimingAudit, ...]
    gate_result: FinancialSourceGateResult
    input_fingerprint: str
    timing_audit_fingerprint: str
    output_fingerprint: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "batch_available": self.batch is not None,
            "timing_audits": [audit.to_dict() for audit in self.timing_audits],
            "gate_result": self.gate_result.to_dict(),
            "input_fingerprint": self.input_fingerprint,
            "timing_audit_fingerprint": self.timing_audit_fingerprint,
            "output_fingerprint": self.output_fingerprint,
        }


def adapt_financial_source_records(
    records: Iterable[Mapping[str, Any]],
    *,
    factor_id: str,
    version: str,
    source: str,
    policy: FinancialTimingPolicy,
    frequency: str = "quarterly",
    universe: str | None = None,
) -> FinancialSourceAdaptationResult:
    """Validate all source records and return a batch only when every row passes."""

    raw_records = list(records)
    input_fingerprint = _fingerprint_unordered(raw_records)
    errors: list[FinancialSourceIssue] = []
    audits: list[TimingAudit] = []
    normalized_rows: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    seen_statement_versions: set[tuple[str, str, str]] = set()

    if not _nonempty_text(factor_id):
        errors.append(_issue("MISSING_FACTOR_ID", "factor_id must be non-empty", "factor_id"))
    if not _nonempty_text(version):
        errors.append(_issue("MISSING_VERSION", "version must be non-empty", "version"))
    if not _nonempty_text(source):
        errors.append(_issue("MISSING_SOURCE", "source must be non-empty", "source"))
    if not _nonempty_text(frequency):
        errors.append(_issue("MISSING_FREQUENCY", "frequency must be non-empty", "frequency"))
    if not raw_records:
        errors.append(_issue("EMPTY_SOURCE_RECORDS", "at least one source record is required"))

    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, Mapping):
            errors.append(
                _issue(
                    "INVALID_SOURCE_RECORD",
                    "each source record must be a mapping",
                    details={"record_index": index},
                )
            )
            continue
        record = dict(raw_record)
        record_details = {"record_index": index}

        dynamic_fields = sorted(
            name
            for name in _DYNAMIC_FORMULA_FIELDS
            if name in record and not _missing(record[name])
        )
        if dynamic_fields:
            errors.append(
                _issue(
                    "DYNAMIC_FORMULA_NOT_ALLOWED",
                    "dynamic formula or executable code is not accepted",
                    ",".join(dynamic_fields),
                    {**record_details, "fields": dynamic_fields},
                )
            )
            continue

        missing = sorted(
            field_name
            for field_name in _REQUIRED_FIELDS
            if field_name not in record or _missing(record[field_name])
        )
        if missing:
            errors.append(
                _issue(
                    "MISSING_REQUIRED_COLUMN",
                    f"missing required source fields: {missing}",
                    ",".join(missing),
                    record_details,
                )
            )
            continue

        if record.get("synthetic_test_only") is not True:
            errors.append(
                _issue(
                    "NON_SYNTHETIC_INPUT_NOT_AUTHORIZED",
                    "FIN-R1A currently accepts only synthetic_test_only=true records",
                    "synthetic_test_only",
                    record_details,
                )
            )
            continue

        code = record["code"]
        statement_version = record["statement_version"]
        source_record_id = record["source_record_id"]
        if not _nonempty_text(code):
            errors.append(_issue("INVALID_FIELD_TYPE", "code must be non-empty text", "code", record_details))
            continue
        if not _nonempty_text(statement_version):
            errors.append(
                _issue(
                    "INVALID_FIELD_TYPE",
                    "statement_version must be non-empty text",
                    "statement_version",
                    record_details,
                )
            )
            continue
        if not _nonempty_text(source_record_id):
            errors.append(
                _issue(
                    "INVALID_FIELD_TYPE",
                    "source_record_id must be non-empty text",
                    "source_record_id",
                    record_details,
                )
            )
            continue
        code = code.strip()
        statement_version = statement_version.strip()
        source_record_id = source_record_id.strip()
        record_details["source_record_id"] = source_record_id

        if source_record_id in seen_source_ids:
            errors.append(
                _issue(
                    "DUPLICATE_SOURCE_RECORD_ID",
                    "source_record_id must be unique",
                    "source_record_id",
                    record_details,
                )
            )
            continue
        seen_source_ids.add(source_record_id)

        try:
            report_period = _date_iso(record["report_period"])
        except (TypeError, ValueError):
            errors.append(
                _issue(
                    "INVALID_DATE",
                    "report_period must be a valid calendar date",
                    "report_period",
                    record_details,
                )
            )
            continue

        statement_key = (code, report_period, statement_version)
        if statement_key in seen_statement_versions:
            errors.append(
                _issue(
                    "DUPLICATE_STATEMENT_VERSION",
                    "statement_version must be unique for code and report_period",
                    "statement_version",
                    record_details,
                )
            )
            continue
        seen_statement_versions.add(statement_key)

        try:
            factor_value = _finite_number(record["factor_value"])
        except (TypeError, ValueError):
            errors.append(
                _issue(
                    "NON_NUMERIC_VALUE",
                    "factor_value must be a finite number",
                    "factor_value",
                    record_details,
                )
            )
            continue

        audit = evaluate_financial_timing(
            FinancialTimingObservation(
                code=code,
                publish_date=record["publish_date"],
                announcement_timestamp=record.get("announcement_timestamp"),
                announcement_timezone=record.get("announcement_timezone"),
                statement_version=statement_version,
                source_record_id=source_record_id,
                provided_effective_date=record.get("provided_effective_date"),
                return_start_date=record.get("return_start_date"),
            ),
            policy,
        )
        audits.append(audit)
        if audit.overall_status == "blocked":
            for timing_error in audit.errors:
                errors.append(
                    _issue(
                        timing_error.code,
                        timing_error.message,
                        timing_error.field_name,
                        record_details,
                    )
                )
            continue

        normalized_rows.append(
            {
                "code": code,
                "report_period": report_period,
                "publish_date": audit.publish_date,
                "effective_date": audit.derived_effective_date,
                "factor_value": factor_value,
                "_statement_version": statement_version,
                "_source_record_id": source_record_id,
            }
        )

    revision_conflicts = _revision_effective_date_conflicts(normalized_rows)
    if revision_conflicts:
        errors.append(
            _issue(
                REVISION_EFFECTIVE_DATE_INVALID,
                "successive statement versions must have strictly later effective dates",
                "statement_version,effective_date",
                {"conflicts": revision_conflicts},
            )
        )

    duplicate_output_keys = _duplicate_keys(
        normalized_rows, ("code", "report_period", "effective_date")
    )
    if duplicate_output_keys:
        errors.append(
            _issue(
                "DUPLICATE_FINANCIAL_TIMING_KEY",
                "multiple source records resolve to the same FinancialBatch key",
                "code,report_period,effective_date",
                {"duplicate_keys": duplicate_output_keys},
            )
        )

    audits = sorted(
        audits,
        key=lambda item: (
            item.code or "",
            item.publish_date or "",
            item.derived_effective_date or "",
            item.statement_version or "",
            item.source_record_id or "",
        ),
    )
    timing_audit_fingerprint = _fingerprint_ordered(
        [audit.to_dict() for audit in audits]
    )

    if errors:
        return _blocked_result(
            factor_id=factor_id,
            raw_count=len(raw_records),
            accepted_count=len(normalized_rows),
            audits=audits,
            errors=errors,
            policy=policy,
            input_fingerprint=input_fingerprint,
            timing_audit_fingerprint=timing_audit_fingerprint,
        )

    normalized_rows.sort(
        key=lambda row: (
            row["code"],
            row["report_period"],
            row["effective_date"],
            row["_source_record_id"],
        )
    )
    output_rows = [
        {
            "code": row["code"],
            "report_period": row["report_period"],
            "publish_date": row["publish_date"],
            "effective_date": row["effective_date"],
            "factor_value": row["factor_value"],
        }
        for row in normalized_rows
    ]
    output_fingerprint = _fingerprint_ordered(output_rows)

    frame = pd.DataFrame(
        output_rows,
        columns=[
            "code",
            "report_period",
            "publish_date",
            "effective_date",
            "factor_value",
        ],
    )
    try:
        batch = FinancialBatch(
            factor_id=factor_id.strip(),
            factor_type=FactorType.FINANCIAL,
            value_scope=ValueScope.SECURITY_LEVEL,
            version=version.strip(),
            source=source.strip(),
            frequency=frequency.strip(),
            universe=universe,
            _frame=frame,
            provenance={
                "timing_policy_version": policy.timing_policy_version,
                "trading_calendar_version": policy.trading_calendar_version,
                "timezone": policy.timezone,
                "synthetic_test_only": True,
                "input_row_count": len(raw_records),
                "output_row_count": len(output_rows),
                "input_fingerprint": input_fingerprint,
                "timing_audit_fingerprint": timing_audit_fingerprint,
                "output_fingerprint": output_fingerprint,
            },
        )
    except EvaluationInputContractError as exc:
        errors.append(
            _issue(
                exc.code,
                str(exc),
                exc.field_name,
                {"contract_details": exc.details},
            )
        )
        return _blocked_result(
            factor_id=factor_id,
            raw_count=len(raw_records),
            accepted_count=len(normalized_rows),
            audits=audits,
            errors=errors,
            policy=policy,
            input_fingerprint=input_fingerprint,
            timing_audit_fingerprint=timing_audit_fingerprint,
        )

    gate = FinancialSourceGateResult(
        overall_status="ready",
        evidence={
            "input_row_count": len(raw_records),
            "output_row_count": len(output_rows),
            "timing_policy_version": policy.timing_policy_version,
            "trading_calendar_version": policy.trading_calendar_version,
            "timezone": policy.timezone,
            "synthetic_test_only": True,
        },
    )
    return FinancialSourceAdaptationResult(
        factor_id=factor_id.strip(),
        batch=batch,
        timing_audits=tuple(audits),
        gate_result=gate,
        input_fingerprint=input_fingerprint,
        timing_audit_fingerprint=timing_audit_fingerprint,
        output_fingerprint=output_fingerprint,
    )


def _blocked_result(
    *,
    factor_id: str,
    raw_count: int,
    accepted_count: int,
    audits: list[TimingAudit],
    errors: list[FinancialSourceIssue],
    policy: FinancialTimingPolicy,
    input_fingerprint: str,
    timing_audit_fingerprint: str,
) -> FinancialSourceAdaptationResult:
    return FinancialSourceAdaptationResult(
        factor_id=factor_id.strip() if isinstance(factor_id, str) else "",
        batch=None,
        timing_audits=tuple(audits),
        gate_result=FinancialSourceGateResult(
            overall_status="blocked",
            errors=tuple(errors),
            evidence={
                "input_row_count": raw_count,
                "accepted_row_count": accepted_count,
                "output_row_count": 0,
                "timing_policy_version": policy.timing_policy_version,
                "trading_calendar_version": policy.trading_calendar_version,
                "timezone": policy.timezone,
                "synthetic_test_only": True,
            },
        ),
        input_fingerprint=input_fingerprint,
        timing_audit_fingerprint=timing_audit_fingerprint,
        output_fingerprint=None,
    )


def _issue(
    code: str,
    message: str,
    field_name: str | None = None,
    details: dict[str, Any] | None = None,
) -> FinancialSourceIssue:
    return FinancialSourceIssue(
        code=code,
        message=message,
        field_name=field_name,
        details=details or {},
    )


def _duplicate_keys(
    rows: list[dict[str, Any]], key_fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    counts: dict[tuple[Any, ...], int] = {}
    for row in rows:
        key = tuple(row[field_name] for field_name in key_fields)
        counts[key] = counts.get(key, 0) + 1
    return [
        {**dict(zip(key_fields, key)), "count": count}
        for key, count in sorted(counts.items())
        if count > 1
    ]


def _revision_effective_date_conflicts(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["code"], row["report_period"]), []).append(row)

    conflicts: list[dict[str, Any]] = []
    for (code, report_period), group in sorted(groups.items()):
        ordered = sorted(
            group,
            key=lambda row: (
                row["publish_date"],
                row["effective_date"],
                row["_source_record_id"],
            ),
        )
        for previous, current in zip(ordered, ordered[1:]):
            if current["effective_date"] <= previous["effective_date"]:
                conflicts.append(
                    {
                        "code": code,
                        "report_period": report_period,
                        "previous_statement_version":
                            previous["_statement_version"],
                        "previous_effective_date": previous["effective_date"],
                        "current_statement_version":
                            current["_statement_version"],
                        "current_effective_date": current["effective_date"],
                    }
                )
    return conflicts


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("boolean is not a factor value")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError("factor value must be finite")
    return converted


def _date_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        raise TypeError("date must be non-empty")
    return date.fromisoformat(value.strip()).isoformat()


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _fingerprint_unordered(values: list[Any]) -> str:
    canonical_values = [_canonical_json_value(value) for value in values]
    canonical_values.sort(
        key=lambda value: json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return _sha256_json(canonical_values)


def _fingerprint_ordered(values: list[Any]) -> str:
    return _sha256_json([_canonical_json_value(value) for value in values])


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)
