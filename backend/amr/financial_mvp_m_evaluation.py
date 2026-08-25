"""FIN-MVP-M-EVAL: minimal month-end Track-M evaluation.

The module keeps the public price/volume wrapper untouched.  It reuses the
public result schema and shared group-return/HAC utilities while applying the
frozen financial-specific sample, calendar, and configuration rules.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from backend.amr.evaluation_core import (
    DailyICResult,
    EvaluationStatus,
    SecurityLevelEvaluationResult,
)
from backend.amr.evaluation_group_returns import (
    DailyGroupReturnResult,
    evaluate_group_returns,
)
from backend.amr.evaluation_input_contract import (
    FinancialBatch,
    ForwardReturnBatch,
    ValueScope,
)
from backend.amr.evaluation_statistics import hac_t_stat
from backend.amr.financial_mvp_batch import (
    SUPPORTED_FACTOR_IDS,
    MVPFinancialBatchResult,
    recompute_observation_content_hash,
)
from backend.amr.financial_preprocessing import (
    FinancialPreprocessingResult,
)

M_EVAL_SCHEMA_VERSION = "FinancialMVPMEvaluation-v1.0"
M_EVAL_AUDIT_SCHEMA_VERSION = "FinancialMVPMEvaluationAudit-v1.0"
M_EVAL_FACTOR_AUDIT_SCHEMA_VERSION = "FinancialMVPMFactorAudit-v1.0"
M_EVAL_HASH_CONTRACT_VERSION = "FIN-MVP-M-EVAL-HASH-v2.0"
HASH_FLOAT_DECIMAL_PLACES = 8
M_EVAL_POLICY_VERSION = "FIN-MVP-M-EVAL-POLICY-v1.0"
M_EVAL_TRACK = "M"
M_EVAL_FREQUENCY = "month_end"
M_EVAL_HORIZON = 20
M_EVAL_MIN_CROSS_SECTION = 30
M_EVAL_MIN_PERIODS = 12
M_EVAL_QUANTILES = 5
M_EVAL_VALUE_VARIANT = "evaluation_factor_value"


class MEvaluationGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class MEvaluationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class MEvaluationErrorCode(str, Enum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_MVP_BATCH_RESULT = "INVALID_MVP_BATCH_RESULT"
    MVP_BATCH_GATE_BLOCKED = "MVP_BATCH_GATE_BLOCKED"
    OBSERVATION_REFERENCE_MISSING = "OBSERVATION_REFERENCE_MISSING"
    OBSERVATION_HASH_MISMATCH = "OBSERVATION_HASH_MISMATCH"
    FACTOR_BATCH_COVERAGE_INVALID = "FACTOR_BATCH_COVERAGE_INVALID"
    PUBLIC_BATCH_RAW_VALUE_MISMATCH = "PUBLIC_BATCH_RAW_VALUE_MISMATCH"
    INVALID_PREPROCESSING_RESULT = "INVALID_PREPROCESSING_RESULT"
    PREPROCESSING_GATE_BLOCKED = "PREPROCESSING_GATE_BLOCKED"
    PREPROCESSING_COVERAGE_MISMATCH = "PREPROCESSING_COVERAGE_MISMATCH"
    PREPROCESSING_RAW_VALUE_MISMATCH = "PREPROCESSING_RAW_VALUE_MISMATCH"
    NONFINITE_EVALUATION_VALUE = "NONFINITE_EVALUATION_VALUE"
    EVALUATION_DATE_COVERAGE_MISMATCH = "EVALUATION_DATE_COVERAGE_MISMATCH"
    INVALID_FORWARD_RETURN_BATCH = "INVALID_FORWARD_RETURN_BATCH"
    NON_SYNTHETIC_RETURN_INPUT = "NON_SYNTHETIC_RETURN_INPUT"
    RETURN_HORIZON_MISSING = "RETURN_HORIZON_MISSING"
    INPUT_MUTATED = "INPUT_MUTATED"


@dataclass(frozen=True)
class FinancialMVPMEvaluationConfig:
    evaluation_dates: tuple[str, ...]
    evaluation_calendar_reference: str
    evaluation_calendar_version: str
    hac_max_lag: int
    evaluation_frequency: str = M_EVAL_FREQUENCY
    return_horizon: int = M_EVAL_HORIZON
    minimum_cross_section_size: int = M_EVAL_MIN_CROSS_SECTION
    minimum_evaluation_periods: int = M_EVAL_MIN_PERIODS
    quantiles: int = M_EVAL_QUANTILES
    primary_value_variant: str = M_EVAL_VALUE_VARIANT
    schema_version: str = M_EVAL_SCHEMA_VERSION
    policy_version: str = M_EVAL_POLICY_VERSION
    synthetic_test_only: bool = True

    def __post_init__(self) -> None:
        try:
            supplied_dates = tuple(self.evaluation_dates)
            normalized_dates = tuple(
                sorted(
                    {
                        _date_iso(value, "evaluation_date")
                        for value in supplied_dates
                    }
                )
            )
        except TypeError as exc:
            raise ValueError(
                "evaluation_dates must be an iterable of YYYY-MM-DD values"
            ) from exc
        if len(normalized_dates) != len(supplied_dates):
            raise ValueError("evaluation_dates must be unique")
        if len(normalized_dates) < M_EVAL_MIN_PERIODS:
            raise ValueError(
                f"evaluation_dates must contain at least {M_EVAL_MIN_PERIODS} dates"
            )
        months = {value[:7] for value in normalized_dates}
        if len(months) != len(normalized_dates):
            raise ValueError(
                "month-end configuration permits only one date per calendar month"
            )
        object.__setattr__(self, "evaluation_dates", normalized_dates)
        _required_text(
            self.evaluation_calendar_reference,
            "evaluation_calendar_reference",
        )
        _required_text(
            self.evaluation_calendar_version,
            "evaluation_calendar_version",
        )
        if (
            isinstance(self.hac_max_lag, bool)
            or not isinstance(self.hac_max_lag, (int, np.integer))
            or self.hac_max_lag < 0
            or self.hac_max_lag >= M_EVAL_MIN_PERIODS
        ):
            raise ValueError(
                "hac_max_lag must be an explicit integer in [0, 11]"
            )
        frozen = {
            "evaluation_frequency": (
                self.evaluation_frequency,
                M_EVAL_FREQUENCY,
            ),
            "return_horizon": (self.return_horizon, M_EVAL_HORIZON),
            "minimum_cross_section_size": (
                self.minimum_cross_section_size,
                M_EVAL_MIN_CROSS_SECTION,
            ),
            "minimum_evaluation_periods": (
                self.minimum_evaluation_periods,
                M_EVAL_MIN_PERIODS,
            ),
            "quantiles": (self.quantiles, M_EVAL_QUANTILES),
            "primary_value_variant": (
                self.primary_value_variant,
                M_EVAL_VALUE_VARIANT,
            ),
            "schema_version": (
                self.schema_version,
                M_EVAL_SCHEMA_VERSION,
            ),
            "policy_version": (
                self.policy_version,
                M_EVAL_POLICY_VERSION,
            ),
        }
        for field_name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{field_name} must be frozen at {expected}")
        if self.synthetic_test_only is not True:
            raise ValueError(
                "FIN-MVP-M-EVAL is authorized for synthetic input only"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_dates": list(self.evaluation_dates),
            "evaluation_calendar_reference":
                self.evaluation_calendar_reference,
            "evaluation_calendar_version":
                self.evaluation_calendar_version,
            "hac_max_lag": int(self.hac_max_lag),
            "evaluation_frequency": self.evaluation_frequency,
            "return_horizon": self.return_horizon,
            "minimum_cross_section_size":
                self.minimum_cross_section_size,
            "minimum_evaluation_periods":
                self.minimum_evaluation_periods,
            "quantiles": self.quantiles,
            "primary_value_variant": self.primary_value_variant,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "synthetic_test_only": self.synthetic_test_only,
        }


@dataclass(frozen=True)
class MEvaluationIssue:
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
class FinancialMVPMFactorAudit:
    factor_id: str
    configured_date_count: int
    factor_sample_count: int
    label_available_count: int
    valid_pair_count: int
    evaluated_date_count: int
    excluded_date_count: int
    factor_sample_fingerprint: str
    label_alignment_fingerprint: str
    common_result_fingerprint: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "configured_date_count": self.configured_date_count,
            "factor_sample_count": self.factor_sample_count,
            "label_available_count": self.label_available_count,
            "valid_pair_count": self.valid_pair_count,
            "evaluated_date_count": self.evaluated_date_count,
            "excluded_date_count": self.excluded_date_count,
            "factor_sample_fingerprint": self.factor_sample_fingerprint,
            "label_alignment_fingerprint": self.label_alignment_fingerprint,
            "common_result_fingerprint": self.common_result_fingerprint,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialMVPMEvaluationAudit:
    gate_status: str
    errors: tuple[MEvaluationIssue, ...]
    warnings: tuple[MEvaluationIssue, ...]
    supported_factor_ids: tuple[str, ...]
    configuration_fingerprint: str
    mvp_batch_fingerprint: str
    preprocessing_fingerprint: str
    return_input_fingerprint: str
    factor_sample_fingerprint: str
    output_fingerprint: str
    schema_version: str
    audit_schema_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_status": self.gate_status,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
            "supported_factor_ids": list(self.supported_factor_ids),
            "configuration_fingerprint": self.configuration_fingerprint,
            "mvp_batch_fingerprint": self.mvp_batch_fingerprint,
            "preprocessing_fingerprint": self.preprocessing_fingerprint,
            "return_input_fingerprint": self.return_input_fingerprint,
            "factor_sample_fingerprint": self.factor_sample_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "schema_version": self.schema_version,
            "audit_schema_version": self.audit_schema_version,
            "hash_contract_version": self.hash_contract_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialMVPMEvaluationResult:
    common_results: tuple[SecurityLevelEvaluationResult, ...]
    factor_audits: tuple[FinancialMVPMFactorAudit, ...]
    evaluation_audit: FinancialMVPMEvaluationAudit

    def get_result(self, factor_id: Any) -> SecurityLevelEvaluationResult:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item for item in self.common_results
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one common result for {normalized}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def get_factor_audit(
        self, factor_id: Any
    ) -> FinancialMVPMFactorAudit:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item for item in self.factor_audits
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one factor audit for {normalized}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "common_results": [
                item.to_dict() for item in self.common_results
            ],
            "factor_audits": [
                item.to_dict() for item in self.factor_audits
            ],
            "evaluation_audit": self.evaluation_audit.to_dict(),
        }


def evaluate_financial_mvp_m(
    mvp_batch_result: MVPFinancialBatchResult,
    preprocessing_result: FinancialPreprocessingResult,
    forward_returns: ForwardReturnBatch,
    *,
    configuration: FinancialMVPMEvaluationConfig,
) -> FinancialMVPMEvaluationResult:
    """Evaluate the three approved factors against month-end 20D returns."""

    if not isinstance(configuration, FinancialMVPMEvaluationConfig):
        return _blocked_result(
            (
                _error(
                    MEvaluationErrorCode.INVALID_CONFIGURATION,
                    "configuration must be FinancialMVPMEvaluationConfig",
                    "configuration",
                ),
            )
        )
    errors: list[MEvaluationIssue] = []
    warnings: list[MEvaluationIssue] = []

    if not isinstance(mvp_batch_result, MVPFinancialBatchResult):
        errors.append(
            _error(
                MEvaluationErrorCode.INVALID_MVP_BATCH_RESULT,
                "mvp_batch_result must be MVPFinancialBatchResult",
                "mvp_batch_result",
            )
        )
    elif (
        mvp_batch_result.financial_batch_audit.gate_status
        != MEvaluationGateStatus.READY.value
    ):
        errors.append(
            _error(
                MEvaluationErrorCode.MVP_BATCH_GATE_BLOCKED,
                "FIN-MVP-DATA gate must be ready",
                "financial_batch_audit.gate_status",
            )
        )
    elif mvp_batch_result.observation_reference is None:
        errors.append(
            _error(
                MEvaluationErrorCode.OBSERVATION_REFERENCE_MISSING,
                "MVP observation reference is required",
                "observation_reference",
            )
        )

    if not isinstance(
        preprocessing_result, FinancialPreprocessingResult
    ):
        errors.append(
            _error(
                MEvaluationErrorCode.INVALID_PREPROCESSING_RESULT,
                "preprocessing_result must be FinancialPreprocessingResult",
                "preprocessing_result",
            )
        )
    elif (
        preprocessing_result.preprocessing_audit.gate_status
        != MEvaluationGateStatus.READY.value
    ):
        errors.append(
            _error(
                MEvaluationErrorCode.PREPROCESSING_GATE_BLOCKED,
                "FIN-R2-PREP gate must be ready",
                "preprocessing_audit.gate_status",
            )
        )

    if not isinstance(forward_returns, ForwardReturnBatch):
        errors.append(
            _error(
                MEvaluationErrorCode.INVALID_FORWARD_RETURN_BATCH,
                "forward_returns must be ForwardReturnBatch",
                "forward_returns",
            )
        )
    elif forward_returns.value_scope is not ValueScope.SECURITY_LEVEL:
        errors.append(
            _error(
                MEvaluationErrorCode.INVALID_FORWARD_RETURN_BATCH,
                "Track M requires security-level forward returns",
                "value_scope",
            )
        )
    elif forward_returns.provenance.get("synthetic_test_only") is not True:
        errors.append(
            _error(
                MEvaluationErrorCode.NON_SYNTHETIC_RETURN_INPUT,
                "forward return provenance must set synthetic_test_only=true",
                "provenance.synthetic_test_only",
            )
        )
    if errors:
        return _blocked_result(
            tuple(_deduplicate_issues(errors)),
            configuration=configuration,
        )

    mvp_before = _versioned_hash(
        "mvp_input_guard", _mvp_guard_payload(mvp_batch_result)
    )
    prep_before = _versioned_hash(
        "preprocessing_input_guard",
        {
            "prepared_inputs": [
                item.to_dict()
                for item in preprocessing_result.prepared_inputs
            ],
            "mad_audits": [
                item.to_dict()
                for item in preprocessing_result.mad_audits
            ],
            "audit":
                preprocessing_result.preprocessing_audit.to_dict(),
        },
    )
    return_frame = forward_returns.get_frame()
    return_before = _versioned_hash(
        "return_input_guard", _frame_records(return_frame)
    )

    observation_reference = mvp_batch_result.observation_reference
    assert observation_reference is not None
    observations = tuple(observation_reference.records)
    for item in observations:
        try:
            recomputed = recompute_observation_content_hash(item)
        except (TypeError, ValueError) as exc:
            recomputed = ""
            errors.append(
                _error(
                    MEvaluationErrorCode.OBSERVATION_HASH_MISMATCH,
                    str(exc),
                    "content_hash",
                    item.observation_id,
                )
            )
        if recomputed != item.content_hash:
            errors.append(
                _error(
                    MEvaluationErrorCode.OBSERVATION_HASH_MISMATCH,
                    "MVP observation content hash mismatch",
                    "content_hash",
                    item.observation_id,
                )
            )
    observed_factor_ids = {item.factor_id for item in observations}
    batch_factor_ids = {
        item.factor_id
        for item in mvp_batch_result.batches
        if isinstance(item, FinancialBatch)
    }
    if (
        observed_factor_ids != set(SUPPORTED_FACTOR_IDS)
        or batch_factor_ids != set(SUPPORTED_FACTOR_IDS)
        or len(mvp_batch_result.batches) != len(SUPPORTED_FACTOR_IDS)
    ):
        errors.append(
            _error(
                MEvaluationErrorCode.FACTOR_BATCH_COVERAGE_INVALID,
                "M evaluation requires exactly ROE, BP, and OCF_NP",
                "factor_id",
            )
        )

    configured_dates = set(configuration.evaluation_dates)
    observation_dates = {item.evaluation_date for item in observations}
    if observation_dates != configured_dates:
        errors.append(
            _error(
                MEvaluationErrorCode.EVALUATION_DATE_COVERAGE_MISMATCH,
                "MVP observation dates must exactly match configured "
                "month-end evaluation dates",
                "evaluation_date",
            )
        )

    batch_lookup = _public_batch_lookup(
        mvp_batch_result.batches, errors
    )
    observation_by_key: dict[tuple[str, str, str], Any] = {}
    for item in observations:
        key = (item.evaluation_date, item.code, item.factor_id)
        if item.factor_sample_mask is not True:
            errors.append(
                _error(
                    MEvaluationErrorCode.FACTOR_BATCH_COVERAGE_INVALID,
                    "M evaluation requires factor_sample_mask=true",
                    "factor_sample_mask",
                    "|".join(key),
                )
            )
        if key in observation_by_key:
            errors.append(
                _error(
                    MEvaluationErrorCode.FACTOR_BATCH_COVERAGE_INVALID,
                    "duplicate MVP integration key",
                    "evaluation_date,code,factor_id",
                    "|".join(key),
                )
            )
            continue
        observation_by_key[key] = item
        batch_key = (
            item.factor_id,
            item.code,
            item.report_period,
            item.effective_date,
        )
        public_value = batch_lookup.get(batch_key)
        if public_value is None or public_value != item.factor_value:
            errors.append(
                _error(
                    MEvaluationErrorCode.PUBLIC_BATCH_RAW_VALUE_MISMATCH,
                    "MVP observation raw value differs from public "
                    "FinancialBatch",
                    "factor_value",
                    "|".join(key),
                )
            )

    prep_by_key = {
        item.preparation_key: item
        for item in preprocessing_result.prepared_inputs
    }
    if (
        len(prep_by_key)
        != len(preprocessing_result.prepared_inputs)
        or set(prep_by_key) != set(observation_by_key)
    ):
        errors.append(
            _error(
                MEvaluationErrorCode.PREPROCESSING_COVERAGE_MISMATCH,
                "FIN-R2-PREP keys must exactly match MVP observation keys",
                "evaluation_date,code,factor_id",
            )
        )
    factor_rows: list[dict[str, Any]] = []
    for key in sorted(observation_by_key):
        observation = observation_by_key[key]
        prepared = prep_by_key.get(key)
        if prepared is None:
            continue
        if prepared.raw_pit_factor_value != observation.factor_value:
            errors.append(
                _error(
                    MEvaluationErrorCode.PREPROCESSING_RAW_VALUE_MISMATCH,
                    "preprocessing raw value differs from MVP raw value",
                    "raw_pit_factor_value",
                    "|".join(key),
                )
            )
        if not math.isfinite(prepared.evaluation_factor_value):
            errors.append(
                _error(
                    MEvaluationErrorCode.NONFINITE_EVALUATION_VALUE,
                    "evaluation_factor_value must be finite",
                    "evaluation_factor_value",
                    "|".join(key),
                )
            )
        factor_rows.append(
            {
                "date": observation.evaluation_date,
                "code": observation.code,
                "factor_id": observation.factor_id,
                "factor_value": prepared.evaluation_factor_value,
                "raw_pit_factor_value": observation.factor_value,
                "observation_id": observation.observation_id,
                "observation_content_hash": observation.content_hash,
                "sample_content_hash": observation.sample_content_hash,
                "preprocessing_content_hash": prepared.content_hash,
            }
        )

    selected_returns = _select_returns(
        return_frame,
        configuration=configuration,
        errors=errors,
    )
    mvp_after = _versioned_hash(
        "mvp_input_guard", _mvp_guard_payload(mvp_batch_result)
    )
    prep_after = _versioned_hash(
        "preprocessing_input_guard",
        {
            "prepared_inputs": [
                item.to_dict()
                for item in preprocessing_result.prepared_inputs
            ],
            "mad_audits": [
                item.to_dict()
                for item in preprocessing_result.mad_audits
            ],
            "audit":
                preprocessing_result.preprocessing_audit.to_dict(),
        },
    )
    return_after = _versioned_hash(
        "return_input_guard",
        _frame_records(forward_returns.get_frame()),
    )
    if (
        mvp_before != mvp_after
        or prep_before != prep_after
        or return_before != return_after
    ):
        errors.append(
            _error(
                MEvaluationErrorCode.INPUT_MUTATED,
                "one or more evaluation inputs changed during evaluation",
                "inputs",
            )
        )
    if errors:
        return _blocked_result(
            tuple(_deduplicate_issues(errors)),
            configuration=configuration,
            mvp_fingerprint=mvp_before,
            preprocessing_fingerprint=prep_before,
            return_fingerprint=return_before,
        )

    factor_frame = pd.DataFrame(factor_rows).sort_values(
        ["factor_id", "date", "code"], kind="mergesort"
    )
    common_results: list[SecurityLevelEvaluationResult] = []
    factor_audits: list[FinancialMVPMFactorAudit] = []
    for factor_id in SUPPORTED_FACTOR_IDS:
        factor_slice = factor_frame[
            factor_frame["factor_id"] == factor_id
        ].copy()
        merged = factor_slice.merge(
            selected_returns,
            on=["date", "code"],
            how="left",
            validate="one_to_one",
            sort=False,
        ).sort_values(["date", "code"], kind="mergesort")
        common_result = _evaluate_one_factor(
            factor_id=factor_id,
            factor_frame=merged,
            return_set_id=forward_returns.return_set_id,
            configuration=configuration,
        )
        common_results.append(common_result)
        factor_audits.append(
            _build_factor_audit(
                factor_id=factor_id,
                frame=merged,
                common_result=common_result,
                configuration=configuration,
            )
        )

    common_tuple = tuple(common_results)
    factor_audit_tuple = tuple(factor_audits)
    factor_sample_fingerprint = _versioned_hash(
        "all_factor_samples",
        [
            {
                "factor_id": item.factor_id,
                "factor_sample_fingerprint":
                    item.factor_sample_fingerprint,
            }
            for item in factor_audit_tuple
        ],
    )
    output_fingerprint = _versioned_hash(
        "m_evaluation_output",
        {
            "common_results": [
                item.to_dict() for item in common_tuple
            ],
            "factor_audits": [
                item.to_dict() for item in factor_audit_tuple
            ],
        },
    )
    audit = _build_audit(
        gate_status=MEvaluationGateStatus.READY,
        errors=(),
        warnings=tuple(warnings),
        configuration=configuration,
        mvp_fingerprint=mvp_before,
        preprocessing_fingerprint=prep_before,
        return_fingerprint=return_before,
        factor_sample_fingerprint=factor_sample_fingerprint,
        output_fingerprint=output_fingerprint,
    )
    return FinancialMVPMEvaluationResult(
        common_results=common_tuple,
        factor_audits=factor_audit_tuple,
        evaluation_audit=audit,
    )


def _mvp_guard_payload(
    result: MVPFinancialBatchResult,
) -> dict[str, Any]:
    payload = result.to_dict(include_rows=True)
    if result.observation_reference is not None:
        payload["observation_reference"] = (
            result.observation_reference.to_dict(include_records=True)
        )
    return payload


def _public_batch_lookup(
    batches: tuple[FinancialBatch, ...],
    errors: list[MEvaluationIssue],
) -> dict[tuple[str, str, str, str], float]:
    lookup: dict[tuple[str, str, str, str], float] = {}
    for batch in batches:
        if not isinstance(batch, FinancialBatch):
            errors.append(
                _error(
                    MEvaluationErrorCode.FACTOR_BATCH_COVERAGE_INVALID,
                    "all MVP batches must be FinancialBatch",
                    "batches",
                )
            )
            continue
        frame = batch.get_frame()
        for row in frame.to_dict(orient="records"):
            key = (
                batch.factor_id,
                str(row["code"]),
                _date_iso(row["report_period"], "report_period"),
                _date_iso(row["effective_date"], "effective_date"),
            )
            try:
                value = _finite_number(
                    row["factor_value"], "factor_value"
                )
            except (TypeError, ValueError) as exc:
                errors.append(
                    _error(
                        MEvaluationErrorCode.PUBLIC_BATCH_RAW_VALUE_MISMATCH,
                        str(exc),
                        "factor_value",
                        "|".join(key),
                    )
                )
                continue
            if key in lookup and lookup[key] != value:
                errors.append(
                    _error(
                        MEvaluationErrorCode.PUBLIC_BATCH_RAW_VALUE_MISMATCH,
                        "conflicting public FinancialBatch values",
                        "factor_value",
                        "|".join(key),
                    )
                )
            lookup[key] = value
    return lookup


def _select_returns(
    frame: pd.DataFrame,
    *,
    configuration: FinancialMVPMEvaluationConfig,
    errors: list[MEvaluationIssue],
) -> pd.DataFrame:
    selected = frame[
        frame["horizon"].astype(str)
        == str(configuration.return_horizon)
    ].copy()
    if selected.empty:
        errors.append(
            _error(
                MEvaluationErrorCode.RETURN_HORIZON_MISSING,
                "ForwardReturnBatch does not contain horizon=20",
                "horizon",
            )
        )
        return pd.DataFrame(
            columns=["date", "code", "forward_return"]
        )
    selected["date"] = pd.to_datetime(
        selected["date"], errors="raise"
    ).dt.date.astype(str)
    selected = selected[
        selected["date"].isin(configuration.evaluation_dates)
    ][["date", "code", "forward_return"]]
    selected["code"] = selected["code"].astype(str)
    selected["forward_return"] = pd.to_numeric(
        selected["forward_return"], errors="coerce"
    )
    return selected.sort_values(
        ["date", "code"], kind="mergesort"
    ).reset_index(drop=True)


def _evaluate_one_factor(
    *,
    factor_id: str,
    factor_frame: pd.DataFrame,
    return_set_id: str,
    configuration: FinancialMVPMEvaluationConfig,
) -> SecurityLevelEvaluationResult:
    daily_results: list[DailyICResult] = []
    rank_ics: list[float] = []
    pearson_ics: list[float] = []
    for evaluation_date in configuration.evaluation_dates:
        date_slice = factor_frame[
            factor_frame["date"] == evaluation_date
        ]
        factor_values = pd.to_numeric(
            date_slice["factor_value"], errors="coerce"
        )
        returns = pd.to_numeric(
            date_slice["forward_return"], errors="coerce"
        )
        valid = (
            factor_values.notna()
            & returns.notna()
            & np.isfinite(factor_values)
            & np.isfinite(returns)
        )
        values = factor_values.loc[valid]
        valid_returns = returns.loc[valid]
        sample_size = len(values)
        issue_codes: list[str] = []
        rank_ic: float | None = None
        pearson_ic: float | None = None
        evaluated = True
        if sample_size < configuration.minimum_cross_section_size:
            issue_codes.append("INSUFFICIENT_CROSS_SECTION")
            evaluated = False
        elif int(values.nunique()) <= 1:
            issue_codes.append("CONSTANT_FACTOR_CROSS_SECTION")
            evaluated = False
        elif int(valid_returns.nunique()) <= 1:
            issue_codes.append("CONSTANT_RETURN_CROSS_SECTION")
            evaluated = False
        else:
            rank_stat = spearmanr(values, valid_returns)
            pearson_stat = pearsonr(values, valid_returns)
            if math.isfinite(float(rank_stat.correlation)):
                rank_ic = float(rank_stat.correlation)
                rank_ics.append(rank_ic)
            else:
                issue_codes.append("NONFINITE_RANK_IC")
            if math.isfinite(float(pearson_stat.statistic)):
                pearson_ic = float(pearson_stat.statistic)
                pearson_ics.append(pearson_ic)
            else:
                issue_codes.append("NONFINITE_PEARSON_IC")
            if rank_ic is None and pearson_ic is None:
                issue_codes.append("NO_VALID_IC_FOR_DATE")
                evaluated = False
        daily_results.append(
            DailyICResult(
                date=evaluation_date,
                sample_size=sample_size,
                rank_ic=rank_ic,
                pearson_ic=pearson_ic,
                evaluated=evaluated,
                issue_codes=issue_codes,
            )
        )

    evaluated_dates = sum(item.evaluated for item in daily_results)
    excluded_dates = len(daily_results) - evaluated_dates
    total_observations = sum(item.sample_size for item in daily_results)
    eligible_dates = {
        item.date for item in daily_results if item.evaluated
    }
    group_summary = evaluate_group_returns(
        factor_frame[
            factor_frame["date"].isin(eligible_dates)
        ][["date", "factor_value", "forward_return"]],
        quantiles=configuration.quantiles,
    )
    if evaluated_dates < configuration.minimum_evaluation_periods:
        return SecurityLevelEvaluationResult(
            factor_id=factor_id,
            return_set_id=return_set_id,
            horizon=str(configuration.return_horizon),
            factor_type="financial",
            value_scope="security_level",
            overall_status=EvaluationStatus.NOT_RUN,
            quantiles=configuration.quantiles,
            daily_group_returns=_complete_daily_group_results(
                group_summary.daily_group_returns,
                daily_results,
            ),
            group_return_issue_codes=list(
                group_summary.issue_codes
            ),
            total_dates=len(configuration.evaluation_dates),
            evaluated_dates=evaluated_dates,
            excluded_dates=excluded_dates,
            total_observations=total_observations,
            daily_results=daily_results,
            issue_codes=["INSUFFICIENT_VALID_EVALUATION_PERIODS"],
            gate_status=MEvaluationGateStatus.READY.value,
            gate_issue_codes=[],
        )

    rank_mean = float(np.mean(rank_ics)) if rank_ics else None
    rank_std = (
        float(np.std(rank_ics, ddof=1)) if len(rank_ics) > 1 else None
    )
    pearson_mean = (
        float(np.mean(pearson_ics)) if pearson_ics else None
    )
    pearson_std = (
        float(np.std(pearson_ics, ddof=1))
        if len(pearson_ics) > 1
        else None
    )
    issue_codes: list[str] = []
    rank_ir = _safe_ratio(rank_mean, rank_std)
    pearson_ir = _safe_ratio(pearson_mean, pearson_std)
    if rank_std is not None and math.isclose(
        rank_std, 0.0, rel_tol=0.0, abs_tol=1e-12
    ):
        rank_ir = None
        issue_codes.append("ZERO_RANK_IC_VARIANCE")
    if pearson_std is not None and math.isclose(
        pearson_std, 0.0, rel_tol=0.0, abs_tol=1e-12
    ):
        pearson_ir = None
        issue_codes.append("ZERO_PEARSON_IC_VARIANCE")
    overall_status = (
        EvaluationStatus.COMPLETED
        if excluded_dates == 0
        else EvaluationStatus.PARTIAL
    )
    return SecurityLevelEvaluationResult(
        factor_id=factor_id,
        return_set_id=return_set_id,
        horizon=str(configuration.return_horizon),
        factor_type="financial",
        value_scope="security_level",
        overall_status=overall_status,
        rank_ic_mean=rank_mean,
        rank_ic_std=rank_std,
        rank_ic_ir=rank_ir,
        rank_ic_t_stat=hac_t_stat(
            rank_ics, max_lag=configuration.hac_max_lag
        ),
        rank_ic_positive_ratio=(
            float(np.mean([value > 0 for value in rank_ics]))
            if rank_ics
            else None
        ),
        pearson_ic_mean=pearson_mean,
        pearson_ic_std=pearson_std,
        pearson_ic_ir=pearson_ir,
        pearson_ic_t_stat=hac_t_stat(
            pearson_ics, max_lag=configuration.hac_max_lag
        ),
        pearson_ic_positive_ratio=(
            float(np.mean([value > 0 for value in pearson_ics]))
            if pearson_ics
            else None
        ),
        quantiles=configuration.quantiles,
        quantile_returns=group_summary.quantile_returns,
        long_short_mean=group_summary.long_short_mean,
        monotonicity_spearman=group_summary.monotonicity_spearman,
        daily_group_returns=_complete_daily_group_results(
            group_summary.daily_group_returns,
            daily_results,
        ),
        group_return_issue_codes=group_summary.issue_codes,
        total_dates=len(configuration.evaluation_dates),
        evaluated_dates=evaluated_dates,
        excluded_dates=excluded_dates,
        total_observations=total_observations,
        daily_results=daily_results,
        issue_codes=issue_codes,
        gate_status=MEvaluationGateStatus.READY.value,
        gate_issue_codes=[],
    )


def _complete_daily_group_results(
    results: list[DailyGroupReturnResult],
    daily_ic_results: list[DailyICResult],
) -> list[DailyGroupReturnResult]:
    by_date = {item.date: item for item in results}
    return [
        by_date.get(
            daily_result.date,
            DailyGroupReturnResult(
                date=daily_result.date,
                sample_size=daily_result.sample_size,
                issue_codes=(
                    list(daily_result.issue_codes)
                    or ["DATE_EXCLUDED_FROM_GROUP_RETURNS"]
                ),
            ),
        )
        for daily_result in daily_ic_results
    ]


def _build_factor_audit(
    *,
    factor_id: str,
    frame: pd.DataFrame,
    common_result: SecurityLevelEvaluationResult,
    configuration: FinancialMVPMEvaluationConfig,
) -> FinancialMVPMFactorAudit:
    factor_sample_records = [
        {
            "date": str(row["date"]),
            "code": str(row["code"]),
            "factor_value": float(row["factor_value"]),
            "raw_pit_factor_value": float(
                row["raw_pit_factor_value"]
            ),
            "observation_id": str(row["observation_id"]),
            "observation_content_hash": str(
                row["observation_content_hash"]
            ),
            "sample_content_hash": str(row["sample_content_hash"]),
            "preprocessing_content_hash": str(
                row["preprocessing_content_hash"]
            ),
        }
        for row in frame.to_dict(orient="records")
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
        for row in frame.to_dict(orient="records")
    ]
    label_available_count = sum(
        item["forward_return"] is not None for item in label_records
    )
    factor_sample_fingerprint = _versioned_hash(
        "factor_sample", factor_sample_records
    )
    label_alignment_fingerprint = _versioned_hash(
        "label_alignment", label_records
    )
    common_result_fingerprint = _versioned_hash(
        "common_result", common_result.to_dict()
    )
    fields = {
        "factor_id": factor_id,
        "configured_date_count": len(configuration.evaluation_dates),
        "factor_sample_count": len(factor_sample_records),
        "label_available_count": label_available_count,
        "valid_pair_count": label_available_count,
        "evaluated_date_count": common_result.evaluated_dates,
        "excluded_date_count": common_result.excluded_dates,
        "factor_sample_fingerprint": factor_sample_fingerprint,
        "label_alignment_fingerprint": label_alignment_fingerprint,
        "common_result_fingerprint": common_result_fingerprint,
        "schema_version": M_EVAL_FACTOR_AUDIT_SCHEMA_VERSION,
    }
    return FinancialMVPMFactorAudit(
        **fields,
        content_hash=_versioned_hash("m_factor_audit", fields),
    )


def _build_audit(
    *,
    gate_status: MEvaluationGateStatus,
    errors: tuple[MEvaluationIssue, ...],
    warnings: tuple[MEvaluationIssue, ...],
    configuration: FinancialMVPMEvaluationConfig | None,
    mvp_fingerprint: str,
    preprocessing_fingerprint: str,
    return_fingerprint: str,
    factor_sample_fingerprint: str,
    output_fingerprint: str,
) -> FinancialMVPMEvaluationAudit:
    configuration_payload = (
        configuration.to_dict()
        if configuration is not None
        else {"configuration": "invalid"}
    )
    fields = {
        "gate_status": gate_status.value,
        "errors": errors,
        "warnings": warnings,
        "supported_factor_ids": SUPPORTED_FACTOR_IDS,
        "configuration_fingerprint": _versioned_hash(
            "m_evaluation_configuration", configuration_payload
        ),
        "mvp_batch_fingerprint": mvp_fingerprint,
        "preprocessing_fingerprint": preprocessing_fingerprint,
        "return_input_fingerprint": return_fingerprint,
        "factor_sample_fingerprint": factor_sample_fingerprint,
        "output_fingerprint": output_fingerprint,
        "schema_version": M_EVAL_SCHEMA_VERSION,
        "audit_schema_version": M_EVAL_AUDIT_SCHEMA_VERSION,
        "hash_contract_version": M_EVAL_HASH_CONTRACT_VERSION,
    }
    return FinancialMVPMEvaluationAudit(
        **fields,
        content_hash=_versioned_hash("m_evaluation_audit", fields),
    )


def _blocked_result(
    errors: tuple[MEvaluationIssue, ...],
    *,
    configuration: FinancialMVPMEvaluationConfig | None = None,
    mvp_fingerprint: str | None = None,
    preprocessing_fingerprint: str | None = None,
    return_fingerprint: str | None = None,
) -> FinancialMVPMEvaluationResult:
    empty = _versioned_hash("empty", [])
    audit = _build_audit(
        gate_status=MEvaluationGateStatus.BLOCKED,
        errors=errors,
        warnings=(),
        configuration=configuration,
        mvp_fingerprint=mvp_fingerprint or empty,
        preprocessing_fingerprint=preprocessing_fingerprint or empty,
        return_fingerprint=return_fingerprint or empty,
        factor_sample_fingerprint=empty,
        output_fingerprint=empty,
    )
    return FinancialMVPMEvaluationResult(
        common_results=(),
        factor_audits=(),
        evaluation_audit=audit,
    )


def _error(
    code: MEvaluationErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> MEvaluationIssue:
    return MEvaluationIssue(
        code=code.value,
        message=message,
        severity=MEvaluationSeverity.ERROR.value,
        field_name=field_name,
        record_key=record_key,
    )


def _deduplicate_issues(
    issues: list[MEvaluationIssue] | tuple[MEvaluationIssue, ...],
) -> list[MEvaluationIssue]:
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
            key=lambda value: tuple(
                "" if item is None else item for item in value
            ),
        )
    ]


def _safe_ratio(
    numerator: float | None, denominator: float | None
) -> float | None:
    if (
        numerator is None
        or denominator is None
        or denominator == 0
    ):
        return None
    return float(numerator / denominator)


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        records.append(
            {
                str(key): _canonical_json_value(value)
                for key, value in sorted(row.items())
            }
        )
    return records


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value, (int, float, np.number)
    ):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} is required")
    return value.strip()


def _date_iso(value: Any, field_name: str) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
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
            for key, item in sorted(
                value.items(), key=lambda pair: str(pair[0])
            )
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_canonical_json_value(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
    if isinstance(value, (pd.Timestamp, date)):
        return _date_iso(value, "date")
    if value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError("non-finite values cannot enter official hashes")
        value = round(value, HASH_FLOAT_DECIMAL_PLACES)
        if value == 0:
            return 0.0
    return value


def _versioned_hash(domain: str, value: Any) -> str:
    payload = {
        "domain": domain,
        "hash_contract_version": M_EVAL_HASH_CONTRACT_VERSION,
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
