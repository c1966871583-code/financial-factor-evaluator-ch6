"""FIN-R1C: independent PIT universe, factor sample, and label left joins.

Sample formation is completed before label records are inspected.  The module
consumes FIN-R1A dates through ``FinancialBatch`` and FIN-R1B lineage records;
it does not derive effective dates, rewrite provenance, execute formulas, or
access network/database services.
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
from .financial_lineage import (
    NOT_APPLICABLE,
    FinancialObservationLineage,
    ObservationLineageReference,
    compute_factor_value_hash,
    recompute_lineage_content_hash,
)


SAMPLE_SCHEMA_VERSION = "FinancialSampleFormation-v1.0"
LABEL_JOIN_SCHEMA_VERSION = "FinancialLabelJoinAudit-v1.0"
HASH_CONTRACT_VERSION = "FIN-R1C-HASH-v1.0"
SAMPLE_INDEX_FIELDS = ("evaluation_date", "code", "factor_id")
PAIRING_INDEX_FIELDS = (
    "evaluation_date",
    "code",
    "factor_id",
    "validation_track",
)


class ValidationTrack(str, Enum):
    MARKET_RETURN = "M"
    FINANCIAL_TARGET = "F"
    RISK_LABEL = "R"


class SampleGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class SampleErrorCode(str, Enum):
    INDEPENDENT_SAMPLE_DEFINITION_MISSING = (
        "INDEPENDENT_SAMPLE_DEFINITION_MISSING"
    )
    PIT_EFFECTIVE_DATE_UNVERIFIED = "PIT_EFFECTIVE_DATE_UNVERIFIED"
    PIT_PROVENANCE_INCOMPLETE = "PIT_PROVENANCE_INCOMPLETE"
    PIT_SOURCE_VERSION_CONFLICT = "PIT_SOURCE_VERSION_CONFLICT"
    OBSERVATION_LINEAGE_INCOMPLETE = "OBSERVATION_LINEAGE_INCOMPLETE"
    PIT_OBSERVATION_NOT_AVAILABLE = "PIT_OBSERVATION_NOT_AVAILABLE"
    STALE_FINANCIAL_OBSERVATION = "STALE_FINANCIAL_OBSERVATION"
    FACTOR_NOT_APPLICABLE = "FACTOR_NOT_APPLICABLE"
    SECURITY_NOT_IN_UNIVERSE = "SECURITY_NOT_IN_UNIVERSE"
    MISSING_FINANCIAL_VALUE = "MISSING_FINANCIAL_VALUE"
    LABEL_TIME_LEAKAGE = "LABEL_TIME_LEAKAGE"
    NON_CONSECUTIVE_FINANCIAL_TARGET = "NON_CONSECUTIVE_FINANCIAL_TARGET"
    DUPLICATE_UNIVERSE_KEY = "DUPLICATE_UNIVERSE_KEY"
    DUPLICATE_LABEL_KEY = "DUPLICATE_LABEL_KEY"
    LABEL_REFERENCE_NOT_FOUND = "LABEL_REFERENCE_NOT_FOUND"
    INVALID_SAMPLE_INPUT = "INVALID_SAMPLE_INPUT"
    INPUT_MUTATION_DETECTED = "INPUT_MUTATION_DETECTED"
    NONDETERMINISTIC_SAMPLE_OUTPUT = "NONDETERMINISTIC_SAMPLE_OUTPUT"
    CONTENT_HASH_MISMATCH = "CONTENT_HASH_MISMATCH"


class SampleLookupError(LookupError):
    def __init__(
        self,
        code: SampleErrorCode,
        message: str,
        *,
        lookup_key: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.code = code.value
        self.lookup_key = lookup_key


@dataclass(frozen=True)
class SampleFormationConfig:
    evaluation_dates: tuple[str, ...]
    evaluation_calendar_version: str
    universe_version: str
    freshness_max_age_days: int
    sample_policy_version: str = "FIN-R1C-PIT-SAMPLE-v1.0"
    applicability_policy_version: str = "FIN-R1C-APPLICABILITY-v1.0"
    supported_tracks: tuple[str, ...] = ("M", "F", "R")

    def __post_init__(self) -> None:
        normalized = tuple(sorted({_date_iso(item) for item in self.evaluation_dates}))
        if not normalized:
            raise ValueError("evaluation_dates must be non-empty")
        if len(normalized) != len(self.evaluation_dates):
            raise ValueError("evaluation_dates must not contain duplicates")
        for field_name in (
            "evaluation_calendar_version",
            "universe_version",
            "sample_policy_version",
            "applicability_policy_version",
        ):
            _required_text(getattr(self, field_name), field_name)
        if (
            isinstance(self.freshness_max_age_days, bool)
            or not isinstance(self.freshness_max_age_days, int)
            or self.freshness_max_age_days < 0
        ):
            raise ValueError("freshness_max_age_days must be a non-negative int")
        tracks = tuple(item.value for item in ValidationTrack)
        if tuple(self.supported_tracks) != tracks:
            raise ValueError("supported_tracks must be exactly ('M', 'F', 'R')")
        object.__setattr__(self, "evaluation_dates", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_dates": list(self.evaluation_dates),
            "evaluation_calendar_version": self.evaluation_calendar_version,
            "universe_version": self.universe_version,
            "freshness_max_age_days": self.freshness_max_age_days,
            "sample_policy_version": self.sample_policy_version,
            "applicability_policy_version":
                self.applicability_policy_version,
            "supported_tracks": list(self.supported_tracks),
        }


@dataclass(frozen=True)
class SampleIssue:
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
class FactorSampleRecord:
    schema_version: str
    sample_id: str
    evaluation_date: str
    code: str
    factor_id: str
    evaluation_calendar_version: str
    universe_version: str
    universe_record_id: str
    in_universe: bool
    factor_applicable: bool
    pit_available: bool
    report_period: str
    publish_date: str
    effective_date: str
    financial_statement_version: str
    financial_lineage_id: str
    financial_lineage_content_hash: str
    raw_pit_factor_value: float | None
    factor_value_hash: str
    financial_age_days: int | None
    freshness_status: str
    factor_sample_mask: bool
    exclusion_reason_codes: tuple[str, ...]
    configuration_hash: str
    content_hash: str

    def to_dict(self, *, include_content_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "evaluation_date": self.evaluation_date,
            "code": self.code,
            "factor_id": self.factor_id,
            "evaluation_calendar_version":
                self.evaluation_calendar_version,
            "universe_version": self.universe_version,
            "universe_record_id": self.universe_record_id,
            "in_universe": self.in_universe,
            "factor_applicable": self.factor_applicable,
            "pit_available": self.pit_available,
            "report_period": self.report_period,
            "publish_date": self.publish_date,
            "effective_date": self.effective_date,
            "financial_statement_version":
                self.financial_statement_version,
            "financial_lineage_id": self.financial_lineage_id,
            "financial_lineage_content_hash":
                self.financial_lineage_content_hash,
            "raw_pit_factor_value": self.raw_pit_factor_value,
            "factor_value_hash": self.factor_value_hash,
            "financial_age_days": self.financial_age_days,
            "freshness_status": self.freshness_status,
            "factor_sample_mask": self.factor_sample_mask,
            "exclusion_reason_codes": list(self.exclusion_reason_codes),
            "configuration_hash": self.configuration_hash,
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class LabelPairingRecord:
    schema_version: str
    pairing_id: str
    sample_id: str
    evaluation_date: str
    code: str
    factor_id: str
    validation_track: str
    factor_sample_mask: bool
    label_available: bool
    valid_pair_mask: bool
    label_id: str
    label_type: str
    label_value: str | float | int | bool | None
    label_publish_date: str
    label_effective_date: str
    label_available_at: str
    label_source_record_id: str
    label_source: str
    label_version: str
    label_snapshot_fingerprint: str
    target_report_period: str
    exclusion_reason_codes: tuple[str, ...]
    content_hash: str

    def to_dict(self, *, include_content_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "pairing_id": self.pairing_id,
            "sample_id": self.sample_id,
            "evaluation_date": self.evaluation_date,
            "code": self.code,
            "factor_id": self.factor_id,
            "validation_track": self.validation_track,
            "factor_sample_mask": self.factor_sample_mask,
            "label_available": self.label_available,
            "valid_pair_mask": self.valid_pair_mask,
            "label_id": self.label_id,
            "label_type": self.label_type,
            "label_value": self.label_value,
            "label_publish_date": self.label_publish_date,
            "label_effective_date": self.label_effective_date,
            "label_available_at": self.label_available_at,
            "label_source_record_id": self.label_source_record_id,
            "label_source": self.label_source,
            "label_version": self.label_version,
            "label_snapshot_fingerprint":
                self.label_snapshot_fingerprint,
            "target_report_period": self.target_report_period,
            "exclusion_reason_codes": list(self.exclusion_reason_codes),
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class CoverageRecord:
    evaluation_date: str
    validation_track: str
    universe_count: int
    pit_available_count: int
    non_stale_count: int
    valid_factor_count: int
    label_available_count: int
    valid_pair_count: int
    pit_coverage: float
    freshness_coverage: float
    factor_valid_coverage: float
    label_coverage: float
    pair_coverage: float
    exclusion_counts_by_reason: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date,
            "validation_track": self.validation_track,
            "universe_count": self.universe_count,
            "pit_available_count": self.pit_available_count,
            "non_stale_count": self.non_stale_count,
            "valid_factor_count": self.valid_factor_count,
            "label_available_count": self.label_available_count,
            "valid_pair_count": self.valid_pair_count,
            "pit_coverage": self.pit_coverage,
            "freshness_coverage": self.freshness_coverage,
            "factor_valid_coverage": self.factor_valid_coverage,
            "label_coverage": self.label_coverage,
            "pair_coverage": self.pair_coverage,
            "exclusion_counts_by_reason": dict(
                self.exclusion_counts_by_reason
            ),
        }


@dataclass(frozen=True)
class SampleFormationReference:
    location: str
    schema_version: str
    row_count: int
    index_fields: tuple[str, ...]
    sample_fingerprint: str
    content_hash: str
    records: tuple[FactorSampleRecord, ...]

    def lookup(
        self,
        evaluation_date: Any,
        code: Any,
        factor_id: Any,
    ) -> FactorSampleRecord:
        key = (
            _date_iso(evaluation_date),
            _required_text(code, "code"),
            _required_text(factor_id, "factor_id"),
        )
        matches = [
            item
            for item in self.records
            if (item.evaluation_date, item.code, item.factor_id) == key
        ]
        if len(matches) != 1:
            raise SampleLookupError(
                SampleErrorCode.OBSERVATION_LINEAGE_INCOMPLETE,
                f"expected one factor sample for {key}, found {len(matches)}",
                lookup_key=key,
            )
        return matches[0]

    def to_dict(self, *, include_records: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "location": self.location,
            "schema_version": self.schema_version,
            "row_count": self.row_count,
            "index_fields": list(self.index_fields),
            "sample_fingerprint": self.sample_fingerprint,
            "content_hash": self.content_hash,
        }
        if include_records:
            payload["records"] = [item.to_dict() for item in self.records]
        return payload


@dataclass(frozen=True)
class LabelJoinAudit:
    location: str
    schema_version: str
    row_count: int
    index_fields: tuple[str, ...]
    content_hash: str
    records: tuple[LabelPairingRecord, ...]

    def lookup(
        self,
        evaluation_date: Any,
        code: Any,
        factor_id: Any,
        validation_track: Any,
    ) -> LabelPairingRecord:
        key = (
            _date_iso(evaluation_date),
            _required_text(code, "code"),
            _required_text(factor_id, "factor_id"),
            _track_value(validation_track),
        )
        matches = [
            item
            for item in self.records
            if (
                item.evaluation_date,
                item.code,
                item.factor_id,
                item.validation_track,
            ) == key
        ]
        if len(matches) != 1:
            raise SampleLookupError(
                SampleErrorCode.LABEL_REFERENCE_NOT_FOUND,
                f"expected one label pairing for {key}, found {len(matches)}",
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
            payload["records"] = [item.to_dict() for item in self.records]
        return payload


@dataclass(frozen=True)
class SampleGateResult:
    overall_status: str
    errors: tuple[SampleIssue, ...]
    warnings: tuple[SampleIssue, ...]
    total_universe_rows: int
    factor_sample_count: int
    valid_pair_count: int
    run_id: str
    content_hash: str

    def to_dict(self, *, include_content_hash: bool = True) -> dict[str, Any]:
        payload = {
            "overall_status": self.overall_status,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
            "total_universe_rows": self.total_universe_rows,
            "factor_sample_count": self.factor_sample_count,
            "valid_pair_count": self.valid_pair_count,
            "run_id": self.run_id,
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class FinancialSampleResult:
    gate_result: SampleGateResult
    sample_reference: SampleFormationReference | None
    label_join_audit: LabelJoinAudit | None
    coverage_funnel: tuple[CoverageRecord, ...]
    coverage_content_hash: str
    sample_records: tuple[FactorSampleRecord, ...]
    pairing_records: tuple[LabelPairingRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_result": self.gate_result.to_dict(),
            "sample_reference": (
                self.sample_reference.to_dict()
                if self.sample_reference is not None
                else None
            ),
            "label_join_audit": (
                self.label_join_audit.to_dict()
                if self.label_join_audit is not None
                else None
            ),
            "coverage_funnel": [
                item.to_dict() for item in self.coverage_funnel
            ],
            "coverage_content_hash": self.coverage_content_hash,
            "sample_record_count": len(self.sample_records),
            "pairing_record_count": len(self.pairing_records),
        }


def recompute_sample_content_hash(record: FactorSampleRecord) -> str:
    return _versioned_hash(
        "factor_sample_record",
        record.to_dict(include_content_hash=False),
    )


def recompute_pairing_content_hash(record: LabelPairingRecord) -> str:
    return _versioned_hash(
        "label_pairing_record",
        record.to_dict(include_content_hash=False),
    )


def compute_sample_fingerprint(
    records: Iterable[FactorSampleRecord],
) -> str:
    ordered = sorted(
        records,
        key=lambda item: (
            item.evaluation_date,
            item.code,
            item.factor_id,
        ),
    )
    return _versioned_hash(
        "factor_sample_fingerprint",
        [item.to_dict() for item in ordered],
    )


def form_financial_sample(
    batch: FinancialBatch,
    lineage_reference: ObservationLineageReference,
    universe_records: Iterable[Mapping[str, Any]],
    label_records: Iterable[Mapping[str, Any]],
    *,
    configuration: SampleFormationConfig,
) -> FinancialSampleResult:
    """Form the independent factor sample, then left-join labels by track."""

    if not isinstance(batch, FinancialBatch):
        return _blocked_empty(
            _issue(
                SampleErrorCode.INVALID_SAMPLE_INPUT,
                "batch must be a FinancialBatch",
                "batch",
            )
        )
    if not isinstance(lineage_reference, ObservationLineageReference):
        return _blocked_empty(
            _issue(
                SampleErrorCode.PIT_PROVENANCE_INCOMPLETE,
                "lineage_reference must be a FIN-R1B reference",
                "lineage_reference",
            )
        )
    if not isinstance(configuration, SampleFormationConfig):
        return _blocked_empty(
            _issue(
                SampleErrorCode.INVALID_SAMPLE_INPUT,
                "configuration must be a SampleFormationConfig",
                "configuration",
            )
        )

    try:
        raw_universe = list(universe_records)
        raw_labels = list(label_records)
        universe = copy.deepcopy(raw_universe)
        labels = copy.deepcopy(raw_labels)
        input_before = _versioned_hash(
            "input_mutation_guard",
            {
                "universe_records": raw_universe,
                "label_records": raw_labels,
                "configuration": configuration.to_dict(),
            },
        )
    except Exception as exc:
        return _blocked_empty(
            _issue(
                SampleErrorCode.INVALID_SAMPLE_INPUT,
                f"inputs are not canonicalizable: {type(exc).__name__}",
                "universe_records,label_records",
            )
        )

    errors: list[SampleIssue] = []
    warnings: list[SampleIssue] = []
    normalized_universe = _normalize_universe(
        universe, configuration, errors
    )
    if not normalized_universe:
        errors.append(
            _issue(
                SampleErrorCode.INDEPENDENT_SAMPLE_DEFINITION_MISSING,
                "historical universe must contain at least one valid row",
                "universe_records",
            )
        )

    _validate_calendar_coverage(
        normalized_universe, configuration, errors
    )
    lineages = _validate_lineage_reference(
        lineage_reference, batch.factor_id, errors
    )
    batch_rows = _normalize_batch(batch, errors)
    samples = _build_samples(
        batch_rows=batch_rows,
        lineages=lineages,
        universe=normalized_universe,
        configuration=configuration,
        factor_id=batch.factor_id,
        errors=errors,
    )
    samples.sort(
        key=lambda item: (
            item.evaluation_date,
            item.code,
            item.factor_id,
        )
    )

    sample_keys = [
        (item.evaluation_date, item.code, item.factor_id)
        for item in samples
    ]
    if len(sample_keys) != len(set(sample_keys)):
        errors.append(
            _issue(
                SampleErrorCode.DUPLICATE_UNIVERSE_KEY,
                "sample output contains duplicate public keys",
                ",".join(SAMPLE_INDEX_FIELDS),
            )
        )

    # This is the hard boundary: labels are not read until sample records and
    # their fingerprint have been finalized.
    sample_fingerprint = compute_sample_fingerprint(samples)
    normalized_labels = _normalize_labels(
        labels,
        configuration=configuration,
        factor_id=batch.factor_id,
        errors=errors,
    )
    pairings = _left_join_labels(
        samples=samples,
        labels=normalized_labels,
        errors=errors,
        warnings=warnings,
    )
    pairings.sort(
        key=lambda item: (
            item.evaluation_date,
            item.code,
            item.factor_id,
            item.validation_track,
        )
    )
    coverage = _coverage_funnel(samples, pairings, configuration)

    try:
        input_after = _versioned_hash(
            "input_mutation_guard",
            {
                "universe_records": raw_universe,
                "label_records": raw_labels,
                "configuration": configuration.to_dict(),
            },
        )
        if input_before != input_after:
            errors.append(
                _issue(
                    SampleErrorCode.INPUT_MUTATION_DETECTED,
                    "input objects changed while the sample was formed",
                )
            )
    except Exception:
        errors.append(
            _issue(
                SampleErrorCode.INPUT_MUTATION_DETECTED,
                "input objects changed into non-canonical values",
            )
        )

    errors = _deduplicate_issues(errors)
    warnings = _deduplicate_issues(warnings)
    ready = not errors
    published_samples = tuple(samples) if ready else ()
    published_pairings = tuple(pairings) if ready else ()
    published_coverage = tuple(coverage) if ready else ()
    coverage_content_hash = _versioned_hash(
        "coverage_funnel",
        [item.to_dict() for item in published_coverage],
    )
    sample_reference = (
        _sample_reference(published_samples, sample_fingerprint)
        if ready
        else None
    )
    label_join_audit = (
        _label_join_audit(published_pairings) if ready else None
    )
    gate = _gate_result(
        errors=tuple(errors),
        warnings=tuple(warnings),
        total_universe_rows=len(normalized_universe),
        factor_sample_count=sum(item.factor_sample_mask for item in samples),
        valid_pair_count=sum(item.valid_pair_mask for item in pairings),
        configuration=configuration,
        sample_fingerprint=sample_fingerprint,
        label_join_hash=(
            label_join_audit.content_hash
            if label_join_audit is not None
            else _versioned_hash(
                "blocked_label_join",
                [item.to_dict() for item in pairings],
            )
        ),
        coverage_content_hash=coverage_content_hash,
    )
    return FinancialSampleResult(
        gate_result=gate,
        sample_reference=sample_reference,
        label_join_audit=label_join_audit,
        coverage_funnel=published_coverage,
        coverage_content_hash=coverage_content_hash,
        sample_records=published_samples,
        pairing_records=published_pairings,
    )


def _normalize_universe(
    records: list[Any],
    configuration: SampleFormationConfig,
    errors: list[SampleIssue],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    counts: dict[tuple[str, str], int] = {}
    for index, item in enumerate(records):
        record_key = f"universe_records[{index}]"
        if not isinstance(item, Mapping):
            errors.append(
                _issue(
                    SampleErrorCode.INVALID_SAMPLE_INPUT,
                    "universe row must be a mapping",
                    "universe_records",
                    record_key,
                )
            )
            continue
        record = dict(item)
        try:
            evaluation_date = _date_iso(record.get("evaluation_date"))
            code = _required_text(record.get("code"), "code")
            universe_record_id = _required_text(
                record.get("universe_record_id"), "universe_record_id"
            )
            in_universe = _required_bool(
                record.get("in_universe"), "in_universe"
            )
            factor_applicable = _required_bool(
                record.get("factor_applicable"), "factor_applicable"
            )
        except (TypeError, ValueError) as exc:
            errors.append(
                _issue(
                    SampleErrorCode.INDEPENDENT_SAMPLE_DEFINITION_MISSING,
                    str(exc),
                    "evaluation_date,code,universe_record_id,"
                    "in_universe,factor_applicable",
                    record_key,
                )
            )
            continue
        if record.get("synthetic_test_only") is not True:
            errors.append(
                _issue(
                    SampleErrorCode.INVALID_SAMPLE_INPUT,
                    "FIN-R1C accepts only synthetic_test_only=true rows",
                    "synthetic_test_only",
                    record_key,
                )
            )
            continue
        if evaluation_date not in configuration.evaluation_dates:
            errors.append(
                _issue(
                    SampleErrorCode.INDEPENDENT_SAMPLE_DEFINITION_MISSING,
                    "universe evaluation_date is not in the frozen calendar",
                    "evaluation_date",
                    record_key,
                )
            )
        listed_date = _optional_date(record.get("listed_date"))
        delisted_date = _optional_date(record.get("delisted_date"))
        if in_universe and (
            (listed_date is not None and evaluation_date < listed_date)
            or (delisted_date is not None and evaluation_date > delisted_date)
        ):
            errors.append(
                _issue(
                    SampleErrorCode.INDEPENDENT_SAMPLE_DEFINITION_MISSING,
                    "in_universe=true conflicts with listing boundaries",
                    "in_universe,listed_date,delisted_date",
                    record_key,
                )
            )
        key = (evaluation_date, code)
        counts[key] = counts.get(key, 0) + 1
        normalized.append(
            {
                "evaluation_date": evaluation_date,
                "code": code,
                "universe_record_id": universe_record_id,
                "in_universe": in_universe,
                "factor_applicable": factor_applicable,
                "listed_date": listed_date,
                "delisted_date": delisted_date,
            }
        )
    for key, count in sorted(counts.items()):
        if count > 1:
            errors.append(
                _issue(
                    SampleErrorCode.DUPLICATE_UNIVERSE_KEY,
                    f"historical universe key occurs {count} times",
                    "evaluation_date,code",
                    f"evaluation_date={key[0]}|code={key[1]}",
                )
            )
    return sorted(
        normalized,
        key=lambda item: (item["evaluation_date"], item["code"]),
    )


def _validate_calendar_coverage(
    universe: list[dict[str, Any]],
    configuration: SampleFormationConfig,
    errors: list[SampleIssue],
) -> None:
    dates_with_rows = {item["evaluation_date"] for item in universe}
    dates_with_active_security = {
        item["evaluation_date"] for item in universe if item["in_universe"]
    }
    for evaluation_date in configuration.evaluation_dates:
        if evaluation_date not in dates_with_rows:
            errors.append(
                _issue(
                    SampleErrorCode.INDEPENDENT_SAMPLE_DEFINITION_MISSING,
                    "evaluation date has no historical universe rows",
                    "evaluation_dates",
                    evaluation_date,
                )
            )
        elif evaluation_date not in dates_with_active_security:
            errors.append(
                _issue(
                    SampleErrorCode.INDEPENDENT_SAMPLE_DEFINITION_MISSING,
                    "evaluation date has no active historical securities",
                    "in_universe",
                    evaluation_date,
                )
            )


def _validate_lineage_reference(
    reference: ObservationLineageReference,
    factor_id: str,
    errors: list[SampleIssue],
) -> dict[tuple[str, str, str, str], FinancialObservationLineage]:
    if reference.row_count != len(reference.records):
        errors.append(
            _issue(
                SampleErrorCode.PIT_PROVENANCE_INCOMPLETE,
                "FIN-R1B reference row_count does not match records",
                "lineage_reference.row_count",
            )
        )
    by_key: dict[
        tuple[str, str, str, str], FinancialObservationLineage
    ] = {}
    counts: dict[tuple[str, str, str, str], int] = {}
    for item in reference.records:
        key = (
            item.code,
            item.factor_id,
            item.report_period,
            item.effective_date,
        )
        counts[key] = counts.get(key, 0) + 1
        if item.factor_id != factor_id:
            errors.append(
                _issue(
                    SampleErrorCode.PIT_PROVENANCE_INCOMPLETE,
                    "lineage factor_id differs from FinancialBatch",
                    "factor_id",
                    "|".join(key),
                )
            )
        if item.content_hash != recompute_lineage_content_hash(item):
            errors.append(
                _issue(
                    SampleErrorCode.CONTENT_HASH_MISMATCH,
                    "FIN-R1B lineage content hash mismatch",
                    "content_hash",
                    "|".join(key),
                )
            )
        by_key[key] = item
    for key, count in sorted(counts.items()):
        if count > 1:
            errors.append(
                _issue(
                    SampleErrorCode.PIT_SOURCE_VERSION_CONFLICT,
                    f"lineage observation key occurs {count} times",
                    "code,factor_id,report_period,effective_date",
                    "|".join(key),
                )
            )
    return by_key


def _normalize_batch(
    batch: FinancialBatch,
    errors: list[SampleIssue],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in batch.get_frame().iterrows():
        record_key = f"FinancialBatch[{index}]"
        try:
            report_period = _date_iso(row["report_period"])
            publish_date = _date_iso(row["publish_date"])
            effective_date = _date_iso(row["effective_date"])
            if not report_period <= publish_date <= effective_date:
                raise ValueError(
                    "report_period <= publish_date <= effective_date "
                    "must hold"
                )
            factor_value = _finite_number(row["factor_value"])
            rows.append(
                {
                    "code": _required_text(row["code"], "code"),
                    "factor_id": batch.factor_id,
                    "report_period": report_period,
                    "publish_date": publish_date,
                    "effective_date": effective_date,
                    "factor_value": factor_value,
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(
                _issue(
                    SampleErrorCode.PIT_EFFECTIVE_DATE_UNVERIFIED,
                    f"invalid FinancialBatch row: {exc}",
                    "FinancialBatch",
                    record_key,
                )
            )
    return rows


def _build_samples(
    *,
    batch_rows: list[dict[str, Any]],
    lineages: dict[tuple[str, str, str, str], FinancialObservationLineage],
    universe: list[dict[str, Any]],
    configuration: SampleFormationConfig,
    factor_id: str,
    errors: list[SampleIssue],
) -> list[FactorSampleRecord]:
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in batch_rows:
        by_code.setdefault(row["code"], []).append(row)
    configuration_hash = _versioned_hash(
        "sample_configuration", configuration.to_dict()
    )
    samples: list[FactorSampleRecord] = []
    for universe_row in universe:
        evaluation_date = universe_row["evaluation_date"]
        code = universe_row["code"]
        exclusions: list[str] = []
        if not universe_row["in_universe"]:
            exclusions.append(
                SampleErrorCode.SECURITY_NOT_IN_UNIVERSE.value
            )
        if not universe_row["factor_applicable"]:
            exclusions.append(SampleErrorCode.FACTOR_NOT_APPLICABLE.value)

        candidates = [
            item
            for item in by_code.get(code, [])
            if item["effective_date"] <= evaluation_date
        ]
        selected = (
            max(
                candidates,
                key=lambda item: (
                    item["report_period"],
                    item["effective_date"],
                    item["publish_date"],
                ),
            )
            if candidates
            else None
        )
        lineage: FinancialObservationLineage | None = None
        age_days: int | None = None
        freshness_status = "not_available"
        if selected is None:
            exclusions.append(
                SampleErrorCode.PIT_OBSERVATION_NOT_AVAILABLE.value
            )
        else:
            lineage_key = (
                selected["code"],
                selected["factor_id"],
                selected["report_period"],
                selected["effective_date"],
            )
            lineage = lineages.get(lineage_key)
            if lineage is None:
                errors.append(
                    _issue(
                        SampleErrorCode.OBSERVATION_LINEAGE_INCOMPLETE,
                        "selected PIT observation has no FIN-R1B lineage",
                        "lineage_reference",
                        "|".join(lineage_key),
                    )
                )
            elif (
                lineage.factor_value_hash
                != compute_factor_value_hash(selected["factor_value"])
            ):
                errors.append(
                    _issue(
                        SampleErrorCode.CONTENT_HASH_MISMATCH,
                        "selected factor value differs from FIN-R1B hash",
                        "factor_value_hash",
                        "|".join(lineage_key),
                    )
                )
            age_days = (
                date.fromisoformat(evaluation_date)
                - date.fromisoformat(selected["effective_date"])
            ).days
            if age_days < 0:
                errors.append(
                    _issue(
                        SampleErrorCode.PIT_EFFECTIVE_DATE_UNVERIFIED,
                        "selected observation is not yet effective",
                        "effective_date",
                        f"{evaluation_date}|{code}",
                    )
                )
            elif age_days > configuration.freshness_max_age_days:
                freshness_status = "stale"
                exclusions.append(
                    SampleErrorCode.STALE_FINANCIAL_OBSERVATION.value
                )
            else:
                freshness_status = "fresh"

        mask = (
            universe_row["in_universe"]
            and universe_row["factor_applicable"]
            and selected is not None
            and lineage is not None
            and freshness_status == "fresh"
        )
        sample_id = _versioned_hash(
            "sample_id",
            {
                "evaluation_date": evaluation_date,
                "code": code,
                "factor_id": factor_id,
                "universe_version": configuration.universe_version,
                "sample_policy_version": configuration.sample_policy_version,
            },
        )
        fields = {
            "schema_version": SAMPLE_SCHEMA_VERSION,
            "sample_id": sample_id,
            "evaluation_date": evaluation_date,
            "code": code,
            "factor_id": factor_id,
            "evaluation_calendar_version":
                configuration.evaluation_calendar_version,
            "universe_version": configuration.universe_version,
            "universe_record_id": universe_row["universe_record_id"],
            "in_universe": universe_row["in_universe"],
            "factor_applicable": universe_row["factor_applicable"],
            "pit_available": selected is not None,
            "report_period": (
                selected["report_period"]
                if selected is not None
                else NOT_APPLICABLE
            ),
            "publish_date": (
                selected["publish_date"]
                if selected is not None
                else NOT_APPLICABLE
            ),
            "effective_date": (
                selected["effective_date"]
                if selected is not None
                else NOT_APPLICABLE
            ),
            "financial_statement_version": (
                lineage.financial_statement_version
                if lineage is not None
                else NOT_APPLICABLE
            ),
            "financial_lineage_id": (
                lineage.lineage_id
                if lineage is not None
                else NOT_APPLICABLE
            ),
            "financial_lineage_content_hash": (
                lineage.content_hash
                if lineage is not None
                else NOT_APPLICABLE
            ),
            "raw_pit_factor_value": (
                selected["factor_value"]
                if selected is not None
                else None
            ),
            "factor_value_hash": (
                compute_factor_value_hash(selected["factor_value"])
                if selected is not None
                else NOT_APPLICABLE
            ),
            "financial_age_days": age_days,
            "freshness_status": freshness_status,
            "factor_sample_mask": mask,
            "exclusion_reason_codes": tuple(sorted(set(exclusions))),
            "configuration_hash": configuration_hash,
        }
        content_hash = _versioned_hash("factor_sample_record", fields)
        samples.append(
            FactorSampleRecord(**fields, content_hash=content_hash)
        )
    return samples


def _normalize_labels(
    records: list[Any],
    *,
    configuration: SampleFormationConfig,
    factor_id: str,
    errors: list[SampleIssue],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    counts: dict[tuple[str, str, str, str], int] = {}
    required_fields = (
        "label_id",
        "label_type",
        "label_source_record_id",
        "label_source",
        "label_version",
        "label_snapshot_fingerprint",
    )
    for index, item in enumerate(records):
        record_key = f"label_records[{index}]"
        if not isinstance(item, Mapping):
            errors.append(
                _issue(
                    SampleErrorCode.INVALID_SAMPLE_INPUT,
                    "label row must be a mapping",
                    "label_records",
                    record_key,
                )
            )
            continue
        record = dict(item)
        try:
            evaluation_date = _date_iso(record.get("evaluation_date"))
            code = _required_text(record.get("code"), "code")
            item_factor_id = _required_text(
                record.get("factor_id"), "factor_id"
            )
            track = _track_value(record.get("validation_track"))
            label_publish_date = _date_iso(record.get("label_publish_date"))
            label_effective_date = _date_iso(
                record.get("label_effective_date")
            )
            label_available_at = _date_iso(record.get("label_available_at"))
            texts = {
                field_name: _required_text(record.get(field_name), field_name)
                for field_name in required_fields
            }
            label_value = _label_scalar(record.get("label_value"))
        except (TypeError, ValueError) as exc:
            errors.append(
                _issue(
                    SampleErrorCode.INVALID_SAMPLE_INPUT,
                    str(exc),
                    "label_records",
                    record_key,
                )
            )
            continue
        if record.get("synthetic_test_only") is not True:
            errors.append(
                _issue(
                    SampleErrorCode.INVALID_SAMPLE_INPUT,
                    "FIN-R1C accepts only synthetic_test_only=true labels",
                    "synthetic_test_only",
                    record_key,
                )
            )
            continue
        if item_factor_id != factor_id:
            errors.append(
                _issue(
                    SampleErrorCode.LABEL_REFERENCE_NOT_FOUND,
                    "label factor_id differs from FinancialBatch",
                    "factor_id",
                    record_key,
                )
            )
        if evaluation_date not in configuration.evaluation_dates:
            errors.append(
                _issue(
                    SampleErrorCode.LABEL_REFERENCE_NOT_FOUND,
                    "label evaluation_date is not in the frozen calendar",
                    "evaluation_date",
                    record_key,
                )
            )
        if not (
            label_publish_date
            <= label_effective_date
            <= label_available_at
        ):
            errors.append(
                _issue(
                    SampleErrorCode.INVALID_SAMPLE_INPUT,
                    "label dates must satisfy publish <= effective <= available",
                    "label_publish_date,label_effective_date,"
                    "label_available_at",
                    record_key,
                )
            )
        if label_available_at <= evaluation_date:
            errors.append(
                _issue(
                    SampleErrorCode.LABEL_TIME_LEAKAGE,
                    "future label must become available after evaluation_date",
                    "label_available_at",
                    record_key,
                )
            )
        target_report_period = _optional_date(
            record.get("target_report_period")
        )
        key = (evaluation_date, code, item_factor_id, track)
        counts[key] = counts.get(key, 0) + 1
        normalized.append(
            {
                "record_key": record_key,
                "evaluation_date": evaluation_date,
                "code": code,
                "factor_id": item_factor_id,
                "validation_track": track,
                "label_value": label_value,
                "label_publish_date": label_publish_date,
                "label_effective_date": label_effective_date,
                "label_available_at": label_available_at,
                "target_report_period": (
                    target_report_period or NOT_APPLICABLE
                ),
                **texts,
            }
        )
    for key, count in sorted(counts.items()):
        if count > 1:
            errors.append(
                _issue(
                    SampleErrorCode.DUPLICATE_LABEL_KEY,
                    f"label pairing key occurs {count} times",
                    ",".join(PAIRING_INDEX_FIELDS),
                    "|".join(key),
                )
            )
    return sorted(
        normalized,
        key=lambda item: (
            item["evaluation_date"],
            item["code"],
            item["factor_id"],
            item["validation_track"],
        ),
    )


def _left_join_labels(
    *,
    samples: list[FactorSampleRecord],
    labels: list[dict[str, Any]],
    errors: list[SampleIssue],
    warnings: list[SampleIssue],
) -> list[LabelPairingRecord]:
    sample_by_key = {
        (item.evaluation_date, item.code, item.factor_id): item
        for item in samples
    }
    label_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for label in labels:
        base_key = (
            label["evaluation_date"],
            label["code"],
            label["factor_id"],
        )
        full_key = (*base_key, label["validation_track"])
        if base_key not in sample_by_key:
            warnings.append(
                _issue(
                    SampleErrorCode.LABEL_REFERENCE_NOT_FOUND,
                    "label has no left-side sample row and was ignored",
                    ",".join(SAMPLE_INDEX_FIELDS),
                    "|".join(full_key),
                )
            )
            continue
        if full_key not in label_by_key:
            label_by_key[full_key] = label

    pairings: list[LabelPairingRecord] = []
    for sample in samples:
        for track in tuple(item.value for item in ValidationTrack):
            key = (
                sample.evaluation_date,
                sample.code,
                sample.factor_id,
                track,
            )
            label = label_by_key.get(key)
            exclusion_codes: list[str] = []
            label_valid = label is not None
            if label is None:
                exclusion_codes.append(
                    SampleErrorCode.LABEL_REFERENCE_NOT_FOUND.value
                )
            elif (
                track == ValidationTrack.FINANCIAL_TARGET.value
                and sample.report_period != NOT_APPLICABLE
            ):
                try:
                    expected = _next_quarter_end(sample.report_period)
                except ValueError:
                    expected = "a natural next-quarter end"
                if label["target_report_period"] != expected:
                    errors.append(
                        _issue(
                            SampleErrorCode.NON_CONSECUTIVE_FINANCIAL_TARGET,
                            f"F target must be next natural quarter {expected}",
                            "target_report_period",
                            label["record_key"],
                        )
                    )
                    label_valid = False
                    exclusion_codes.append(
                        SampleErrorCode.NON_CONSECUTIVE_FINANCIAL_TARGET.value
                    )
            if not sample.factor_sample_mask:
                exclusion_codes.extend(sample.exclusion_reason_codes)

            label_fields = (
                {
                    "label_id": label["label_id"],
                    "label_type": label["label_type"],
                    "label_value": label["label_value"],
                    "label_publish_date": label["label_publish_date"],
                    "label_effective_date": label["label_effective_date"],
                    "label_available_at": label["label_available_at"],
                    "label_source_record_id":
                        label["label_source_record_id"],
                    "label_source": label["label_source"],
                    "label_version": label["label_version"],
                    "label_snapshot_fingerprint":
                        label["label_snapshot_fingerprint"],
                    "target_report_period":
                        label["target_report_period"],
                }
                if label is not None
                else {
                    "label_id": NOT_APPLICABLE,
                    "label_type": NOT_APPLICABLE,
                    "label_value": None,
                    "label_publish_date": NOT_APPLICABLE,
                    "label_effective_date": NOT_APPLICABLE,
                    "label_available_at": NOT_APPLICABLE,
                    "label_source_record_id": NOT_APPLICABLE,
                    "label_source": NOT_APPLICABLE,
                    "label_version": NOT_APPLICABLE,
                    "label_snapshot_fingerprint": NOT_APPLICABLE,
                    "target_report_period": NOT_APPLICABLE,
                }
            )
            pairing_id = _versioned_hash(
                "pairing_id",
                {
                    "sample_id": sample.sample_id,
                    "validation_track": track,
                },
            )
            fields = {
                "schema_version": LABEL_JOIN_SCHEMA_VERSION,
                "pairing_id": pairing_id,
                "sample_id": sample.sample_id,
                "evaluation_date": sample.evaluation_date,
                "code": sample.code,
                "factor_id": sample.factor_id,
                "validation_track": track,
                "factor_sample_mask": sample.factor_sample_mask,
                "label_available": label_valid,
                "valid_pair_mask":
                    sample.factor_sample_mask and label_valid,
                **label_fields,
                "exclusion_reason_codes":
                    tuple(sorted(set(exclusion_codes))),
            }
            content_hash = _versioned_hash("label_pairing_record", fields)
            pairings.append(
                LabelPairingRecord(**fields, content_hash=content_hash)
            )
    return pairings


def _coverage_funnel(
    samples: list[FactorSampleRecord],
    pairings: list[LabelPairingRecord],
    configuration: SampleFormationConfig,
) -> list[CoverageRecord]:
    pairing_by_key = {
        (
            item.evaluation_date,
            item.code,
            item.factor_id,
            item.validation_track,
        ): item
        for item in pairings
    }
    output: list[CoverageRecord] = []
    for evaluation_date in configuration.evaluation_dates:
        dated_samples = [
            item
            for item in samples
            if item.evaluation_date == evaluation_date
        ]
        for track in configuration.supported_tracks:
            dated_pairings = [
                pairing_by_key[
                    (
                        item.evaluation_date,
                        item.code,
                        item.factor_id,
                        track,
                    )
                ]
                for item in dated_samples
            ]
            universe_count = sum(item.in_universe for item in dated_samples)
            pit_count = sum(
                item.in_universe and item.pit_available
                for item in dated_samples
            )
            fresh_count = sum(
                item.in_universe
                and item.pit_available
                and item.freshness_status == "fresh"
                for item in dated_samples
            )
            valid_factor_count = sum(
                item.factor_sample_mask for item in dated_samples
            )
            label_count = sum(
                item.label_available and sample.in_universe
                for item, sample in zip(dated_pairings, dated_samples)
            )
            pair_count = sum(
                item.valid_pair_mask for item in dated_pairings
            )
            exclusion_counts: dict[str, int] = {}
            for item in dated_pairings:
                for reason in item.exclusion_reason_codes:
                    exclusion_counts[reason] = (
                        exclusion_counts.get(reason, 0) + 1
                    )
            output.append(
                CoverageRecord(
                    evaluation_date=evaluation_date,
                    validation_track=track,
                    universe_count=universe_count,
                    pit_available_count=pit_count,
                    non_stale_count=fresh_count,
                    valid_factor_count=valid_factor_count,
                    label_available_count=label_count,
                    valid_pair_count=pair_count,
                    pit_coverage=_ratio(pit_count, universe_count),
                    freshness_coverage=_ratio(
                        fresh_count, universe_count
                    ),
                    factor_valid_coverage=_ratio(
                        valid_factor_count, universe_count
                    ),
                    label_coverage=_ratio(label_count, universe_count),
                    pair_coverage=_ratio(pair_count, universe_count),
                    exclusion_counts_by_reason=tuple(
                        sorted(exclusion_counts.items())
                    ),
                )
            )
    return output


def _sample_reference(
    records: tuple[FactorSampleRecord, ...],
    sample_fingerprint: str,
) -> SampleFormationReference:
    content_hash = _versioned_hash(
        "sample_reference",
        {
            "sample_fingerprint": sample_fingerprint,
            "records": [item.to_dict() for item in records],
        },
    )
    return SampleFormationReference(
        location=f"immutable://financial-sample/{content_hash}.json",
        schema_version=SAMPLE_SCHEMA_VERSION,
        row_count=len(records),
        index_fields=SAMPLE_INDEX_FIELDS,
        sample_fingerprint=sample_fingerprint,
        content_hash=content_hash,
        records=records,
    )


def _label_join_audit(
    records: tuple[LabelPairingRecord, ...],
) -> LabelJoinAudit:
    content_hash = _versioned_hash(
        "label_join_audit",
        [item.to_dict() for item in records],
    )
    return LabelJoinAudit(
        location=f"immutable://financial-label-join/{content_hash}.json",
        schema_version=LABEL_JOIN_SCHEMA_VERSION,
        row_count=len(records),
        index_fields=PAIRING_INDEX_FIELDS,
        content_hash=content_hash,
        records=records,
    )


def _gate_result(
    *,
    errors: tuple[SampleIssue, ...],
    warnings: tuple[SampleIssue, ...],
    total_universe_rows: int,
    factor_sample_count: int,
    valid_pair_count: int,
    configuration: SampleFormationConfig,
    sample_fingerprint: str,
    label_join_hash: str,
    coverage_content_hash: str,
) -> SampleGateResult:
    status = (
        SampleGateStatus.BLOCKED.value
        if errors
        else SampleGateStatus.READY.value
    )
    fields = {
        "overall_status": status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "total_universe_rows": total_universe_rows,
        "factor_sample_count": factor_sample_count,
        "valid_pair_count": valid_pair_count,
        "configuration": configuration.to_dict(),
        "sample_fingerprint": sample_fingerprint,
        "label_join_hash": label_join_hash,
        "coverage_content_hash": coverage_content_hash,
    }
    run_id = _versioned_hash("sample_run", fields)
    public_fields = {
        key: value
        for key, value in fields.items()
        if key not in {"configuration", "sample_fingerprint", "label_join_hash"}
    }
    public_fields["run_id"] = run_id
    content_hash = _versioned_hash("sample_gate", public_fields)
    return SampleGateResult(
        overall_status=status,
        errors=errors,
        warnings=warnings,
        total_universe_rows=total_universe_rows,
        factor_sample_count=factor_sample_count,
        valid_pair_count=valid_pair_count,
        run_id=run_id,
        content_hash=content_hash,
    )


def _blocked_empty(issue: SampleIssue) -> FinancialSampleResult:
    configuration_fallback = SampleFormationConfig(
        evaluation_dates=("1970-01-01",),
        evaluation_calendar_version="invalid-input",
        universe_version="invalid-input",
        freshness_max_age_days=0,
    )
    gate = _gate_result(
        errors=(issue,),
        warnings=(),
        total_universe_rows=0,
        factor_sample_count=0,
        valid_pair_count=0,
        configuration=configuration_fallback,
        sample_fingerprint=_versioned_hash("empty_sample", None),
        label_join_hash=_versioned_hash("empty_label_join", None),
        coverage_content_hash=_versioned_hash("coverage_funnel", []),
    )
    return FinancialSampleResult(
        gate_result=gate,
        sample_reference=None,
        label_join_audit=None,
        coverage_funnel=(),
        coverage_content_hash=_versioned_hash("coverage_funnel", []),
        sample_records=(),
        pairing_records=(),
    )


def _issue(
    code: SampleErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> SampleIssue:
    return SampleIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
    )


def _deduplicate_issues(issues: Iterable[SampleIssue]) -> list[SampleIssue]:
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


def _track_value(value: Any) -> str:
    if isinstance(value, ValidationTrack):
        return value.value
    text = _required_text(value, "validation_track")
    if text not in {item.value for item in ValidationTrack}:
        raise ValueError("validation_track must be M, F, or R")
    return text


def _next_quarter_end(report_period: str) -> str:
    current = date.fromisoformat(report_period)
    quarter_ends = ((3, 31), (6, 30), (9, 30), (12, 31))
    try:
        index = quarter_ends.index((current.month, current.day))
    except ValueError as exc:
        raise ValueError("report_period must be a natural quarter end") from exc
    if index == 3:
        return date(current.year + 1, 3, 31).isoformat()
    month, day = quarter_ends[index + 1]
    return date(current.year, month, day).isoformat()


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _label_scalar(value: Any) -> str | float | int | bool:
    if value is None:
        raise ValueError("label_value must not be null for a label record")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("label_value must be finite")
    if not isinstance(value, (str, int, float, bool)):
        raise TypeError("label_value must be a JSON scalar")
    return value


def _required_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("boolean is not a factor value")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError("factor value must be finite")
    return converted


def _optional_date(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _date_iso(value)


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
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _canonical_json_value(value.to_dict())
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")
