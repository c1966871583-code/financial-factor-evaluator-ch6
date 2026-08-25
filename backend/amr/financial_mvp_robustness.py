"""FIN-MVP-ROBUST: frozen Phase-1 financial robustness summary."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from backend.amr.evaluation_group_returns import evaluate_group_returns
from backend.amr.evaluation_input_contract import (
    ForwardReturnBatch,
    ValueScope,
)
from backend.amr.evaluation_statistics import hac_t_stat
from backend.amr.financial_mvp_batch import (
    SUPPORTED_FACTOR_IDS,
    MVPFinancialBatchResult,
)
from backend.amr.financial_mvp_m_evaluation import (
    M_EVAL_MIN_CROSS_SECTION,
    M_EVAL_MIN_PERIODS,
    M_EVAL_QUANTILES,
    FinancialMVPMEvaluationConfig,
    FinancialMVPMEvaluationResult,
    evaluate_financial_mvp_m,
)
from backend.amr.financial_preprocessing import (
    FinancialPreprocessingResult,
)

ROBUSTNESS_SCHEMA_VERSION = "FinancialMVPRobustness-v1.0"
ROBUSTNESS_AUDIT_SCHEMA_VERSION = "FinancialMVPRobustnessAudit-v1.0"
ROBUSTNESS_CELL_SCHEMA_VERSION = "FinancialMVPRobustnessCell-v1.0"
ROBUSTNESS_FACTOR_SCHEMA_VERSION = "FinancialMVPFactorRobustness-v1.0"
ROBUSTNESS_HASH_CONTRACT_VERSION = "FIN-MVP-ROBUST-HASH-v2.0"
HASH_FLOAT_DECIMAL_PLACES = 8
ROBUSTNESS_POLICY_VERSION = "FIN-MVP-ROBUST-POLICY-v1.0"
ROBUSTNESS_SPLIT_POLICY = "chronological_equal_halves"
ROBUSTNESS_VARIANTS = ("raw_pit_factor_value", "evaluation_factor_value")
ROBUSTNESS_SEGMENTS = ("full", "first_half", "second_half")
ROBUSTNESS_MIN_SUBPERIODS = 6
_ZERO_TOLERANCE = 1e-12


class RobustnessGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class RobustnessCellStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    NOT_RUN = "not_run"


class RobustnessDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    ZERO = "zero"
    NOT_EVALUABLE = "not_evaluable"


class RobustnessConsistency(str, Enum):
    CONSISTENT = "consistent"
    MIXED = "mixed"
    INSUFFICIENT = "insufficient"


class RobustnessErrorCode(str, Enum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_MVP_BATCH_RESULT = "INVALID_MVP_BATCH_RESULT"
    INVALID_PREPROCESSING_RESULT = "INVALID_PREPROCESSING_RESULT"
    INVALID_FORWARD_RETURN_BATCH = "INVALID_FORWARD_RETURN_BATCH"
    INVALID_M_EVALUATION_RESULT = "INVALID_M_EVALUATION_RESULT"
    M_EVALUATION_GATE_BLOCKED = "M_EVALUATION_GATE_BLOCKED"
    M_EVALUATION_OUTPUT_MISMATCH = "M_EVALUATION_OUTPUT_MISMATCH"
    FACTOR_INPUT_COVERAGE_MISMATCH = "FACTOR_INPUT_COVERAGE_MISMATCH"
    MAD_PRIMARY_STATISTIC_MISMATCH = "MAD_PRIMARY_STATISTIC_MISMATCH"
    INPUT_MUTATED = "INPUT_MUTATED"


@dataclass(frozen=True)
class FinancialMVPRobustnessConfig:
    m_evaluation_configuration: FinancialMVPMEvaluationConfig
    split_policy: str = ROBUSTNESS_SPLIT_POLICY
    minimum_subperiod_evaluation_periods: int = ROBUSTNESS_MIN_SUBPERIODS
    variants: tuple[str, ...] = ROBUSTNESS_VARIANTS
    segments: tuple[str, ...] = ROBUSTNESS_SEGMENTS
    schema_version: str = ROBUSTNESS_SCHEMA_VERSION
    policy_version: str = ROBUSTNESS_POLICY_VERSION
    synthetic_test_only: bool = True

    def __post_init__(self) -> None:
        if not isinstance(
            self.m_evaluation_configuration,
            FinancialMVPMEvaluationConfig,
        ):
            raise TypeError(
                "m_evaluation_configuration must be "
                "FinancialMVPMEvaluationConfig"
            )
        frozen = {
            "split_policy": (self.split_policy, ROBUSTNESS_SPLIT_POLICY),
            "minimum_subperiod_evaluation_periods": (
                self.minimum_subperiod_evaluation_periods,
                ROBUSTNESS_MIN_SUBPERIODS,
            ),
            "variants": (tuple(self.variants), ROBUSTNESS_VARIANTS),
            "segments": (tuple(self.segments), ROBUSTNESS_SEGMENTS),
            "schema_version": (
                self.schema_version,
                ROBUSTNESS_SCHEMA_VERSION,
            ),
            "policy_version": (
                self.policy_version,
                ROBUSTNESS_POLICY_VERSION,
            ),
            "synthetic_test_only": (self.synthetic_test_only, True),
        }
        for field_name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{field_name} must be frozen at {expected}")

    @property
    def evaluation_dates(self) -> tuple[str, ...]:
        return self.m_evaluation_configuration.evaluation_dates

    @property
    def first_half_dates(self) -> tuple[str, ...]:
        midpoint = len(self.evaluation_dates) // 2
        return self.evaluation_dates[:midpoint]

    @property
    def second_half_dates(self) -> tuple[str, ...]:
        midpoint = len(self.evaluation_dates) // 2
        return self.evaluation_dates[midpoint:]

    def to_dict(self) -> dict[str, Any]:
        return {
            "m_evaluation_configuration":
                self.m_evaluation_configuration.to_dict(),
            "split_policy": self.split_policy,
            "minimum_subperiod_evaluation_periods":
                self.minimum_subperiod_evaluation_periods,
            "variants": list(self.variants),
            "segments": list(self.segments),
            "first_half_dates": list(self.first_half_dates),
            "second_half_dates": list(self.second_half_dates),
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "synthetic_test_only": self.synthetic_test_only,
        }


@dataclass(frozen=True)
class RobustnessIssue:
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
class RobustnessCell:
    factor_id: str
    value_variant: str
    segment: str
    evaluation_dates: tuple[str, ...]
    status: str
    configured_date_count: int
    effective_date_count: int
    excluded_date_count: int
    factor_sample_count: int
    label_available_count: int
    paired_coverage_rate: float
    insufficient_cross_section_count: int
    constant_factor_count: int
    constant_return_count: int
    rank_ic_mean: float | None
    rank_ic_std: float | None
    rank_ic_ir: float | None
    rank_ic_t_stat: float | None
    rank_ic_positive_ratio: float | None
    pearson_ic_mean: float | None
    pearson_ic_std: float | None
    pearson_ic_ir: float | None
    pearson_ic_t_stat: float | None
    pearson_ic_positive_ratio: float | None
    quantile_returns: tuple[tuple[str, float], ...]
    long_short_mean: float | None
    monotonicity_spearman: float | None
    direction: str
    issue_codes: tuple[str, ...]
    input_fingerprint: str
    label_fingerprint: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "value_variant": self.value_variant,
            "segment": self.segment,
            "evaluation_dates": list(self.evaluation_dates),
            "status": self.status,
            "configured_date_count": self.configured_date_count,
            "effective_date_count": self.effective_date_count,
            "excluded_date_count": self.excluded_date_count,
            "factor_sample_count": self.factor_sample_count,
            "label_available_count": self.label_available_count,
            "paired_coverage_rate": self.paired_coverage_rate,
            "insufficient_cross_section_count":
                self.insufficient_cross_section_count,
            "constant_factor_count": self.constant_factor_count,
            "constant_return_count": self.constant_return_count,
            "rank_ic_mean": self.rank_ic_mean,
            "rank_ic_std": self.rank_ic_std,
            "rank_ic_ir": self.rank_ic_ir,
            "rank_ic_t_stat": self.rank_ic_t_stat,
            "rank_ic_positive_ratio": self.rank_ic_positive_ratio,
            "pearson_ic_mean": self.pearson_ic_mean,
            "pearson_ic_std": self.pearson_ic_std,
            "pearson_ic_ir": self.pearson_ic_ir,
            "pearson_ic_t_stat": self.pearson_ic_t_stat,
            "pearson_ic_positive_ratio": self.pearson_ic_positive_ratio,
            "quantile_returns": dict(self.quantile_returns),
            "long_short_mean": self.long_short_mean,
            "monotonicity_spearman": self.monotonicity_spearman,
            "direction": self.direction,
            "issue_codes": list(self.issue_codes),
            "input_fingerprint": self.input_fingerprint,
            "label_fingerprint": self.label_fingerprint,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialMVPFactorRobustness:
    factor_id: str
    cells: tuple[RobustnessCell, ...]
    preprocessing_consistency: str
    raw_subperiod_direction_consistency: str
    mad_subperiod_direction_consistency: str
    subperiod_direction_consistency: str
    coverage_consistent: bool
    constant_degradation_detected: bool
    raw_vs_mad_rank_ic_delta: float | None
    raw_vs_mad_pearson_ic_delta: float | None
    raw_vs_mad_long_short_delta: float | None
    raw_factor_sample_fingerprint: str
    mad_factor_sample_fingerprint: str
    label_fingerprint: str
    best_cell_selected: bool
    schema_version: str
    content_hash: str

    def get_cell(self, value_variant: Any, segment: Any) -> RobustnessCell:
        key = (
            _required_text(value_variant, "value_variant"),
            _required_text(segment, "segment"),
        )
        matches = [
            item for item in self.cells
            if (item.value_variant, item.segment) == key
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one robustness cell for {key}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "cells": [item.to_dict() for item in self.cells],
            "preprocessing_consistency": self.preprocessing_consistency,
            "raw_subperiod_direction_consistency":
                self.raw_subperiod_direction_consistency,
            "mad_subperiod_direction_consistency":
                self.mad_subperiod_direction_consistency,
            "subperiod_direction_consistency":
                self.subperiod_direction_consistency,
            "coverage_consistent": self.coverage_consistent,
            "constant_degradation_detected":
                self.constant_degradation_detected,
            "raw_vs_mad_rank_ic_delta":
                self.raw_vs_mad_rank_ic_delta,
            "raw_vs_mad_pearson_ic_delta":
                self.raw_vs_mad_pearson_ic_delta,
            "raw_vs_mad_long_short_delta":
                self.raw_vs_mad_long_short_delta,
            "raw_factor_sample_fingerprint":
                self.raw_factor_sample_fingerprint,
            "mad_factor_sample_fingerprint":
                self.mad_factor_sample_fingerprint,
            "label_fingerprint": self.label_fingerprint,
            "best_cell_selected": self.best_cell_selected,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialMVPRobustnessAudit:
    gate_status: str
    errors: tuple[RobustnessIssue, ...]
    supported_factor_ids: tuple[str, ...]
    configuration_fingerprint: str
    m_evaluation_output_fingerprint: str
    factor_input_fingerprint: str
    label_input_fingerprint: str
    output_fingerprint: str
    schema_version: str
    audit_schema_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_status": self.gate_status,
            "errors": [item.to_dict() for item in self.errors],
            "supported_factor_ids": list(self.supported_factor_ids),
            "configuration_fingerprint":
                self.configuration_fingerprint,
            "m_evaluation_output_fingerprint":
                self.m_evaluation_output_fingerprint,
            "factor_input_fingerprint": self.factor_input_fingerprint,
            "label_input_fingerprint": self.label_input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "schema_version": self.schema_version,
            "audit_schema_version": self.audit_schema_version,
            "hash_contract_version": self.hash_contract_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialMVPRobustnessResult:
    factor_summaries: tuple[FinancialMVPFactorRobustness, ...]
    robustness_audit: FinancialMVPRobustnessAudit

    def get_factor(
        self, factor_id: Any
    ) -> FinancialMVPFactorRobustness:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item for item in self.factor_summaries
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one factor summary for {normalized}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_summaries": [
                item.to_dict() for item in self.factor_summaries
            ],
            "robustness_audit": self.robustness_audit.to_dict(),
        }


@dataclass(frozen=True)
class _DailyVariantResult:
    date: str
    factor_sample_count: int
    label_available_count: int
    rank_ic: float | None
    pearson_ic: float | None
    evaluated: bool
    issue_codes: tuple[str, ...]


def evaluate_financial_mvp_robustness(
    mvp_batch_result: MVPFinancialBatchResult,
    preprocessing_result: FinancialPreprocessingResult,
    forward_returns: ForwardReturnBatch,
    m_evaluation_result: FinancialMVPMEvaluationResult,
    *,
    configuration: FinancialMVPRobustnessConfig,
) -> FinancialMVPRobustnessResult:
    """Build the complete frozen raw/MAD and fixed-half summary."""

    errors = _validate_top_level_inputs(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        m_evaluation_result,
        configuration,
    )
    if errors:
        return _blocked_result(tuple(errors), configuration)

    input_before = _input_guard(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        m_evaluation_result,
    )
    recomputed = evaluate_financial_mvp_m(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        configuration=configuration.m_evaluation_configuration,
    )
    expected_output = (
        m_evaluation_result.evaluation_audit.output_fingerprint
    )
    if (
        recomputed.evaluation_audit.gate_status
        != RobustnessGateStatus.READY.value
        or recomputed.evaluation_audit.output_fingerprint
        != expected_output
    ):
        errors.append(
            _error(
                RobustnessErrorCode.M_EVALUATION_OUTPUT_MISMATCH,
                "provided M evaluation must exactly match recomputation",
                "m_evaluation_result",
            )
        )
        return _blocked_result(
            tuple(errors),
            configuration,
            m_evaluation_output_fingerprint=expected_output,
        )

    factor_frame = _build_factor_frame(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        configuration,
        errors,
    )
    if errors:
        return _blocked_result(
            tuple(errors),
            configuration,
            m_evaluation_output_fingerprint=expected_output,
        )

    summaries = []
    for factor_id in SUPPORTED_FACTOR_IDS:
        factor_slice = factor_frame[
            factor_frame["factor_id"] == factor_id
        ].copy()
        cells = []
        for variant in ROBUSTNESS_VARIANTS:
            value_column = (
                "raw_factor_value"
                if variant == "raw_pit_factor_value"
                else "mad_factor_value"
            )
            daily = _evaluate_daily_variant(
                factor_slice,
                value_column=value_column,
                configuration=configuration,
            )
            for segment in ROBUSTNESS_SEGMENTS:
                cells.append(
                    _build_cell(
                        factor_id=factor_id,
                        value_variant=variant,
                        segment=segment,
                        frame=factor_slice,
                        value_column=value_column,
                        daily=daily,
                        configuration=configuration,
                    )
                )
        summary = _build_factor_summary(factor_id, tuple(cells))
        _validate_primary_mad_statistics(
            summary,
            m_evaluation_result,
            errors,
        )
        summaries.append(summary)

    input_after = _input_guard(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        m_evaluation_result,
    )
    if input_before != input_after:
        errors.append(
            _error(
                RobustnessErrorCode.INPUT_MUTATED,
                "one or more robustness inputs changed during evaluation",
                "inputs",
            )
        )
    if errors:
        return _blocked_result(
            tuple(_deduplicate_issues(errors)),
            configuration,
            m_evaluation_output_fingerprint=expected_output,
        )

    summary_tuple = tuple(summaries)
    factor_input_fingerprint = _hash(
        "factor_inputs",
        [
            {
                "factor_id": item.factor_id,
                "raw": item.raw_factor_sample_fingerprint,
                "mad": item.mad_factor_sample_fingerprint,
            }
            for item in summary_tuple
        ],
    )
    label_input_fingerprint = _hash(
        "label_inputs",
        [
            {
                "factor_id": item.factor_id,
                "label": item.label_fingerprint,
            }
            for item in summary_tuple
        ],
    )
    output_fingerprint = _hash(
        "robustness_output",
        [item.to_dict() for item in summary_tuple],
    )
    audit = _build_audit(
        RobustnessGateStatus.READY,
        (),
        configuration,
        expected_output,
        factor_input_fingerprint,
        label_input_fingerprint,
        output_fingerprint,
    )
    return FinancialMVPRobustnessResult(
        factor_summaries=summary_tuple,
        robustness_audit=audit,
    )


def _validate_top_level_inputs(
    mvp: Any,
    prep: Any,
    returns: Any,
    m_result: Any,
    configuration: Any,
) -> list[RobustnessIssue]:
    errors: list[RobustnessIssue] = []
    if not isinstance(configuration, FinancialMVPRobustnessConfig):
        errors.append(
            _error(
                RobustnessErrorCode.INVALID_CONFIGURATION,
                "configuration must be FinancialMVPRobustnessConfig",
                "configuration",
            )
        )
        return errors
    if not isinstance(mvp, MVPFinancialBatchResult):
        errors.append(
            _error(
                RobustnessErrorCode.INVALID_MVP_BATCH_RESULT,
                "mvp_batch_result must be MVPFinancialBatchResult",
                "mvp_batch_result",
            )
        )
    if not isinstance(prep, FinancialPreprocessingResult):
        errors.append(
            _error(
                RobustnessErrorCode.INVALID_PREPROCESSING_RESULT,
                "preprocessing_result must be FinancialPreprocessingResult",
                "preprocessing_result",
            )
        )
    if not isinstance(returns, ForwardReturnBatch):
        errors.append(
            _error(
                RobustnessErrorCode.INVALID_FORWARD_RETURN_BATCH,
                "forward_returns must be ForwardReturnBatch",
                "forward_returns",
            )
        )
    elif (
        returns.value_scope is not ValueScope.SECURITY_LEVEL
        or returns.provenance.get("synthetic_test_only") is not True
    ):
        errors.append(
            _error(
                RobustnessErrorCode.INVALID_FORWARD_RETURN_BATCH,
                "returns must be security-level approved synthetic input",
                "forward_returns",
            )
        )
    if not isinstance(m_result, FinancialMVPMEvaluationResult):
        errors.append(
            _error(
                RobustnessErrorCode.INVALID_M_EVALUATION_RESULT,
                "m_evaluation_result must be FinancialMVPMEvaluationResult",
                "m_evaluation_result",
            )
        )
    elif (
        m_result.evaluation_audit.gate_status
        != RobustnessGateStatus.READY.value
    ):
        errors.append(
            _error(
                RobustnessErrorCode.M_EVALUATION_GATE_BLOCKED,
                "FIN-MVP-M-EVAL gate must be ready",
                "evaluation_audit.gate_status",
            )
        )
    return errors


def _build_factor_frame(
    mvp: MVPFinancialBatchResult,
    prep: FinancialPreprocessingResult,
    returns: ForwardReturnBatch,
    configuration: FinancialMVPRobustnessConfig,
    errors: list[RobustnessIssue],
) -> pd.DataFrame:
    reference = mvp.observation_reference
    if reference is None:
        errors.append(
            _error(
                RobustnessErrorCode.FACTOR_INPUT_COVERAGE_MISMATCH,
                "MVP observation reference is required",
                "observation_reference",
            )
        )
        return pd.DataFrame()
    observations = {
        (item.evaluation_date, item.code, item.factor_id): item
        for item in reference.records
    }
    prepared = {
        item.preparation_key: item for item in prep.prepared_inputs
    }
    if (
        len(observations) != len(reference.records)
        or len(prepared) != len(prep.prepared_inputs)
        or set(observations) != set(prepared)
    ):
        errors.append(
            _error(
                RobustnessErrorCode.FACTOR_INPUT_COVERAGE_MISMATCH,
                "MVP and preprocessing keys must match exactly",
                "evaluation_date,code,factor_id",
            )
        )
        return pd.DataFrame()
    rows = []
    for key in sorted(observations):
        observation = observations[key]
        item = prepared[key]
        rows.append(
            {
                "date": observation.evaluation_date,
                "code": observation.code,
                "factor_id": observation.factor_id,
                "raw_factor_value": item.raw_pit_factor_value,
                "mad_factor_value": item.evaluation_factor_value,
                "observation_content_hash": observation.content_hash,
                "preprocessing_content_hash": item.content_hash,
            }
        )
    factor_frame = pd.DataFrame(rows)
    return_frame = returns.get_frame()
    return_frame = return_frame[
        return_frame["horizon"].astype(str)
        == str(
            configuration.m_evaluation_configuration.return_horizon
        )
    ].copy()
    return_frame["date"] = pd.to_datetime(
        return_frame["date"], errors="raise"
    ).dt.date.astype(str)
    return_frame = return_frame[
        return_frame["date"].isin(configuration.evaluation_dates)
    ][["date", "code", "forward_return"]]
    return_frame["code"] = return_frame["code"].astype(str)
    return_frame["forward_return"] = pd.to_numeric(
        return_frame["forward_return"], errors="coerce"
    )
    try:
        merged = factor_frame.merge(
            return_frame,
            on=["date", "code"],
            how="left",
            validate="many_to_one",
            sort=False,
        )
    except pd.errors.MergeError:
        errors.append(
            _error(
                RobustnessErrorCode.FACTOR_INPUT_COVERAGE_MISMATCH,
                "return labels must be unique by evaluation_date + code",
                "date,code",
            )
        )
        return pd.DataFrame()
    return merged.sort_values(
        ["factor_id", "date", "code"], kind="mergesort"
    ).reset_index(drop=True)


def _evaluate_daily_variant(
    frame: pd.DataFrame,
    *,
    value_column: str,
    configuration: FinancialMVPRobustnessConfig,
) -> tuple[_DailyVariantResult, ...]:
    daily = []
    for evaluation_date in configuration.evaluation_dates:
        date_slice = frame[frame["date"] == evaluation_date]
        factor_values = pd.to_numeric(
            date_slice[value_column], errors="coerce"
        )
        labels = pd.to_numeric(
            date_slice["forward_return"], errors="coerce"
        )
        finite_factor = factor_values.notna() & np.isfinite(factor_values)
        finite_label = labels.notna() & np.isfinite(labels)
        valid = finite_factor & finite_label
        values = factor_values.loc[valid]
        valid_labels = labels.loc[valid]
        issues = []
        rank_ic = pearson_ic = None
        evaluated = False
        if len(values) < M_EVAL_MIN_CROSS_SECTION:
            issues.append("INSUFFICIENT_CROSS_SECTION")
        elif int(values.nunique()) <= 1:
            issues.append("CONSTANT_FACTOR_CROSS_SECTION")
        elif int(valid_labels.nunique()) <= 1:
            issues.append("CONSTANT_RETURN_CROSS_SECTION")
        else:
            rank_stat = spearmanr(values, valid_labels)
            pearson_stat = pearsonr(values, valid_labels)
            if math.isfinite(float(rank_stat.correlation)):
                rank_ic = float(rank_stat.correlation)
            else:
                issues.append("NONFINITE_RANK_IC")
            if math.isfinite(float(pearson_stat.statistic)):
                pearson_ic = float(pearson_stat.statistic)
            else:
                issues.append("NONFINITE_PEARSON_IC")
            evaluated = rank_ic is not None or pearson_ic is not None
        daily.append(
            _DailyVariantResult(
                date=evaluation_date,
                factor_sample_count=int(finite_factor.sum()),
                label_available_count=int(valid.sum()),
                rank_ic=rank_ic,
                pearson_ic=pearson_ic,
                evaluated=evaluated,
                issue_codes=tuple(issues),
            )
        )
    return tuple(daily)


def _build_cell(
    *,
    factor_id: str,
    value_variant: str,
    segment: str,
    frame: pd.DataFrame,
    value_column: str,
    daily: tuple[_DailyVariantResult, ...],
    configuration: FinancialMVPRobustnessConfig,
) -> RobustnessCell:
    dates = _segment_dates(segment, configuration)
    selected_daily = tuple(item for item in daily if item.date in dates)
    effective = tuple(item for item in selected_daily if item.evaluated)
    required_periods = (
        M_EVAL_MIN_PERIODS
        if segment == "full"
        else configuration.minimum_subperiod_evaluation_periods
    )
    if len(effective) < required_periods:
        status = RobustnessCellStatus.NOT_RUN
    elif len(effective) == len(selected_daily):
        status = RobustnessCellStatus.COMPLETED
    else:
        status = RobustnessCellStatus.PARTIAL
    selected_frame = frame[frame["date"].isin(dates)].copy()
    factor_records = [
        {
            "date": str(row["date"]),
            "code": str(row["code"]),
            "factor_value": float(row[value_column]),
            "observation_content_hash": str(
                row["observation_content_hash"]
            ),
            "preprocessing_content_hash": str(
                row["preprocessing_content_hash"]
            ),
        }
        for row in selected_frame.to_dict(orient="records")
    ]
    label_records = [
        {
            "date": str(row["date"]),
            "code": str(row["code"]),
            "forward_return": (
                float(row["forward_return"])
                if pd.notna(row["forward_return"])
                and math.isfinite(float(row["forward_return"]))
                else None
            ),
        }
        for row in selected_frame.to_dict(orient="records")
    ]
    issue_codes = sorted(
        {
            code
            for item in selected_daily
            for code in item.issue_codes
        }
    )
    statistic_fields = _empty_statistics()
    if status is not RobustnessCellStatus.NOT_RUN:
        rank_values = [
            item.rank_ic
            for item in effective
            if item.rank_ic is not None
        ]
        pearson_values = [
            item.pearson_ic
            for item in effective
            if item.pearson_ic is not None
        ]
        statistic_fields.update(
            _ic_statistics(
                rank_values,
                pearson_values,
                configuration.m_evaluation_configuration.hac_max_lag,
            )
        )
        eligible_dates = {item.date for item in effective}
        group_frame = selected_frame[
            selected_frame["date"].isin(eligible_dates)
        ][["date", value_column, "forward_return"]].rename(
            columns={value_column: "factor_value"}
        )
        group = evaluate_group_returns(
            group_frame, quantiles=M_EVAL_QUANTILES
        )
        statistic_fields.update(
            {
                "quantile_returns": tuple(
                    sorted(group.quantile_returns.items())
                ),
                "long_short_mean": group.long_short_mean,
                "monotonicity_spearman":
                    group.monotonicity_spearman,
            }
        )
        issue_codes.extend(group.issue_codes)
    rank_mean = statistic_fields["rank_ic_mean"]
    direction = _direction(rank_mean)
    fields = {
        "factor_id": factor_id,
        "value_variant": value_variant,
        "segment": segment,
        "evaluation_dates": dates,
        "status": status.value,
        "configured_date_count": len(dates),
        "effective_date_count": len(effective),
        "excluded_date_count": len(dates) - len(effective),
        "factor_sample_count": sum(
            item.factor_sample_count for item in selected_daily
        ),
        "label_available_count": sum(
            item.label_available_count for item in selected_daily
        ),
        "paired_coverage_rate": (
            sum(item.label_available_count for item in selected_daily)
            / sum(item.factor_sample_count for item in selected_daily)
            if sum(
                item.factor_sample_count for item in selected_daily
            )
            else 0.0
        ),
        "insufficient_cross_section_count": sum(
            "INSUFFICIENT_CROSS_SECTION" in item.issue_codes
            for item in selected_daily
        ),
        "constant_factor_count": sum(
            "CONSTANT_FACTOR_CROSS_SECTION" in item.issue_codes
            for item in selected_daily
        ),
        "constant_return_count": sum(
            "CONSTANT_RETURN_CROSS_SECTION" in item.issue_codes
            for item in selected_daily
        ),
        **statistic_fields,
        "direction": direction.value,
        "issue_codes": tuple(sorted(set(issue_codes))),
        "input_fingerprint": _hash(
            f"{value_variant}:{segment}:factor", factor_records
        ),
        "label_fingerprint": _hash(
            f"{segment}:labels", label_records
        ),
        "schema_version": ROBUSTNESS_CELL_SCHEMA_VERSION,
    }
    return RobustnessCell(
        **fields,
        content_hash=_hash("robustness_cell", fields),
    )


def _build_factor_summary(
    factor_id: str,
    cells: tuple[RobustnessCell, ...],
) -> FinancialMVPFactorRobustness:
    by_key = {
        (item.value_variant, item.segment): item for item in cells
    }
    raw_full = by_key[("raw_pit_factor_value", "full")]
    mad_full = by_key[("evaluation_factor_value", "full")]
    raw_subperiod = _direction_consistency(
        by_key[("raw_pit_factor_value", "first_half")],
        by_key[("raw_pit_factor_value", "second_half")],
    )
    mad_subperiod = _direction_consistency(
        by_key[("evaluation_factor_value", "first_half")],
        by_key[("evaluation_factor_value", "second_half")],
    )
    preprocessing = _direction_consistency(raw_full, mad_full)
    subperiod = _combine_consistency(raw_subperiod, mad_subperiod)
    fields = {
        "factor_id": factor_id,
        "cells": cells,
        "preprocessing_consistency": preprocessing.value,
        "raw_subperiod_direction_consistency": raw_subperiod.value,
        "mad_subperiod_direction_consistency": mad_subperiod.value,
        "subperiod_direction_consistency": subperiod.value,
        "coverage_consistent": (
            math.isclose(
                raw_full.paired_coverage_rate,
                mad_full.paired_coverage_rate,
                rel_tol=0.0,
                abs_tol=0.0,
            )
            and raw_full.label_available_count
            == mad_full.label_available_count
        ),
        "constant_degradation_detected": any(
            item.constant_factor_count > 0
            or item.constant_return_count > 0
            for item in cells
        ),
        "raw_vs_mad_rank_ic_delta": _difference(
            mad_full.rank_ic_mean, raw_full.rank_ic_mean
        ),
        "raw_vs_mad_pearson_ic_delta": _difference(
            mad_full.pearson_ic_mean, raw_full.pearson_ic_mean
        ),
        "raw_vs_mad_long_short_delta": _difference(
            mad_full.long_short_mean, raw_full.long_short_mean
        ),
        "raw_factor_sample_fingerprint":
            raw_full.input_fingerprint,
        "mad_factor_sample_fingerprint":
            mad_full.input_fingerprint,
        "label_fingerprint": raw_full.label_fingerprint,
        "best_cell_selected": False,
        "schema_version": ROBUSTNESS_FACTOR_SCHEMA_VERSION,
    }
    return FinancialMVPFactorRobustness(
        **fields,
        content_hash=_hash("factor_robustness", fields),
    )


def _validate_primary_mad_statistics(
    summary: FinancialMVPFactorRobustness,
    primary: FinancialMVPMEvaluationResult,
    errors: list[RobustnessIssue],
) -> None:
    cell = summary.get_cell("evaluation_factor_value", "full")
    common = primary.get_result(summary.factor_id)
    comparisons = {
        "rank_ic_mean": (cell.rank_ic_mean, common.rank_ic_mean),
        "rank_ic_std": (cell.rank_ic_std, common.rank_ic_std),
        "rank_ic_ir": (cell.rank_ic_ir, common.rank_ic_ir),
        "rank_ic_t_stat": (
            cell.rank_ic_t_stat,
            common.rank_ic_t_stat,
        ),
        "rank_ic_positive_ratio": (
            cell.rank_ic_positive_ratio,
            common.rank_ic_positive_ratio,
        ),
        "pearson_ic_mean": (
            cell.pearson_ic_mean,
            common.pearson_ic_mean,
        ),
        "pearson_ic_std": (
            cell.pearson_ic_std,
            common.pearson_ic_std,
        ),
        "pearson_ic_ir": (
            cell.pearson_ic_ir,
            common.pearson_ic_ir,
        ),
        "pearson_ic_t_stat": (
            cell.pearson_ic_t_stat,
            common.pearson_ic_t_stat,
        ),
        "pearson_ic_positive_ratio": (
            cell.pearson_ic_positive_ratio,
            common.pearson_ic_positive_ratio,
        ),
        "long_short_mean": (
            cell.long_short_mean,
            common.long_short_mean,
        ),
        "monotonicity_spearman": (
            cell.monotonicity_spearman,
            common.monotonicity_spearman,
        ),
    }
    for field_name, (actual, expected) in comparisons.items():
        if not _same_optional_number(actual, expected):
            errors.append(
                _error(
                    RobustnessErrorCode.MAD_PRIMARY_STATISTIC_MISMATCH,
                    "MAD full-sample statistic must match M evaluation",
                    field_name,
                    summary.factor_id,
                )
            )
    structural_matches = (
        cell.effective_date_count == common.evaluated_dates
        and cell.excluded_date_count == common.excluded_dates
        and cell.label_available_count == common.total_observations
        and dict(cell.quantile_returns) == common.quantile_returns
    )
    if not structural_matches:
        errors.append(
            _error(
                RobustnessErrorCode.MAD_PRIMARY_STATISTIC_MISMATCH,
                "MAD full-sample structure must match M evaluation",
                "dates,observations,quantile_returns",
                summary.factor_id,
            )
        )


def _ic_statistics(
    rank_values: list[float],
    pearson_values: list[float],
    hac_max_lag: int,
) -> dict[str, Any]:
    return {
        **_one_ic_statistics("rank_ic", rank_values, hac_max_lag),
        **_one_ic_statistics(
            "pearson_ic", pearson_values, hac_max_lag
        ),
    }


def _one_ic_statistics(
    prefix: str,
    values: list[float],
    hac_max_lag: int,
) -> dict[str, float | None]:
    mean = float(np.mean(values)) if values else None
    standard_deviation = (
        float(np.std(values, ddof=1)) if len(values) > 1 else None
    )
    ratio = (
        mean / standard_deviation
        if mean is not None
        and standard_deviation is not None
        and not math.isclose(
            standard_deviation,
            0.0,
            rel_tol=0.0,
            abs_tol=_ZERO_TOLERANCE,
        )
        else None
    )
    return {
        f"{prefix}_mean": mean,
        f"{prefix}_std": standard_deviation,
        f"{prefix}_ir": ratio,
        f"{prefix}_t_stat": (
            hac_t_stat(values, max_lag=hac_max_lag)
            if values
            else None
        ),
        f"{prefix}_positive_ratio": (
            float(np.mean([value > 0 for value in values]))
            if values
            else None
        ),
    }


def _empty_statistics() -> dict[str, Any]:
    return {
        "rank_ic_mean": None,
        "rank_ic_std": None,
        "rank_ic_ir": None,
        "rank_ic_t_stat": None,
        "rank_ic_positive_ratio": None,
        "pearson_ic_mean": None,
        "pearson_ic_std": None,
        "pearson_ic_ir": None,
        "pearson_ic_t_stat": None,
        "pearson_ic_positive_ratio": None,
        "quantile_returns": (),
        "long_short_mean": None,
        "monotonicity_spearman": None,
    }


def _segment_dates(
    segment: str, configuration: FinancialMVPRobustnessConfig
) -> tuple[str, ...]:
    if segment == "full":
        return configuration.evaluation_dates
    if segment == "first_half":
        return configuration.first_half_dates
    if segment == "second_half":
        return configuration.second_half_dates
    raise ValueError(f"unsupported segment: {segment}")


def _direction(value: float | None) -> RobustnessDirection:
    if value is None:
        return RobustnessDirection.NOT_EVALUABLE
    if math.isclose(
        value, 0.0, rel_tol=0.0, abs_tol=_ZERO_TOLERANCE
    ):
        return RobustnessDirection.ZERO
    return (
        RobustnessDirection.POSITIVE
        if value > 0
        else RobustnessDirection.NEGATIVE
    )


def _direction_consistency(
    left: RobustnessCell,
    right: RobustnessCell,
) -> RobustnessConsistency:
    not_evaluable = RobustnessDirection.NOT_EVALUABLE.value
    if left.direction == not_evaluable or right.direction == not_evaluable:
        return RobustnessConsistency.INSUFFICIENT
    return (
        RobustnessConsistency.CONSISTENT
        if left.direction == right.direction
        else RobustnessConsistency.MIXED
    )


def _combine_consistency(
    left: RobustnessConsistency,
    right: RobustnessConsistency,
) -> RobustnessConsistency:
    if RobustnessConsistency.INSUFFICIENT in (left, right):
        return RobustnessConsistency.INSUFFICIENT
    if left is RobustnessConsistency.CONSISTENT and right is left:
        return RobustnessConsistency.CONSISTENT
    return RobustnessConsistency.MIXED


def _difference(
    left: float | None, right: float | None
) -> float | None:
    if left is None or right is None:
        return None
    return float(left - right)


def _same_optional_number(
    left: float | None, right: float | None
) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(
        left, right, rel_tol=1e-12, abs_tol=1e-12
    )


def _input_guard(
    mvp: MVPFinancialBatchResult,
    prep: FinancialPreprocessingResult,
    returns: ForwardReturnBatch,
    m_result: FinancialMVPMEvaluationResult,
) -> str:
    reference = mvp.observation_reference
    return _hash(
        "robustness_input_guard",
        {
            "mvp": {
                **mvp.to_dict(include_rows=True),
                "observation_reference": (
                    reference.to_dict(include_records=True)
                    if reference is not None
                    else None
                ),
            },
            "preprocessing": {
                "prepared_inputs": [
                    item.to_dict() for item in prep.prepared_inputs
                ],
                "mad_audits": [
                    item.to_dict() for item in prep.mad_audits
                ],
                "audit": prep.preprocessing_audit.to_dict(),
            },
            "returns": _frame_records(returns.get_frame()),
            "m_evaluation_result": m_result.to_dict(),
        },
    )


def _blocked_result(
    errors: tuple[RobustnessIssue, ...],
    configuration: FinancialMVPRobustnessConfig | None,
    *,
    m_evaluation_output_fingerprint: str | None = None,
) -> FinancialMVPRobustnessResult:
    empty = _hash("empty", [])
    audit = _build_audit(
        RobustnessGateStatus.BLOCKED,
        tuple(_deduplicate_issues(errors)),
        configuration,
        m_evaluation_output_fingerprint or empty,
        empty,
        empty,
        empty,
    )
    return FinancialMVPRobustnessResult(
        factor_summaries=(),
        robustness_audit=audit,
    )


def _build_audit(
    gate_status: RobustnessGateStatus,
    errors: tuple[RobustnessIssue, ...],
    configuration: FinancialMVPRobustnessConfig | None,
    m_evaluation_output_fingerprint: str,
    factor_input_fingerprint: str,
    label_input_fingerprint: str,
    output_fingerprint: str,
) -> FinancialMVPRobustnessAudit:
    fields = {
        "gate_status": gate_status.value,
        "errors": errors,
        "supported_factor_ids": SUPPORTED_FACTOR_IDS,
        "configuration_fingerprint": _hash(
            "robustness_configuration",
            (
                configuration.to_dict()
                if configuration is not None
                else {"configuration": "invalid"}
            ),
        ),
        "m_evaluation_output_fingerprint":
            m_evaluation_output_fingerprint,
        "factor_input_fingerprint": factor_input_fingerprint,
        "label_input_fingerprint": label_input_fingerprint,
        "output_fingerprint": output_fingerprint,
        "schema_version": ROBUSTNESS_SCHEMA_VERSION,
        "audit_schema_version": ROBUSTNESS_AUDIT_SCHEMA_VERSION,
        "hash_contract_version": ROBUSTNESS_HASH_CONTRACT_VERSION,
    }
    return FinancialMVPRobustnessAudit(
        **fields,
        content_hash=_hash("robustness_audit", fields),
    )


def _error(
    code: RobustnessErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> RobustnessIssue:
    return RobustnessIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
    )


def _deduplicate_issues(
    issues: list[RobustnessIssue] | tuple[RobustnessIssue, ...],
) -> list[RobustnessIssue]:
    unique = {
        (
            item.code,
            item.message,
            item.field_name,
            item.record_key,
        ): item
        for item in issues
    }
    return [
        unique[key]
        for key in sorted(
            unique,
            key=lambda value: tuple(
                "" if item is None else item for item in value
            ),
        )
    ]


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} is required")
    return value.strip()


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            str(key): _canonical(value)
            for key, value in sorted(row.items())
        }
        for row in frame.to_dict(orient="records")
    ]


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _canonical(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _canonical(item)
            for key, item in value.__dict__.items()
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(
                value.items(), key=lambda pair: str(pair[0])
            )
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_canonical(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError("non-finite value cannot enter official hash")
        value = round(value, HASH_FLOAT_DECIMAL_PLACES)
        if value == 0:
            return 0.0
    return value


def _hash(domain: str, value: Any) -> str:
    payload = {
        "domain": domain,
        "hash_contract_version": ROBUSTNESS_HASH_CONTRACT_VERSION,
        "value": _canonical(value),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
