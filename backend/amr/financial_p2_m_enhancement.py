"""FIN-P2-M-ENH: deterministic multi-horizon Track-M evidence.

This additive Phase-2 module keeps the accepted Phase-1 evaluator frozen.  It
uses the accepted 20D result as the primary anchor, adds pre-registered 5D and
60D robustness horizons, requires an expanded stable universe, and reports
rolling direction/coverage evidence without selecting a best horizon.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.amr.evaluation_core import SecurityLevelEvaluationResult
from backend.amr.evaluation_input_contract import (
    ForwardReturnBatch,
    ValueScope,
)
from backend.amr.financial_mvp_batch import (
    SUPPORTED_FACTOR_IDS,
    MVPFinancialBatchResult,
)
from backend.amr.financial_mvp_m_evaluation import (
    FinancialMVPMEvaluationConfig,
    FinancialMVPMEvaluationResult,
    _evaluate_one_factor,
    evaluate_financial_mvp_m,
)
from backend.amr.financial_preprocessing import (
    FinancialPreprocessingResult,
)


P2_M_SCHEMA_VERSION = "FinancialP2MEnhancement-v1.0"
P2_M_AUDIT_SCHEMA_VERSION = "FinancialP2MEnhancementAudit-v1.0"
P2_M_HORIZON_SCHEMA_VERSION = "FinancialP2MHorizonEvidence-v1.0"
P2_M_ROLLING_SCHEMA_VERSION = "FinancialP2MRollingEvidence-v1.0"
P2_M_FACTOR_SCHEMA_VERSION = "FinancialP2MFactorEvidence-v1.0"
P2_M_HASH_CONTRACT_VERSION = "FIN-P2-M-ENH-HASH-v1.0"
P2_M_POLICY_VERSION = "FIN-P2-M-ENH-POLICY-v1.0"
P2_M_HORIZONS = (5, 20, 60)
P2_M_PRIMARY_HORIZON = 20
P2_M_MIN_UNIVERSE = 60
P2_M_ROLLING_WINDOW = 6
P2_M_TRACK = "M"
P2_M_EVIDENCE_PRIORITY = "primary"
P2_M_WEIGHTING = "equal"
P2_M_NOT_RUN = "not_run"


class P2MGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class P2MEvidenceStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    NOT_RUN = "not_run"


class P2MDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    ZERO = "zero"
    NOT_EVALUABLE = "not_evaluable"


class P2MConsistency(str, Enum):
    CONSISTENT = "consistent"
    MIXED = "mixed"
    INSUFFICIENT = "insufficient"


class P2MErrorCode(str, Enum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_MVP_BATCH_RESULT = "INVALID_MVP_BATCH_RESULT"
    INVALID_PREPROCESSING_RESULT = "INVALID_PREPROCESSING_RESULT"
    INVALID_FORWARD_RETURN_BATCH = "INVALID_FORWARD_RETURN_BATCH"
    NON_SYNTHETIC_RETURN_INPUT = "NON_SYNTHETIC_RETURN_INPUT"
    PRIMARY_M_EVALUATION_BLOCKED = "PRIMARY_M_EVALUATION_BLOCKED"
    EXPANDED_UNIVERSE_TOO_SMALL = "EXPANDED_UNIVERSE_TOO_SMALL"
    UNIVERSE_MEMBERSHIP_DRIFT = "UNIVERSE_MEMBERSHIP_DRIFT"
    RETURN_HORIZON_MISSING = "RETURN_HORIZON_MISSING"
    DUPLICATE_RETURN_KEY = "DUPLICATE_RETURN_KEY"
    PRIMARY_HORIZON_MISMATCH = "PRIMARY_HORIZON_MISMATCH"
    INPUT_MUTATED = "INPUT_MUTATED"


@dataclass(frozen=True)
class FinancialP2MEnhancementConfig:
    mvp_configuration: FinancialMVPMEvaluationConfig
    universe_reference: str
    universe_version: str
    horizons: tuple[int, ...] = P2_M_HORIZONS
    primary_horizon: int = P2_M_PRIMARY_HORIZON
    minimum_universe_size: int = P2_M_MIN_UNIVERSE
    rolling_window_months: int = P2_M_ROLLING_WINDOW
    validation_track: str = P2_M_TRACK
    evidence_priority: str = P2_M_EVIDENCE_PRIORITY
    weighting: str = P2_M_WEIGHTING
    direction_source: str = "original_direction_only"
    neutralization_status: str = P2_M_NOT_RUN
    fama_macbeth_status: str = P2_M_NOT_RUN
    oos_status: str = P2_M_NOT_RUN
    multiple_testing_status: str = P2_M_NOT_RUN
    schema_version: str = P2_M_SCHEMA_VERSION
    policy_version: str = P2_M_POLICY_VERSION
    synthetic_test_only: bool = True

    def __post_init__(self) -> None:
        if not isinstance(
            self.mvp_configuration, FinancialMVPMEvaluationConfig
        ):
            raise TypeError(
                "mvp_configuration must be FinancialMVPMEvaluationConfig"
            )
        _required_text(self.universe_reference, "universe_reference")
        _required_text(self.universe_version, "universe_version")
        frozen = {
            "horizons": (tuple(self.horizons), P2_M_HORIZONS),
            "primary_horizon": (
                self.primary_horizon,
                P2_M_PRIMARY_HORIZON,
            ),
            "minimum_universe_size": (
                self.minimum_universe_size,
                P2_M_MIN_UNIVERSE,
            ),
            "rolling_window_months": (
                self.rolling_window_months,
                P2_M_ROLLING_WINDOW,
            ),
            "validation_track": (self.validation_track, P2_M_TRACK),
            "evidence_priority": (
                self.evidence_priority,
                P2_M_EVIDENCE_PRIORITY,
            ),
            "weighting": (self.weighting, P2_M_WEIGHTING),
            "direction_source": (
                self.direction_source,
                "original_direction_only",
            ),
            "neutralization_status": (
                self.neutralization_status,
                P2_M_NOT_RUN,
            ),
            "fama_macbeth_status": (
                self.fama_macbeth_status,
                P2_M_NOT_RUN,
            ),
            "oos_status": (self.oos_status, P2_M_NOT_RUN),
            "multiple_testing_status": (
                self.multiple_testing_status,
                P2_M_NOT_RUN,
            ),
            "schema_version": (
                self.schema_version,
                P2_M_SCHEMA_VERSION,
            ),
            "policy_version": (
                self.policy_version,
                P2_M_POLICY_VERSION,
            ),
            "synthetic_test_only": (self.synthetic_test_only, True),
        }
        for field_name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{field_name} must be frozen at {expected}")
        if (
            self.rolling_window_months
            > len(self.mvp_configuration.evaluation_dates)
        ):
            raise ValueError(
                "rolling_window_months cannot exceed evaluation dates"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mvp_configuration": self.mvp_configuration.to_dict(),
            "universe_reference": self.universe_reference,
            "universe_version": self.universe_version,
            "horizons": list(self.horizons),
            "primary_horizon": self.primary_horizon,
            "minimum_universe_size": self.minimum_universe_size,
            "rolling_window_months": self.rolling_window_months,
            "validation_track": self.validation_track,
            "evidence_priority": self.evidence_priority,
            "weighting": self.weighting,
            "direction_source": self.direction_source,
            "neutralization_status": self.neutralization_status,
            "fama_macbeth_status": self.fama_macbeth_status,
            "oos_status": self.oos_status,
            "multiple_testing_status": self.multiple_testing_status,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "synthetic_test_only": self.synthetic_test_only,
        }


@dataclass(frozen=True)
class P2MIssue:
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
class FinancialP2MHorizonEvidence:
    factor_id: str
    horizon: int
    is_primary: bool
    universe_count: int
    configured_date_count: int
    factor_sample_count: int
    label_available_count: int
    paired_coverage_rate: float
    common_result: SecurityLevelEvaluationResult
    factor_sample_fingerprint: str
    label_fingerprint: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "horizon": self.horizon,
            "is_primary": self.is_primary,
            "universe_count": self.universe_count,
            "configured_date_count": self.configured_date_count,
            "factor_sample_count": self.factor_sample_count,
            "label_available_count": self.label_available_count,
            "paired_coverage_rate": self.paired_coverage_rate,
            "common_result": self.common_result.to_dict(),
            "factor_sample_fingerprint":
                self.factor_sample_fingerprint,
            "label_fingerprint": self.label_fingerprint,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2MRollingEvidence:
    factor_id: str
    horizon: int
    window_start: str
    window_end: str
    configured_periods: int
    effective_periods: int
    paired_observations: int
    paired_coverage_rate: float
    rank_ic_mean: float | None
    rank_ic_positive_ratio: float | None
    direction: str
    status: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "horizon": self.horizon,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "configured_periods": self.configured_periods,
            "effective_periods": self.effective_periods,
            "paired_observations": self.paired_observations,
            "paired_coverage_rate": self.paired_coverage_rate,
            "rank_ic_mean": self.rank_ic_mean,
            "rank_ic_positive_ratio": self.rank_ic_positive_ratio,
            "direction": self.direction,
            "status": self.status,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2MFactorEvidence:
    factor_id: str
    validation_track: str
    evidence_priority: str
    primary_horizon: int
    horizon_evidence: tuple[FinancialP2MHorizonEvidence, ...]
    rolling_evidence: tuple[FinancialP2MRollingEvidence, ...]
    horizon_direction_consistency: str
    primary_rolling_direction_consistency: str
    best_horizon_selection_status: str
    neutralization_status: str
    fama_macbeth_status: str
    oos_status: str
    multiple_testing_status: str
    schema_version: str
    content_hash: str

    def get_horizon(self, horizon: Any) -> FinancialP2MHorizonEvidence:
        if isinstance(horizon, bool) or not isinstance(
            horizon, (int, np.integer)
        ):
            raise TypeError("horizon must be an integer")
        matches = [
            item
            for item in self.horizon_evidence
            if item.horizon == int(horizon)
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one horizon={horizon} for {self.factor_id}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "validation_track": self.validation_track,
            "evidence_priority": self.evidence_priority,
            "primary_horizon": self.primary_horizon,
            "horizon_evidence": [
                item.to_dict() for item in self.horizon_evidence
            ],
            "rolling_evidence": [
                item.to_dict() for item in self.rolling_evidence
            ],
            "horizon_direction_consistency":
                self.horizon_direction_consistency,
            "primary_rolling_direction_consistency":
                self.primary_rolling_direction_consistency,
            "best_horizon_selection_status":
                self.best_horizon_selection_status,
            "neutralization_status": self.neutralization_status,
            "fama_macbeth_status": self.fama_macbeth_status,
            "oos_status": self.oos_status,
            "multiple_testing_status": self.multiple_testing_status,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2MEnhancementAudit:
    gate_status: str
    errors: tuple[P2MIssue, ...]
    warnings: tuple[P2MIssue, ...]
    supported_factor_ids: tuple[str, ...]
    horizons: tuple[int, ...]
    primary_horizon: int
    universe_count: int
    configuration_fingerprint: str
    primary_m_evaluation_fingerprint: str
    universe_fingerprint: str
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
            "warnings": [item.to_dict() for item in self.warnings],
            "supported_factor_ids": list(self.supported_factor_ids),
            "horizons": list(self.horizons),
            "primary_horizon": self.primary_horizon,
            "universe_count": self.universe_count,
            "configuration_fingerprint": self.configuration_fingerprint,
            "primary_m_evaluation_fingerprint":
                self.primary_m_evaluation_fingerprint,
            "universe_fingerprint": self.universe_fingerprint,
            "factor_input_fingerprint":
                self.factor_input_fingerprint,
            "label_input_fingerprint": self.label_input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "schema_version": self.schema_version,
            "audit_schema_version": self.audit_schema_version,
            "hash_contract_version": self.hash_contract_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2MEnhancementResult:
    factor_evidence: tuple[FinancialP2MFactorEvidence, ...]
    enhancement_audit: FinancialP2MEnhancementAudit

    def get_factor(self, factor_id: Any) -> FinancialP2MFactorEvidence:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item
            for item in self.factor_evidence
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one factor evidence for {normalized}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_evidence": [
                item.to_dict() for item in self.factor_evidence
            ],
            "enhancement_audit": self.enhancement_audit.to_dict(),
        }


@dataclass(frozen=True)
class _HorizonEvaluationConfig:
    evaluation_dates: tuple[str, ...]
    return_horizon: int
    minimum_cross_section_size: int
    minimum_evaluation_periods: int
    quantiles: int
    hac_max_lag: int


def evaluate_financial_p2_m_enhancement(
    mvp_batch_result: MVPFinancialBatchResult,
    preprocessing_result: FinancialPreprocessingResult,
    forward_returns: ForwardReturnBatch,
    *,
    configuration: FinancialP2MEnhancementConfig,
) -> FinancialP2MEnhancementResult:
    """Build pre-registered multi-horizon and rolling Track-M evidence."""

    errors = _validate_types(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        configuration,
    )
    if errors:
        return _blocked_result(errors, configuration)

    input_before = _input_guard(
        mvp_batch_result, preprocessing_result, forward_returns
    )
    primary = evaluate_financial_mvp_m(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        configuration=configuration.mvp_configuration,
    )
    if primary.evaluation_audit.gate_status != P2MGateStatus.READY.value:
        errors.append(
            _error(
                P2MErrorCode.PRIMARY_M_EVALUATION_BLOCKED,
                "accepted 20D M evaluation must be ready",
                "primary_m_evaluation",
            )
        )
        return _blocked_result(
            errors,
            configuration,
            primary_fingerprint=(
                primary.evaluation_audit.output_fingerprint
            ),
        )

    factor_frame, universe_codes = _build_factor_frame(
        mvp_batch_result,
        preprocessing_result,
        configuration,
        errors,
    )
    return_frame = _normalize_returns(
        forward_returns, configuration, errors
    )
    if errors:
        return _blocked_result(
            errors,
            configuration,
            primary_fingerprint=(
                primary.evaluation_audit.output_fingerprint
            ),
        )

    horizon_by_factor: dict[
        str, list[FinancialP2MHorizonEvidence]
    ] = {factor_id: [] for factor_id in SUPPORTED_FACTOR_IDS}
    rolling_by_factor: dict[
        str, list[FinancialP2MRollingEvidence]
    ] = {factor_id: [] for factor_id in SUPPORTED_FACTOR_IDS}
    universe_count = len(universe_codes)
    for factor_id in SUPPORTED_FACTOR_IDS:
        factor_slice = factor_frame[
            factor_frame["factor_id"] == factor_id
        ].copy()
        for horizon in configuration.horizons:
            labels = return_frame[
                return_frame["horizon"] == horizon
            ][["date", "code", "forward_return"]]
            merged = factor_slice.merge(
                labels,
                on=["date", "code"],
                how="left",
                validate="one_to_one",
                sort=False,
            ).sort_values(["date", "code"], kind="mergesort")
            horizon_config = _HorizonEvaluationConfig(
                evaluation_dates=(
                    configuration.mvp_configuration.evaluation_dates
                ),
                return_horizon=horizon,
                minimum_cross_section_size=(
                    configuration.mvp_configuration
                    .minimum_cross_section_size
                ),
                minimum_evaluation_periods=(
                    configuration.mvp_configuration
                    .minimum_evaluation_periods
                ),
                quantiles=configuration.mvp_configuration.quantiles,
                hac_max_lag=(
                    configuration.mvp_configuration.hac_max_lag
                ),
            )
            common = _evaluate_one_factor(
                factor_id=factor_id,
                factor_frame=merged,
                return_set_id=forward_returns.return_set_id,
                configuration=horizon_config,
            )
            if (
                horizon == configuration.primary_horizon
                and common.to_dict()
                != primary.get_result(factor_id).to_dict()
            ):
                errors.append(
                    _error(
                        P2MErrorCode.PRIMARY_HORIZON_MISMATCH,
                        "20D enhancement result must equal accepted MVP M result",
                        "common_result",
                        factor_id,
                    )
                )
            horizon_evidence = _build_horizon_evidence(
                factor_id,
                horizon,
                merged,
                common,
                universe_count,
                configuration,
            )
            horizon_by_factor[factor_id].append(horizon_evidence)
            rolling_by_factor[factor_id].extend(
                _build_rolling_evidence(
                    factor_id,
                    horizon,
                    common,
                    universe_count,
                    configuration,
                )
            )

    input_after = _input_guard(
        mvp_batch_result, preprocessing_result, forward_returns
    )
    if input_before != input_after:
        errors.append(
            _error(
                P2MErrorCode.INPUT_MUTATED,
                "one or more enhancement inputs changed during evaluation",
                "inputs",
            )
        )
    if errors:
        return _blocked_result(
            errors,
            configuration,
            primary_fingerprint=(
                primary.evaluation_audit.output_fingerprint
            ),
        )

    factors = tuple(
        _build_factor_evidence(
            factor_id,
            tuple(horizon_by_factor[factor_id]),
            tuple(rolling_by_factor[factor_id]),
            configuration,
        )
        for factor_id in SUPPORTED_FACTOR_IDS
    )
    output_fingerprint = _hash(
        "p2_m_output", [item.to_dict() for item in factors]
    )
    audit = _build_audit(
        gate_status=P2MGateStatus.READY,
        errors=(),
        warnings=(),
        configuration=configuration,
        primary_fingerprint=(
            primary.evaluation_audit.output_fingerprint
        ),
        universe_codes=universe_codes,
        factor_frame=factor_frame,
        return_frame=return_frame,
        output_fingerprint=output_fingerprint,
    )
    return FinancialP2MEnhancementResult(
        factor_evidence=factors,
        enhancement_audit=audit,
    )


def _validate_types(
    mvp: Any,
    prep: Any,
    returns: Any,
    configuration: Any,
) -> list[P2MIssue]:
    errors: list[P2MIssue] = []
    if not isinstance(configuration, FinancialP2MEnhancementConfig):
        return [
            _error(
                P2MErrorCode.INVALID_CONFIGURATION,
                "configuration must be FinancialP2MEnhancementConfig",
                "configuration",
            )
        ]
    if not isinstance(mvp, MVPFinancialBatchResult):
        errors.append(
            _error(
                P2MErrorCode.INVALID_MVP_BATCH_RESULT,
                "mvp_batch_result must be MVPFinancialBatchResult",
                "mvp_batch_result",
            )
        )
    if not isinstance(prep, FinancialPreprocessingResult):
        errors.append(
            _error(
                P2MErrorCode.INVALID_PREPROCESSING_RESULT,
                "preprocessing_result must be FinancialPreprocessingResult",
                "preprocessing_result",
            )
        )
    if not isinstance(returns, ForwardReturnBatch):
        errors.append(
            _error(
                P2MErrorCode.INVALID_FORWARD_RETURN_BATCH,
                "forward_returns must be ForwardReturnBatch",
                "forward_returns",
            )
        )
    elif returns.value_scope is not ValueScope.SECURITY_LEVEL:
        errors.append(
            _error(
                P2MErrorCode.INVALID_FORWARD_RETURN_BATCH,
                "Track M requires security-level forward returns",
                "value_scope",
            )
        )
    elif returns.provenance.get("synthetic_test_only") is not True:
        errors.append(
            _error(
                P2MErrorCode.NON_SYNTHETIC_RETURN_INPUT,
                "return provenance must set synthetic_test_only=true",
                "provenance.synthetic_test_only",
            )
        )
    return errors


def _build_factor_frame(
    mvp: MVPFinancialBatchResult,
    prep: FinancialPreprocessingResult,
    configuration: FinancialP2MEnhancementConfig,
    errors: list[P2MIssue],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    reference = mvp.observation_reference
    assert reference is not None
    observations = {
        (item.evaluation_date, item.code, item.factor_id): item
        for item in reference.records
    }
    prepared = {
        item.preparation_key: item for item in prep.prepared_inputs
    }
    rows = [
        {
            "date": key[0],
            "code": key[1],
            "factor_id": key[2],
            "factor_value": prepared[key].evaluation_factor_value,
            "raw_pit_factor_value":
                prepared[key].raw_pit_factor_value,
            "observation_content_hash":
                observations[key].content_hash,
            "preprocessing_content_hash": prepared[key].content_hash,
        }
        for key in sorted(observations)
    ]
    frame = pd.DataFrame(rows)
    expected_dates = (
        configuration.mvp_configuration.evaluation_dates
    )
    code_sets: dict[tuple[str, str], frozenset[str]] = {}
    for factor_id in SUPPORTED_FACTOR_IDS:
        for evaluation_date in expected_dates:
            selected = frame[
                (frame["factor_id"] == factor_id)
                & (frame["date"] == evaluation_date)
            ]
            code_sets[(factor_id, evaluation_date)] = frozenset(
                selected["code"].astype(str)
            )
    distinct_sets = set(code_sets.values())
    if len(distinct_sets) != 1:
        errors.append(
            _error(
                P2MErrorCode.UNIVERSE_MEMBERSHIP_DRIFT,
                "all factors and dates must share one frozen universe",
                "factor_id,evaluation_date,code",
            )
        )
        universe = min(
            distinct_sets, key=lambda item: (len(item), sorted(item))
        )
    else:
        universe = next(iter(distinct_sets), frozenset())
    if len(universe) < configuration.minimum_universe_size:
        errors.append(
            _error(
                P2MErrorCode.EXPANDED_UNIVERSE_TOO_SMALL,
                "expanded M universe must contain at least 60 securities",
                "code",
            )
        )
    return (
        frame.sort_values(
            ["factor_id", "date", "code"], kind="mergesort"
        ).reset_index(drop=True),
        tuple(sorted(universe)),
    )


def _normalize_returns(
    returns: ForwardReturnBatch,
    configuration: FinancialP2MEnhancementConfig,
    errors: list[P2MIssue],
) -> pd.DataFrame:
    frame = returns.get_frame()
    selected = frame[
        frame["horizon"].astype(str).isin(
            {str(value) for value in configuration.horizons}
        )
    ].copy()
    selected["date"] = pd.to_datetime(
        selected["date"], errors="raise"
    ).dt.date.astype(str)
    selected["code"] = selected["code"].astype(str)
    selected["horizon"] = pd.to_numeric(
        selected["horizon"], errors="raise"
    ).astype(int)
    selected["forward_return"] = pd.to_numeric(
        selected["forward_return"], errors="coerce"
    )
    selected = selected[
        selected["date"].isin(
            configuration.mvp_configuration.evaluation_dates
        )
    ][["date", "code", "horizon", "forward_return"]]
    present = set(selected["horizon"])
    for horizon in configuration.horizons:
        if horizon not in present:
            errors.append(
                _error(
                    P2MErrorCode.RETURN_HORIZON_MISSING,
                    f"forward returns are missing horizon={horizon}",
                    "horizon",
                    str(horizon),
                )
            )
    duplicate = selected.duplicated(
        ["date", "code", "horizon"], keep=False
    )
    if duplicate.any():
        errors.append(
            _error(
                P2MErrorCode.DUPLICATE_RETURN_KEY,
                "return labels must be unique by date, code, and horizon",
                "date,code,horizon",
            )
        )
    return selected.sort_values(
        ["horizon", "date", "code"], kind="mergesort"
    ).reset_index(drop=True)


def _build_horizon_evidence(
    factor_id: str,
    horizon: int,
    frame: pd.DataFrame,
    common: SecurityLevelEvaluationResult,
    universe_count: int,
    configuration: FinancialP2MEnhancementConfig,
) -> FinancialP2MHorizonEvidence:
    factor_records = [
        {
            "date": str(row["date"]),
            "code": str(row["code"]),
            "factor_value": float(row["factor_value"]),
            "observation_content_hash": str(
                row["observation_content_hash"]
            ),
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
    label_count = sum(
        item["forward_return"] is not None for item in label_records
    )
    fields = {
        "factor_id": factor_id,
        "horizon": horizon,
        "is_primary": horizon == configuration.primary_horizon,
        "universe_count": universe_count,
        "configured_date_count": len(
            configuration.mvp_configuration.evaluation_dates
        ),
        "factor_sample_count": len(factor_records),
        "label_available_count": label_count,
        "paired_coverage_rate": (
            label_count / len(factor_records) if factor_records else 0.0
        ),
        "common_result": common,
        "factor_sample_fingerprint": _hash(
            "p2_m_factor_sample", factor_records
        ),
        "label_fingerprint": _hash(
            f"p2_m_label_h{horizon}", label_records
        ),
        "schema_version": P2_M_HORIZON_SCHEMA_VERSION,
    }
    return FinancialP2MHorizonEvidence(
        **fields,
        content_hash=_hash("p2_m_horizon_evidence", fields),
    )


def _build_rolling_evidence(
    factor_id: str,
    horizon: int,
    common: SecurityLevelEvaluationResult,
    universe_count: int,
    configuration: FinancialP2MEnhancementConfig,
) -> tuple[FinancialP2MRollingEvidence, ...]:
    dates = configuration.mvp_configuration.evaluation_dates
    window = configuration.rolling_window_months
    by_date = {item.date: item for item in common.daily_results}
    evidence = []
    for start in range(0, len(dates) - window + 1):
        selected_dates = dates[start : start + window]
        daily = tuple(by_date[value] for value in selected_dates)
        evaluated = tuple(item for item in daily if item.evaluated)
        rank_values = [
            item.rank_ic
            for item in evaluated
            if item.rank_ic is not None
        ]
        rank_mean = (
            float(np.mean(rank_values)) if rank_values else None
        )
        status = (
            P2MEvidenceStatus.NOT_RUN
            if not evaluated
            else (
                P2MEvidenceStatus.COMPLETED
                if len(evaluated) == window
                else P2MEvidenceStatus.PARTIAL
            )
        )
        paired = sum(item.sample_size for item in daily)
        fields = {
            "factor_id": factor_id,
            "horizon": horizon,
            "window_start": selected_dates[0],
            "window_end": selected_dates[-1],
            "configured_periods": window,
            "effective_periods": len(evaluated),
            "paired_observations": paired,
            "paired_coverage_rate": (
                paired / (universe_count * window)
                if universe_count
                else 0.0
            ),
            "rank_ic_mean": rank_mean,
            "rank_ic_positive_ratio": (
                float(np.mean([value > 0 for value in rank_values]))
                if rank_values
                else None
            ),
            "direction": _direction(rank_mean).value,
            "status": status.value,
            "schema_version": P2_M_ROLLING_SCHEMA_VERSION,
        }
        evidence.append(
            FinancialP2MRollingEvidence(
                **fields,
                content_hash=_hash("p2_m_rolling_evidence", fields),
            )
        )
    return tuple(evidence)


def _build_factor_evidence(
    factor_id: str,
    horizons: tuple[FinancialP2MHorizonEvidence, ...],
    rolling: tuple[FinancialP2MRollingEvidence, ...],
    configuration: FinancialP2MEnhancementConfig,
) -> FinancialP2MFactorEvidence:
    full_directions = tuple(
        _direction(item.common_result.rank_ic_mean) for item in horizons
    )
    horizon_consistency = _consistency(full_directions)
    primary = next(
        item for item in horizons if item.horizon == P2_M_PRIMARY_HORIZON
    )
    primary_direction = _direction(
        primary.common_result.rank_ic_mean
    )
    primary_windows = tuple(
        P2MDirection(item.direction)
        for item in rolling
        if item.horizon == P2_M_PRIMARY_HORIZON
    )
    rolling_consistency = _consistency(
        primary_windows,
        reference=primary_direction,
    )
    fields = {
        "factor_id": factor_id,
        "validation_track": configuration.validation_track,
        "evidence_priority": configuration.evidence_priority,
        "primary_horizon": configuration.primary_horizon,
        "horizon_evidence": horizons,
        "rolling_evidence": rolling,
        "horizon_direction_consistency":
            horizon_consistency.value,
        "primary_rolling_direction_consistency":
            rolling_consistency.value,
        "best_horizon_selection_status": P2_M_NOT_RUN,
        "neutralization_status": configuration.neutralization_status,
        "fama_macbeth_status": configuration.fama_macbeth_status,
        "oos_status": configuration.oos_status,
        "multiple_testing_status":
            configuration.multiple_testing_status,
        "schema_version": P2_M_FACTOR_SCHEMA_VERSION,
    }
    return FinancialP2MFactorEvidence(
        **fields,
        content_hash=_hash("p2_m_factor_evidence", fields),
    )


def _consistency(
    directions: tuple[P2MDirection, ...],
    *,
    reference: P2MDirection | None = None,
) -> P2MConsistency:
    if not directions or any(
        item is P2MDirection.NOT_EVALUABLE for item in directions
    ):
        return P2MConsistency.INSUFFICIENT
    if reference is not None:
        if reference in (
            P2MDirection.NOT_EVALUABLE,
            P2MDirection.ZERO,
        ):
            return P2MConsistency.INSUFFICIENT
        return (
            P2MConsistency.CONSISTENT
            if all(item is reference for item in directions)
            else P2MConsistency.MIXED
        )
    return (
        P2MConsistency.CONSISTENT
        if len(set(directions)) == 1
        and directions[0] is not P2MDirection.ZERO
        else P2MConsistency.MIXED
    )


def _direction(value: float | None) -> P2MDirection:
    if value is None:
        return P2MDirection.NOT_EVALUABLE
    if math.isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-12):
        return P2MDirection.ZERO
    return (
        P2MDirection.POSITIVE
        if value > 0
        else P2MDirection.NEGATIVE
    )


def _input_guard(
    mvp: MVPFinancialBatchResult,
    prep: FinancialPreprocessingResult,
    returns: ForwardReturnBatch,
) -> str:
    reference = mvp.observation_reference
    return _hash(
        "p2_m_input_guard",
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
        },
    )


def _blocked_result(
    errors: list[P2MIssue],
    configuration: FinancialP2MEnhancementConfig | None,
    *,
    primary_fingerprint: str | None = None,
) -> FinancialP2MEnhancementResult:
    audit = _build_audit(
        gate_status=P2MGateStatus.BLOCKED,
        errors=tuple(_deduplicate_issues(errors)),
        warnings=(),
        configuration=configuration,
        primary_fingerprint=primary_fingerprint or _hash("empty", []),
        universe_codes=(),
        factor_frame=pd.DataFrame(),
        return_frame=pd.DataFrame(),
        output_fingerprint=_hash("empty", []),
    )
    return FinancialP2MEnhancementResult(
        factor_evidence=(),
        enhancement_audit=audit,
    )


def _build_audit(
    *,
    gate_status: P2MGateStatus,
    errors: tuple[P2MIssue, ...],
    warnings: tuple[P2MIssue, ...],
    configuration: FinancialP2MEnhancementConfig | None,
    primary_fingerprint: str,
    universe_codes: tuple[str, ...],
    factor_frame: pd.DataFrame,
    return_frame: pd.DataFrame,
    output_fingerprint: str,
) -> FinancialP2MEnhancementAudit:
    fields = {
        "gate_status": gate_status.value,
        "errors": errors,
        "warnings": warnings,
        "supported_factor_ids": SUPPORTED_FACTOR_IDS,
        "horizons": (
            configuration.horizons
            if configuration is not None
            else P2_M_HORIZONS
        ),
        "primary_horizon": (
            configuration.primary_horizon
            if configuration is not None
            else P2_M_PRIMARY_HORIZON
        ),
        "universe_count": len(universe_codes),
        "configuration_fingerprint": _hash(
            "p2_m_configuration",
            (
                configuration.to_dict()
                if configuration is not None
                else {"configuration": "invalid"}
            ),
        ),
        "primary_m_evaluation_fingerprint": primary_fingerprint,
        "universe_fingerprint": _hash(
            "p2_m_universe",
            {
                "reference": (
                    configuration.universe_reference
                    if configuration is not None
                    else None
                ),
                "version": (
                    configuration.universe_version
                    if configuration is not None
                    else None
                ),
                "codes": universe_codes,
            },
        ),
        "factor_input_fingerprint": _hash(
            "p2_m_factor_inputs", _frame_records(factor_frame)
        ),
        "label_input_fingerprint": _hash(
            "p2_m_label_inputs", _frame_records(return_frame)
        ),
        "output_fingerprint": output_fingerprint,
        "schema_version": P2_M_SCHEMA_VERSION,
        "audit_schema_version": P2_M_AUDIT_SCHEMA_VERSION,
        "hash_contract_version": P2_M_HASH_CONTRACT_VERSION,
    }
    return FinancialP2MEnhancementAudit(
        **fields,
        content_hash=_hash("p2_m_audit", fields),
    )


def _error(
    code: P2MErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> P2MIssue:
    return P2MIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
    )


def _deduplicate_issues(issues: list[P2MIssue]) -> list[P2MIssue]:
    unique = {
        (item.code, item.message, item.field_name, item.record_key): item
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
    if frame.empty:
        return []
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
        if value == 0:
            return 0.0
    return value


def _hash(domain: str, value: Any) -> str:
    payload = {
        "domain": domain,
        "hash_contract_version": P2_M_HASH_CONTRACT_VERSION,
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
