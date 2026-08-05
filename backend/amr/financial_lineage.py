"""FIN-R1B: deterministic, fail-closed financial observation provenance.

The module consumes an already validated :class:`FinancialBatch` and FIN-R1A
``TimingAudit`` objects.  It never derives or changes ``effective_date``, never
executes formula text, and performs no network or database access.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Iterable, Mapping

from .evaluation_input_contract import FinancialBatch
from .financial_timing import TimingAudit


LINEAGE_SCHEMA_VERSION = "FinancialObservationLineage-v1.0"
HASH_CONTRACT_VERSION = "FIN-R1B-HASH-v1.0"
NOT_APPLICABLE = "not_applicable"
LINEAGE_INDEX_FIELDS = ("evaluation_date", "code", "factor_id")
FINANCIAL_OBSERVATION_KEY_FIELDS = (
    "code",
    "factor_id",
    "report_period",
    "effective_date",
)


class PathType(str, Enum):
    UPSTREAM_COMPUTED = "A"
    REGISTERED_FORMULA = "B"


class LineageGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class ProvenanceErrorCode(str, Enum):
    """Frozen FIN-R1B reason-code enum.

    Gate status is deliberately not encoded in these values.
    """

    SOURCE_PROVIDER_MISSING = "SOURCE_PROVIDER_MISSING"
    SOURCE_DATASET_MISSING = "SOURCE_DATASET_MISSING"
    SOURCE_SNAPSHOT_MISSING = "SOURCE_SNAPSHOT_MISSING"
    SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH = (
        "SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH"
    )
    SOURCE_RECORD_REFERENCE_MISSING = "SOURCE_RECORD_REFERENCE_MISSING"
    FINANCIAL_VERSION_MISSING = "FINANCIAL_VERSION_MISSING"
    REVISION_CHAIN_BROKEN = "REVISION_CHAIN_BROKEN"
    FUTURE_REVISION_BACKFILL_DETECTED = "FUTURE_REVISION_BACKFILL_DETECTED"
    MULTISOURCE_CONFLICT = "MULTISOURCE_CONFLICT"
    CROSS_SECURITY_LINEAGE_DETECTED = "CROSS_SECURITY_LINEAGE_DETECTED"
    SOURCE_INPUT_HASH_MISMATCH = "SOURCE_INPUT_HASH_MISMATCH"
    FACTOR_VALUE_HASH_MISMATCH = "FACTOR_VALUE_HASH_MISMATCH"
    LINEAGE_REFERENCE_NOT_FOUND = "LINEAGE_REFERENCE_NOT_FOUND"
    INPUT_MUTATION_DETECTED = "INPUT_MUTATION_DETECTED"
    NONDETERMINISTIC_LINEAGE_OUTPUT = "NONDETERMINISTIC_LINEAGE_OUTPUT"
    INVALID_LINEAGE_INPUT = "INVALID_LINEAGE_INPUT"
    PATH_PROOF_MISSING = "PATH_PROOF_MISSING"
    PIT_TIMING_AUDIT_MISMATCH = "PIT_TIMING_AUDIT_MISMATCH"
    FINANCIAL_BATCH_MISMATCH = "FINANCIAL_BATCH_MISMATCH"
    DUPLICATE_LINEAGE_KEY = "DUPLICATE_LINEAGE_KEY"
    FUTURE_LABEL_INPUT_NOT_ALLOWED = "FUTURE_LABEL_INPUT_NOT_ALLOWED"
    CONTENT_HASH_MISMATCH = "CONTENT_HASH_MISMATCH"
    CONFIGURATION_HASH_MISMATCH = "CONFIGURATION_HASH_MISMATCH"


class LineageLookupError(LookupError):
    """Coded lookup failure for a sidecar reference."""

    def __init__(
        self,
        code: ProvenanceErrorCode,
        message: str,
        *,
        lookup_key: tuple[str, str, str],
    ) -> None:
        super().__init__(message)
        self.code = code.value
        self.lookup_key = lookup_key


@dataclass(frozen=True)
class LineageIssue:
    code: str
    message: str
    field_name: str | None = None
    record_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_name": self.field_name,
            "record_key": self.record_key,
        }


@dataclass(frozen=True)
class SourceSnapshotFingerprint:
    provider: str
    dataset: str
    snapshot_id: str
    as_of_version: str
    fingerprint: str
    hash_contract_version: str = HASH_CONTRACT_VERSION

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "dataset": self.dataset,
            "snapshot_id": self.snapshot_id,
            "as_of_version": self.as_of_version,
            "fingerprint": self.fingerprint,
            "hash_contract_version": self.hash_contract_version,
        }


@dataclass(frozen=True)
class FinancialObservationLineage:
    schema_version: str
    lineage_id: str
    evaluation_date: str
    code: str
    factor_id: str
    report_period: str
    publish_date: str
    effective_date: str
    effective_date_policy_version: str
    trading_calendar_version: str
    path_type: str
    source_provider: str
    source_dataset: str
    source_snapshot_id: str
    source_as_of_version: str
    source_snapshot_fingerprint: str
    source_record_id: str
    announcement_id: str
    financial_statement_version: str
    revision_version: str
    supersedes_reference: str
    transformation_reference: str
    formula_reference: str
    upstream_calculation_reference: str
    source_input_hash: str
    factor_value_hash: str
    configuration_hash: str
    content_hash: str
    conflict_status: str = "none"
    warnings: tuple[str, ...] = ()

    def to_dict(self, *, include_content_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "lineage_id": self.lineage_id,
            "evaluation_date": self.evaluation_date,
            "code": self.code,
            "factor_id": self.factor_id,
            "report_period": self.report_period,
            "publish_date": self.publish_date,
            "effective_date": self.effective_date,
            "effective_date_policy_version":
                self.effective_date_policy_version,
            "trading_calendar_version": self.trading_calendar_version,
            "path_type": self.path_type,
            "source_provider": self.source_provider,
            "source_dataset": self.source_dataset,
            "source_snapshot_id": self.source_snapshot_id,
            "source_as_of_version": self.source_as_of_version,
            "source_snapshot_fingerprint":
                self.source_snapshot_fingerprint,
            "source_record_id": self.source_record_id,
            "announcement_id": self.announcement_id,
            "financial_statement_version":
                self.financial_statement_version,
            "revision_version": self.revision_version,
            "supersedes_reference": self.supersedes_reference,
            "transformation_reference": self.transformation_reference,
            "formula_reference": self.formula_reference,
            "upstream_calculation_reference":
                self.upstream_calculation_reference,
            "source_input_hash": self.source_input_hash,
            "factor_value_hash": self.factor_value_hash,
            "configuration_hash": self.configuration_hash,
            "conflict_status": self.conflict_status,
            "warnings": list(self.warnings),
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class ObservationLineageReference:
    location: str
    schema_version: str
    row_count: int
    index_fields: tuple[str, ...]
    content_hash: str
    records: tuple[FinancialObservationLineage, ...]

    def lookup(
        self,
        evaluation_date: Any,
        code: Any,
        factor_id: Any,
    ) -> FinancialObservationLineage:
        key = (
            _date_iso(evaluation_date),
            _required_text(code, "code"),
            _required_text(factor_id, "factor_id"),
        )
        matches = [
            record
            for record in self.records
            if (
                record.evaluation_date,
                record.code,
                record.factor_id,
            ) == key
        ]
        if len(matches) != 1:
            raise LineageLookupError(
                ProvenanceErrorCode.LINEAGE_REFERENCE_NOT_FOUND,
                f"expected exactly one lineage record for {key}, "
                f"found {len(matches)}",
                lookup_key=key,
            )
        return matches[0]

    def to_dict(self, *, include_records: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "location": self.location,
            "schema_version": self.schema_version,
            "row_count": self.row_count,
            "index_fields": list(self.index_fields),
            "content_hash": self.content_hash,
        }
        if include_records:
            payload["records"] = [record.to_dict() for record in self.records]
        return payload


@dataclass(frozen=True)
class ProvenanceAudit:
    schema_version: str
    run_id: str
    source_providers: tuple[str, ...]
    source_datasets: tuple[str, ...]
    source_snapshots: tuple[str, ...]
    total_observations: int
    lineage_complete_count: int
    lineage_incomplete_count: int
    revision_count: int
    conflict_count: int
    hash_mismatch_count: int
    gate_status: str
    errors: tuple[LineageIssue, ...]
    warnings: tuple[LineageIssue, ...]
    content_hash: str

    def to_dict(self, *, include_content_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "source_providers": list(self.source_providers),
            "source_datasets": list(self.source_datasets),
            "source_snapshots": list(self.source_snapshots),
            "total_observations": self.total_observations,
            "lineage_complete_count": self.lineage_complete_count,
            "lineage_incomplete_count": self.lineage_incomplete_count,
            "revision_count": self.revision_count,
            "conflict_count": self.conflict_count,
            "hash_mismatch_count": self.hash_mismatch_count,
            "gate_status": self.gate_status,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class FinancialProvenanceResult:
    provenance_audit: ProvenanceAudit
    observation_lineage_reference: ObservationLineageReference | None
    source_snapshot_fingerprints: tuple[SourceSnapshotFingerprint, ...]
    lineage_records: tuple[FinancialObservationLineage, ...]

    @property
    def source_snapshot_fingerprint(
        self,
    ) -> tuple[SourceSnapshotFingerprint, ...]:
        """Formal FIN-R1B output name; a run may bind multiple datasets."""

        return self.source_snapshot_fingerprints

    def to_dict(self) -> dict[str, Any]:
        return {
            "provenance_audit": self.provenance_audit.to_dict(),
            "observation_lineage_reference": (
                self.observation_lineage_reference.to_dict()
                if self.observation_lineage_reference is not None
                else None
            ),
            "source_snapshot_fingerprint": [
                item.to_dict() for item in self.source_snapshot_fingerprints
            ],
            "lineage_record_count": len(self.lineage_records),
        }


def compute_source_input_hash(payload: Any) -> str:
    """Hash a source input under the frozen FIN-R1B canonical JSON contract."""

    return _versioned_hash("source_input", payload)


def compute_factor_value_hash(value: Any) -> str:
    """Hash one finite factor value without coercing booleans."""

    if isinstance(value, bool):
        raise TypeError("factor_value must be numeric, not boolean")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError("factor_value must be finite")
    return _versioned_hash("factor_value", {"factor_value": converted})


def compute_source_snapshot_fingerprint(
    provider: Any,
    dataset: Any,
    snapshot_id: Any,
    as_of_version: Any,
    manifest: Any,
) -> str:
    payload = {
        "provider": _required_text(provider, "source_provider"),
        "dataset": _required_text(dataset, "source_dataset"),
        "snapshot_id": _required_text(snapshot_id, "source_snapshot_id"),
        "as_of_version": _required_text(
            as_of_version, "source_as_of_version"
        ),
        "manifest": manifest,
    }
    return _versioned_hash("source_snapshot", payload)


def compute_configuration_hash(
    configuration: Mapping[str, Any],
    *,
    timing_policy_version: Any,
    trading_calendar_version: Any,
    timezone: Any,
) -> str:
    payload = {
        "configuration": configuration,
        "timing_policy_version": _required_text(
            timing_policy_version, "timing_policy_version"
        ),
        "trading_calendar_version": _required_text(
            trading_calendar_version, "trading_calendar_version"
        ),
        "timezone": _required_text(timezone, "timezone"),
    }
    return _versioned_hash("configuration", payload)


def recompute_lineage_content_hash(
    record: FinancialObservationLineage,
) -> str:
    return _versioned_hash(
        "lineage_content",
        record.to_dict(include_content_hash=False),
    )


def verify_lineage_hashes(
    record: FinancialObservationLineage,
    *,
    source_input_payload: Any,
    factor_value: Any,
    configuration: Mapping[str, Any],
    source_snapshot_manifest: Any,
    timezone: str = "Asia/Shanghai",
) -> tuple[LineageIssue, ...]:
    """Recompute every independently verifiable hash for one lineage row."""

    issues: list[LineageIssue] = []
    key = _record_key(record)
    checks = (
        (
            record.source_input_hash,
            compute_source_input_hash(source_input_payload),
            ProvenanceErrorCode.SOURCE_INPUT_HASH_MISMATCH,
            "source_input_hash",
        ),
        (
            record.factor_value_hash,
            compute_factor_value_hash(factor_value),
            ProvenanceErrorCode.FACTOR_VALUE_HASH_MISMATCH,
            "factor_value_hash",
        ),
        (
            record.source_snapshot_fingerprint,
            compute_source_snapshot_fingerprint(
                record.source_provider,
                record.source_dataset,
                record.source_snapshot_id,
                record.source_as_of_version,
                source_snapshot_manifest,
            ),
            ProvenanceErrorCode.SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH,
            "source_snapshot_fingerprint",
        ),
        (
            record.configuration_hash,
            compute_configuration_hash(
                configuration,
                timing_policy_version=
                    record.effective_date_policy_version,
                trading_calendar_version=record.trading_calendar_version,
                timezone=timezone,
            ),
            ProvenanceErrorCode.CONFIGURATION_HASH_MISMATCH,
            "configuration_hash",
        ),
        (
            record.content_hash,
            recompute_lineage_content_hash(record),
            ProvenanceErrorCode.CONTENT_HASH_MISMATCH,
            "content_hash",
        ),
    )
    for expected, actual, code, field_name in checks:
        if expected != actual:
            issues.append(
                _issue(
                    code,
                    f"{field_name} does not match canonical recomputation",
                    field_name,
                    key,
                )
            )
    return tuple(issues)


def build_financial_provenance(
    batch: FinancialBatch,
    source_records: Iterable[Mapping[str, Any]],
    *,
    configuration: Mapping[str, Any],
) -> FinancialProvenanceResult:
    """Build an all-or-nothing provenance sidecar for ``batch``.

    ``effective_date`` and all timing policy fields are copied only after they
    match a passed FIN-R1A ``TimingAudit``.  Any error blocks the sidecar
    reference and prevents partial lineage publication.
    """

    errors: list[LineageIssue] = []
    warnings: list[LineageIssue] = []

    if not isinstance(batch, FinancialBatch):
        return _blocked_empty(
            [_issue(
                ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                "batch must be a FinancialBatch",
                "batch",
            )]
        )
    if not isinstance(configuration, Mapping):
        return _blocked_empty(
            [_issue(
                ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                "configuration must be a mapping",
                "configuration",
            )]
        )

    try:
        raw_records = list(source_records)
    except TypeError:
        return _blocked_empty(
            [_issue(
                ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                "source_records must be iterable",
                "source_records",
            )]
        )

    try:
        records = copy.deepcopy(raw_records)
        config = copy.deepcopy(dict(configuration))
        input_before = _versioned_hash(
            "builder_input",
            {"source_records": raw_records, "configuration": configuration},
        )
    except Exception as exc:
        return _blocked_empty(
            [_issue(
                ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                f"inputs are not canonicalizable: {type(exc).__name__}",
                "source_records,configuration",
            )]
        )

    forbidden = _find_future_label_fields(config)
    if forbidden:
        errors.append(
            _issue(
                ProvenanceErrorCode.FUTURE_LABEL_INPUT_NOT_ALLOWED,
                "configuration contains future-label fields",
                ",".join(forbidden),
            )
        )

    frame = batch.get_frame()
    batch_rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        try:
            batch_rows.append(
                {
                    "code": _required_text(row["code"], "code"),
                    "factor_id": batch.factor_id,
                    "report_period": _date_iso(row["report_period"]),
                    "publish_date": _date_iso(row["publish_date"]),
                    "effective_date": _date_iso(row["effective_date"]),
                    "factor_value": _finite_number(row["factor_value"]),
                }
            )
        except (TypeError, ValueError, KeyError) as exc:
            errors.append(
                _issue(
                    ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                    f"invalid FinancialBatch row: {exc}",
                    "batch",
                )
            )

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        record_key = f"source_records[{index}]"
        if not isinstance(item, Mapping):
            errors.append(
                _issue(
                    ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                    "source record must be a mapping",
                    "source_records",
                    record_key,
                )
            )
            continue
        record = dict(item)
        parsed = _normalize_source_record(
            record,
            batch=batch,
            record_key=record_key,
            errors=errors,
        )
        if parsed is not None:
            normalized.append(parsed)

    batch_key_counts = _key_counts(batch_rows, FINANCIAL_OBSERVATION_KEY_FIELDS)
    source_key_counts = _key_counts(
        normalized, FINANCIAL_OBSERVATION_KEY_FIELDS
    )
    for key, count in sorted(source_key_counts.items()):
        if count > 1:
            errors.append(
                _issue(
                    ProvenanceErrorCode.MULTISOURCE_CONFLICT,
                    f"public financial key has {count} source candidates",
                    ",".join(FINANCIAL_OBSERVATION_KEY_FIELDS),
                    _format_key(FINANCIAL_OBSERVATION_KEY_FIELDS, key),
                )
            )
    for key in sorted(batch_key_counts):
        count = source_key_counts.get(key, 0)
        if count == 0:
            errors.append(
                _issue(
                    ProvenanceErrorCode.LINEAGE_REFERENCE_NOT_FOUND,
                    "FinancialBatch observation has no source lineage",
                    ",".join(FINANCIAL_OBSERVATION_KEY_FIELDS),
                    _format_key(FINANCIAL_OBSERVATION_KEY_FIELDS, key),
                )
            )
    for key in sorted(source_key_counts):
        if key not in batch_key_counts:
            errors.append(
                _issue(
                    ProvenanceErrorCode.FINANCIAL_BATCH_MISMATCH,
                    "source lineage has no matching FinancialBatch observation",
                    ",".join(FINANCIAL_OBSERVATION_KEY_FIELDS),
                    _format_key(FINANCIAL_OBSERVATION_KEY_FIELDS, key),
                )
            )

    _validate_source_reference_isolation(normalized, errors)
    _validate_snapshot_governance(normalized, errors)
    _validate_revision_chains(normalized, errors)

    lineages: list[FinancialObservationLineage] = []
    batch_by_key = {
        tuple(row[field] for field in FINANCIAL_OBSERVATION_KEY_FIELDS): row
        for row in batch_rows
    }
    for record in sorted(normalized, key=_source_sort_key):
        key = tuple(
            record[field] for field in FINANCIAL_OBSERVATION_KEY_FIELDS
        )
        batch_row = batch_by_key.get(key)
        if batch_row is None or source_key_counts.get(key) != 1:
            continue
        if record["publish_date"] != batch_row["publish_date"]:
            errors.append(
                _issue(
                    ProvenanceErrorCode.FINANCIAL_BATCH_MISMATCH,
                    "publish_date differs from FinancialBatch",
                    "publish_date",
                    record["record_key"],
                )
            )
            continue
        if record["factor_value"] != batch_row["factor_value"]:
            errors.append(
                _issue(
                    ProvenanceErrorCode.FINANCIAL_BATCH_MISMATCH,
                    "factor_value differs from FinancialBatch",
                    "factor_value",
                    record["record_key"],
                )
            )
            continue
        lineage = _build_lineage(record, config, errors)
        if lineage is not None:
            lineages.append(lineage)

    lineages.sort(
        key=lambda row: (
            row.evaluation_date,
            row.code,
            row.factor_id,
            row.report_period,
            row.effective_date,
            row.lineage_id,
        )
    )
    lookup_counts: dict[tuple[str, str, str], int] = {}
    for row in lineages:
        key = (row.evaluation_date, row.code, row.factor_id)
        lookup_counts[key] = lookup_counts.get(key, 0) + 1
    for key, count in sorted(lookup_counts.items()):
        if count > 1:
            errors.append(
                _issue(
                    ProvenanceErrorCode.DUPLICATE_LINEAGE_KEY,
                    f"sidecar lookup key resolves to {count} records",
                    ",".join(LINEAGE_INDEX_FIELDS),
                    _format_key(LINEAGE_INDEX_FIELDS, key),
                )
            )

    try:
        input_after = _versioned_hash(
            "builder_input",
            {"source_records": raw_records, "configuration": configuration},
        )
        if input_before != input_after:
            errors.append(
                _issue(
                    ProvenanceErrorCode.INPUT_MUTATION_DETECTED,
                    "input objects changed while lineage was being built",
                )
            )
    except Exception:
        errors.append(
            _issue(
                ProvenanceErrorCode.INPUT_MUTATION_DETECTED,
                "input objects were no longer canonicalizable after build",
            )
        )

    errors = _deduplicate_issues(errors)
    warnings = _deduplicate_issues(warnings)
    snapshots = _snapshot_objects(normalized)
    total = len(batch_rows)
    ready = not errors and len(lineages) == total
    published_lineages = tuple(lineages) if ready else ()
    reference = (
        _build_reference(published_lineages) if ready else None
    )
    governed_fingerprint = _governed_input_fingerprint(normalized, config)
    audit = _build_audit(
        normalized=normalized,
        total_observations=total,
        complete_count=len(lineages) if ready else 0,
        errors=tuple(errors),
        warnings=tuple(warnings),
        snapshots=snapshots,
        input_fingerprint=governed_fingerprint,
    )
    return FinancialProvenanceResult(
        provenance_audit=audit,
        observation_lineage_reference=reference,
        source_snapshot_fingerprints=snapshots,
        lineage_records=published_lineages,
    )


def _normalize_source_record(
    record: dict[str, Any],
    *,
    batch: FinancialBatch,
    record_key: str,
    errors: list[LineageIssue],
) -> dict[str, Any] | None:
    required_text_fields = {
        "evaluation_date": ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
        "code": ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
        "factor_id": ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
        "report_period": ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
        "publish_date": ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
        "effective_date": ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
        "path_type": ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
        "source_provider": ProvenanceErrorCode.SOURCE_PROVIDER_MISSING,
        "source_dataset": ProvenanceErrorCode.SOURCE_DATASET_MISSING,
        "source_snapshot_id": ProvenanceErrorCode.SOURCE_SNAPSHOT_MISSING,
        "source_as_of_version": ProvenanceErrorCode.SOURCE_SNAPSHOT_MISSING,
        "financial_statement_version":
            ProvenanceErrorCode.FINANCIAL_VERSION_MISSING,
        "revision_version": ProvenanceErrorCode.FINANCIAL_VERSION_MISSING,
        "transformation_reference":
            ProvenanceErrorCode.PATH_PROOF_MISSING,
    }
    values: dict[str, Any] = {"record_key": record_key}
    failed = False
    for field_name, code in required_text_fields.items():
        try:
            values[field_name] = _required_text(record.get(field_name), field_name)
        except (TypeError, ValueError):
            errors.append(
                _issue(
                    code,
                    f"{field_name} must be non-empty",
                    field_name,
                    record_key,
                )
            )
            failed = True

    for field_name in (
        "evaluation_date",
        "report_period",
        "publish_date",
        "effective_date",
    ):
        if field_name in values:
            try:
                values[field_name] = _date_iso(values[field_name])
            except (TypeError, ValueError):
                errors.append(
                    _issue(
                        ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                        f"{field_name} must be a calendar date",
                        field_name,
                        record_key,
                    )
                )
                failed = True

    try:
        values["factor_value"] = _finite_number(record.get("factor_value"))
    except (TypeError, ValueError):
        errors.append(
            _issue(
                ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                "factor_value must be a finite number",
                "factor_value",
                record_key,
            )
        )
        failed = True

    if record.get("synthetic_test_only") is not True:
        errors.append(
            _issue(
                ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                "FIN-R1B is authorized for synthetic_test_only=true input",
                "synthetic_test_only",
                record_key,
            )
        )
        failed = True

    source_record_id = _optional_text(record.get("source_record_id"))
    announcement_id = _optional_text(record.get("announcement_id"))
    if source_record_id is None and announcement_id is None:
        errors.append(
            _issue(
                ProvenanceErrorCode.SOURCE_RECORD_REFERENCE_MISSING,
                "source_record_id or announcement_id is required",
                "source_record_id,announcement_id",
                record_key,
            )
        )
        failed = True
    values["source_record_id"] = source_record_id or NOT_APPLICABLE
    values["announcement_id"] = announcement_id or NOT_APPLICABLE

    values["supersedes_reference"] = (
        _optional_text(record.get("supersedes_reference")) or NOT_APPLICABLE
    )
    values["formula_reference"] = (
        _optional_text(record.get("formula_reference")) or NOT_APPLICABLE
    )
    values["upstream_calculation_reference"] = (
        _optional_text(record.get("upstream_calculation_reference"))
        or NOT_APPLICABLE
    )

    if values.get("path_type") not in {item.value for item in PathType}:
        errors.append(
            _issue(
                ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                "path_type must be A or B",
                "path_type",
                record_key,
            )
        )
        failed = True
    elif (
        values["path_type"] == PathType.UPSTREAM_COMPUTED.value
        and values["upstream_calculation_reference"] == NOT_APPLICABLE
    ):
        errors.append(
            _issue(
                ProvenanceErrorCode.PATH_PROOF_MISSING,
                "path A requires upstream_calculation_reference",
                "upstream_calculation_reference",
                record_key,
            )
        )
        failed = True
    elif (
        values["path_type"] == PathType.REGISTERED_FORMULA.value
        and values["formula_reference"] == NOT_APPLICABLE
    ):
        errors.append(
            _issue(
                ProvenanceErrorCode.PATH_PROOF_MISSING,
                "path B requires formula_reference",
                "formula_reference",
                record_key,
            )
        )
        failed = True

    if "source_input_payload" not in record:
        errors.append(
            _issue(
                ProvenanceErrorCode.SOURCE_RECORD_REFERENCE_MISSING,
                "source_input_payload is required",
                "source_input_payload",
                record_key,
            )
        )
        failed = True
    else:
        values["source_input_payload"] = record["source_input_payload"]
        forbidden = _find_future_label_fields(
            values["source_input_payload"]
        )
        if forbidden:
            errors.append(
                _issue(
                    ProvenanceErrorCode.FUTURE_LABEL_INPUT_NOT_ALLOWED,
                    "source_input_payload contains future-label fields",
                    ",".join(forbidden),
                    record_key,
                )
            )
            failed = True

    if "source_snapshot_manifest" not in record:
        errors.append(
            _issue(
                ProvenanceErrorCode.SOURCE_SNAPSHOT_MISSING,
                "source_snapshot_manifest is required",
                "source_snapshot_manifest",
                record_key,
            )
        )
        failed = True
    else:
        values["source_snapshot_manifest"] = record[
            "source_snapshot_manifest"
        ]

    timing_audit = record.get("timing_audit")
    if not isinstance(timing_audit, TimingAudit):
        errors.append(
            _issue(
                ProvenanceErrorCode.PIT_TIMING_AUDIT_MISMATCH,
                "timing_audit must be a FIN-R1A TimingAudit",
                "timing_audit",
                record_key,
            )
        )
        failed = True
    else:
        values["timing_audit"] = timing_audit

    if failed:
        return None

    if values["factor_id"] != batch.factor_id:
        errors.append(
            _issue(
                ProvenanceErrorCode.FINANCIAL_BATCH_MISMATCH,
                "factor_id differs from FinancialBatch",
                "factor_id",
                record_key,
            )
        )
    _validate_timing_audit(values, errors)

    if values["evaluation_date"] < values["effective_date"]:
        errors.append(
            _issue(
                ProvenanceErrorCode.FUTURE_REVISION_BACKFILL_DETECTED,
                "evaluation_date precedes the FIN-R1A effective_date",
                "evaluation_date,effective_date",
                record_key,
            )
        )

    try:
        values["source_input_hash"] = compute_source_input_hash(
            values["source_input_payload"]
        )
        values["factor_value_hash"] = compute_factor_value_hash(
            values["factor_value"]
        )
        values["source_snapshot_fingerprint"] = (
            compute_source_snapshot_fingerprint(
                values["source_provider"],
                values["source_dataset"],
                values["source_snapshot_id"],
                values["source_as_of_version"],
                values["source_snapshot_manifest"],
            )
        )
    except (TypeError, ValueError) as exc:
        errors.append(
            _issue(
                ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                f"unable to compute lineage hash: {exc}",
                "source_input_payload,source_snapshot_manifest",
                record_key,
            )
        )
        return None

    expected_checks = (
        (
            "expected_source_input_hash",
            values["source_input_hash"],
            ProvenanceErrorCode.SOURCE_INPUT_HASH_MISMATCH,
        ),
        (
            "expected_factor_value_hash",
            values["factor_value_hash"],
            ProvenanceErrorCode.FACTOR_VALUE_HASH_MISMATCH,
        ),
        (
            "expected_source_snapshot_fingerprint",
            values["source_snapshot_fingerprint"],
            ProvenanceErrorCode.SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH,
        ),
    )
    for field_name, actual, code in expected_checks:
        expected = _optional_text(record.get(field_name))
        if expected is not None and expected != actual:
            errors.append(
                _issue(
                    code,
                    f"{field_name} does not match canonical recomputation",
                    field_name,
                    record_key,
                )
            )
    return values


def _validate_timing_audit(
    record: dict[str, Any],
    errors: list[LineageIssue],
) -> None:
    audit: TimingAudit = record["timing_audit"]
    comparisons = {
        "code": (audit.code, record["code"]),
        "publish_date": (audit.publish_date, record["publish_date"]),
        "effective_date": (
            audit.derived_effective_date,
            record["effective_date"],
        ),
        "financial_statement_version": (
            audit.statement_version,
            record["financial_statement_version"],
        ),
    }
    reference = (
        record["source_record_id"]
        if record["source_record_id"] != NOT_APPLICABLE
        else record["announcement_id"]
    )
    comparisons["source_record_reference"] = (
        audit.source_record_id,
        reference,
    )
    mismatches = [
        name for name, (actual, expected) in comparisons.items()
        if actual != expected
    ]
    if audit.overall_status != "passed":
        mismatches.append("overall_status")
    if mismatches:
        errors.append(
            _issue(
                ProvenanceErrorCode.PIT_TIMING_AUDIT_MISMATCH,
                f"FIN-R1A timing audit mismatch: {sorted(mismatches)}",
                ",".join(sorted(mismatches)),
                record["record_key"],
            )
        )


def _validate_source_reference_isolation(
    records: list[dict[str, Any]],
    errors: list[LineageIssue],
) -> None:
    owners: dict[tuple[str, str, str], set[str]] = {}
    for record in records:
        reference = (
            record["source_record_id"]
            if record["source_record_id"] != NOT_APPLICABLE
            else record["announcement_id"]
        )
        scoped_reference = (
            record["source_provider"],
            record["source_dataset"],
            reference,
        )
        owners.setdefault(scoped_reference, set()).add(record["code"])
    for reference, codes in sorted(owners.items()):
        if len(codes) > 1:
            errors.append(
                _issue(
                    ProvenanceErrorCode.CROSS_SECURITY_LINEAGE_DETECTED,
                    "one scoped source reference is attached to multiple "
                    f"securities: {sorted(codes)}",
                    "source_record_id,announcement_id",
                    "|".join(reference),
                )
            )


def _validate_snapshot_governance(
    records: list[dict[str, Any]],
    errors: list[LineageIssue],
) -> None:
    identities: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
    for record in records:
        key = (record["source_provider"], record["source_dataset"])
        identity = (
            record["source_snapshot_id"],
            record["source_as_of_version"],
            record["source_snapshot_fingerprint"],
        )
        identities.setdefault(key, set()).add(identity)
    for key, values in sorted(identities.items()):
        if len(values) > 1:
            errors.append(
                _issue(
                    ProvenanceErrorCode.SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH,
                    "provider/dataset switched snapshot within one run",
                    "source_snapshot_id,source_as_of_version",
                    "|".join(key),
                )
            )


def _validate_revision_chains(
    records: list[dict[str, Any]],
    errors: list[LineageIssue],
) -> None:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (
            record["code"],
            record["factor_id"],
            record["report_period"],
        )
        groups.setdefault(key, []).append(record)

    for key, group in sorted(groups.items()):
        by_reference: dict[str, dict[str, Any]] = {}
        for record in group:
            for field_name in ("source_record_id", "announcement_id"):
                reference = record[field_name]
                if reference != NOT_APPLICABLE:
                    by_reference[reference] = record

        ordered = sorted(
            group,
            key=lambda row: (
                row["effective_date"],
                row["publish_date"],
                row["record_key"],
            ),
        )
        for index, record in enumerate(ordered):
            is_original = record["revision_version"].lower() in {
                "original",
                "initial",
                "v1",
            }
            supersedes = record["supersedes_reference"]
            if is_original:
                if supersedes != NOT_APPLICABLE:
                    errors.append(
                        _issue(
                            ProvenanceErrorCode.REVISION_CHAIN_BROKEN,
                            "original version must not supersede another record",
                            "supersedes_reference",
                            record["record_key"],
                        )
                    )
            else:
                previous = by_reference.get(supersedes)
                if (
                    supersedes == NOT_APPLICABLE
                    or previous is None
                    or previous is record
                    or previous["effective_date"] >= record["effective_date"]
                ):
                    errors.append(
                        _issue(
                            ProvenanceErrorCode.REVISION_CHAIN_BROKEN,
                            "revision must supersede an earlier version in "
                            f"the same chain {key}",
                            "supersedes_reference",
                            record["record_key"],
                        )
                    )
            if index + 1 < len(ordered):
                next_effective = ordered[index + 1]["effective_date"]
                if record["evaluation_date"] >= next_effective:
                    errors.append(
                        _issue(
                            ProvenanceErrorCode.FUTURE_REVISION_BACKFILL_DETECTED,
                            "historical evaluation selects an old version "
                            "after a revision became effective",
                            "evaluation_date,revision_version",
                            record["record_key"],
                        )
                    )


def _build_lineage(
    record: dict[str, Any],
    configuration: Mapping[str, Any],
    errors: list[LineageIssue],
) -> FinancialObservationLineage | None:
    audit: TimingAudit = record["timing_audit"]
    try:
        configuration_hash = compute_configuration_hash(
            configuration,
            timing_policy_version=audit.timing_policy_version,
            trading_calendar_version=audit.trading_calendar_version,
            timezone=audit.timezone,
        )
    except (TypeError, ValueError) as exc:
        errors.append(
            _issue(
                ProvenanceErrorCode.INVALID_LINEAGE_INPUT,
                f"configuration is not hashable: {exc}",
                "configuration",
                record["record_key"],
            )
        )
        return None

    lineage_id = _versioned_hash(
        "lineage_id",
        {
            "evaluation_date": record["evaluation_date"],
            "code": record["code"],
            "factor_id": record["factor_id"],
            "report_period": record["report_period"],
            "effective_date": record["effective_date"],
            "source_provider": record["source_provider"],
            "source_dataset": record["source_dataset"],
            "source_snapshot_id": record["source_snapshot_id"],
            "source_reference": (
                record["source_record_id"],
                record["announcement_id"],
            ),
            "financial_statement_version":
                record["financial_statement_version"],
            "revision_version": record["revision_version"],
        },
    )
    fields = {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "lineage_id": lineage_id,
        "evaluation_date": record["evaluation_date"],
        "code": record["code"],
        "factor_id": record["factor_id"],
        "report_period": record["report_period"],
        "publish_date": record["publish_date"],
        "effective_date": record["effective_date"],
        "effective_date_policy_version": audit.timing_policy_version,
        "trading_calendar_version": audit.trading_calendar_version,
        "path_type": record["path_type"],
        "source_provider": record["source_provider"],
        "source_dataset": record["source_dataset"],
        "source_snapshot_id": record["source_snapshot_id"],
        "source_as_of_version": record["source_as_of_version"],
        "source_snapshot_fingerprint":
            record["source_snapshot_fingerprint"],
        "source_record_id": record["source_record_id"],
        "announcement_id": record["announcement_id"],
        "financial_statement_version":
            record["financial_statement_version"],
        "revision_version": record["revision_version"],
        "supersedes_reference": record["supersedes_reference"],
        "transformation_reference": record["transformation_reference"],
        "formula_reference": record["formula_reference"],
        "upstream_calculation_reference":
            record["upstream_calculation_reference"],
        "source_input_hash": record["source_input_hash"],
        "factor_value_hash": record["factor_value_hash"],
        "configuration_hash": configuration_hash,
        "conflict_status": "none",
        "warnings": (),
    }
    content_hash = _versioned_hash("lineage_content", fields)
    return FinancialObservationLineage(
        **fields,
        content_hash=content_hash,
    )


def _build_reference(
    records: tuple[FinancialObservationLineage, ...],
) -> ObservationLineageReference:
    content_hash = _versioned_hash(
        "sidecar",
        [record.to_dict() for record in records],
    )
    return ObservationLineageReference(
        location=f"immutable://financial-lineage/{content_hash}.json",
        schema_version=LINEAGE_SCHEMA_VERSION,
        row_count=len(records),
        index_fields=LINEAGE_INDEX_FIELDS,
        content_hash=content_hash,
        records=records,
    )


def _snapshot_objects(
    records: list[dict[str, Any]],
) -> tuple[SourceSnapshotFingerprint, ...]:
    unique = {
        (
            record["source_provider"],
            record["source_dataset"],
            record["source_snapshot_id"],
            record["source_as_of_version"],
            record["source_snapshot_fingerprint"],
        )
        for record in records
    }
    return tuple(
        SourceSnapshotFingerprint(
            provider=item[0],
            dataset=item[1],
            snapshot_id=item[2],
            as_of_version=item[3],
            fingerprint=item[4],
        )
        for item in sorted(unique)
    )


def _build_audit(
    *,
    normalized: list[dict[str, Any]],
    total_observations: int,
    complete_count: int,
    errors: tuple[LineageIssue, ...],
    warnings: tuple[LineageIssue, ...],
    snapshots: tuple[SourceSnapshotFingerprint, ...],
    input_fingerprint: str,
) -> ProvenanceAudit:
    gate_status = (
        LineageGateStatus.BLOCKED.value
        if errors
        else LineageGateStatus.READY.value
    )
    revision_count = sum(
        record["revision_version"].lower()
        not in {"original", "initial", "v1"}
        for record in normalized
    )
    conflict_codes = {
        ProvenanceErrorCode.MULTISOURCE_CONFLICT.value,
        ProvenanceErrorCode.CROSS_SECURITY_LINEAGE_DETECTED.value,
        ProvenanceErrorCode.DUPLICATE_LINEAGE_KEY.value,
    }
    hash_codes = {
        ProvenanceErrorCode.SOURCE_INPUT_HASH_MISMATCH.value,
        ProvenanceErrorCode.FACTOR_VALUE_HASH_MISMATCH.value,
        ProvenanceErrorCode.SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH.value,
        ProvenanceErrorCode.CONFIGURATION_HASH_MISMATCH.value,
        ProvenanceErrorCode.CONTENT_HASH_MISMATCH.value,
    }
    providers = tuple(sorted({item.provider for item in snapshots}))
    datasets = tuple(
        sorted(f"{item.provider}/{item.dataset}" for item in snapshots)
    )
    snapshot_ids = tuple(
        sorted(
            f"{item.provider}/{item.dataset}/{item.snapshot_id}"
            f"@{item.as_of_version}#{item.fingerprint}"
            for item in snapshots
        )
    )
    base = {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "source_providers": providers,
        "source_datasets": datasets,
        "source_snapshots": snapshot_ids,
        "total_observations": total_observations,
        "lineage_complete_count": complete_count,
        "lineage_incomplete_count": total_observations - complete_count,
        "revision_count": revision_count,
        "conflict_count": sum(
            issue.code in conflict_codes for issue in errors
        ),
        "hash_mismatch_count": sum(
            issue.code in hash_codes for issue in errors
        ),
        "gate_status": gate_status,
        "errors": [issue.to_dict() for issue in errors],
        "warnings": [issue.to_dict() for issue in warnings],
    }
    run_id = _versioned_hash(
        "provenance_run",
        {"input_fingerprint": input_fingerprint, "audit": base},
    )
    content_fields = {**base, "run_id": run_id}
    content_hash = _versioned_hash("provenance_audit", content_fields)
    return ProvenanceAudit(
        schema_version=LINEAGE_SCHEMA_VERSION,
        run_id=run_id,
        source_providers=providers,
        source_datasets=datasets,
        source_snapshots=snapshot_ids,
        total_observations=total_observations,
        lineage_complete_count=complete_count,
        lineage_incomplete_count=total_observations - complete_count,
        revision_count=revision_count,
        conflict_count=base["conflict_count"],
        hash_mismatch_count=base["hash_mismatch_count"],
        gate_status=gate_status,
        errors=errors,
        warnings=warnings,
        content_hash=content_hash,
    )


def _blocked_empty(errors: list[LineageIssue]) -> FinancialProvenanceResult:
    canonical_errors = tuple(_deduplicate_issues(errors))
    audit = _build_audit(
        normalized=[],
        total_observations=0,
        complete_count=0,
        errors=canonical_errors,
        warnings=(),
        snapshots=(),
        input_fingerprint=_versioned_hash("empty_input", None),
    )
    return FinancialProvenanceResult(
        provenance_audit=audit,
        observation_lineage_reference=None,
        source_snapshot_fingerprints=(),
        lineage_records=(),
    )


def _issue(
    code: ProvenanceErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> LineageIssue:
    return LineageIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
    )


def _deduplicate_issues(
    issues: Iterable[LineageIssue],
) -> list[LineageIssue]:
    unique = {
        (item.code, item.message, item.field_name, item.record_key): item
        for item in issues
    }
    return [
        unique[key]
        for key in sorted(
            unique,
            key=lambda item: tuple("" if part is None else part for part in item),
        )
    ]


def _key_counts(
    rows: Iterable[dict[str, Any]],
    fields: tuple[str, ...],
) -> dict[tuple[Any, ...], int]:
    counts: dict[tuple[Any, ...], int] = {}
    for row in rows:
        if all(field in row for field in fields):
            key = tuple(row[field] for field in fields)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _format_key(fields: tuple[str, ...], key: tuple[Any, ...]) -> str:
    return "|".join(
        f"{field_name}={value}"
        for field_name, value in zip(fields, key)
    )


def _source_sort_key(record: dict[str, Any]) -> tuple[str, ...]:
    return (
        record["evaluation_date"],
        record["code"],
        record["factor_id"],
        record["report_period"],
        record["effective_date"],
        record["source_provider"],
        record["source_dataset"],
        record["source_record_id"],
        record["announcement_id"],
    )


def _governed_input_fingerprint(
    records: list[dict[str, Any]],
    configuration: Mapping[str, Any],
) -> str:
    """Fingerprint only FIN-R1B inputs, excluding order and future labels."""

    excluded = {"record_key"}
    canonical_records = [
        {
            key: value
            for key, value in record.items()
            if key not in excluded
        }
        for record in records
    ]
    canonical_records.sort(
        key=lambda item: json.dumps(
            _canonical_json_value(item),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return _versioned_hash(
        "builder_governed_input",
        {
            "source_records": canonical_records,
            "configuration": configuration,
        },
    )


def _record_key(record: FinancialObservationLineage) -> str:
    return _format_key(
        LINEAGE_INDEX_FIELDS,
        (record.evaluation_date, record.code, record.factor_id),
    )


_FUTURE_LABEL_KEYS = frozenset(
    {
        "future_label",
        "future_return",
        "forward_return",
        "target",
        "outcome",
        "realized_return",
    }
)


def _find_future_label_fields(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            item_path = f"{path}.{name}" if path else name
            if name.lower() in _FUTURE_LABEL_KEYS:
                found.append(item_path)
            found.extend(_find_future_label_fields(item, item_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            found.extend(_find_future_label_fields(item, item_path))
    return sorted(found)


def _versioned_hash(domain: str, value: Any) -> str:
    payload = {
        "hash_contract_version": HASH_CONTRACT_VERSION,
        "domain": domain,
        "payload": _canonical_json_value(value),
    }
    encoded = json.dumps(
        payload,
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
    if isinstance(value, Enum):
        return _canonical_json_value(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not canonical JSON")
        return value
    if isinstance(value, TimingAudit):
        return _canonical_json_value(value.to_dict())
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _canonical_json_value(value.to_dict())
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


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


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
