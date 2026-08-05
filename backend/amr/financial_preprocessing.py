"""FIN-R2-PREP: deterministic preparation for the three-factor MVP.

The module is deliberately independent from the public ``FinancialBatch``
contract.  It prepares the fixed formula inputs consumed by
``financial_mvp_batch`` and keeps raw PIT values separate from research
preprocessing values.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from typing import Any, Iterable, Mapping

from backend.amr.financial_mvp_batch import (
    SUPPORTED_FACTOR_IDS,
    formula_definition_for,
)


PREPROCESSING_SCHEMA_VERSION = "FinancialPreprocessing-v1.0"
PREPROCESSING_AUDIT_SCHEMA_VERSION = "FinancialPreprocessingAudit-v1.0"
PREPROCESSING_HASH_CONTRACT_VERSION = "FIN-R2-PREP-HASH-v1.0"
PREPROCESSING_POLICY_VERSION = "FIN-R2-PREP-POLICY-v1.0"
MAD_POLICY_VERSION = "FIN-R2-PREP-MAD-v1.0"
MAD_SCALE = 1.4826
MAD_THRESHOLD = 3.0

_STANDARD_REPORT_PERIODS = {"03-31", "06-30", "09-30", "12-31"}
_ANNUAL_REPORT_PERIOD = "12-31"
_RAW_FIELDS = (
    "parent_net_profit_ytd",
    "operating_cash_flow_ytd",
    "parent_equity",
    "market_cap",
    "prior_fy_parent_net_profit",
    "prior_fy_operating_cash_flow",
    "prior_year_same_period_parent_net_profit_ytd",
    "prior_year_same_period_operating_cash_flow_ytd",
    "prior_year_same_period_parent_equity",
)
_DENOMINATOR_BY_FACTOR = {
    "ROE": "average_parent_equity",
    "BP": "market_cap",
    "OCF_NP": "parent_net_profit_ttm",
}


class PreprocessingGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class PreprocessingSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class PreprocessingErrorCode(str, Enum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_INPUT_CONTAINER = "INVALID_INPUT_CONTAINER"
    INVALID_INPUT_RECORD = "INVALID_INPUT_RECORD"
    NON_SYNTHETIC_INPUT = "NON_SYNTHETIC_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_DATE = "INVALID_DATE"
    INVALID_DATE_ORDER = "INVALID_DATE_ORDER"
    UNSUPPORTED_REPORT_PERIOD = "UNSUPPORTED_REPORT_PERIOD"
    NONFINITE_FINANCIAL_INPUT = "NONFINITE_FINANCIAL_INPUT"
    INVALID_SOURCE_SNAPSHOT = "INVALID_SOURCE_SNAPSHOT"
    MISSING_INPUT_REFERENCE = "MISSING_INPUT_REFERENCE"
    DUPLICATE_PREPARATION_KEY = "DUPLICATE_PREPARATION_KEY"
    NONPOSITIVE_FORMULA_DENOMINATOR = "NONPOSITIVE_FORMULA_DENOMINATOR"
    INPUT_MUTATED = "INPUT_MUTATED"
    INSUFFICIENT_MAD_CROSS_SECTION = "INSUFFICIENT_MAD_CROSS_SECTION"
    MAD_ZERO_NO_WINSOR = "MAD_ZERO_NO_WINSOR"


class MADStatus(str, Enum):
    APPLIED = "applied"
    SKIPPED_INSUFFICIENT = "skipped_insufficient"
    MAD_ZERO_NO_WINSOR = "mad_zero_no_winsor"


@dataclass(frozen=True)
class FinancialPreprocessingConfig:
    """Frozen research-preparation policy.

    ``minimum_cross_section_size`` is deliberately mandatory.  The authority
    running a study must choose it explicitly and the value enters the config
    fingerprint; FIN-R2-PREP does not inherit a price/volume default.
    """

    minimum_cross_section_size: int
    mad_threshold: float = MAD_THRESHOLD
    mad_scale: float = MAD_SCALE
    schema_version: str = PREPROCESSING_SCHEMA_VERSION
    policy_version: str = PREPROCESSING_POLICY_VERSION
    mad_policy_version: str = MAD_POLICY_VERSION
    synthetic_test_only: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_cross_section_size, bool)
            or not isinstance(self.minimum_cross_section_size, int)
            or self.minimum_cross_section_size < 2
        ):
            raise ValueError("minimum_cross_section_size must be an integer >= 2")
        if self.mad_threshold != MAD_THRESHOLD:
            raise ValueError(f"mad_threshold must be frozen at {MAD_THRESHOLD}")
        if self.mad_scale != MAD_SCALE:
            raise ValueError(f"mad_scale must be frozen at {MAD_SCALE}")
        if self.schema_version != PREPROCESSING_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {PREPROCESSING_SCHEMA_VERSION}"
            )
        if self.policy_version != PREPROCESSING_POLICY_VERSION:
            raise ValueError(
                f"policy_version must be {PREPROCESSING_POLICY_VERSION}"
            )
        if self.mad_policy_version != MAD_POLICY_VERSION:
            raise ValueError(
                f"mad_policy_version must be {MAD_POLICY_VERSION}"
            )
        if self.synthetic_test_only is not True:
            raise ValueError("FIN-R2-PREP is authorized for synthetic input only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum_cross_section_size": self.minimum_cross_section_size,
            "mad_threshold": self.mad_threshold,
            "mad_scale": self.mad_scale,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "mad_policy_version": self.mad_policy_version,
            "synthetic_test_only": self.synthetic_test_only,
        }


@dataclass(frozen=True)
class PreprocessingIssue:
    code: str
    message: str
    severity: str
    field_name: str | None = None
    record_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "field_name": self.field_name,
            "record_key": self.record_key,
        }


@dataclass(frozen=True)
class PreparedFormulaInput:
    evaluation_date: str
    code: str
    factor_id: str
    report_period: str
    publish_date: str
    effective_date: str
    formula_inputs_items: tuple[tuple[str, float], ...]
    formula_input_references: tuple[str, ...]
    source_snapshot_fingerprint: str
    preparation_input_hash: str
    raw_pit_factor_value: float
    evaluation_factor_value: float
    mad_status: str
    was_winsorized: bool
    schema_version: str
    policy_version: str
    content_hash: str

    @property
    def formula_inputs(self) -> dict[str, float]:
        return dict(self.formula_inputs_items)

    @property
    def preparation_key(self) -> tuple[str, str, str]:
        return (self.evaluation_date, self.code, self.factor_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date,
            "code": self.code,
            "factor_id": self.factor_id,
            "report_period": self.report_period,
            "publish_date": self.publish_date,
            "effective_date": self.effective_date,
            "formula_inputs": self.formula_inputs,
            "formula_input_references": list(self.formula_input_references),
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "preparation_input_hash": self.preparation_input_hash,
            "raw_pit_factor_value": self.raw_pit_factor_value,
            "evaluation_factor_value": self.evaluation_factor_value,
            "neutralized_factor_value": None,
            "mad_status": self.mad_status,
            "was_winsorized": self.was_winsorized,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class MADCrossSectionAudit:
    evaluation_date: str
    factor_id: str
    status: str
    input_count: int
    valid_count: int
    minimum_cross_section_size: int
    median: float | None
    raw_mad: float | None
    scaled_mad: float | None
    lower_bound: float | None
    upper_bound: float | None
    clipped_count: int
    input_fingerprint: str
    output_fingerprint: str
    schema_version: str
    mad_policy_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date,
            "factor_id": self.factor_id,
            "status": self.status,
            "input_count": self.input_count,
            "valid_count": self.valid_count,
            "minimum_cross_section_size": self.minimum_cross_section_size,
            "median": self.median,
            "raw_mad": self.raw_mad,
            "scaled_mad": self.scaled_mad,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "clipped_count": self.clipped_count,
            "input_fingerprint": self.input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "schema_version": self.schema_version,
            "mad_policy_version": self.mad_policy_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialPreprocessingAudit:
    gate_status: str
    issues: tuple[PreprocessingIssue, ...]
    input_record_count: int
    prepared_record_count: int
    factor_observation_count: int
    blocked_record_count: int
    configuration_fingerprint: str
    input_fingerprint: str
    output_fingerprint: str
    mad_audit_fingerprint: str
    schema_version: str
    audit_schema_version: str
    hash_contract_version: str
    content_hash: str

    @property
    def errors(self) -> tuple[PreprocessingIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == PreprocessingSeverity.ERROR.value
        )

    @property
    def warnings(self) -> tuple[PreprocessingIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == PreprocessingSeverity.WARNING.value
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_status": self.gate_status,
            "issues": [item.to_dict() for item in self.issues],
            "input_record_count": self.input_record_count,
            "prepared_record_count": self.prepared_record_count,
            "factor_observation_count": self.factor_observation_count,
            "blocked_record_count": self.blocked_record_count,
            "configuration_fingerprint": self.configuration_fingerprint,
            "input_fingerprint": self.input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "mad_audit_fingerprint": self.mad_audit_fingerprint,
            "schema_version": self.schema_version,
            "audit_schema_version": self.audit_schema_version,
            "hash_contract_version": self.hash_contract_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialPreprocessingResult:
    prepared_inputs: tuple[PreparedFormulaInput, ...]
    mad_audits: tuple[MADCrossSectionAudit, ...]
    preprocessing_audit: FinancialPreprocessingAudit

    def get(
        self, evaluation_date: Any, code: Any, factor_id: Any
    ) -> PreparedFormulaInput:
        key = (
            _date_iso(evaluation_date, "evaluation_date"),
            _required_text(code, "code"),
            _required_text(factor_id, "factor_id"),
        )
        for item in self.prepared_inputs:
            if item.preparation_key == key:
                return item
        raise LookupError(f"prepared formula input not found: {key}")

    def to_mvp_path_b_records(
        self,
        *,
        source_snapshot_fingerprints: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return fresh dictionaries accepted by FIN-MVP-DATA path B.

        The MVP batch keeps the raw fixed-formula value.  MAD-processed
        ``evaluation_factor_value`` stays in the FIN-R2-PREP sidecar and is not
        smuggled into the public ``FinancialBatch``.
        """

        snapshot_bindings: dict[str, str] = {}
        if source_snapshot_fingerprints is not None:
            if not isinstance(source_snapshot_fingerprints, Mapping):
                raise TypeError(
                    "source_snapshot_fingerprints must be a mapping"
                )
            if set(source_snapshot_fingerprints) != set(SUPPORTED_FACTOR_IDS):
                raise ValueError(
                    "source_snapshot_fingerprints must cover exactly "
                    "ROE, BP, and OCF_NP"
                )
            snapshot_bindings = {
                factor_id: _sha256_text(
                    source_snapshot_fingerprints[factor_id],
                    f"source_snapshot_fingerprints[{factor_id}]",
                )
                for factor_id in SUPPORTED_FACTOR_IDS
            }
        records: list[dict[str, Any]] = []
        for item in self.prepared_inputs:
            definition = formula_definition_for(item.factor_id)
            records.append(
                {
                    "evaluation_date": item.evaluation_date,
                    "code": item.code,
                    "factor_id": item.factor_id,
                    "report_period": item.report_period,
                    "publish_date": item.publish_date,
                    "effective_date": item.effective_date,
                    "path_type": "B",
                    "formula_id": definition.formula_id,
                    "formula_version": definition.formula_version,
                    "formula_inputs": item.formula_inputs,
                    "formula_input_references": list(
                        item.formula_input_references
                    ),
                    "source_snapshot_fingerprint": snapshot_bindings.get(
                        item.factor_id,
                        item.source_snapshot_fingerprint,
                    ),
                    "synthetic_test_only": True,
                }
            )
        return records


def prepare_financial_formula_inputs(
    records: Iterable[Mapping[str, Any]],
    *,
    configuration: FinancialPreprocessingConfig,
    future_labels: Any = None,
) -> FinancialPreprocessingResult:
    """Prepare the three fixed-formula inputs and MAD evaluation values.

    Any input error blocks the entire three-factor package.  ``future_labels``
    is an isolation probe and is intentionally neither inspected nor hashed.
    """

    del future_labels
    if not isinstance(configuration, FinancialPreprocessingConfig):
        return _blocked_result(
            (
                _issue(
                    PreprocessingErrorCode.INVALID_CONFIGURATION,
                    "configuration must be FinancialPreprocessingConfig",
                    "configuration",
                ),
            )
        )
    try:
        raw_records = list(records)
    except TypeError:
        return _blocked_result(
            (
                _issue(
                    PreprocessingErrorCode.INVALID_INPUT_CONTAINER,
                    "records must be an iterable of mappings",
                    "records",
                ),
            ),
            configuration=configuration,
        )

    before_guard = _versioned_hash(
        "mutation_guard",
        [_mutation_guard_value(record) for record in raw_records],
    )
    normalized: list[dict[str, Any]] = []
    issues: list[PreprocessingIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for index, record in enumerate(raw_records):
        record_key = f"records[{index}]"
        item = _normalize_record(record, record_key=record_key, issues=issues)
        if item is None:
            continue
        key = (item["evaluation_date"], item["code"], item["report_period"])
        if key in seen:
            issues.append(
                _issue(
                    PreprocessingErrorCode.DUPLICATE_PREPARATION_KEY,
                    "duplicate evaluation_date + code + report_period",
                    "evaluation_date,code,report_period",
                    record_key,
                )
            )
            continue
        seen.add(key)
        normalized.append(item)

    after_guard = _versioned_hash(
        "mutation_guard",
        [_mutation_guard_value(record) for record in raw_records],
    )
    if before_guard != after_guard:
        issues.append(
            _issue(
                PreprocessingErrorCode.INPUT_MUTATED,
                "input records changed during preprocessing",
                "records",
            )
        )

    errors = _errors(issues)
    normalized.sort(
        key=lambda item: (
            item["evaluation_date"],
            item["code"],
            item["report_period"],
            item["effective_date"],
        )
    )
    input_fingerprint = _versioned_hash(
        "preprocessing_input", normalized
    )
    if errors:
        return _blocked_result(
            tuple(_deduplicate_issues(issues)),
            configuration=configuration,
            input_count=len(raw_records),
            blocked_count=len(raw_records),
            input_fingerprint=input_fingerprint,
        )

    prepared: list[PreparedFormulaInput] = []
    for record in normalized:
        prepared.extend(_prepare_one_record(record, issues))
    if _errors(issues):
        return _blocked_result(
            tuple(_deduplicate_issues(issues)),
            configuration=configuration,
            input_count=len(raw_records),
            blocked_count=len(raw_records),
            input_fingerprint=input_fingerprint,
        )

    prepared, mad_audits, mad_issues = _apply_mad(
        prepared, configuration
    )
    issues.extend(mad_issues)
    prepared_tuple = tuple(sorted(prepared, key=_prepared_sort_key))
    mad_tuple = tuple(
        sorted(
            mad_audits,
            key=lambda item: (item.evaluation_date, item.factor_id),
        )
    )
    audit = _build_audit(
        configuration=configuration,
        issues=tuple(_deduplicate_issues(issues)),
        input_count=len(raw_records),
        prepared_count=len(normalized),
        observations=prepared_tuple,
        mad_audits=mad_tuple,
        input_fingerprint=input_fingerprint,
        blocked_count=0,
    )
    return FinancialPreprocessingResult(
        prepared_inputs=prepared_tuple,
        mad_audits=mad_tuple,
        preprocessing_audit=audit,
    )


def _normalize_record(
    record: Any,
    *,
    record_key: str,
    issues: list[PreprocessingIssue],
) -> dict[str, Any] | None:
    if not isinstance(record, Mapping):
        issues.append(
            _issue(
                PreprocessingErrorCode.INVALID_INPUT_RECORD,
                "each record must be a mapping",
                "record",
                record_key,
            )
        )
        return None
    try:
        code = _required_text(record.get("code"), "code")
        evaluation_date = _date_iso(
            record.get("evaluation_date"), "evaluation_date"
        )
        report_period = _date_iso(
            record.get("report_period"), "report_period"
        )
        publish_date = _date_iso(
            record.get("publish_date"), "publish_date"
        )
        effective_date = _date_iso(
            record.get("effective_date"), "effective_date"
        )
    except (TypeError, ValueError) as exc:
        issues.append(
            _issue(
                PreprocessingErrorCode.MISSING_REQUIRED_FIELD
                if "required" in str(exc)
                else PreprocessingErrorCode.INVALID_DATE,
                str(exc),
                "code,evaluation_date,report_period,publish_date,effective_date",
                record_key,
            )
        )
        return None

    if (
        report_period > publish_date
        or publish_date > effective_date
        or effective_date > evaluation_date
    ):
        issues.append(
            _issue(
                PreprocessingErrorCode.INVALID_DATE_ORDER,
                "require report_period <= publish_date <= effective_date "
                "<= evaluation_date",
                "report_period,publish_date,effective_date,evaluation_date",
                record_key,
            )
        )
        return None
    if report_period[5:] not in _STANDARD_REPORT_PERIODS:
        issues.append(
            _issue(
                PreprocessingErrorCode.UNSUPPORTED_REPORT_PERIOD,
                "report_period must end in 03-31, 06-30, 09-30, or 12-31",
                "report_period",
                record_key,
            )
        )
        return None
    if record.get("synthetic_test_only") is not True:
        issues.append(
            _issue(
                PreprocessingErrorCode.NON_SYNTHETIC_INPUT,
                "FIN-R2-PREP accepts only synthetic_test_only=true input",
                "synthetic_test_only",
                record_key,
            )
        )
        return None

    values: dict[str, float] = {}
    for field_name in _RAW_FIELDS:
        required = (
            field_name
            not in {
                "prior_fy_parent_net_profit",
                "prior_fy_operating_cash_flow",
                "prior_year_same_period_parent_net_profit_ytd",
                "prior_year_same_period_operating_cash_flow_ytd",
            }
            or report_period[5:] != _ANNUAL_REPORT_PERIOD
        )
        value = record.get(field_name)
        if value is None and not required:
            values[field_name] = 0.0
            continue
        try:
            values[field_name] = _finite_number(value, field_name)
        except (TypeError, ValueError) as exc:
            issues.append(
                _issue(
                    PreprocessingErrorCode.MISSING_REQUIRED_FIELD
                    if value is None
                    else PreprocessingErrorCode.NONFINITE_FINANCIAL_INPUT,
                    str(exc),
                    field_name,
                    record_key,
                )
            )
    try:
        snapshot = _sha256_text(
            record.get("source_snapshot_fingerprint"),
            "source_snapshot_fingerprint",
        )
    except (TypeError, ValueError) as exc:
        issues.append(
            _issue(
                PreprocessingErrorCode.INVALID_SOURCE_SNAPSHOT,
                str(exc),
                "source_snapshot_fingerprint",
                record_key,
            )
        )
        snapshot = ""
    try:
        references = _reference_tuple(record.get("input_record_references"))
    except (TypeError, ValueError) as exc:
        issues.append(
            _issue(
                PreprocessingErrorCode.MISSING_INPUT_REFERENCE,
                str(exc),
                "input_record_references",
                record_key,
            )
        )
        references = ()
    if any(
        item.record_key == record_key
        and item.severity == PreprocessingSeverity.ERROR.value
        for item in issues
    ):
        return None
    return {
        "evaluation_date": evaluation_date,
        "code": code,
        "report_period": report_period,
        "publish_date": publish_date,
        "effective_date": effective_date,
        **values,
        "source_snapshot_fingerprint": snapshot,
        "input_record_references": references,
        "synthetic_test_only": True,
    }


def _prepare_one_record(
    record: dict[str, Any],
    issues: list[PreprocessingIssue],
) -> list[PreparedFormulaInput]:
    record_key = (
        f"{record['evaluation_date']}|{record['code']}|"
        f"{record['report_period']}"
    )
    annual = record["report_period"][5:] == _ANNUAL_REPORT_PERIOD
    if annual:
        parent_net_profit_ttm = record["parent_net_profit_ytd"]
        operating_cash_flow_ttm = record["operating_cash_flow_ytd"]
    else:
        parent_net_profit_ttm = (
            record["parent_net_profit_ytd"]
            + record["prior_fy_parent_net_profit"]
            - record[
                "prior_year_same_period_parent_net_profit_ytd"
            ]
        )
        operating_cash_flow_ttm = (
            record["operating_cash_flow_ytd"]
            + record["prior_fy_operating_cash_flow"]
            - record[
                "prior_year_same_period_operating_cash_flow_ytd"
            ]
        )
    average_parent_equity = (
        record["parent_equity"]
        + record["prior_year_same_period_parent_equity"]
    ) / 2.0
    prepared_values = {
        "parent_net_profit_ttm": parent_net_profit_ttm,
        "operating_cash_flow_ttm": operating_cash_flow_ttm,
        "average_parent_equity": average_parent_equity,
        "parent_equity": record["parent_equity"],
        "market_cap": record["market_cap"],
    }
    for field_name, value in prepared_values.items():
        if not math.isfinite(value):
            issues.append(
                _issue(
                    PreprocessingErrorCode.NONFINITE_FINANCIAL_INPUT,
                    f"prepared {field_name} must be finite",
                    field_name,
                    record_key,
                )
            )
    formula_inputs_by_factor = {
        "ROE": {
            "parent_net_profit_ttm": parent_net_profit_ttm,
            "average_parent_equity": average_parent_equity,
        },
        "BP": {
            "parent_equity": record["parent_equity"],
            "market_cap": record["market_cap"],
        },
        "OCF_NP": {
            "operating_cash_flow_ttm": operating_cash_flow_ttm,
            "parent_net_profit_ttm": parent_net_profit_ttm,
        },
    }
    for factor_id in SUPPORTED_FACTOR_IDS:
        denominator_field = _DENOMINATOR_BY_FACTOR[factor_id]
        denominator = formula_inputs_by_factor[factor_id][denominator_field]
        if denominator <= 0:
            issues.append(
                _issue(
                    PreprocessingErrorCode.NONPOSITIVE_FORMULA_DENOMINATOR,
                    f"{factor_id} denominator {denominator_field} must be > 0",
                    denominator_field,
                    record_key,
                )
            )
    if _errors(issues):
        return []

    preparation_input_hash = _versioned_hash(
        "preparation_record",
        {
            **record,
            "prepared_values": prepared_values,
            "policy_version": PREPROCESSING_POLICY_VERSION,
        },
    )
    result: list[PreparedFormulaInput] = []
    for factor_id in SUPPORTED_FACTOR_IDS:
        definition = formula_definition_for(factor_id)
        formula_inputs = formula_inputs_by_factor[factor_id]
        numerator = formula_inputs[definition.numerator_field]
        denominator = formula_inputs[definition.denominator_field]
        raw_value = numerator / denominator
        fields = {
            "evaluation_date": record["evaluation_date"],
            "code": record["code"],
            "factor_id": factor_id,
            "report_period": record["report_period"],
            "publish_date": record["publish_date"],
            "effective_date": record["effective_date"],
            "formula_inputs_items": tuple(
                sorted(formula_inputs.items())
            ),
            "formula_input_references": record[
                "input_record_references"
            ],
            "source_snapshot_fingerprint": record[
                "source_snapshot_fingerprint"
            ],
            "preparation_input_hash": preparation_input_hash,
            "raw_pit_factor_value": raw_value,
            "evaluation_factor_value": raw_value,
            "mad_status": MADStatus.SKIPPED_INSUFFICIENT.value,
            "was_winsorized": False,
            "schema_version": PREPROCESSING_SCHEMA_VERSION,
            "policy_version": PREPROCESSING_POLICY_VERSION,
        }
        content_hash = _versioned_hash("prepared_formula_input", fields)
        result.append(PreparedFormulaInput(**fields, content_hash=content_hash))
    return result


def _apply_mad(
    observations: list[PreparedFormulaInput],
    configuration: FinancialPreprocessingConfig,
) -> tuple[
    list[PreparedFormulaInput],
    list[MADCrossSectionAudit],
    list[PreprocessingIssue],
]:
    groups: dict[tuple[str, str], list[PreparedFormulaInput]] = {}
    for item in observations:
        groups.setdefault(
            (item.evaluation_date, item.factor_id), []
        ).append(item)
    output: list[PreparedFormulaInput] = []
    audits: list[MADCrossSectionAudit] = []
    issues: list[PreprocessingIssue] = []
    for key in sorted(groups):
        evaluation_date, factor_id = key
        group = sorted(groups[key], key=lambda item: item.code)
        values = [item.raw_pit_factor_value for item in group]
        input_fingerprint = _versioned_hash(
            "mad_input",
            [
                {"code": item.code, "value": item.raw_pit_factor_value}
                for item in group
            ],
        )
        if len(values) < configuration.minimum_cross_section_size:
            status = MADStatus.SKIPPED_INSUFFICIENT
            transformed = values
            median_value = raw_mad = scaled_mad = None
            lower = upper = None
            clipped_count = 0
            issues.append(
                _warning(
                    PreprocessingErrorCode.INSUFFICIENT_MAD_CROSS_SECTION,
                    "MAD not applied because the valid cross-section is "
                    "smaller than minimum_cross_section_size",
                    "minimum_cross_section_size",
                    f"{evaluation_date}|{factor_id}",
                )
            )
        else:
            median_value = float(statistics.median(values))
            raw_mad = float(
                statistics.median(
                    [abs(value - median_value) for value in values]
                )
            )
            scaled_mad = raw_mad * configuration.mad_scale
            if raw_mad == 0:
                status = MADStatus.MAD_ZERO_NO_WINSOR
                transformed = values
                lower = upper = median_value
                clipped_count = 0
                issues.append(
                    _warning(
                        PreprocessingErrorCode.MAD_ZERO_NO_WINSOR,
                        "MAD=0; original values returned without fallback",
                        "raw_mad",
                        f"{evaluation_date}|{factor_id}",
                    )
                )
            else:
                status = MADStatus.APPLIED
                lower = (
                    median_value
                    - configuration.mad_threshold * scaled_mad
                )
                upper = (
                    median_value
                    + configuration.mad_threshold * scaled_mad
                )
                transformed = [
                    min(max(value, lower), upper) for value in values
                ]
                clipped_count = sum(
                    original != changed
                    for original, changed in zip(values, transformed)
                )
        updated_group: list[PreparedFormulaInput] = []
        for item, transformed_value in zip(group, transformed):
            updated_fields = {
                **{
                    key: value
                    for key, value in item.__dict__.items()
                    if key != "content_hash"
                },
                "evaluation_factor_value": float(transformed_value),
                "mad_status": status.value,
                "was_winsorized":
                    transformed_value != item.raw_pit_factor_value,
            }
            updated = replace(
                item,
                evaluation_factor_value=float(transformed_value),
                mad_status=status.value,
                was_winsorized=(
                    transformed_value != item.raw_pit_factor_value
                ),
                content_hash=_versioned_hash(
                    "prepared_formula_input", updated_fields
                ),
            )
            updated_group.append(updated)
        output.extend(updated_group)
        output_fingerprint = _versioned_hash(
            "mad_output",
            [
                {
                    "code": item.code,
                    "raw": item.raw_pit_factor_value,
                    "evaluation": item.evaluation_factor_value,
                }
                for item in updated_group
            ],
        )
        audit_fields = {
            "evaluation_date": evaluation_date,
            "factor_id": factor_id,
            "status": status.value,
            "input_count": len(group),
            "valid_count": len(values),
            "minimum_cross_section_size":
                configuration.minimum_cross_section_size,
            "median": median_value,
            "raw_mad": raw_mad,
            "scaled_mad": scaled_mad,
            "lower_bound": lower,
            "upper_bound": upper,
            "clipped_count": clipped_count,
            "input_fingerprint": input_fingerprint,
            "output_fingerprint": output_fingerprint,
            "schema_version": PREPROCESSING_SCHEMA_VERSION,
            "mad_policy_version": MAD_POLICY_VERSION,
        }
        audits.append(
            MADCrossSectionAudit(
                **audit_fields,
                content_hash=_versioned_hash(
                    "mad_cross_section_audit", audit_fields
                ),
            )
        )
    return output, audits, issues


def _build_audit(
    *,
    configuration: FinancialPreprocessingConfig,
    issues: tuple[PreprocessingIssue, ...],
    input_count: int,
    prepared_count: int,
    observations: tuple[PreparedFormulaInput, ...],
    mad_audits: tuple[MADCrossSectionAudit, ...],
    input_fingerprint: str,
    blocked_count: int,
) -> FinancialPreprocessingAudit:
    gate = (
        PreprocessingGateStatus.BLOCKED
        if _errors(issues)
        else PreprocessingGateStatus.READY
    )
    configuration_fingerprint = _versioned_hash(
        "preprocessing_configuration", configuration.to_dict()
    )
    output_fingerprint = _versioned_hash(
        "preprocessing_output",
        [item.to_dict() for item in observations],
    )
    mad_audit_fingerprint = _versioned_hash(
        "mad_audits",
        [item.to_dict() for item in mad_audits],
    )
    fields = {
        "gate_status": gate.value,
        "issues": tuple(issues),
        "input_record_count": input_count,
        "prepared_record_count": prepared_count,
        "factor_observation_count": len(observations),
        "blocked_record_count": blocked_count,
        "configuration_fingerprint": configuration_fingerprint,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": output_fingerprint,
        "mad_audit_fingerprint": mad_audit_fingerprint,
        "schema_version": PREPROCESSING_SCHEMA_VERSION,
        "audit_schema_version": PREPROCESSING_AUDIT_SCHEMA_VERSION,
        "hash_contract_version": PREPROCESSING_HASH_CONTRACT_VERSION,
    }
    return FinancialPreprocessingAudit(
        **fields,
        content_hash=_versioned_hash("preprocessing_audit", fields),
    )


def _blocked_result(
    issues: tuple[PreprocessingIssue, ...],
    *,
    configuration: FinancialPreprocessingConfig | None = None,
    input_count: int = 0,
    blocked_count: int = 0,
    input_fingerprint: str | None = None,
) -> FinancialPreprocessingResult:
    if configuration is None:
        configuration = FinancialPreprocessingConfig(
            minimum_cross_section_size=2
        )
    audit = _build_audit(
        configuration=configuration,
        issues=issues,
        input_count=input_count,
        prepared_count=0,
        observations=(),
        mad_audits=(),
        input_fingerprint=input_fingerprint
        or _versioned_hash("preprocessing_input", []),
        blocked_count=blocked_count,
    )
    return FinancialPreprocessingResult(
        prepared_inputs=(),
        mad_audits=(),
        preprocessing_audit=audit,
    )


def _issue(
    code: PreprocessingErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> PreprocessingIssue:
    return PreprocessingIssue(
        code=code.value,
        message=message,
        severity=PreprocessingSeverity.ERROR.value,
        field_name=field_name,
        record_key=record_key,
    )


def _warning(
    code: PreprocessingErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> PreprocessingIssue:
    return PreprocessingIssue(
        code=code.value,
        message=message,
        severity=PreprocessingSeverity.WARNING.value,
        field_name=field_name,
        record_key=record_key,
    )


def _errors(
    issues: Iterable[PreprocessingIssue],
) -> tuple[PreprocessingIssue, ...]:
    return tuple(
        issue
        for issue in issues
        if issue.severity == PreprocessingSeverity.ERROR.value
    )


def _deduplicate_issues(
    issues: Iterable[PreprocessingIssue],
) -> list[PreprocessingIssue]:
    unique = {
        (
            item.code,
            item.message,
            item.severity,
            item.field_name,
            item.record_key,
        ): item
        for item in issues
    }
    return [
        unique[key]
        for key in sorted(
            unique,
            key=lambda value: tuple("" if item is None else item for item in value),
        )
    ]


def _prepared_sort_key(
    item: PreparedFormulaInput,
) -> tuple[str, int, str, str, str]:
    return (
        item.evaluation_date,
        SUPPORTED_FACTOR_IDS.index(item.factor_id),
        item.code,
        item.report_period,
        item.effective_date,
    )


def _reference_tuple(values: Any) -> tuple[str, ...]:
    if values is None or isinstance(values, str):
        raise TypeError("input_record_references must be a non-empty iterable")
    try:
        result = tuple(
            sorted(
                {
                    _required_text(value, "input_record_reference")
                    for value in values
                }
            )
        )
    except TypeError as exc:
        raise TypeError(
            "input_record_references must be a non-empty iterable"
        ) from exc
    if not result:
        raise ValueError("input_record_references must not be empty")
    return result


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be a finite number")
    return result


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} is required")
    return value.strip()


def _date_iso(value: Any, field_name: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = _required_text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{field_name} must be canonical YYYY-MM-DD")
    return text


def _sha256_text(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return text


def _mutation_guard_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _mutation_guard_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_mutation_guard_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_mutation_guard_value(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
    if isinstance(value, float) and not math.isfinite(value):
        return f"__{value!s}__"
    if isinstance(value, date):
        return value.isoformat()
    return value


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _canonical_json_value(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _canonical_json_value(item)
            for key, item in value.__dict__.items()
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_canonical_json_value(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite values cannot enter official hashes")
        if value == 0:
            return 0.0
    return value


def _versioned_hash(domain: str, value: Any) -> str:
    payload = {
        "domain": domain,
        "hash_contract_version": PREPROCESSING_HASH_CONTRACT_VERSION,
        "value": _canonical_json_value(value),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
