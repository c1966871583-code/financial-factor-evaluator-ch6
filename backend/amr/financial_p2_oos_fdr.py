"""FIN-P2-OOS-FDR: frozen one-shot OOS tests and family-wise BH-FDR.

This additive, synthetic-only module implements the 23 named hypotheses in
FIN-EXP-00-HYP-v1.0.  It reads only the frozen test partition, preserves every
failed or non-evaluable run, and uses the full registered family size as the
Benjamini-Hochberg denominator.  Passing a p-value or q-value never creates an
admission, production, fraud, return, or trading conclusion.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import t as student_t


OOS_SCHEMA_VERSION = "FinancialP2OOSFDR-v1.0"
OOS_AUDIT_SCHEMA_VERSION = "FinancialP2OOSFDRAudit-v1.0"
OOS_HYPOTHESIS_SCHEMA_VERSION = "FinancialP2OOSHypothesis-v1.0"
OOS_FAMILY_SCHEMA_VERSION = "FinancialP2OOSFamily-v1.0"
OOS_POLICY_VERSION = "FIN-P2-OOS-FDR-POLICY-v1.0"
OOS_HASH_CONTRACT_VERSION = "FIN-P2-OOS-FDR-HASH-v1.0"
OOS_REGISTRY_VERSION = "FIN-EXP-00-HYP-v1.0"
OOS_MATRIX_VERSION = "FIN-EXP-00-MATRIX-v1.0"
OOS_ADJUSTMENT_METHOD = "benjamini_hochberg"
OOS_ALPHA = 0.05
OOS_SPLIT = (0.60, 0.20, 0.20)
OOS_PERMUTATION_COUNT = 199
OOS_RANDOM_SEED = 20260731
OOS_MIN_EFFECT_OBSERVATIONS = 12
OOS_MIN_R_POSITIVES = 30
OOS_MIN_R_NEGATIVES = 30
OOS_INDEPENDENCE_OUTPUT_FINGERPRINT = (
    "34048940ea418305b51ff36072d41ea7bd4c6220dbf47938377ed331811c9ae7"
)
OOS_CONCLUSION_BOUNDARY = (
    "Synthetic one-shot OOS/FDR contract evidence only; not an admission, "
    "production, return, fraud or misstatement determination, no-risk "
    "determination, or trading instruction."
)

FAMILY_F = "F_FORECAST_PRIMARY_V1"
FAMILY_R_HARD = "R_HARD_PRIMARY_V1"
FAMILY_R_SOFT = "R_SOFT_SECONDARY_V1"
FAMILY_M = "M_RETURN_20D_EXPLORATORY_V1"
FAMILY_ROBUSTNESS = "ROBUSTNESS_EXPLORATORY_V1"
OOS_FAMILY_IDS = (
    FAMILY_F,
    FAMILY_R_HARD,
    FAMILY_R_SOFT,
    FAMILY_M,
    FAMILY_ROBUSTNESS,
)

_FRAME_COLUMNS = (
    "hypothesis_id",
    "observation_id",
    "split",
    "period",
    "company_id",
    "effect_value",
    "label_state",
    "label",
    "baseline_score",
    "augmented_score",
)
_MANIFEST_COLUMNS = (
    "observation_id",
    "split",
    "period",
    "company_id",
)
_ALLOWED_SPLITS = ("train", "calibration", "test")
_ALLOWED_R_STATES = (
    "hard_positive",
    "soft_positive",
    "confirmed_negative",
    "unlabeled",
)


class OOSGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class OOSRunStatus(str, Enum):
    COMPLETED = "completed"
    INVALID = "invalid"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    INSUFFICIENT_LABEL = "insufficient_label"
    SOURCE_CONFLICT = "source_conflict"
    DATA_ERROR = "data_error"
    ABORTED = "aborted"
    EXECUTION_FAILED = "execution_failed"
    NOT_APPLICABLE = "not_applicable"


class OOSErrorCode(str, Enum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_BATCH = "INVALID_BATCH"
    INVALID_INDEPENDENCE_ANCHOR = "INVALID_INDEPENDENCE_ANCHOR"
    NON_SYNTHETIC_INPUT = "NON_SYNTHETIC_INPUT"
    MISSING_COLUMN = "MISSING_COLUMN"
    DUPLICATE_OBSERVATION_ID = "DUPLICATE_OBSERVATION_ID"
    DUPLICATE_HYPOTHESIS_OBSERVATION = (
        "DUPLICATE_HYPOTHESIS_OBSERVATION"
    )
    UNKNOWN_HYPOTHESIS = "UNKNOWN_HYPOTHESIS"
    INVALID_SPLIT = "INVALID_SPLIT"
    PARTITION_MISMATCH = "PARTITION_MISMATCH"
    PARTITION_FINGERPRINT_MISMATCH = (
        "PARTITION_FINGERPRINT_MISMATCH"
    )
    SPLIT_RATIO_MISMATCH = "SPLIT_RATIO_MISMATCH"
    TIME_ORDER_VIOLATION = "TIME_ORDER_VIOLATION"
    R_COMPANY_OVERLAP = "R_COMPANY_OVERLAP"
    TEST_SELECTION_FIELD_PRESENT = "TEST_SELECTION_FIELD_PRESENT"
    INPUT_MUTATED = "INPUT_MUTATED"


class OOSWarningCode(str, Enum):
    SYNTHETIC_OOS_ONLY = "SYNTHETIC_OOS_ONLY"
    FAILED_RUNS_RETAINED = "FAILED_RUNS_RETAINED"
    ROBUSTNESS_FAMILY_NOT_NAMED = "ROBUSTNESS_FAMILY_NOT_NAMED"
    FDR_NOT_ADMISSION = "FDR_NOT_ADMISSION"


@dataclass(frozen=True)
class FrozenHypothesisSpec:
    hypothesis_id: str
    factor_id: str
    validation_track: str
    hypothesis_class: str
    test_family_id: str
    metric_name: str
    prior_direction: str
    test_method: str
    train_period: str
    validation_period: str
    test_period: str

    def to_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }


def _specs() -> tuple[FrozenHypothesisSpec, ...]:
    items: list[FrozenHypothesisSpec] = []
    f_rows = (
        ("F-P01", "GPM_DELTA", "oos_relative_mae_improvement", "positive"),
        ("F-P02", "GPM_DELTA", "oos_relative_mae_improvement", "positive"),
        ("F-P03", "OCF_MARGIN", "oos_relative_mae_improvement", "positive"),
        ("F-P04", "OCF_MARGIN", "oos_relative_mae_improvement", "positive"),
        ("F-P05", "AR_REV_RATIO", "residual_rank_ic", "negative"),
        ("F-P06", "AR_REV_GAP", "residual_rank_ic", "negative"),
    )
    for hypothesis_id, factor_id, metric, direction in f_rows:
        items.append(
            FrozenHypothesisSpec(
                hypothesis_id=hypothesis_id,
                factor_id=factor_id,
                validation_track="F",
                hypothesis_class="primary",
                test_family_id=FAMILY_F,
                metric_name=metric,
                prior_direction=direction,
                test_method="one_sample_mean",
                train_period="earliest_60pct",
                validation_period="middle_20pct_calibration",
                test_period="latest_20pct_one_shot",
            )
        )
    r_factors = (
        "ACCRUAL_GAP_ASSET",
        "PROFIT_OCF_DIVERGENCE",
        "AR_ANOMALY",
        "AUDIT_OPINION_EVENT",
        "RESTATEMENT_EVENT",
    )
    for index, factor_id in enumerate(r_factors, start=1):
        items.append(
            FrozenHypothesisSpec(
                hypothesis_id=f"R-H{index:02d}",
                factor_id=factor_id,
                validation_track="R",
                hypothesis_class="primary",
                test_family_id=FAMILY_R_HARD,
                metric_name="pr_auc",
                prior_direction="positive",
                test_method="pr_auc_increment_permutation",
                train_period="earliest_60pct_company_disjoint",
                validation_period="middle_20pct_calibration",
                test_period="latest_20pct_one_shot_company_disjoint",
            )
        )
    soft_metrics = (
        "residual_rank_ic",
        "residual_rank_ic",
        "residual_rank_ic",
        "event_effect_estimate",
        "event_effect_estimate",
    )
    for index, (factor_id, metric) in enumerate(
        zip(r_factors, soft_metrics),
        start=1,
    ):
        items.append(
            FrozenHypothesisSpec(
                hypothesis_id=f"R-S{index:02d}",
                factor_id=factor_id,
                validation_track="R",
                hypothesis_class="secondary",
                test_family_id=FAMILY_R_SOFT,
                metric_name=metric,
                prior_direction="positive",
                test_method="one_sample_mean",
                train_period="earliest_60pct_company_disjoint",
                validation_period="middle_20pct_calibration",
                test_period="latest_20pct_one_shot_company_disjoint",
            )
        )
    m_factors = (
        "GPM_DELTA",
        "OCF_MARGIN",
        "AR_REV_RATIO",
        "AR_REV_GAP",
        "ACCRUAL_GAP_ASSET",
        "PROFIT_OCF_DIVERGENCE",
        "AR_ANOMALY",
    )
    for index, factor_id in enumerate(m_factors, start=1):
        items.append(
            FrozenHypothesisSpec(
                hypothesis_id=f"M-E{index:02d}",
                factor_id=factor_id,
                validation_track="M",
                hypothesis_class="exploratory",
                test_family_id=FAMILY_M,
                metric_name="rank_ic_mean",
                prior_direction="two_sided",
                test_method="one_sample_mean",
                train_period="earliest_60pct_descriptive",
                validation_period="middle_20pct_validation",
                test_period="latest_20pct_one_shot",
            )
        )
    return tuple(items)


FROZEN_HYPOTHESES = _specs()
FROZEN_HYPOTHESIS_IDS = tuple(
    item.hypothesis_id for item in FROZEN_HYPOTHESES
)
_SPEC_BY_ID = {
    item.hypothesis_id: item
    for item in FROZEN_HYPOTHESES
}
_FAMILY_COUNTS = {
    family_id: sum(
        item.test_family_id == family_id
        for item in FROZEN_HYPOTHESES
    )
    for family_id in OOS_FAMILY_IDS
}


@dataclass(frozen=True)
class FinancialP2OOSFDRConfig:
    expected_partition_fingerprint: str
    execution_timestamp: str
    alpha: float = OOS_ALPHA
    split: tuple[float, ...] = OOS_SPLIT
    adjustment_method: str = OOS_ADJUSTMENT_METHOD
    adjustment_scope: str = "within_frozen_family"
    permutation_count: int = OOS_PERMUTATION_COUNT
    random_seed: int = OOS_RANDOM_SEED
    minimum_effect_observations: int = OOS_MIN_EFFECT_OBSERVATIONS
    minimum_r_positives: int = OOS_MIN_R_POSITIVES
    minimum_r_negatives: int = OOS_MIN_R_NEGATIVES
    test_use_policy: str = "latest_20pct_one_shot_read_only"
    test_selection_allowed: bool = False
    failed_runs_retained: bool = True
    failed_runs_count_in_family_denominator: bool = True
    registry_version: str = OOS_REGISTRY_VERSION
    matrix_version: str = OOS_MATRIX_VERSION
    schema_version: str = OOS_SCHEMA_VERSION
    policy_version: str = OOS_POLICY_VERSION
    synthetic_test_only: bool = True

    def __post_init__(self) -> None:
        if not _is_sha256(self.expected_partition_fingerprint):
            raise ValueError(
                "expected_partition_fingerprint must be SHA-256"
            )
        _datetime_text(self.execution_timestamp, "execution_timestamp")
        frozen = {
            "alpha": (float(self.alpha), OOS_ALPHA),
            "split": (tuple(self.split), OOS_SPLIT),
            "adjustment_method": (
                self.adjustment_method,
                OOS_ADJUSTMENT_METHOD,
            ),
            "adjustment_scope": (
                self.adjustment_scope,
                "within_frozen_family",
            ),
            "permutation_count": (
                self.permutation_count,
                OOS_PERMUTATION_COUNT,
            ),
            "random_seed": (self.random_seed, OOS_RANDOM_SEED),
            "minimum_effect_observations": (
                self.minimum_effect_observations,
                OOS_MIN_EFFECT_OBSERVATIONS,
            ),
            "minimum_r_positives": (
                self.minimum_r_positives,
                OOS_MIN_R_POSITIVES,
            ),
            "minimum_r_negatives": (
                self.minimum_r_negatives,
                OOS_MIN_R_NEGATIVES,
            ),
            "test_use_policy": (
                self.test_use_policy,
                "latest_20pct_one_shot_read_only",
            ),
            "test_selection_allowed": (
                self.test_selection_allowed,
                False,
            ),
            "failed_runs_retained": (
                self.failed_runs_retained,
                True,
            ),
            "failed_runs_count_in_family_denominator": (
                self.failed_runs_count_in_family_denominator,
                True,
            ),
            "registry_version": (
                self.registry_version,
                OOS_REGISTRY_VERSION,
            ),
            "matrix_version": (
                self.matrix_version,
                OOS_MATRIX_VERSION,
            ),
            "schema_version": (
                self.schema_version,
                OOS_SCHEMA_VERSION,
            ),
            "policy_version": (
                self.policy_version,
                OOS_POLICY_VERSION,
            ),
            "synthetic_test_only": (
                self.synthetic_test_only,
                True,
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
        values["split"] = list(self.split)
        return values


@dataclass(frozen=True)
class FinancialP2OOSBatch:
    dataset_id: str
    version: str
    source: str
    _frame: pd.DataFrame
    _partition_manifest: pd.DataFrame
    declared_partition_fingerprint: str
    independence_anchor: Mapping[str, Any]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        _required_text(self.dataset_id, "dataset_id")
        _required_text(self.version, "version")
        _required_text(self.source, "source")
        if not isinstance(self._frame, pd.DataFrame):
            raise TypeError("_frame must be a pandas DataFrame")
        if not isinstance(self._partition_manifest, pd.DataFrame):
            raise TypeError(
                "_partition_manifest must be a pandas DataFrame"
            )
        if not _is_sha256(self.declared_partition_fingerprint):
            raise ValueError(
                "declared_partition_fingerprint must be SHA-256"
            )
        if not isinstance(self.independence_anchor, Mapping):
            raise TypeError("independence_anchor must be a mapping")
        if not isinstance(self.provenance, Mapping):
            raise TypeError("provenance must be a mapping")
        object.__setattr__(self, "_frame", self._frame.copy(deep=True))
        object.__setattr__(
            self,
            "_partition_manifest",
            self._partition_manifest.copy(deep=True),
        )
        object.__setattr__(
            self,
            "independence_anchor",
            copy.deepcopy(dict(self.independence_anchor)),
        )
        object.__setattr__(
            self,
            "provenance",
            copy.deepcopy(dict(self.provenance)),
        )

    def get_frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)

    def get_partition_manifest(self) -> pd.DataFrame:
        return self._partition_manifest.copy(deep=True)

    def get_independence_anchor(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.independence_anchor))

    def get_provenance(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.provenance))


@dataclass(frozen=True)
class OOSIssue:
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
class FinancialP2OOSHypothesisResult:
    hypothesis_id: str
    hypothesis_class: str
    test_family_id: str
    factor_id: str
    validation_track: str
    metric_name: str
    prior_direction: str
    test_method: str
    estimate: float | None
    raw_test_stat: float | None
    raw_p_value: float | None
    adjustment_method: str
    adjusted_q_value: float | None
    null_hypothesis_rejected_after_adjustment: bool
    direction_aligned: bool | None
    train_period: str
    validation_period: str
    test_period: str
    test_observation_count: int
    test_positive_count: int | None
    test_negative_count: int | None
    run_id: str
    run_status: str
    failure_reason_code: str | None
    failure_reason_detail: str | None
    started_at: str
    completed_at: str
    input_snapshot_reference: str
    test_partition_fingerprint: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class FinancialP2OOSFamilyResult:
    test_family_id: str
    registered_hypothesis_count: int
    completed_hypothesis_count: int
    failed_hypothesis_count: int
    fdr_denominator_count: int
    adjustment_method: str
    alpha: float
    family_status: str
    reason_code: str | None
    rejected_hypothesis_ids: tuple[str, ...]
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["rejected_hypothesis_ids"] = list(
            self.rejected_hypothesis_ids
        )
        return values


@dataclass(frozen=True)
class FinancialP2OOSFDRAudit:
    gate_status: str
    errors: tuple[OOSIssue, ...]
    warnings: tuple[OOSIssue, ...]
    registered_hypothesis_count: int
    retained_run_count: int
    completed_run_count: int
    failed_run_count: int
    registry_fingerprint: str
    configuration_fingerprint: str
    input_fingerprint: str
    partition_fingerprint: str
    test_input_fingerprint: str
    independence_output_fingerprint: str
    output_fingerprint: str
    test_use_policy: str
    test_selection_allowed: bool
    failed_runs_retained: bool
    failed_runs_count_in_family_denominator: bool
    synthetic_test_only: bool
    research_conclusion: str
    production_status: str
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
        values["warnings"] = [
            item.to_dict() for item in self.warnings
        ]
        return values


@dataclass(frozen=True)
class FinancialP2OOSFDRResult:
    hypothesis_results: tuple[FinancialP2OOSHypothesisResult, ...]
    family_results: tuple[FinancialP2OOSFamilyResult, ...]
    oos_fdr_audit: FinancialP2OOSFDRAudit

    def get_hypothesis(
        self,
        hypothesis_id: Any,
    ) -> FinancialP2OOSHypothesisResult:
        normalized = _required_text(hypothesis_id, "hypothesis_id")
        matches = [
            item
            for item in self.hypothesis_results
            if item.hypothesis_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one result for {normalized}"
            )
        return matches[0]

    def get_family(
        self,
        family_id: Any,
    ) -> FinancialP2OOSFamilyResult:
        normalized = _required_text(family_id, "family_id")
        matches = [
            item
            for item in self.family_results
            if item.test_family_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one family result for {normalized}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_results": [
                item.to_dict() for item in self.hypothesis_results
            ],
            "family_results": [
                item.to_dict() for item in self.family_results
            ],
            "oos_fdr_audit": self.oos_fdr_audit.to_dict(),
        }


def compute_partition_fingerprint(
    manifest: pd.DataFrame,
) -> str:
    """Return the canonical partition SHA-256 used by the freeze contract."""

    if not isinstance(manifest, pd.DataFrame):
        raise TypeError("manifest must be a pandas DataFrame")
    if any(column not in manifest.columns for column in _MANIFEST_COLUMNS):
        raise ValueError("manifest is missing required columns")
    records = _records(
        manifest,
        _MANIFEST_COLUMNS,
        sort_by=("observation_id",),
    )
    return _hash("oos_partition_manifest", records)


def evaluate_financial_p2_oos_fdr(
    batch: FinancialP2OOSBatch,
    *,
    configuration: FinancialP2OOSFDRConfig,
) -> FinancialP2OOSFDRResult:
    if not isinstance(batch, FinancialP2OOSBatch):
        raise TypeError("batch must be FinancialP2OOSBatch")
    if not isinstance(configuration, FinancialP2OOSFDRConfig):
        raise TypeError(
            "configuration must be FinancialP2OOSFDRConfig"
        )

    frame = batch.get_frame()
    manifest = batch.get_partition_manifest()
    anchor = batch.get_independence_anchor()
    provenance = batch.get_provenance()
    guard = _hash(
        "oos_batch_guard",
        {
            "frame": _frame_records(frame),
            "manifest": _frame_records(manifest),
            "anchor": anchor,
            "provenance": provenance,
            "declared_partition_fingerprint":
                batch.declared_partition_fingerprint,
        },
    )
    errors: list[OOSIssue] = []
    warnings: list[OOSIssue] = [
        _warning(
            OOSWarningCode.SYNTHETIC_OOS_ONLY,
            "Only deterministic synthetic OOS/FDR evidence is authorized.",
        ),
        _warning(
            OOSWarningCode.FAILED_RUNS_RETAINED,
            "Failed and non-evaluable runs remain in frozen family "
            "denominators.",
        ),
        _warning(
            OOSWarningCode.ROBUSTNESS_FAMILY_NOT_NAMED,
            "ROBUSTNESS_EXPLORATORY_V1 has no named hypothesis and "
            "remains not_run.",
        ),
        _warning(
            OOSWarningCode.FDR_NOT_ADMISSION,
            "A raw p-value or BH-FDR rejection is not an admission or "
            "production conclusion.",
        ),
    ]
    _validate_anchor(anchor, errors)
    if not bool(provenance.get("synthetic_test_only")):
        errors.append(
            _error(
                OOSErrorCode.NON_SYNTHETIC_INPUT,
                "provenance.synthetic_test_only must be true",
            )
        )
    normalized_manifest = _normalize_manifest(manifest, errors)
    normalized_frame = _normalize_frame(frame, errors)
    partition_fingerprint = (
        compute_partition_fingerprint(normalized_manifest)
        if not normalized_manifest.empty
        else _hash("oos_partition_manifest", [])
    )
    if partition_fingerprint != batch.declared_partition_fingerprint:
        errors.append(
            _error(
                OOSErrorCode.PARTITION_FINGERPRINT_MISMATCH,
                "declared partition fingerprint does not match manifest",
            )
        )
    if partition_fingerprint != (
        configuration.expected_partition_fingerprint
    ):
        errors.append(
            _error(
                OOSErrorCode.PARTITION_FINGERPRINT_MISMATCH,
                "manifest does not match the frozen configuration",
            )
        )
    _validate_partition(
        normalized_manifest,
        normalized_frame,
        errors,
    )
    input_fingerprint = _hash(
        "oos_input",
        _frame_records(frame),
    )
    test_input_fingerprint = _hash(
        "oos_test_input",
        _frame_records(
            normalized_frame[
                normalized_frame["split"] == "test"
            ]
        ),
    )
    if errors:
        return _blocked_result(
            configuration=configuration,
            errors=errors,
            warnings=warnings,
            input_fingerprint=input_fingerprint,
            partition_fingerprint=partition_fingerprint,
            test_input_fingerprint=test_input_fingerprint,
        )

    raw_results = [
        _evaluate_spec(
            spec,
            normalized_frame[
                normalized_frame["hypothesis_id"]
                == spec.hypothesis_id
            ],
            configuration=configuration,
            partition_fingerprint=partition_fingerprint,
            input_snapshot_reference=batch.dataset_id,
        )
        for spec in FROZEN_HYPOTHESES
    ]
    adjusted = _apply_family_bh(
        raw_results,
        alpha=configuration.alpha,
    )
    families = _build_family_results(
        adjusted,
        alpha=configuration.alpha,
    )
    output_fingerprint = _hash(
        "oos_fdr_output",
        {
            "hypotheses": [item.to_dict() for item in adjusted],
            "families": [item.to_dict() for item in families],
        },
    )
    current_guard = _hash(
        "oos_batch_guard",
        {
            "frame": _frame_records(batch.get_frame()),
            "manifest": _frame_records(
                batch.get_partition_manifest()
            ),
            "anchor": batch.get_independence_anchor(),
            "provenance": batch.get_provenance(),
            "declared_partition_fingerprint":
                batch.declared_partition_fingerprint,
        },
    )
    if current_guard != guard:
        return _blocked_result(
            configuration=configuration,
            errors=[
                _error(
                    OOSErrorCode.INPUT_MUTATED,
                    "input batch changed during evaluation",
                )
            ],
            warnings=warnings,
            input_fingerprint=input_fingerprint,
            partition_fingerprint=partition_fingerprint,
            test_input_fingerprint=test_input_fingerprint,
        )
    audit = _build_audit(
        gate_status=OOSGateStatus.READY.value,
        configuration=configuration,
        errors=(),
        warnings=_deduplicate(warnings),
        input_fingerprint=input_fingerprint,
        partition_fingerprint=partition_fingerprint,
        test_input_fingerprint=test_input_fingerprint,
        results=adjusted,
        output_fingerprint=output_fingerprint,
    )
    return FinancialP2OOSFDRResult(
        hypothesis_results=tuple(adjusted),
        family_results=tuple(families),
        oos_fdr_audit=audit,
    )


def _validate_anchor(
    anchor: Mapping[str, Any],
    errors: list[OOSIssue],
) -> None:
    if (
        anchor.get("task_id") != "FIN-P2-INDEP"
        or str(anchor.get("status", "")).upper() != "ACCEPTED"
        or anchor.get("output_fingerprint")
        != OOS_INDEPENDENCE_OUTPUT_FINGERPRINT
    ):
        errors.append(
            _error(
                OOSErrorCode.INVALID_INDEPENDENCE_ANCHOR,
                "FIN-P2-INDEP accepted output anchor does not match",
            )
        )


def _normalize_manifest(
    manifest: pd.DataFrame,
    errors: list[OOSIssue],
) -> pd.DataFrame:
    missing = [
        column
        for column in _MANIFEST_COLUMNS
        if column not in manifest.columns
    ]
    for column in missing:
        errors.append(
            _error(
                OOSErrorCode.MISSING_COLUMN,
                f"manifest column {column!r} is missing",
                field_name=column,
            )
        )
    if missing:
        return pd.DataFrame(columns=_MANIFEST_COLUMNS)
    output = manifest.loc[:, _MANIFEST_COLUMNS].copy()
    for column in _MANIFEST_COLUMNS:
        output[column] = output[column].map(
            lambda value: _required_text(value, column)
        )
    invalid = ~output["split"].isin(_ALLOWED_SPLITS)
    if bool(invalid.any()):
        errors.append(
            _error(
                OOSErrorCode.INVALID_SPLIT,
                "manifest contains an invalid split",
            )
        )
    if bool(output["observation_id"].duplicated().any()):
        errors.append(
            _error(
                OOSErrorCode.DUPLICATE_OBSERVATION_ID,
                "manifest observation_id must be unique",
            )
        )
    return output.sort_values(
        ["observation_id"],
        kind="stable",
    ).reset_index(drop=True)


def _normalize_frame(
    frame: pd.DataFrame,
    errors: list[OOSIssue],
) -> pd.DataFrame:
    missing = [
        column for column in _FRAME_COLUMNS if column not in frame.columns
    ]
    for column in missing:
        errors.append(
            _error(
                OOSErrorCode.MISSING_COLUMN,
                f"input column {column!r} is missing",
                field_name=column,
            )
        )
    forbidden = {
        "selected_direction",
        "selected_threshold",
        "selected_model",
        "selected_family",
        "selected_sample",
    } & set(str(column) for column in frame.columns)
    if forbidden:
        errors.append(
            _error(
                OOSErrorCode.TEST_SELECTION_FIELD_PRESENT,
                "test-selection fields are forbidden",
                field_name=",".join(sorted(forbidden)),
            )
        )
    if missing:
        return pd.DataFrame(columns=_FRAME_COLUMNS)
    output = frame.loc[:, _FRAME_COLUMNS].copy()
    for column in (
        "hypothesis_id",
        "observation_id",
        "split",
        "period",
        "company_id",
    ):
        output[column] = output[column].map(
            lambda value: _required_text(value, column)
        )
    unknown = sorted(
        set(output["hypothesis_id"]) - set(FROZEN_HYPOTHESIS_IDS)
    )
    if unknown:
        errors.append(
            _error(
                OOSErrorCode.UNKNOWN_HYPOTHESIS,
                f"unknown hypotheses: {unknown}",
            )
        )
    if bool(
        output.duplicated(
            ["hypothesis_id", "observation_id"]
        ).any()
    ):
        errors.append(
            _error(
                OOSErrorCode.DUPLICATE_HYPOTHESIS_OBSERVATION,
                "hypothesis_id + observation_id must be unique",
            )
        )
    if bool((~output["split"].isin(_ALLOWED_SPLITS)).any()):
        errors.append(
            _error(
                OOSErrorCode.INVALID_SPLIT,
                "input contains an invalid split",
            )
        )
    return output.sort_values(
        ["hypothesis_id", "observation_id"],
        kind="stable",
    ).reset_index(drop=True)


def _validate_partition(
    manifest: pd.DataFrame,
    frame: pd.DataFrame,
    errors: list[OOSIssue],
) -> None:
    if manifest.empty or frame.empty:
        return
    if bool(manifest["observation_id"].duplicated().any()):
        # The duplicate has already been recorded by normalization.  Do not
        # construct a non-unique lookup that could turn a governed rejection
        # into an unhandled pandas exception.
        return
    lookup = manifest.set_index("observation_id")
    missing_ids = sorted(
        set(frame["observation_id"]) - set(lookup.index)
    )
    if missing_ids:
        errors.append(
            _error(
                OOSErrorCode.PARTITION_MISMATCH,
                "input observations are absent from manifest",
            )
        )
        return
    for column in ("split", "period", "company_id"):
        expected = frame["observation_id"].map(lookup[column])
        if bool((frame[column] != expected).any()):
            errors.append(
                _error(
                    OOSErrorCode.PARTITION_MISMATCH,
                    f"input {column} differs from frozen manifest",
                    field_name=column,
                )
            )
    counts = manifest["split"].value_counts()
    total = len(manifest)
    ratios = tuple(
        counts.get(split, 0) / total
        for split in _ALLOWED_SPLITS
    )
    if any(
        abs(actual - expected) > 1e-12
        for actual, expected in zip(ratios, OOS_SPLIT)
    ):
        errors.append(
            _error(
                OOSErrorCode.SPLIT_RATIO_MISMATCH,
                "manifest must use exact 60/20/20 counts",
            )
        )
    period_dates = {
        split: sorted(
            pd.Timestamp(value)
            for value in manifest.loc[
                manifest["split"] == split,
                "period",
            ].unique()
        )
        for split in _ALLOWED_SPLITS
    }
    if all(period_dates.values()) and not (
        max(period_dates["train"])
        < min(period_dates["calibration"])
        < min(period_dates["test"])
    ):
        errors.append(
            _error(
                OOSErrorCode.TIME_ORDER_VIOLATION,
                "train, calibration, and test periods must be ordered",
            )
        )
    r_ids = set(
        frame.loc[
            frame["hypothesis_id"].str.startswith("R-"),
            "observation_id",
        ]
    )
    r_manifest = manifest[manifest["observation_id"].isin(r_ids)]
    company_splits = r_manifest.groupby("company_id")[
        "split"
    ].nunique()
    if bool((company_splits > 1).any()):
        errors.append(
            _error(
                OOSErrorCode.R_COMPANY_OVERLAP,
                "R companies must be disjoint across splits",
            )
        )


def _evaluate_spec(
    spec: FrozenHypothesisSpec,
    frame: pd.DataFrame,
    *,
    configuration: FinancialP2OOSFDRConfig,
    partition_fingerprint: str,
    input_snapshot_reference: str,
) -> FinancialP2OOSHypothesisResult:
    test = frame[frame["split"] == "test"].copy()
    test_fingerprint = _hash(
        f"oos_test_{spec.hypothesis_id}",
        _frame_records(test),
    )
    base = {
        "hypothesis_id": spec.hypothesis_id,
        "hypothesis_class": spec.hypothesis_class,
        "test_family_id": spec.test_family_id,
        "factor_id": spec.factor_id,
        "validation_track": spec.validation_track,
        "metric_name": spec.metric_name,
        "prior_direction": spec.prior_direction,
        "test_method": spec.test_method,
        "adjustment_method": OOS_ADJUSTMENT_METHOD,
        "adjusted_q_value": None,
        "null_hypothesis_rejected_after_adjustment": False,
        "train_period": spec.train_period,
        "validation_period": spec.validation_period,
        "test_period": spec.test_period,
        "run_id": _hash(
            "oos_run_id",
            {
                "hypothesis_id": spec.hypothesis_id,
                "test_fingerprint": test_fingerprint,
                "execution_timestamp":
                    configuration.execution_timestamp,
            },
        ),
        "started_at": configuration.execution_timestamp,
        "completed_at": configuration.execution_timestamp,
        "input_snapshot_reference": input_snapshot_reference,
        "test_partition_fingerprint": partition_fingerprint,
        "schema_version": OOS_HYPOTHESIS_SCHEMA_VERSION,
    }
    if spec.test_method == "one_sample_mean":
        values = pd.to_numeric(
            test["effect_value"],
            errors="coerce",
        ).dropna().to_numpy(float)
        if len(values) < configuration.minimum_effect_observations:
            return _failed_hypothesis(
                base,
                status=OOSRunStatus.INSUFFICIENT_SAMPLE.value,
                reason_code="INSUFFICIENT_TEST_OBSERVATIONS",
                reason_detail=(
                    f"need {configuration.minimum_effect_observations}; "
                    f"got {len(values)}"
                ),
                count=len(values),
            )
        estimate = float(np.mean(values))
        std = float(np.std(values, ddof=1))
        if std <= 1e-15:
            return _failed_hypothesis(
                base,
                status=OOSRunStatus.INVALID.value,
                reason_code="CONSTANT_TEST_EFFECT",
                reason_detail="test effect has zero variance",
                count=len(values),
            )
        statistic = estimate / (std / math.sqrt(len(values)))
        degrees = len(values) - 1
        if spec.prior_direction == "positive":
            p_value = float(student_t.sf(statistic, degrees))
            aligned: bool | None = estimate > 0
        elif spec.prior_direction == "negative":
            p_value = float(student_t.cdf(statistic, degrees))
            aligned = estimate < 0
        else:
            p_value = float(
                2.0 * student_t.sf(abs(statistic), degrees)
            )
            aligned = None
        return _completed_hypothesis(
            base,
            estimate=estimate,
            statistic=statistic,
            p_value=p_value,
            direction_aligned=aligned,
            count=len(values),
            positive_count=None,
            negative_count=None,
        )

    states = test["label_state"].astype(str)
    eligible = test[
        states.isin(["hard_positive", "confirmed_negative"])
    ].copy()
    positives = int(
        (eligible["label_state"] == "hard_positive").sum()
    )
    negatives = int(
        (eligible["label_state"] == "confirmed_negative").sum()
    )
    if (
        positives < configuration.minimum_r_positives
        or negatives < configuration.minimum_r_negatives
    ):
        return _failed_hypothesis(
            base,
            status=OOSRunStatus.INSUFFICIENT_LABEL.value,
            reason_code="INSUFFICIENT_HARD_TEST_LABELS",
            reason_detail=(
                f"positive={positives}; negative={negatives}"
            ),
            count=len(eligible),
            positive_count=positives,
            negative_count=negatives,
        )
    y = (
        eligible["label_state"] == "hard_positive"
    ).astype(float).to_numpy()
    baseline = pd.to_numeric(
        eligible["baseline_score"],
        errors="coerce",
    ).to_numpy(float)
    augmented = pd.to_numeric(
        eligible["augmented_score"],
        errors="coerce",
    ).to_numpy(float)
    if not (
        np.isfinite(baseline).all()
        and np.isfinite(augmented).all()
    ):
        return _failed_hypothesis(
            base,
            status=OOSRunStatus.DATA_ERROR.value,
            reason_code="NON_FINITE_TEST_SCORE",
            reason_detail="test scores must be finite",
            count=len(eligible),
            positive_count=positives,
            negative_count=negatives,
        )
    baseline_pr = _average_precision(y, baseline)
    augmented_pr = _average_precision(y, augmented)
    estimate = augmented_pr - baseline_pr
    increments = augmented - baseline
    rng = np.random.default_rng(
        _seed_for(spec.hypothesis_id, configuration.random_seed)
    )
    exceed = 0
    for _ in range(configuration.permutation_count):
        candidate = baseline + rng.permutation(increments)
        statistic = _average_precision(y, candidate) - baseline_pr
        if statistic >= estimate - 1e-15:
            exceed += 1
    p_value = (exceed + 1.0) / (
        configuration.permutation_count + 1.0
    )
    return _completed_hypothesis(
        base,
        estimate=estimate,
        statistic=estimate,
        p_value=float(p_value),
        direction_aligned=estimate > 0,
        count=len(eligible),
        positive_count=positives,
        negative_count=negatives,
    )


def _completed_hypothesis(
    base: Mapping[str, Any],
    *,
    estimate: float,
    statistic: float,
    p_value: float,
    direction_aligned: bool | None,
    count: int,
    positive_count: int | None,
    negative_count: int | None,
) -> FinancialP2OOSHypothesisResult:
    payload = {
        **base,
        "estimate": estimate,
        "raw_test_stat": statistic,
        "raw_p_value": p_value,
        "direction_aligned": direction_aligned,
        "test_observation_count": count,
        "test_positive_count": positive_count,
        "test_negative_count": negative_count,
        "run_status": OOSRunStatus.COMPLETED.value,
        "failure_reason_code": None,
        "failure_reason_detail": None,
    }
    return FinancialP2OOSHypothesisResult(
        **payload,
        content_hash=_hash("oos_hypothesis", payload),
    )


def _failed_hypothesis(
    base: Mapping[str, Any],
    *,
    status: str,
    reason_code: str,
    reason_detail: str,
    count: int,
    positive_count: int | None = None,
    negative_count: int | None = None,
) -> FinancialP2OOSHypothesisResult:
    payload = {
        **base,
        "estimate": None,
        "raw_test_stat": None,
        "raw_p_value": None,
        "direction_aligned": None,
        "test_observation_count": count,
        "test_positive_count": positive_count,
        "test_negative_count": negative_count,
        "run_status": status,
        "failure_reason_code": reason_code,
        "failure_reason_detail": reason_detail,
    }
    return FinancialP2OOSHypothesisResult(
        **payload,
        content_hash=_hash("oos_hypothesis", payload),
    )


def _apply_family_bh(
    results: Sequence[FinancialP2OOSHypothesisResult],
    *,
    alpha: float,
) -> list[FinancialP2OOSHypothesisResult]:
    output = list(results)
    for family_id in OOS_FAMILY_IDS:
        indices = [
            index
            for index, item in enumerate(output)
            if item.test_family_id == family_id
            and item.raw_p_value is not None
        ]
        if not indices:
            continue
        ordered = sorted(
            indices,
            key=lambda index: (
                float(output[index].raw_p_value),
                output[index].hypothesis_id,
            ),
        )
        denominator = _FAMILY_COUNTS[family_id]
        adjusted: dict[int, float] = {}
        running = 1.0
        for rank_index in range(len(ordered) - 1, -1, -1):
            rank = rank_index + 1
            index = ordered[rank_index]
            candidate = min(
                1.0,
                float(output[index].raw_p_value)
                * denominator
                / rank,
            )
            running = min(running, candidate)
            adjusted[index] = running
        for index in indices:
            item = output[index]
            q_value = adjusted[index]
            aligned = (
                item.direction_aligned is not False
            )
            rejected = bool(q_value <= alpha and aligned)
            updated = replace(
                item,
                adjusted_q_value=q_value,
                null_hypothesis_rejected_after_adjustment=rejected,
                content_hash="",
            )
            payload = updated.to_dict()
            payload.pop("content_hash")
            output[index] = replace(
                updated,
                content_hash=_hash(
                    "oos_hypothesis_adjusted",
                    payload,
                ),
            )
    return output


def _build_family_results(
    results: Sequence[FinancialP2OOSHypothesisResult],
    *,
    alpha: float,
) -> list[FinancialP2OOSFamilyResult]:
    families: list[FinancialP2OOSFamilyResult] = []
    for family_id in OOS_FAMILY_IDS:
        members = [
            item
            for item in results
            if item.test_family_id == family_id
        ]
        registered = _FAMILY_COUNTS[family_id]
        completed = sum(
            item.run_status == OOSRunStatus.COMPLETED.value
            for item in members
        )
        failed = registered - completed
        if registered == 0:
            status = "not_run"
            reason = "NO_NAMED_HYPOTHESES_REGISTERED"
        elif failed:
            status = "partial"
            reason = "FAILED_RUNS_RETAINED"
        else:
            status = "completed"
            reason = None
        rejected = tuple(
            item.hypothesis_id
            for item in members
            if item.null_hypothesis_rejected_after_adjustment
        )
        payload = {
            "test_family_id": family_id,
            "registered_hypothesis_count": registered,
            "completed_hypothesis_count": completed,
            "failed_hypothesis_count": failed,
            "fdr_denominator_count": registered,
            "adjustment_method": OOS_ADJUSTMENT_METHOD,
            "alpha": alpha,
            "family_status": status,
            "reason_code": reason,
            "rejected_hypothesis_ids": list(rejected),
            "schema_version": OOS_FAMILY_SCHEMA_VERSION,
        }
        families.append(
            FinancialP2OOSFamilyResult(
                test_family_id=family_id,
                registered_hypothesis_count=registered,
                completed_hypothesis_count=completed,
                failed_hypothesis_count=failed,
                fdr_denominator_count=registered,
                adjustment_method=OOS_ADJUSTMENT_METHOD,
                alpha=alpha,
                family_status=status,
                reason_code=reason,
                rejected_hypothesis_ids=rejected,
                schema_version=OOS_FAMILY_SCHEMA_VERSION,
                content_hash=_hash("oos_family", payload),
            )
        )
    return families


def _blocked_result(
    *,
    configuration: FinancialP2OOSFDRConfig,
    errors: Sequence[OOSIssue],
    warnings: Sequence[OOSIssue],
    input_fingerprint: str,
    partition_fingerprint: str,
    test_input_fingerprint: str,
) -> FinancialP2OOSFDRResult:
    audit = _build_audit(
        gate_status=OOSGateStatus.BLOCKED.value,
        configuration=configuration,
        errors=_deduplicate(errors),
        warnings=_deduplicate(warnings),
        input_fingerprint=input_fingerprint,
        partition_fingerprint=partition_fingerprint,
        test_input_fingerprint=test_input_fingerprint,
        results=(),
        output_fingerprint=_hash(
            "oos_blocked_output",
            [item.to_dict() for item in errors],
        ),
    )
    return FinancialP2OOSFDRResult(
        hypothesis_results=(),
        family_results=(),
        oos_fdr_audit=audit,
    )


def _build_audit(
    *,
    gate_status: str,
    configuration: FinancialP2OOSFDRConfig,
    errors: Sequence[OOSIssue],
    warnings: Sequence[OOSIssue],
    input_fingerprint: str,
    partition_fingerprint: str,
    test_input_fingerprint: str,
    results: Sequence[FinancialP2OOSHypothesisResult],
    output_fingerprint: str,
) -> FinancialP2OOSFDRAudit:
    completed = sum(
        item.run_status == OOSRunStatus.COMPLETED.value
        for item in results
    )
    retained = len(results)
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "registered_hypothesis_count": len(FROZEN_HYPOTHESES),
        "retained_run_count": retained,
        "completed_run_count": completed,
        "failed_run_count": retained - completed,
        "registry_fingerprint": _hash(
            "oos_frozen_registry",
            [item.to_dict() for item in FROZEN_HYPOTHESES],
        ),
        "configuration_fingerprint": _hash(
            "oos_configuration",
            configuration.to_dict(),
        ),
        "input_fingerprint": input_fingerprint,
        "partition_fingerprint": partition_fingerprint,
        "test_input_fingerprint": test_input_fingerprint,
        "independence_output_fingerprint":
            OOS_INDEPENDENCE_OUTPUT_FINGERPRINT,
        "output_fingerprint": output_fingerprint,
        "test_use_policy": "latest_20pct_one_shot_read_only",
        "test_selection_allowed": False,
        "failed_runs_retained": True,
        "failed_runs_count_in_family_denominator": True,
        "synthetic_test_only": True,
        "research_conclusion": "exploratory",
        "production_status": "not production ready",
        "conclusion_boundary": OOS_CONCLUSION_BOUNDARY,
        "schema_version": OOS_SCHEMA_VERSION,
        "audit_schema_version": OOS_AUDIT_SCHEMA_VERSION,
        "policy_version": OOS_POLICY_VERSION,
        "hash_contract_version": OOS_HASH_CONTRACT_VERSION,
    }
    return FinancialP2OOSFDRAudit(
        gate_status=gate_status,
        errors=tuple(errors),
        warnings=tuple(warnings),
        registered_hypothesis_count=len(FROZEN_HYPOTHESES),
        retained_run_count=retained,
        completed_run_count=completed,
        failed_run_count=retained - completed,
        registry_fingerprint=payload["registry_fingerprint"],
        configuration_fingerprint=payload[
            "configuration_fingerprint"
        ],
        input_fingerprint=input_fingerprint,
        partition_fingerprint=partition_fingerprint,
        test_input_fingerprint=test_input_fingerprint,
        independence_output_fingerprint=
            OOS_INDEPENDENCE_OUTPUT_FINGERPRINT,
        output_fingerprint=output_fingerprint,
        test_use_policy="latest_20pct_one_shot_read_only",
        test_selection_allowed=False,
        failed_runs_retained=True,
        failed_runs_count_in_family_denominator=True,
        synthetic_test_only=True,
        research_conclusion="exploratory",
        production_status="not production ready",
        conclusion_boundary=OOS_CONCLUSION_BOUNDARY,
        schema_version=OOS_SCHEMA_VERSION,
        audit_schema_version=OOS_AUDIT_SCHEMA_VERSION,
        policy_version=OOS_POLICY_VERSION,
        hash_contract_version=OOS_HASH_CONTRACT_VERSION,
        content_hash=_hash("oos_audit", payload),
    )


def _average_precision(y: np.ndarray, score: np.ndarray) -> float:
    order = np.argsort(-score, kind="stable")
    ordered = y[order]
    positives = int(np.sum(ordered))
    if positives == 0:
        return 0.0
    cumulative = np.cumsum(ordered)
    precision = cumulative / np.arange(1, len(ordered) + 1)
    return float(np.sum(precision * ordered) / positives)


def _seed_for(hypothesis_id: str, base_seed: int) -> int:
    digest = hashlib.sha256(
        f"{base_seed}:{hypothesis_id}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _records(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    sort_by: Sequence[str],
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    ordered = frame.loc[:, list(columns)].sort_values(
        list(sort_by),
        kind="stable",
    )
    return [
        _canonical(row)
        for row in ordered.to_dict(orient="records")
    ]


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    columns = sorted(str(column) for column in frame.columns)
    sort_by = [
        column
        for column in (
            "hypothesis_id",
            "observation_id",
        )
        if column in columns
    ]
    ordered = frame.loc[:, columns]
    if sort_by:
        ordered = ordered.sort_values(sort_by, kind="stable")
    return [
        _canonical(row)
        for row in ordered.to_dict(orient="records")
    ]


def _error(
    code: OOSErrorCode,
    message: str,
    *,
    field_name: str | None = None,
    record_key: str | None = None,
) -> OOSIssue:
    return OOSIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
    )


def _warning(
    code: OOSWarningCode,
    message: str,
) -> OOSIssue:
    return OOSIssue(code=code.value, message=message)


def _deduplicate(
    issues: Sequence[OOSIssue],
) -> tuple[OOSIssue, ...]:
    unique = {
        json.dumps(
            issue.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
        ): issue
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
        raise ValueError(
            f"{field_name} must be an ISO datetime"
        ) from exc
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
            for key, item in sorted(
                value.items(),
                key=lambda pair: str(pair[0]),
            )
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
        "hash_contract_version": OOS_HASH_CONTRACT_VERSION,
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
    "FROZEN_HYPOTHESES",
    "FROZEN_HYPOTHESIS_IDS",
    "FinancialP2OOSBatch",
    "FinancialP2OOSFDRAudit",
    "FinancialP2OOSFDRConfig",
    "FinancialP2OOSFDRResult",
    "FinancialP2OOSFamilyResult",
    "FinancialP2OOSHypothesisResult",
    "FrozenHypothesisSpec",
    "OOSErrorCode",
    "OOSGateStatus",
    "OOSIssue",
    "OOSRunStatus",
    "OOSWarningCode",
    "OOS_ALPHA",
    "OOS_CONCLUSION_BOUNDARY",
    "OOS_FAMILY_IDS",
    "OOS_HASH_CONTRACT_VERSION",
    "OOS_POLICY_VERSION",
    "OOS_SCHEMA_VERSION",
    "compute_partition_fingerprint",
    "evaluate_financial_p2_oos_fdr",
]
