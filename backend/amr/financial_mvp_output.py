"""FIN-MVP-OUTPUT: deterministic run object and research summaries."""

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

from backend.amr.evaluation_core import (
    EvaluationStatus,
    SecurityLevelEvaluationResult,
)
from backend.amr.evaluation_input_contract import ForwardReturnBatch
from backend.amr.financial_mvp_batch import (
    SUPPORTED_FACTOR_IDS,
    FinancialBatchAudit,
    MVPBatchObservationReference,
    MVPFinancialBatchResult,
)
from backend.amr.financial_mvp_m_evaluation import (
    FinancialMVPMEvaluationConfig,
    FinancialMVPMEvaluationResult,
    FinancialMVPMFactorAudit,
)
from backend.amr.financial_mvp_robustness import (
    FinancialMVPFactorRobustness,
    FinancialMVPRobustnessConfig,
    FinancialMVPRobustnessResult,
    evaluate_financial_mvp_robustness,
)
from backend.amr.financial_preprocessing import (
    FinancialPreprocessingAudit,
    FinancialPreprocessingResult,
)

FINANCIAL_RUN_SCHEMA_VERSION = "FinancialEvaluationRun-v1.0"
FACTOR_SUMMARY_SCHEMA_VERSION = "FactorEvaluationSummary-v1.0"
OUTPUT_AUDIT_SCHEMA_VERSION = "FinancialMVPOutputAudit-v1.0"
OUTPUT_HASH_CONTRACT_VERSION = "FIN-MVP-OUTPUT-HASH-v2.0"
HASH_FLOAT_DECIMAL_PLACES = 8
OUTPUT_POLICY_VERSION = "FIN-MVP-OUTPUT-POLICY-v1.0"
OUTPUT_PHASE = "phase1_mvp"
OUTPUT_VALIDATION_TRACK = "M"
OUTPUT_EVIDENCE_PRIORITY = "primary"
OUTPUT_PRODUCTION_STATUS = "not production ready"
OUTPUT_DIRECTION_SOURCE = "original_direction_only"
OUTPUT_OOS_STATUS = "not_run"

FACTOR_IDENTITIES = (
    ("ROE", "Return on Equity", "quality"),
    ("BP", "Book-to-Price", "value"),
    (
        "OCF_NP",
        "Operating Cash Flow to Net Profit",
        "earnings_quality",
    ),
)


class OutputGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class EvidenceAssessment(str, Enum):
    SUPPORTIVE = "supportive"
    MIXED = "mixed"
    UNSUPPORTIVE = "unsupportive"
    INSUFFICIENT = "insufficient"
    EXPLORATORY = "exploratory"


class OutputErrorCode(str, Enum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_MVP_BATCH_RESULT = "INVALID_MVP_BATCH_RESULT"
    INVALID_PREPROCESSING_RESULT = "INVALID_PREPROCESSING_RESULT"
    INVALID_FORWARD_RETURN_BATCH = "INVALID_FORWARD_RETURN_BATCH"
    INVALID_M_EVALUATION_RESULT = "INVALID_M_EVALUATION_RESULT"
    INVALID_ROBUSTNESS_RESULT = "INVALID_ROBUSTNESS_RESULT"
    UPSTREAM_GATE_BLOCKED = "UPSTREAM_GATE_BLOCKED"
    ROBUSTNESS_RECOMPUTATION_MISMATCH = (
        "ROBUSTNESS_RECOMPUTATION_MISMATCH"
    )
    FACTOR_COVERAGE_MISMATCH = "FACTOR_COVERAGE_MISMATCH"
    RUN_CONTENT_HASH_MISMATCH = "RUN_CONTENT_HASH_MISMATCH"
    SUMMARY_PROJECTION_FAILED = "SUMMARY_PROJECTION_FAILED"
    INPUT_MUTATED = "INPUT_MUTATED"


@dataclass(frozen=True)
class FinancialMVPOutputConfig:
    m_evaluation_configuration: FinancialMVPMEvaluationConfig
    robustness_configuration: FinancialMVPRobustnessConfig
    phase: str = OUTPUT_PHASE
    validation_track: str = OUTPUT_VALIDATION_TRACK
    evidence_priority: str = OUTPUT_EVIDENCE_PRIORITY
    production_status: str = OUTPUT_PRODUCTION_STATUS
    factor_direction_source: str = OUTPUT_DIRECTION_SOURCE
    oos_consistency: str = OUTPUT_OOS_STATUS
    run_schema_version: str = FINANCIAL_RUN_SCHEMA_VERSION
    summary_schema_version: str = FACTOR_SUMMARY_SCHEMA_VERSION
    policy_version: str = OUTPUT_POLICY_VERSION
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
        if not isinstance(
            self.robustness_configuration,
            FinancialMVPRobustnessConfig,
        ):
            raise TypeError(
                "robustness_configuration must be "
                "FinancialMVPRobustnessConfig"
            )
        if (
            self.robustness_configuration.m_evaluation_configuration
            != self.m_evaluation_configuration
        ):
            raise ValueError(
                "robustness configuration must bind the same M "
                "evaluation configuration"
            )
        frozen = {
            "phase": (self.phase, OUTPUT_PHASE),
            "validation_track": (
                self.validation_track,
                OUTPUT_VALIDATION_TRACK,
            ),
            "evidence_priority": (
                self.evidence_priority,
                OUTPUT_EVIDENCE_PRIORITY,
            ),
            "production_status": (
                self.production_status,
                OUTPUT_PRODUCTION_STATUS,
            ),
            "factor_direction_source": (
                self.factor_direction_source,
                OUTPUT_DIRECTION_SOURCE,
            ),
            "oos_consistency": (
                self.oos_consistency,
                OUTPUT_OOS_STATUS,
            ),
            "run_schema_version": (
                self.run_schema_version,
                FINANCIAL_RUN_SCHEMA_VERSION,
            ),
            "summary_schema_version": (
                self.summary_schema_version,
                FACTOR_SUMMARY_SCHEMA_VERSION,
            ),
            "policy_version": (
                self.policy_version,
                OUTPUT_POLICY_VERSION,
            ),
            "synthetic_test_only": (self.synthetic_test_only, True),
        }
        for field_name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{field_name} must be frozen at {expected}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "m_evaluation_configuration":
                self.m_evaluation_configuration.to_dict(),
            "robustness_configuration":
                self.robustness_configuration.to_dict(),
            "phase": self.phase,
            "validation_track": self.validation_track,
            "evidence_priority": self.evidence_priority,
            "production_status": self.production_status,
            "factor_direction_source": self.factor_direction_source,
            "oos_consistency": self.oos_consistency,
            "run_schema_version": self.run_schema_version,
            "summary_schema_version": self.summary_schema_version,
            "policy_version": self.policy_version,
            "synthetic_test_only": self.synthetic_test_only,
        }


@dataclass(frozen=True)
class OutputIssue:
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
class FinancialCoverageReport:
    factor_id: str
    universe_count: int | None
    valid_factor_count: int
    paired_count: int
    effective_evaluation_dates: int
    factor_coverage_rate: float | None
    paired_coverage_rate: float | None
    label_to_factor_alignment_rate: float
    universe_denominator_status: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "universe_count": self.universe_count,
            "valid_factor_count": self.valid_factor_count,
            "paired_count": self.paired_count,
            "effective_evaluation_dates":
                self.effective_evaluation_dates,
            "factor_coverage_rate": self.factor_coverage_rate,
            "paired_coverage_rate": self.paired_coverage_rate,
            "label_to_factor_alignment_rate":
                self.label_to_factor_alignment_rate,
            "universe_denominator_status":
                self.universe_denominator_status,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialRunGateResult:
    overall_status: str
    errors: tuple[OutputIssue, ...]
    warnings: tuple[OutputIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
        }


@dataclass(frozen=True)
class FinancialEvidenceAssessment:
    factor_id: str
    assessment: str
    rationale_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "assessment": self.assessment,
            "rationale_codes": list(self.rationale_codes),
        }


@dataclass(frozen=True)
class FinancialEvaluationRun:
    run_schema_version: str
    run_id: str
    phase: str
    validation_track: str
    evidence_priority: str
    evaluation_period: tuple[str, str]
    evaluation_frequency: str
    return_horizon: str
    supported_factor_ids: tuple[str, ...]
    common_evaluation_results: tuple[
        SecurityLevelEvaluationResult, ...
    ]
    alignment_reports: tuple[FinancialMVPMFactorAudit, ...]
    gate_result: FinancialRunGateResult
    timing_audit: tuple[str, ...]
    provenance_audit: FinancialBatchAudit
    coverage_reports: tuple[FinancialCoverageReport, ...]
    preprocessing_audit: FinancialPreprocessingAudit
    financial_evidence: tuple[FinancialMVPFactorRobustness, ...]
    evidence_assessments: tuple[FinancialEvidenceAssessment, ...]
    financial_config_snapshot: FinancialMVPOutputConfig
    observation_lineage_reference: MVPBatchObservationReference
    input_fingerprints: tuple[tuple[str, str], ...]
    synthetic_test_only: bool
    content_hash: str

    def get_common_result(
        self, factor_id: Any
    ) -> SecurityLevelEvaluationResult:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item for item in self.common_evaluation_results
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one common result for {normalized}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def get_robustness(
        self, factor_id: Any
    ) -> FinancialMVPFactorRobustness:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item for item in self.financial_evidence
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one robustness result for {normalized}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def get_coverage(self, factor_id: Any) -> FinancialCoverageReport:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item for item in self.coverage_reports
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one coverage report for {normalized}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def get_assessment(
        self, factor_id: Any
    ) -> FinancialEvidenceAssessment:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item for item in self.evidence_assessments
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one evidence assessment for {normalized}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def to_dict(
        self, *, include_content_hash: bool = True
    ) -> dict[str, Any]:
        payload = {
            "run_schema_version": self.run_schema_version,
            "run_id": self.run_id,
            "phase": self.phase,
            "validation_track": self.validation_track,
            "evidence_priority": self.evidence_priority,
            "evaluation_period": {
                "start": self.evaluation_period[0],
                "end": self.evaluation_period[1],
            },
            "evaluation_frequency": self.evaluation_frequency,
            "return_horizon": self.return_horizon,
            "supported_factor_ids": list(self.supported_factor_ids),
            "common_evaluation_results": [
                item.to_dict()
                for item in self.common_evaluation_results
            ],
            "alignment_reports": [
                item.to_dict() for item in self.alignment_reports
            ],
            "gate_result": self.gate_result.to_dict(),
            "timing_audit": list(self.timing_audit),
            "provenance_audit": self.provenance_audit.to_dict(),
            "coverage_reports": [
                item.to_dict() for item in self.coverage_reports
            ],
            "preprocessing_audit":
                self.preprocessing_audit.to_dict(),
            "financial_evidence": [
                item.to_dict() for item in self.financial_evidence
            ],
            "evidence_assessments": [
                item.to_dict() for item in self.evidence_assessments
            ],
            "financial_config_snapshot":
                self.financial_config_snapshot.to_dict(),
            "observation_lineage_reference":
                self.observation_lineage_reference.to_dict(),
            "input_fingerprints": dict(self.input_fingerprints),
            "synthetic_test_only": self.synthetic_test_only,
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class FactorSampleSummary:
    universe_count: int | None
    valid_factor_count: int
    paired_count: int
    effective_evaluation_dates: int
    factor_coverage_rate: float | None
    paired_coverage_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe_count": self.universe_count,
            "valid_factor_count": self.valid_factor_count,
            "paired_count": self.paired_count,
            "effective_evaluation_dates":
                self.effective_evaluation_dates,
            "factor_coverage_rate": self.factor_coverage_rate,
            "paired_coverage_rate": self.paired_coverage_rate,
        }


@dataclass(frozen=True)
class FactorPrimaryStatistics:
    pearson_ic_mean: float | None
    rank_ic_mean: float | None
    rank_ic_ir: float | None
    rank_ic_t_stat: float | None
    long_short_mean: float | None
    monotonicity_spearman: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pearson_ic_mean": self.pearson_ic_mean,
            "rank_ic_mean": self.rank_ic_mean,
            "rank_ic_ir": self.rank_ic_ir,
            "rank_ic_t_stat": self.rank_ic_t_stat,
            "long_short_mean": self.long_short_mean,
            "monotonicity_spearman":
                self.monotonicity_spearman,
        }


@dataclass(frozen=True)
class FactorRobustnessSummary:
    preprocessing_consistency: str
    subperiod_direction_consistency: str
    oos_consistency: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "preprocessing_consistency":
                self.preprocessing_consistency,
            "subperiod_direction_consistency":
                self.subperiod_direction_consistency,
            "oos_consistency": self.oos_consistency,
        }


@dataclass(frozen=True)
class FactorStatusSummary:
    calculation_status: str
    gate_status: str
    evidence_assessment: str
    production_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "calculation_status": self.calculation_status,
            "gate_status": self.gate_status,
            "evidence_assessment": self.evidence_assessment,
            "production_status": self.production_status,
        }


@dataclass(frozen=True)
class FactorEvaluationSummary:
    summary_schema_version: str
    run_id: str
    factor_id: str
    factor_name: str
    factor_category: str
    validation_track: str
    evidence_priority: str
    evaluation_period: tuple[str, str]
    evaluation_frequency: str
    return_horizon: str
    factor_direction_source: str
    sample_summary: FactorSampleSummary
    primary_statistics: FactorPrimaryStatistics
    robustness_summary: FactorRobustnessSummary
    status_summary: FactorStatusSummary
    key_findings: tuple[str, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    source_run_content_hash: str
    content_hash: str

    def to_dict(
        self, *, include_content_hash: bool = True
    ) -> dict[str, Any]:
        payload = {
            "summary_schema_version": self.summary_schema_version,
            "run_id": self.run_id,
            "factor_id": self.factor_id,
            "factor_name": self.factor_name,
            "factor_category": self.factor_category,
            "validation_track": self.validation_track,
            "evidence_priority": self.evidence_priority,
            "evaluation_period": {
                "start": self.evaluation_period[0],
                "end": self.evaluation_period[1],
            },
            "evaluation_frequency": self.evaluation_frequency,
            "return_horizon": self.return_horizon,
            "factor_direction_source":
                self.factor_direction_source,
            "sample_summary": self.sample_summary.to_dict(),
            "primary_statistics": self.primary_statistics.to_dict(),
            "robustness_summary": self.robustness_summary.to_dict(),
            "status_summary": self.status_summary.to_dict(),
            "key_findings": list(self.key_findings),
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
            "source_run_content_hash": self.source_run_content_hash,
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class FinancialMVPOutputAudit:
    gate_status: str
    errors: tuple[OutputIssue, ...]
    configuration_fingerprint: str
    upstream_fingerprint: str
    run_content_hash: str
    summaries_fingerprint: str
    schema_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_status": self.gate_status,
            "errors": [item.to_dict() for item in self.errors],
            "configuration_fingerprint":
                self.configuration_fingerprint,
            "upstream_fingerprint": self.upstream_fingerprint,
            "run_content_hash": self.run_content_hash,
            "summaries_fingerprint": self.summaries_fingerprint,
            "schema_version": self.schema_version,
            "hash_contract_version": self.hash_contract_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialMVPOutputResult:
    financial_evaluation_run: FinancialEvaluationRun | None
    factor_evaluation_summaries: tuple[FactorEvaluationSummary, ...]
    output_audit: FinancialMVPOutputAudit

    def get_summary(self, factor_id: Any) -> FactorEvaluationSummary:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item for item in self.factor_evaluation_summaries
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one summary for {normalized}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "financial_evaluation_run": (
                self.financial_evaluation_run.to_dict()
                if self.financial_evaluation_run is not None
                else None
            ),
            "factor_evaluation_summaries": [
                item.to_dict()
                for item in self.factor_evaluation_summaries
            ],
            "output_audit": self.output_audit.to_dict(),
        }


def build_financial_mvp_output(
    mvp_batch_result: MVPFinancialBatchResult,
    preprocessing_result: FinancialPreprocessingResult,
    forward_returns: ForwardReturnBatch,
    m_evaluation_result: FinancialMVPMEvaluationResult,
    robustness_result: FinancialMVPRobustnessResult,
    *,
    configuration: FinancialMVPOutputConfig,
) -> FinancialMVPOutputResult:
    """Build one deterministic engineering run and projected summaries."""

    errors = _validate_inputs(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        m_evaluation_result,
        robustness_result,
        configuration,
    )
    if errors:
        return _blocked_output(tuple(errors), configuration)
    input_before = _input_guard(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        m_evaluation_result,
        robustness_result,
        configuration,
    )
    recomputed = evaluate_financial_mvp_robustness(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        m_evaluation_result,
        configuration=configuration.robustness_configuration,
    )
    if (
        recomputed.robustness_audit.gate_status
        != OutputGateStatus.READY.value
        or recomputed.robustness_audit.output_fingerprint
        != robustness_result.robustness_audit.output_fingerprint
    ):
        errors.append(
            _error(
                OutputErrorCode.ROBUSTNESS_RECOMPUTATION_MISMATCH,
                "provided robustness result must exactly match "
                "recomputation",
                "robustness_result",
            )
        )
        return _blocked_output(tuple(errors), configuration)

    run = _build_run(
        mvp_batch_result,
        preprocessing_result,
        m_evaluation_result,
        robustness_result,
        configuration,
    )
    try:
        summaries = project_factor_evaluation_summaries(run)
    except (TypeError, ValueError, LookupError) as exc:
        errors.append(
            _error(
                OutputErrorCode.SUMMARY_PROJECTION_FAILED,
                str(exc),
                "financial_evaluation_run",
            )
        )
        return _blocked_output(tuple(errors), configuration)
    input_after = _input_guard(
        mvp_batch_result,
        preprocessing_result,
        forward_returns,
        m_evaluation_result,
        robustness_result,
        configuration,
    )
    if input_before != input_after:
        errors.append(
            _error(
                OutputErrorCode.INPUT_MUTATED,
                "one or more output inputs changed during construction",
                "inputs",
            )
        )
        return _blocked_output(tuple(errors), configuration)

    summaries_fingerprint = _hash(
        "factor_evaluation_summaries",
        [item.to_dict() for item in summaries],
    )
    audit = _build_output_audit(
        OutputGateStatus.READY,
        (),
        configuration,
        input_before,
        run.content_hash,
        summaries_fingerprint,
    )
    return FinancialMVPOutputResult(
        financial_evaluation_run=run,
        factor_evaluation_summaries=summaries,
        output_audit=audit,
    )


def project_factor_evaluation_summaries(
    run: FinancialEvaluationRun,
) -> tuple[FactorEvaluationSummary, ...]:
    """Project research summaries from a verified run without recalculation."""

    if not isinstance(run, FinancialEvaluationRun):
        raise TypeError("run must be FinancialEvaluationRun")
    if recompute_financial_evaluation_run_content_hash(run) != run.content_hash:
        raise ValueError("FinancialEvaluationRun content hash mismatch")
    identities = {
        factor_id: (name, category)
        for factor_id, name, category in FACTOR_IDENTITIES
    }
    summaries = []
    for factor_id in SUPPORTED_FACTOR_IDS:
        common = run.get_common_result(factor_id)
        robustness = run.get_robustness(factor_id)
        coverage = run.get_coverage(factor_id)
        assessment = run.get_assessment(factor_id)
        name, category = identities[factor_id]
        warnings = ["UNIVERSE_DENOMINATOR_UNAVAILABLE"]
        if (
            robustness.preprocessing_consistency
            not in ("consistent",)
        ):
            warnings.append("PREPROCESSING_DIRECTION_NOT_CONSISTENT")
        if (
            robustness.subperiod_direction_consistency
            not in ("consistent",)
        ):
            warnings.append("SUBPERIOD_DIRECTION_NOT_CONSISTENT")
        if robustness.constant_degradation_detected:
            warnings.append("CONSTANT_DEGRADATION_DETECTED")
        if common.overall_status is not EvaluationStatus.COMPLETED:
            warnings.append("CALCULATION_NOT_COMPLETED")
        limitations = (
            "synthetic_test_only",
            "phase1_mvp_only",
            "universe_denominator_unavailable",
            "oos_not_run",
            "multiple_testing_not_run",
            "no_admission_decision",
        )
        fields = {
            "summary_schema_version": FACTOR_SUMMARY_SCHEMA_VERSION,
            "run_id": run.run_id,
            "factor_id": factor_id,
            "factor_name": name,
            "factor_category": category,
            "validation_track": run.validation_track,
            "evidence_priority": run.evidence_priority,
            "evaluation_period": run.evaluation_period,
            "evaluation_frequency": run.evaluation_frequency,
            "return_horizon": run.return_horizon,
            "factor_direction_source": OUTPUT_DIRECTION_SOURCE,
            "sample_summary": FactorSampleSummary(
                universe_count=coverage.universe_count,
                valid_factor_count=coverage.valid_factor_count,
                paired_count=coverage.paired_count,
                effective_evaluation_dates=(
                    coverage.effective_evaluation_dates
                ),
                factor_coverage_rate=coverage.factor_coverage_rate,
                paired_coverage_rate=coverage.paired_coverage_rate,
            ),
            "primary_statistics": FactorPrimaryStatistics(
                pearson_ic_mean=common.pearson_ic_mean,
                rank_ic_mean=common.rank_ic_mean,
                rank_ic_ir=common.rank_ic_ir,
                rank_ic_t_stat=common.rank_ic_t_stat,
                long_short_mean=common.long_short_mean,
                monotonicity_spearman=(
                    common.monotonicity_spearman
                ),
            ),
            "robustness_summary": FactorRobustnessSummary(
                preprocessing_consistency=(
                    robustness.preprocessing_consistency
                ),
                subperiod_direction_consistency=(
                    robustness.subperiod_direction_consistency
                ),
                oos_consistency=OUTPUT_OOS_STATUS,
            ),
            "status_summary": FactorStatusSummary(
                calculation_status=common.overall_status.value,
                gate_status=run.gate_result.overall_status,
                evidence_assessment=assessment.assessment,
                production_status=OUTPUT_PRODUCTION_STATUS,
            ),
            "key_findings": (
                f"rank_ic_mean={_display_number(common.rank_ic_mean)}",
                f"long_short_mean={_display_number(common.long_short_mean)}",
                (
                    "preprocessing_consistency="
                    f"{robustness.preprocessing_consistency}"
                ),
                (
                    "subperiod_direction_consistency="
                    f"{robustness.subperiod_direction_consistency}"
                ),
            ),
            "warnings": tuple(sorted(set(warnings))),
            "limitations": limitations,
            "source_run_content_hash": run.content_hash,
        }
        summaries.append(
            FactorEvaluationSummary(
                **fields,
                content_hash=_hash("factor_evaluation_summary", fields),
            )
        )
    return tuple(summaries)


def recompute_financial_evaluation_run_content_hash(
    run: FinancialEvaluationRun,
) -> str:
    if not isinstance(run, FinancialEvaluationRun):
        raise TypeError("run must be FinancialEvaluationRun")
    return _hash(
        "financial_evaluation_run",
        run.to_dict(include_content_hash=False),
    )


def _build_run(
    mvp: MVPFinancialBatchResult,
    prep: FinancialPreprocessingResult,
    m_result: FinancialMVPMEvaluationResult,
    robustness: FinancialMVPRobustnessResult,
    configuration: FinancialMVPOutputConfig,
) -> FinancialEvaluationRun:
    reference = mvp.observation_reference
    assert reference is not None
    coverage_reports = tuple(
        _build_coverage_report(
            factor_id,
            robustness.get_factor(factor_id),
        )
        for factor_id in SUPPORTED_FACTOR_IDS
    )
    assessments = tuple(
        _build_evidence_assessment(
            factor_id,
            m_result.get_result(factor_id),
        )
        for factor_id in SUPPORTED_FACTOR_IDS
    )
    gate_warnings = (
        OutputIssue(
            code="UNIVERSE_DENOMINATOR_UNAVAILABLE",
            message=(
                "MVP inputs do not expose a separate PIT universe "
                "denominator; coverage rates remain null"
            ),
            field_name="universe_count",
        ),
    )
    base_fields = {
        "run_schema_version": FINANCIAL_RUN_SCHEMA_VERSION,
        "phase": OUTPUT_PHASE,
        "validation_track": OUTPUT_VALIDATION_TRACK,
        "evidence_priority": OUTPUT_EVIDENCE_PRIORITY,
        "evaluation_period": (
            configuration.m_evaluation_configuration.evaluation_dates[0],
            configuration.m_evaluation_configuration.evaluation_dates[-1],
        ),
        "evaluation_frequency": (
            configuration.m_evaluation_configuration.evaluation_frequency
        ),
        "return_horizon": str(
            configuration.m_evaluation_configuration.return_horizon
        ),
        "supported_factor_ids": SUPPORTED_FACTOR_IDS,
        "common_evaluation_results": m_result.common_results,
        "alignment_reports": m_result.factor_audits,
        "gate_result": FinancialRunGateResult(
            overall_status=OutputGateStatus.READY.value,
            errors=(),
            warnings=gate_warnings,
        ),
        "timing_audit":
            mvp.financial_batch_audit.timing_references,
        "provenance_audit": mvp.financial_batch_audit,
        "coverage_reports": coverage_reports,
        "preprocessing_audit": prep.preprocessing_audit,
        "financial_evidence": robustness.factor_summaries,
        "evidence_assessments": assessments,
        "financial_config_snapshot": configuration,
        "observation_lineage_reference": reference,
        "input_fingerprints": tuple(
            sorted(
                {
                    "mvp_batch":
                        m_result.evaluation_audit.mvp_batch_fingerprint,
                    "preprocessing": (
                        m_result.evaluation_audit
                        .preprocessing_fingerprint
                    ),
                    "return_input": (
                        m_result.evaluation_audit
                        .return_input_fingerprint
                    ),
                    "m_evaluation_output": (
                        m_result.evaluation_audit.output_fingerprint
                    ),
                    "robustness_output": (
                        robustness.robustness_audit.output_fingerprint
                    ),
                }.items()
            )
        ),
        "synthetic_test_only": True,
    }
    run_seed = _hash("financial_evaluation_run_id", base_fields)
    run_id = f"fin-mvp-output-{run_seed[:24]}"
    run_without_hash = FinancialEvaluationRun(
        run_id=run_id,
        content_hash="",
        **base_fields,
    )
    return FinancialEvaluationRun(
        run_id=run_id,
        content_hash=recompute_financial_evaluation_run_content_hash(
            run_without_hash
        ),
        **base_fields,
    )


def _build_coverage_report(
    factor_id: str,
    robustness: FinancialMVPFactorRobustness,
) -> FinancialCoverageReport:
    cell = robustness.get_cell("evaluation_factor_value", "full")
    fields = {
        "factor_id": factor_id,
        "universe_count": None,
        "valid_factor_count": cell.factor_sample_count,
        "paired_count": cell.label_available_count,
        "effective_evaluation_dates": cell.effective_date_count,
        "factor_coverage_rate": None,
        "paired_coverage_rate": None,
        "label_to_factor_alignment_rate":
            cell.paired_coverage_rate,
        "universe_denominator_status": "not_available",
    }
    return FinancialCoverageReport(
        **fields,
        content_hash=_hash("financial_coverage_report", fields),
    )


def _build_evidence_assessment(
    factor_id: str,
    common: SecurityLevelEvaluationResult,
) -> FinancialEvidenceAssessment:
    if common.overall_status in (
        EvaluationStatus.COMPLETED,
        EvaluationStatus.PARTIAL,
    ):
        assessment = EvidenceAssessment.EXPLORATORY
        rationale = (
            "SYNTHETIC_MVP_RESEARCH_ONLY",
            "NO_ADMISSION_DECISION",
        )
    else:
        assessment = EvidenceAssessment.INSUFFICIENT
        rationale = (
            "INSUFFICIENT_EFFECTIVE_EVALUATION_PERIODS",
            "SYNTHETIC_MVP_RESEARCH_ONLY",
        )
    return FinancialEvidenceAssessment(
        factor_id=factor_id,
        assessment=assessment.value,
        rationale_codes=rationale,
    )


def _validate_inputs(
    mvp: Any,
    prep: Any,
    returns: Any,
    m_result: Any,
    robustness: Any,
    configuration: Any,
) -> list[OutputIssue]:
    errors = []
    if not isinstance(configuration, FinancialMVPOutputConfig):
        errors.append(
            _error(
                OutputErrorCode.INVALID_CONFIGURATION,
                "configuration must be FinancialMVPOutputConfig",
                "configuration",
            )
        )
        return errors
    checks = (
        (
            mvp,
            MVPFinancialBatchResult,
            OutputErrorCode.INVALID_MVP_BATCH_RESULT,
            "mvp_batch_result",
        ),
        (
            prep,
            FinancialPreprocessingResult,
            OutputErrorCode.INVALID_PREPROCESSING_RESULT,
            "preprocessing_result",
        ),
        (
            returns,
            ForwardReturnBatch,
            OutputErrorCode.INVALID_FORWARD_RETURN_BATCH,
            "forward_returns",
        ),
        (
            m_result,
            FinancialMVPMEvaluationResult,
            OutputErrorCode.INVALID_M_EVALUATION_RESULT,
            "m_evaluation_result",
        ),
        (
            robustness,
            FinancialMVPRobustnessResult,
            OutputErrorCode.INVALID_ROBUSTNESS_RESULT,
            "robustness_result",
        ),
    )
    for value, expected_type, code, field_name in checks:
        if not isinstance(value, expected_type):
            errors.append(
                _error(
                    code,
                    f"{field_name} must be {expected_type.__name__}",
                    field_name,
                )
            )
    if errors:
        return errors
    gate_values = (
        mvp.financial_batch_audit.gate_status,
        prep.preprocessing_audit.gate_status,
        m_result.evaluation_audit.gate_status,
        robustness.robustness_audit.gate_status,
    )
    if any(value != OutputGateStatus.READY.value for value in gate_values):
        errors.append(
            _error(
                OutputErrorCode.UPSTREAM_GATE_BLOCKED,
                "all predecessor gates must be ready",
                "gate_status",
            )
        )
    factor_sets = (
        tuple(item.factor_id for item in m_result.common_results),
        tuple(item.factor_id for item in m_result.factor_audits),
        tuple(
            item.factor_id for item in robustness.factor_summaries
        ),
    )
    if any(value != SUPPORTED_FACTOR_IDS for value in factor_sets):
        errors.append(
            _error(
                OutputErrorCode.FACTOR_COVERAGE_MISMATCH,
                "all outputs must cover exactly ROE, BP, and OCF_NP",
                "factor_id",
            )
        )
    if mvp.observation_reference is None:
        errors.append(
            _error(
                OutputErrorCode.FACTOR_COVERAGE_MISMATCH,
                "observation lineage reference is required",
                "observation_reference",
            )
        )
    return errors


def _input_guard(
    mvp: MVPFinancialBatchResult,
    prep: FinancialPreprocessingResult,
    returns: ForwardReturnBatch,
    m_result: FinancialMVPMEvaluationResult,
    robustness: FinancialMVPRobustnessResult,
    configuration: FinancialMVPOutputConfig,
) -> str:
    reference = mvp.observation_reference
    return _hash(
        "financial_mvp_output_input_guard",
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
            "m_evaluation": m_result.to_dict(),
            "robustness": robustness.to_dict(),
            "configuration": configuration.to_dict(),
        },
    )


def _blocked_output(
    errors: tuple[OutputIssue, ...],
    configuration: FinancialMVPOutputConfig | None,
) -> FinancialMVPOutputResult:
    empty = _hash("empty", [])
    audit = _build_output_audit(
        OutputGateStatus.BLOCKED,
        tuple(_deduplicate_issues(errors)),
        configuration,
        empty,
        empty,
        empty,
    )
    return FinancialMVPOutputResult(
        financial_evaluation_run=None,
        factor_evaluation_summaries=(),
        output_audit=audit,
    )


def _build_output_audit(
    status: OutputGateStatus,
    errors: tuple[OutputIssue, ...],
    configuration: FinancialMVPOutputConfig | None,
    upstream_fingerprint: str,
    run_content_hash: str,
    summaries_fingerprint: str,
) -> FinancialMVPOutputAudit:
    fields = {
        "gate_status": status.value,
        "errors": errors,
        "configuration_fingerprint": _hash(
            "financial_mvp_output_configuration",
            (
                configuration.to_dict()
                if configuration is not None
                else {"configuration": "invalid"}
            ),
        ),
        "upstream_fingerprint": upstream_fingerprint,
        "run_content_hash": run_content_hash,
        "summaries_fingerprint": summaries_fingerprint,
        "schema_version": OUTPUT_AUDIT_SCHEMA_VERSION,
        "hash_contract_version": OUTPUT_HASH_CONTRACT_VERSION,
    }
    return FinancialMVPOutputAudit(
        **fields,
        content_hash=_hash("financial_mvp_output_audit", fields),
    )


def _error(
    code: OutputErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> OutputIssue:
    return OutputIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
    )


def _deduplicate_issues(
    issues: list[OutputIssue] | tuple[OutputIssue, ...],
) -> list[OutputIssue]:
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


def _display_number(value: float | None) -> str:
    return "not_run" if value is None else repr(float(value))


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
            raise ValueError("non-finite value cannot enter output hash")
        value = round(value, HASH_FLOAT_DECIMAL_PLACES)
        if value == 0:
            return 0.0
    return value


def _hash(domain: str, value: Any) -> str:
    payload = {
        "domain": domain,
        "hash_contract_version": OUTPUT_HASH_CONTRACT_VERSION,
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
