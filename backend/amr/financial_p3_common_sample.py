"""FIN-P3-COMMON-SAMPLE: PIT-safe same-row factor comparator.

This additive, synthetic-only module implements FIN-23.  A single factor and
a predeclared combined factor are evaluated on exactly the same security-date
rows.  It reports deltas only; it does not construct FIN-24 combinations or
make a FIN-25 information-gain, admission, or production decision.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


COMMON_SAMPLE_SCHEMA_VERSION = "FinancialP3CommonSample-v1.0"
COMMON_SAMPLE_AUDIT_SCHEMA_VERSION = (
    "FinancialP3CommonSampleAudit-v1.0"
)
COMMON_SAMPLE_METRICS_SCHEMA_VERSION = (
    "FinancialP3CommonSampleMetrics-v1.0"
)
COMMON_SAMPLE_POLICY_VERSION = "FIN-P3-COMMON-SAMPLE-POLICY-v1.0"
COMMON_SAMPLE_HASH_CONTRACT_VERSION = (
    "FIN-P3-COMMON-SAMPLE-HASH-v1.0"
)
COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT = (
    "9393a240f1bc214fd30bd2815da20ba47e02dedc9c9d319c73fa42c6ada3a1fe"
)
COMMON_SAMPLE_GROUP_COUNT = 5
COMMON_SAMPLE_MIN_CROSS_SECTION = 30
COMMON_SAMPLE_MIN_PERIODS = 12
COMMON_SAMPLE_HORIZON = 20
COMMON_SAMPLE_RESEARCH_ASSESSMENT = "exploratory"
COMMON_SAMPLE_PRODUCTION_STATUS = "not production ready"
COMMON_SAMPLE_ADMISSION_STATUS = "not_assessed"
COMMON_SAMPLE_CONCLUSION_BOUNDARY = (
    "Synthetic FIN-23 common-sample comparison only; deltas are not a FIN-25 "
    "information-gain determination, factor admission or rejection, "
    "production approval, empirical return claim, or trading instruction."
)

_MANIFEST_COLUMNS = (
    "evaluation_date",
    "security_id",
    "eligible",
)
_FRAME_COLUMNS = (
    "evaluation_date",
    "security_id",
    "factor_effective_date",
    "control_effective_date",
    "return_start_date",
    "single_factor_value",
    "combined_factor_value",
    "forward_return",
    "size_control",
    "industry_code",
)
_KEY_COLUMNS = ("evaluation_date", "security_id")
_FORBIDDEN_COLUMNS = {
    "selected_single_factor",
    "selected_combination",
    "selected_metric",
    "best_single_factor",
    "information_gain_decision",
    "admission_decision",
}


class CommonSampleGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class CommonSampleEvaluationStatus(str, Enum):
    COMPLETED = "completed"
    INSUFFICIENT = "insufficient"
    NOT_RUN = "not_run"


class CommonSampleErrorCode(str, Enum):
    INVALID_GATE_ANCHOR = "INVALID_GATE_ANCHOR"
    NON_SYNTHETIC_INPUT = "NON_SYNTHETIC_INPUT"
    MISSING_COLUMN = "MISSING_COLUMN"
    INVALID_KEY = "INVALID_KEY"
    DUPLICATE_MANIFEST_KEY = "DUPLICATE_MANIFEST_KEY"
    DUPLICATE_OBSERVATION_KEY = "DUPLICATE_OBSERVATION_KEY"
    OBSERVATION_OUTSIDE_MANIFEST = "OBSERVATION_OUTSIDE_MANIFEST"
    MANIFEST_FINGERPRINT_MISMATCH = "MANIFEST_FINGERPRINT_MISMATCH"
    FUTURE_FACTOR_OR_CONTROL = "FUTURE_FACTOR_OR_CONTROL"
    INVALID_RETURN_ALIGNMENT = "INVALID_RETURN_ALIGNMENT"
    FORBIDDEN_SELECTION_FIELD = "FORBIDDEN_SELECTION_FIELD"
    INPUT_MUTATED = "INPUT_MUTATED"


class CommonSampleWarningCode(str, Enum):
    SYNTHETIC_COMPARATOR_ONLY = "SYNTHETIC_COMPARATOR_ONLY"
    COVERAGE_LOSS_REPORTED = "COVERAGE_LOSS_REPORTED"
    INFORMATION_GAIN_NOT_DECIDED = "INFORMATION_GAIN_NOT_DECIDED"
    PRODUCTION_GATES_NOT_EVALUATED = "PRODUCTION_GATES_NOT_EVALUATED"


@dataclass(frozen=True)
class CommonSampleIssue:
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
class FinancialP3CommonSampleConfig:
    comparison_id: str
    single_factor_id: str
    combined_factor_id: str
    single_formula_version: str
    combined_formula_version: str
    expected_manifest_fingerprint: str
    execution_timestamp: str
    holding_period: int = COMMON_SAMPLE_HORIZON
    group_count: int = COMMON_SAMPLE_GROUP_COUNT
    minimum_cross_section: int = COMMON_SAMPLE_MIN_CROSS_SECTION
    minimum_periods: int = COMMON_SAMPLE_MIN_PERIODS
    group_weighting: str = "equal_weight"
    ic_method: str = "spearman_rank"
    fm_controls: tuple[str, ...] = ("size", "industry")
    sample_policy: str = "frozen_manifest_intersection"
    comparison_policy: str = "predeclared_pair_only"
    automatic_best_single_selection: bool = False
    information_gain_decision_allowed: bool = False
    fin24_combination_construction_allowed: bool = False
    synthetic_test_only: bool = True
    gate_output_fingerprint: str = (
        COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT
    )
    policy_version: str = COMMON_SAMPLE_POLICY_VERSION
    schema_version: str = COMMON_SAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "comparison_id",
            "single_factor_id",
            "combined_factor_id",
            "single_formula_version",
            "combined_formula_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if self.single_factor_id == self.combined_factor_id:
            raise ValueError("single and combined factor IDs must differ")
        if not _is_sha256(self.expected_manifest_fingerprint):
            raise ValueError(
                "expected_manifest_fingerprint must be SHA-256"
            )
        _datetime_text(self.execution_timestamp, "execution_timestamp")
        frozen = {
            "holding_period": (self.holding_period, 20),
            "group_count": (self.group_count, 5),
            "minimum_cross_section": (
                self.minimum_cross_section,
                30,
            ),
            "minimum_periods": (self.minimum_periods, 12),
            "group_weighting": (
                self.group_weighting,
                "equal_weight",
            ),
            "ic_method": (self.ic_method, "spearman_rank"),
            "fm_controls": (
                tuple(self.fm_controls),
                ("size", "industry"),
            ),
            "sample_policy": (
                self.sample_policy,
                "frozen_manifest_intersection",
            ),
            "comparison_policy": (
                self.comparison_policy,
                "predeclared_pair_only",
            ),
            "automatic_best_single_selection": (
                self.automatic_best_single_selection,
                False,
            ),
            "information_gain_decision_allowed": (
                self.information_gain_decision_allowed,
                False,
            ),
            "fin24_combination_construction_allowed": (
                self.fin24_combination_construction_allowed,
                False,
            ),
            "synthetic_test_only": (self.synthetic_test_only, True),
            "gate_output_fingerprint": (
                self.gate_output_fingerprint,
                COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT,
            ),
            "policy_version": (
                self.policy_version,
                COMMON_SAMPLE_POLICY_VERSION,
            ),
            "schema_version": (
                self.schema_version,
                COMMON_SAMPLE_SCHEMA_VERSION,
            ),
        }
        for name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(
                    f"{name} must be frozen at {expected!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["fm_controls"] = list(self.fm_controls)
        return values


@dataclass(frozen=True)
class FinancialP3CommonSampleBatch:
    dataset_id: str
    version: str
    _manifest: pd.DataFrame
    _frame: pd.DataFrame
    declared_manifest_fingerprint: str
    gate_anchor: Mapping[str, Any]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        _required_text(self.dataset_id, "dataset_id")
        _required_text(self.version, "version")
        if not isinstance(self._manifest, pd.DataFrame):
            raise TypeError("_manifest must be a pandas DataFrame")
        if not isinstance(self._frame, pd.DataFrame):
            raise TypeError("_frame must be a pandas DataFrame")
        if not _is_sha256(self.declared_manifest_fingerprint):
            raise ValueError(
                "declared_manifest_fingerprint must be SHA-256"
            )
        object.__setattr__(
            self,
            "_manifest",
            self._manifest.copy(deep=True),
        )
        object.__setattr__(self, "_frame", self._frame.copy(deep=True))
        object.__setattr__(
            self,
            "gate_anchor",
            MappingProxyType(copy.deepcopy(dict(self.gate_anchor))),
        )
        object.__setattr__(
            self,
            "provenance",
            MappingProxyType(copy.deepcopy(dict(self.provenance))),
        )

    def get_manifest(self) -> pd.DataFrame:
        return self._manifest.copy(deep=True)

    def get_frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)

    def get_gate_anchor(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.gate_anchor))

    def get_provenance(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.provenance))


@dataclass(frozen=True)
class CommonSampleMetrics:
    factor_id: str
    valid_period_count: int
    common_observation_count: int
    mean_rank_ic: float | None
    rank_ic_std: float | None
    icir: float | None
    positive_ic_ratio: float | None
    group_returns: tuple[float, ...]
    long_short_spread: float | None
    monotonicity: float | None
    fm_mean_r2: float | None
    common_sample_fingerprint: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["group_returns"] = list(self.group_returns)
        return values


@dataclass(frozen=True)
class FinancialP3CommonSampleComparison:
    comparison_id: str
    single_factor_id: str
    combined_factor_id: str
    evaluation_status: str
    common_sample_size: int
    eligible_sample_size: int
    single_available_size: int
    combined_available_size: int
    common_period_count: int
    single_factor_metrics: CommonSampleMetrics | None
    combined_factor_metrics: CommonSampleMetrics | None
    delta_ic: float | None
    delta_icir: float | None
    delta_monotonicity: float | None
    delta_fm_r2: float | None
    coverage_loss: float
    common_sample_fingerprint: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "single_factor_id": self.single_factor_id,
            "combined_factor_id": self.combined_factor_id,
            "evaluation_status": self.evaluation_status,
            "common_sample_size": self.common_sample_size,
            "eligible_sample_size": self.eligible_sample_size,
            "single_available_size": self.single_available_size,
            "combined_available_size": self.combined_available_size,
            "common_period_count": self.common_period_count,
            "single_factor_metrics": (
                None
                if self.single_factor_metrics is None
                else self.single_factor_metrics.to_dict()
            ),
            "combined_factor_metrics": (
                None
                if self.combined_factor_metrics is None
                else self.combined_factor_metrics.to_dict()
            ),
            "delta_ic": self.delta_ic,
            "delta_icir": self.delta_icir,
            "delta_monotonicity": self.delta_monotonicity,
            "delta_fm_r2": self.delta_fm_r2,
            "coverage_loss": self.coverage_loss,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP3CommonSampleAudit:
    gate_status: str
    errors: tuple[CommonSampleIssue, ...]
    warnings: tuple[CommonSampleIssue, ...]
    evaluation_status: str
    eligible_sample_size: int
    common_sample_size: int
    valid_period_count: int
    same_sample_enforced: bool
    pit_safe: bool
    information_gain_decision_made: bool
    fin24_combination_constructed: bool
    synthetic_test_only: bool
    research_assessment: str
    production_status: str
    admission_status: str
    manifest_fingerprint: str
    input_fingerprint: str
    common_sample_fingerprint: str
    output_fingerprint: str
    conclusion_boundary: str
    schema_version: str
    audit_schema_version: str
    policy_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["errors"] = [item.to_dict() for item in self.errors]
        values["warnings"] = [item.to_dict() for item in self.warnings]
        return values


@dataclass(frozen=True)
class FinancialP3CommonSampleResult:
    comparison: FinancialP3CommonSampleComparison | None
    common_sample_audit: FinancialP3CommonSampleAudit

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison": (
                None if self.comparison is None else self.comparison.to_dict()
            ),
            "common_sample_audit": self.common_sample_audit.to_dict(),
        }


def compute_common_sample_manifest_fingerprint(
    manifest: pd.DataFrame,
) -> str:
    if not isinstance(manifest, pd.DataFrame):
        raise TypeError("manifest must be a pandas DataFrame")
    if any(column not in manifest.columns for column in _MANIFEST_COLUMNS):
        raise ValueError("manifest is missing required columns")
    return _hash(
        "p3_common_sample_manifest",
        _frame_records(manifest.loc[:, _MANIFEST_COLUMNS]),
    )


def evaluate_financial_p3_common_sample(
    batch: FinancialP3CommonSampleBatch,
    *,
    configuration: FinancialP3CommonSampleConfig,
) -> FinancialP3CommonSampleResult:
    if not isinstance(batch, FinancialP3CommonSampleBatch):
        raise TypeError("batch must be FinancialP3CommonSampleBatch")
    if not isinstance(configuration, FinancialP3CommonSampleConfig):
        raise TypeError(
            "configuration must be FinancialP3CommonSampleConfig"
        )
    manifest = batch.get_manifest()
    frame = batch.get_frame()
    anchor = batch.get_gate_anchor()
    provenance = batch.get_provenance()
    guard = _batch_guard(batch)
    errors: list[CommonSampleIssue] = []
    warnings = [
        _warning(
            CommonSampleWarningCode.SYNTHETIC_COMPARATOR_ONLY,
            "Only deterministic synthetic FIN-23 evidence is authorized.",
        ),
        _warning(
            CommonSampleWarningCode.COVERAGE_LOSS_REPORTED,
            "Coverage loss is reported against the independent manifest.",
        ),
        _warning(
            CommonSampleWarningCode.INFORMATION_GAIN_NOT_DECIDED,
            "Metric deltas do not create a FIN-25 information-gain decision.",
        ),
        _warning(
            CommonSampleWarningCode.PRODUCTION_GATES_NOT_EVALUATED,
            "Costs, trading states, and production gates are out of scope.",
        ),
    ]
    _validate_anchor(anchor, errors)
    if not bool(provenance.get("synthetic_test_only")):
        errors.append(
            _error(
                CommonSampleErrorCode.NON_SYNTHETIC_INPUT,
                "provenance.synthetic_test_only must be true",
            )
        )
    forbidden_provenance = _FORBIDDEN_COLUMNS & set(
        str(key) for key in provenance
    )
    if forbidden_provenance:
        errors.append(
            _error(
                CommonSampleErrorCode.FORBIDDEN_SELECTION_FIELD,
                "selection or decision fields are forbidden",
                field_name=",".join(sorted(forbidden_provenance)),
            )
        )
    normalized_manifest = _normalize_manifest(manifest, errors)
    normalized_frame = _normalize_frame(frame, errors)
    manifest_fingerprint = (
        compute_common_sample_manifest_fingerprint(normalized_manifest)
        if not normalized_manifest.empty
        else _hash("p3_common_sample_manifest", [])
    )
    if manifest_fingerprint != batch.declared_manifest_fingerprint:
        errors.append(
            _error(
                CommonSampleErrorCode.MANIFEST_FINGERPRINT_MISMATCH,
                "declared manifest fingerprint does not match",
            )
        )
    if manifest_fingerprint != configuration.expected_manifest_fingerprint:
        errors.append(
            _error(
                CommonSampleErrorCode.MANIFEST_FINGERPRINT_MISMATCH,
                "configuration does not bind the supplied manifest",
            )
        )
    _validate_relationships(normalized_manifest, normalized_frame, errors)
    input_fingerprint = _hash(
        "p3_common_sample_input",
        {
            "manifest": _frame_records(normalized_manifest),
            "frame": _frame_records(normalized_frame),
            "anchor": anchor,
            "provenance": provenance,
            "configuration": configuration.to_dict(),
        },
    )
    if errors:
        return _blocked_result(
            configuration=configuration,
            errors=errors,
            warnings=warnings,
            manifest_fingerprint=manifest_fingerprint,
            input_fingerprint=input_fingerprint,
        )

    joined = _join_manifest(normalized_manifest, normalized_frame)
    eligible = joined[joined["eligible"]].copy()
    single_mask = _availability_mask(eligible, "single_factor_value")
    combined_mask = _availability_mask(
        eligible,
        "combined_factor_value",
    )
    common = eligible[single_mask & combined_mask].copy()
    counts = common.groupby("evaluation_date").size()
    valid_dates = tuple(
        sorted(
            str(date)
            for date, count in counts.items()
            if count >= configuration.minimum_cross_section
        )
    )
    common = common[
        common["evaluation_date"].isin(valid_dates)
    ].copy()
    common_sample_fingerprint = _hash(
        "p3_common_sample_rows",
        _frame_records(common.loc[:, _KEY_COLUMNS]),
    )
    evaluation_status = (
        CommonSampleEvaluationStatus.COMPLETED.value
        if len(valid_dates) >= configuration.minimum_periods
        else CommonSampleEvaluationStatus.INSUFFICIENT.value
    )
    single_metrics: CommonSampleMetrics | None = None
    combined_metrics: CommonSampleMetrics | None = None
    if valid_dates:
        single_metrics = _compute_metrics(
            common,
            factor_column="single_factor_value",
            factor_id=configuration.single_factor_id,
            common_sample_fingerprint=common_sample_fingerprint,
            group_count=configuration.group_count,
        )
        combined_metrics = _compute_metrics(
            common,
            factor_column="combined_factor_value",
            factor_id=configuration.combined_factor_id,
            common_sample_fingerprint=common_sample_fingerprint,
            group_count=configuration.group_count,
        )
    eligible_count = len(eligible)
    common_count = len(common)
    coverage_loss = (
        1.0 - common_count / eligible_count if eligible_count else 1.0
    )
    comparison = _build_comparison(
        configuration=configuration,
        evaluation_status=evaluation_status,
        eligible_sample_size=eligible_count,
        single_available_size=int(single_mask.sum()),
        combined_available_size=int(combined_mask.sum()),
        common_sample_size=common_count,
        common_period_count=len(valid_dates),
        single_metrics=single_metrics,
        combined_metrics=combined_metrics,
        coverage_loss=coverage_loss,
        common_sample_fingerprint=common_sample_fingerprint,
    )
    output_fingerprint = _hash(
        "p3_common_sample_output",
        comparison.to_dict(),
    )
    if _batch_guard(batch) != guard:
        return _blocked_result(
            configuration=configuration,
            errors=[
                _error(
                    CommonSampleErrorCode.INPUT_MUTATED,
                    "input batch changed during evaluation",
                )
            ],
            warnings=warnings,
            manifest_fingerprint=manifest_fingerprint,
            input_fingerprint=input_fingerprint,
        )
    audit = _build_audit(
        gate_status=CommonSampleGateStatus.READY.value,
        errors=(),
        warnings=_deduplicate(warnings),
        evaluation_status=evaluation_status,
        eligible_sample_size=eligible_count,
        common_sample_size=common_count,
        valid_period_count=len(valid_dates),
        manifest_fingerprint=manifest_fingerprint,
        input_fingerprint=input_fingerprint,
        common_sample_fingerprint=common_sample_fingerprint,
        output_fingerprint=output_fingerprint,
        configuration=configuration,
    )
    return FinancialP3CommonSampleResult(
        comparison=comparison,
        common_sample_audit=audit,
    )


def _validate_anchor(
    anchor: Mapping[str, Any],
    errors: list[CommonSampleIssue],
) -> None:
    if (
        anchor.get("task_id") != "FIN-P2-GATE"
        or str(anchor.get("status", "")).upper() != "ACCEPTED"
        or anchor.get("output_fingerprint")
        != COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT
        or anchor.get("research_integrity_status") != "complete"
        or anchor.get("production_status") != "not production ready"
    ):
        errors.append(
            _error(
                CommonSampleErrorCode.INVALID_GATE_ANCHOR,
                "FIN-P2-GATE accepted anchor does not match",
            )
        )


def _normalize_manifest(
    manifest: pd.DataFrame,
    errors: list[CommonSampleIssue],
) -> pd.DataFrame:
    missing = [
        column for column in _MANIFEST_COLUMNS if column not in manifest.columns
    ]
    for column in missing:
        errors.append(
            _error(
                CommonSampleErrorCode.MISSING_COLUMN,
                f"manifest column {column!r} is missing",
                field_name=column,
            )
        )
    if missing:
        return pd.DataFrame(columns=_MANIFEST_COLUMNS)
    output = manifest.loc[:, _MANIFEST_COLUMNS].copy()
    _normalize_keys(output, errors)
    invalid_eligible = ~output["eligible"].map(
        lambda value: type(value) in (bool, np.bool_)
    )
    if bool(invalid_eligible.any()):
        errors.append(
            _error(
                CommonSampleErrorCode.INVALID_KEY,
                "manifest eligible must be boolean",
                field_name="eligible",
            )
        )
    output["eligible"] = output["eligible"].map(bool)
    if bool(output.duplicated(list(_KEY_COLUMNS)).any()):
        errors.append(
            _error(
                CommonSampleErrorCode.DUPLICATE_MANIFEST_KEY,
                "manifest security-date keys must be unique",
            )
        )
    return output.sort_values(list(_KEY_COLUMNS), kind="stable").reset_index(
        drop=True
    )


def _normalize_frame(
    frame: pd.DataFrame,
    errors: list[CommonSampleIssue],
) -> pd.DataFrame:
    missing = [
        column for column in _FRAME_COLUMNS if column not in frame.columns
    ]
    for column in missing:
        errors.append(
            _error(
                CommonSampleErrorCode.MISSING_COLUMN,
                f"input column {column!r} is missing",
                field_name=column,
            )
        )
    forbidden = _FORBIDDEN_COLUMNS & set(str(column) for column in frame.columns)
    if forbidden:
        errors.append(
            _error(
                CommonSampleErrorCode.FORBIDDEN_SELECTION_FIELD,
                "selection or decision fields are forbidden",
                field_name=",".join(sorted(forbidden)),
            )
        )
    if missing:
        return pd.DataFrame(columns=_FRAME_COLUMNS)
    output = frame.loc[:, _FRAME_COLUMNS].copy()
    _normalize_keys(output, errors)
    for column in (
        "factor_effective_date",
        "control_effective_date",
        "return_start_date",
    ):
        parsed = pd.to_datetime(output[column], errors="coerce", format="mixed")
        if bool(parsed.isna().any()):
            errors.append(
                _error(
                    CommonSampleErrorCode.INVALID_KEY,
                    f"{column} contains an invalid date",
                    field_name=column,
                )
            )
        output[column] = parsed.dt.date.astype(str)
    output["industry_code"] = output["industry_code"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    if bool(output.duplicated(list(_KEY_COLUMNS)).any()):
        errors.append(
            _error(
                CommonSampleErrorCode.DUPLICATE_OBSERVATION_KEY,
                "input security-date keys must be unique",
            )
        )
    return output.sort_values(list(_KEY_COLUMNS), kind="stable").reset_index(
        drop=True
    )


def _normalize_keys(
    frame: pd.DataFrame,
    errors: list[CommonSampleIssue],
) -> None:
    dates = pd.to_datetime(
        frame["evaluation_date"], errors="coerce", format="mixed"
    )
    if bool(dates.isna().any()):
        errors.append(
            _error(
                CommonSampleErrorCode.INVALID_KEY,
                "evaluation_date contains an invalid date",
                field_name="evaluation_date",
            )
        )
    frame["evaluation_date"] = dates.dt.date.astype(str)
    security = frame["security_id"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    if bool((security == "").any()):
        errors.append(
            _error(
                CommonSampleErrorCode.INVALID_KEY,
                "security_id must be non-empty",
                field_name="security_id",
            )
        )
    frame["security_id"] = security


def _validate_relationships(
    manifest: pd.DataFrame,
    frame: pd.DataFrame,
    errors: list[CommonSampleIssue],
) -> None:
    if manifest.empty or frame.empty:
        return
    if bool(manifest.duplicated(list(_KEY_COLUMNS)).any()):
        return
    manifest_keys = set(
        map(tuple, manifest.loc[:, _KEY_COLUMNS].itertuples(index=False, name=None))
    )
    frame_keys = set(
        map(tuple, frame.loc[:, _KEY_COLUMNS].itertuples(index=False, name=None))
    )
    if frame_keys - manifest_keys:
        errors.append(
            _error(
                CommonSampleErrorCode.OBSERVATION_OUTSIDE_MANIFEST,
                "input contains security-date keys outside the manifest",
            )
        )
    evaluation = pd.to_datetime(
        frame["evaluation_date"], errors="coerce", format="mixed"
    )
    factor_effective = pd.to_datetime(
        frame["factor_effective_date"], errors="coerce", format="mixed"
    )
    control_effective = pd.to_datetime(
        frame["control_effective_date"], errors="coerce", format="mixed"
    )
    return_start = pd.to_datetime(
        frame["return_start_date"], errors="coerce", format="mixed"
    )
    if bool(((factor_effective > evaluation) | (control_effective > evaluation)).any()):
        errors.append(
            _error(
                CommonSampleErrorCode.FUTURE_FACTOR_OR_CONTROL,
                "factor and control effective dates must not exceed evaluation date",
            )
        )
    if bool((return_start <= evaluation).any()):
        errors.append(
            _error(
                CommonSampleErrorCode.INVALID_RETURN_ALIGNMENT,
                "return_start_date must be after evaluation_date",
            )
        )


def _join_manifest(
    manifest: pd.DataFrame,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    return manifest.merge(
        frame,
        on=list(_KEY_COLUMNS),
        how="left",
        validate="one_to_one",
        sort=True,
    )


def _availability_mask(frame: pd.DataFrame, factor_column: str) -> pd.Series:
    numeric_columns = (
        factor_column,
        "forward_return",
        "size_control",
    )
    mask = pd.Series(True, index=frame.index)
    for column in numeric_columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        mask &= np.isfinite(values)
    mask &= frame["industry_code"].fillna("").astype(str).str.strip().ne("")
    return mask


def _compute_metrics(
    frame: pd.DataFrame,
    *,
    factor_column: str,
    factor_id: str,
    common_sample_fingerprint: str,
    group_count: int,
) -> CommonSampleMetrics:
    rank_ics: list[float] = []
    group_rows: list[tuple[int, float]] = []
    r2_values: list[float] = []
    for _, period in frame.groupby("evaluation_date", sort=True):
        factor = pd.to_numeric(period[factor_column], errors="coerce")
        returns = pd.to_numeric(period["forward_return"], errors="coerce")
        ic = factor.rank(method="average").corr(
            returns.rank(method="average")
        )
        if pd.notna(ic):
            rank_ics.append(float(ic))
        ranks = factor.rank(method="first")
        groups = pd.qcut(
            ranks,
            q=group_count,
            labels=False,
            duplicates="raise",
        )
        for group_id in range(group_count):
            group_rows.append(
                (
                    group_id,
                    float(returns[groups == group_id].mean()),
                )
            )
        r2 = _cross_sectional_r2(period, factor_column)
        if r2 is not None:
            r2_values.append(r2)
    ic_array = np.asarray(rank_ics, dtype=float)
    mean_ic = float(np.mean(ic_array)) if len(ic_array) else None
    ic_std = (
        float(np.std(ic_array, ddof=1)) if len(ic_array) > 1 else None
    )
    icir = (
        mean_ic / ic_std
        if mean_ic is not None and ic_std is not None and ic_std > 1e-15
        else None
    )
    positive_ratio = (
        float(np.mean(ic_array > 0)) if len(ic_array) else None
    )
    group_returns = tuple(
        float(np.mean([value for group, value in group_rows if group == index]))
        for index in range(group_count)
    )
    spread = group_returns[-1] - group_returns[0]
    monotonicity = float(
        pd.Series(range(group_count), dtype=float).corr(
            pd.Series(group_returns).rank(method="average")
        )
    )
    fm_mean_r2 = float(np.mean(r2_values)) if r2_values else None
    payload = {
        "factor_id": factor_id,
        "valid_period_count": len(rank_ics),
        "common_observation_count": len(frame),
        "mean_rank_ic": mean_ic,
        "rank_ic_std": ic_std,
        "icir": icir,
        "positive_ic_ratio": positive_ratio,
        "group_returns": list(group_returns),
        "long_short_spread": spread,
        "monotonicity": monotonicity,
        "fm_mean_r2": fm_mean_r2,
        "common_sample_fingerprint": common_sample_fingerprint,
        "schema_version": COMMON_SAMPLE_METRICS_SCHEMA_VERSION,
    }
    return CommonSampleMetrics(
        factor_id=factor_id,
        valid_period_count=len(rank_ics),
        common_observation_count=len(frame),
        mean_rank_ic=mean_ic,
        rank_ic_std=ic_std,
        icir=icir,
        positive_ic_ratio=positive_ratio,
        group_returns=group_returns,
        long_short_spread=spread,
        monotonicity=monotonicity,
        fm_mean_r2=fm_mean_r2,
        common_sample_fingerprint=common_sample_fingerprint,
        schema_version=COMMON_SAMPLE_METRICS_SCHEMA_VERSION,
        content_hash=_hash("p3_common_sample_metrics", payload),
    )


def _cross_sectional_r2(frame: pd.DataFrame, factor_column: str) -> float | None:
    y = pd.to_numeric(frame["forward_return"], errors="coerce").to_numpy(float)
    factor = pd.to_numeric(frame[factor_column], errors="coerce").to_numpy(float)
    size = pd.to_numeric(frame["size_control"], errors="coerce").to_numpy(float)
    industries = pd.get_dummies(
        frame["industry_code"].astype(str),
        dtype=float,
        drop_first=True,
    ).to_numpy(float)
    columns = [np.ones(len(frame)), factor, size]
    if industries.shape[1]:
        columns.extend(industries[:, index] for index in range(industries.shape[1]))
    design = np.column_stack(columns)
    if len(frame) <= design.shape[1]:
        return None
    coefficients, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ coefficients
    total = float(np.sum((y - np.mean(y)) ** 2))
    if total <= 1e-18:
        return None
    return float(1.0 - np.sum(residual ** 2) / total)


def _build_comparison(
    *,
    configuration: FinancialP3CommonSampleConfig,
    evaluation_status: str,
    eligible_sample_size: int,
    single_available_size: int,
    combined_available_size: int,
    common_sample_size: int,
    common_period_count: int,
    single_metrics: CommonSampleMetrics | None,
    combined_metrics: CommonSampleMetrics | None,
    coverage_loss: float,
    common_sample_fingerprint: str,
) -> FinancialP3CommonSampleComparison:
    def delta(name: str) -> float | None:
        if single_metrics is None or combined_metrics is None:
            return None
        left = getattr(single_metrics, name)
        right = getattr(combined_metrics, name)
        return None if left is None or right is None else float(right - left)

    values = {
        "comparison_id": configuration.comparison_id,
        "single_factor_id": configuration.single_factor_id,
        "combined_factor_id": configuration.combined_factor_id,
        "evaluation_status": evaluation_status,
        "common_sample_size": common_sample_size,
        "eligible_sample_size": eligible_sample_size,
        "single_available_size": single_available_size,
        "combined_available_size": combined_available_size,
        "common_period_count": common_period_count,
        "single_factor_metrics": (
            None if single_metrics is None else single_metrics.to_dict()
        ),
        "combined_factor_metrics": (
            None if combined_metrics is None else combined_metrics.to_dict()
        ),
        "delta_ic": delta("mean_rank_ic"),
        "delta_icir": delta("icir"),
        "delta_monotonicity": delta("monotonicity"),
        "delta_fm_r2": delta("fm_mean_r2"),
        "coverage_loss": coverage_loss,
        "common_sample_fingerprint": common_sample_fingerprint,
        "schema_version": COMMON_SAMPLE_SCHEMA_VERSION,
    }
    return FinancialP3CommonSampleComparison(
        comparison_id=configuration.comparison_id,
        single_factor_id=configuration.single_factor_id,
        combined_factor_id=configuration.combined_factor_id,
        evaluation_status=evaluation_status,
        common_sample_size=common_sample_size,
        eligible_sample_size=eligible_sample_size,
        single_available_size=single_available_size,
        combined_available_size=combined_available_size,
        common_period_count=common_period_count,
        single_factor_metrics=single_metrics,
        combined_factor_metrics=combined_metrics,
        delta_ic=values["delta_ic"],
        delta_icir=values["delta_icir"],
        delta_monotonicity=values["delta_monotonicity"],
        delta_fm_r2=values["delta_fm_r2"],
        coverage_loss=coverage_loss,
        common_sample_fingerprint=common_sample_fingerprint,
        schema_version=COMMON_SAMPLE_SCHEMA_VERSION,
        content_hash=_hash("p3_common_sample_comparison", values),
    )


def _blocked_result(
    *,
    configuration: FinancialP3CommonSampleConfig,
    errors: Sequence[CommonSampleIssue],
    warnings: Sequence[CommonSampleIssue],
    manifest_fingerprint: str,
    input_fingerprint: str,
) -> FinancialP3CommonSampleResult:
    empty_fingerprint = _hash("p3_common_sample_rows", [])
    output_fingerprint = _hash(
        "p3_common_sample_blocked_output",
        [item.to_dict() for item in _deduplicate(errors)],
    )
    audit = _build_audit(
        gate_status=CommonSampleGateStatus.BLOCKED.value,
        errors=_deduplicate(errors),
        warnings=_deduplicate(warnings),
        evaluation_status=CommonSampleEvaluationStatus.NOT_RUN.value,
        eligible_sample_size=0,
        common_sample_size=0,
        valid_period_count=0,
        manifest_fingerprint=manifest_fingerprint,
        input_fingerprint=input_fingerprint,
        common_sample_fingerprint=empty_fingerprint,
        output_fingerprint=output_fingerprint,
        configuration=configuration,
    )
    return FinancialP3CommonSampleResult(
        comparison=None,
        common_sample_audit=audit,
    )


def _build_audit(
    *,
    gate_status: str,
    errors: Sequence[CommonSampleIssue],
    warnings: Sequence[CommonSampleIssue],
    evaluation_status: str,
    eligible_sample_size: int,
    common_sample_size: int,
    valid_period_count: int,
    manifest_fingerprint: str,
    input_fingerprint: str,
    common_sample_fingerprint: str,
    output_fingerprint: str,
    configuration: FinancialP3CommonSampleConfig,
) -> FinancialP3CommonSampleAudit:
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "evaluation_status": evaluation_status,
        "eligible_sample_size": eligible_sample_size,
        "common_sample_size": common_sample_size,
        "valid_period_count": valid_period_count,
        "same_sample_enforced": True,
        "pit_safe": gate_status == CommonSampleGateStatus.READY.value,
        "information_gain_decision_made": False,
        "fin24_combination_constructed": False,
        "synthetic_test_only": True,
        "research_assessment": COMMON_SAMPLE_RESEARCH_ASSESSMENT,
        "production_status": COMMON_SAMPLE_PRODUCTION_STATUS,
        "admission_status": COMMON_SAMPLE_ADMISSION_STATUS,
        "manifest_fingerprint": manifest_fingerprint,
        "input_fingerprint": input_fingerprint,
        "common_sample_fingerprint": common_sample_fingerprint,
        "output_fingerprint": output_fingerprint,
        "conclusion_boundary": COMMON_SAMPLE_CONCLUSION_BOUNDARY,
        "schema_version": COMMON_SAMPLE_SCHEMA_VERSION,
        "audit_schema_version": COMMON_SAMPLE_AUDIT_SCHEMA_VERSION,
        "policy_version": configuration.policy_version,
        "hash_contract_version": COMMON_SAMPLE_HASH_CONTRACT_VERSION,
    }
    return FinancialP3CommonSampleAudit(
        gate_status=gate_status,
        errors=tuple(errors),
        warnings=tuple(warnings),
        evaluation_status=evaluation_status,
        eligible_sample_size=eligible_sample_size,
        common_sample_size=common_sample_size,
        valid_period_count=valid_period_count,
        same_sample_enforced=True,
        pit_safe=gate_status == CommonSampleGateStatus.READY.value,
        information_gain_decision_made=False,
        fin24_combination_constructed=False,
        synthetic_test_only=True,
        research_assessment=COMMON_SAMPLE_RESEARCH_ASSESSMENT,
        production_status=COMMON_SAMPLE_PRODUCTION_STATUS,
        admission_status=COMMON_SAMPLE_ADMISSION_STATUS,
        manifest_fingerprint=manifest_fingerprint,
        input_fingerprint=input_fingerprint,
        common_sample_fingerprint=common_sample_fingerprint,
        output_fingerprint=output_fingerprint,
        conclusion_boundary=COMMON_SAMPLE_CONCLUSION_BOUNDARY,
        schema_version=COMMON_SAMPLE_SCHEMA_VERSION,
        audit_schema_version=COMMON_SAMPLE_AUDIT_SCHEMA_VERSION,
        policy_version=configuration.policy_version,
        hash_contract_version=COMMON_SAMPLE_HASH_CONTRACT_VERSION,
        content_hash=_hash("p3_common_sample_audit", payload),
    )


def _batch_guard(batch: FinancialP3CommonSampleBatch) -> str:
    return _hash(
        "p3_common_sample_batch_guard",
        {
            "manifest": _frame_records(batch.get_manifest()),
            "frame": _frame_records(batch.get_frame()),
            "anchor": batch.get_gate_anchor(),
            "provenance": batch.get_provenance(),
            "declared_manifest_fingerprint": (
                batch.declared_manifest_fingerprint
            ),
        },
    )


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    columns = sorted(str(column) for column in frame.columns)
    ordered = frame.loc[:, columns]
    sort_by = [column for column in _KEY_COLUMNS if column in columns]
    if sort_by:
        ordered = ordered.sort_values(sort_by, kind="stable")
    return [_canonical(row) for row in ordered.to_dict(orient="records")]


def _error(
    code: CommonSampleErrorCode,
    message: str,
    *,
    field_name: str | None = None,
    record_key: str | None = None,
) -> CommonSampleIssue:
    return CommonSampleIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
    )


def _warning(
    code: CommonSampleWarningCode,
    message: str,
) -> CommonSampleIssue:
    return CommonSampleIssue(code=code.value, message=message)


def _deduplicate(
    issues: Sequence[CommonSampleIssue],
) -> tuple[CommonSampleIssue, ...]:
    unique = {
        json.dumps(issue.to_dict(), sort_keys=True, ensure_ascii=False): issue
        for issue in issues
    }
    return tuple(unique[key] for key in sorted(unique))


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value.strip()


def _datetime_text(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    try:
        dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO datetime") from exc
    return text


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _canonical(value.to_dict())
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if math.isnan(number):
            return None
        if math.isinf(number):
            return str(number)
        return round(number, 15)
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _hash(domain: str, value: Any) -> str:
    payload = {
        "domain": domain,
        "hash_contract_version": COMMON_SAMPLE_HASH_CONTRACT_VERSION,
        "value": _canonical(value),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "COMMON_SAMPLE_CONCLUSION_BOUNDARY",
    "COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT",
    "CommonSampleErrorCode",
    "CommonSampleEvaluationStatus",
    "CommonSampleGateStatus",
    "CommonSampleIssue",
    "CommonSampleMetrics",
    "FinancialP3CommonSampleAudit",
    "FinancialP3CommonSampleBatch",
    "FinancialP3CommonSampleComparison",
    "FinancialP3CommonSampleConfig",
    "FinancialP3CommonSampleResult",
    "compute_common_sample_manifest_fingerprint",
    "evaluate_financial_p3_common_sample",
]
