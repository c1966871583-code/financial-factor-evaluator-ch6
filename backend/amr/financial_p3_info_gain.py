"""FIN-25 information-gain comparison on frozen FIN-24 common samples.

This module consumes accepted combination experiments and independently
recomputed member baselines.  It does not rebuild combinations, samples, or
M/F/R evaluator outputs.  The currently frozen evidence supports M:20D only;
all unavailable contexts remain explicit and prevent a positive production
or admission conclusion.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from backend.amr.financial_p3_combinations import FinancialP3CombinationsResult
from backend.amr.financial_p3_common_sample import CommonSampleMetrics
from backend.amr.financial_p3_common_sample_member_baselines import (
    CommonSampleMemberBaselineResult,
    ComboMemberBaselineBundle,
)
from backend.amr.financial_p3_info_gain_contract import (
    BaselineKind,
    INFO_GAIN_COMBO_ORDER,
    INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT,
    INFO_GAIN_PRODUCTION_STATUS,
    INFO_GAIN_ZERO_DENOMINATOR_EPSILON,
    InfoGainAssessment,
    InfoGainEvaluationConfig,
    MetricBetterDirection,
)


INFO_GAIN_RESULT_SCHEMA_VERSION = "FinancialP3InfoGainResult-v1.0"
INFO_GAIN_AUDIT_SCHEMA_VERSION = "FinancialP3InfoGainAudit-v1.0"
INFO_GAIN_POLICY_VERSION = "FIN-P3-INFO-GAIN-EVALUATION-POLICY-v1.0"
INFO_GAIN_HASH_CONTRACT_VERSION = "FIN-P3-INFO-GAIN-EVALUATION-HASH-v1.0"
INFO_GAIN_RESEARCH_SCOPE = "synthetic_common_sample_M20_only"
INFO_GAIN_CONCLUSION_BOUNDARY = (
    "FIN-25 deterministic comparison on accepted synthetic M:20D evidence. "
    "Missing M:5D/M:60D, F, R, OOS, concentration, multiple-testing, and "
    "production data gates remain explicit; no admission, production, "
    "empirical-return, fraud, or trading conclusion is authorized."
)

_METRIC_ATTRIBUTE = {
    "rank_ic_mean": "mean_rank_ic",
    "rank_ic_ir": "icir",
    "rank_ic_positive_ratio": "positive_ic_ratio",
    "quantile_returns": "group_returns",
    "long_short_mean": "long_short_spread",
    "monotonicity_spearman": "monotonicity",
    "fm_mean_r2": "fm_mean_r2",
}


@dataclass(frozen=True)
class InfoGainIssue:
    code: str
    message: str
    combo_id: str | None = None
    field_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "combo_id": self.combo_id,
            "field_name": self.field_name,
        }


@dataclass(frozen=True)
class FinancialP3InfoGainRunConfig:
    run_id: str
    contract: InfoGainEvaluationConfig
    combination_output_fingerprint: str = INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT
    research_scope: str = INFO_GAIN_RESEARCH_SCOPE
    production_status: str = INFO_GAIN_PRODUCTION_STATUS
    dynamic_weighting_allowed: bool = False
    best_horizon_selection_allowed: bool = False
    cross_track_composite_allowed: bool = False
    policy_version: str = INFO_GAIN_POLICY_VERSION
    schema_version: str = INFO_GAIN_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _required_text(self.run_id, "run_id")
        if not isinstance(self.contract, InfoGainEvaluationConfig):
            raise TypeError("contract must be InfoGainEvaluationConfig")
        frozen = {
            "combination_output_fingerprint": (
                self.combination_output_fingerprint,
                INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT,
            ),
            "research_scope": (self.research_scope, INFO_GAIN_RESEARCH_SCOPE),
            "production_status": (
                self.production_status,
                INFO_GAIN_PRODUCTION_STATUS,
            ),
            "dynamic_weighting_allowed": (self.dynamic_weighting_allowed, False),
            "best_horizon_selection_allowed": (
                self.best_horizon_selection_allowed,
                False,
            ),
            "cross_track_composite_allowed": (
                self.cross_track_composite_allowed,
                False,
            ),
            "policy_version": (self.policy_version, INFO_GAIN_POLICY_VERSION),
            "schema_version": (self.schema_version, INFO_GAIN_RESULT_SCHEMA_VERSION),
        }
        for field_name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{field_name} must be frozen at {expected!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "contract_hash": self.contract.content_hash,
            "combination_output_fingerprint": self.combination_output_fingerprint,
            "research_scope": self.research_scope,
            "production_status": self.production_status,
            "dynamic_weighting_allowed": self.dynamic_weighting_allowed,
            "best_horizon_selection_allowed": self.best_horizon_selection_allowed,
            "cross_track_composite_allowed": self.cross_track_composite_allowed,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class InfoGainMetricComparison:
    track_id: str
    evaluation_context: str
    metric_id: str
    baseline_kind: str
    baseline_factor_id: str | None
    combo_metric_value: Any
    baseline_metric_value: Any
    absolute_increment: float | None
    relative_increment: float | None
    calculation_status: str
    directional_outcome: str
    reason_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "evaluation_context": self.evaluation_context,
            "metric_id": self.metric_id,
            "baseline_kind": self.baseline_kind,
            "baseline_factor_id": self.baseline_factor_id,
            "combo_metric_value": self.combo_metric_value,
            "baseline_metric_value": self.baseline_metric_value,
            "absolute_increment": self.absolute_increment,
            "relative_increment": self.relative_increment,
            "calculation_status": self.calculation_status,
            "directional_outcome": self.directional_outcome,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class CoverageTradeoffReport:
    eligible_sample_count: int
    member_original_evaluable_sample_counts: tuple[tuple[str, int], ...]
    member_original_coverage_ratios: tuple[tuple[str, float], ...]
    combo_common_sample_count: int
    combo_common_sample_coverage_ratio: float
    absolute_coverage_loss: int
    relative_coverage_loss: float
    per_period_common_sample_counts: tuple[tuple[str, int], ...]
    per_period_coverage_ratio_status: str
    valid_period_loss: int
    insufficient_sample_periods: int
    exclusion_reason_categories: tuple[str, ...]
    industry_distribution_change_status: str
    size_distribution_change_status: str
    acceptance_threshold_status: str
    automatic_rejection_applied: bool
    report_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible_sample_count": self.eligible_sample_count,
            "member_original_evaluable_sample_counts": dict(
                self.member_original_evaluable_sample_counts
            ),
            "member_original_coverage_ratios": dict(
                self.member_original_coverage_ratios
            ),
            "combo_common_sample_count": self.combo_common_sample_count,
            "combo_common_sample_coverage_ratio": (
                self.combo_common_sample_coverage_ratio
            ),
            "absolute_coverage_loss": self.absolute_coverage_loss,
            "relative_coverage_loss": self.relative_coverage_loss,
            "per_period_common_sample_counts": [
                {"evaluation_date": date, "count": count}
                for date, count in self.per_period_common_sample_counts
            ],
            "per_period_coverage_ratio_status": (
                self.per_period_coverage_ratio_status
            ),
            "valid_period_loss": self.valid_period_loss,
            "insufficient_sample_periods": self.insufficient_sample_periods,
            "exclusion_reason_categories": list(self.exclusion_reason_categories),
            "industry_distribution_change_status": (
                self.industry_distribution_change_status
            ),
            "size_distribution_change_status": self.size_distribution_change_status,
            "acceptance_threshold_status": self.acceptance_threshold_status,
            "automatic_rejection_applied": self.automatic_rejection_applied,
            "report_status": self.report_status,
        }


@dataclass(frozen=True)
class ComboInfoGainResult:
    combo_id: str
    combo_definition_version: str
    common_sample_fingerprint: str
    strongest_m20_member_factor_id: str
    metric_comparisons: tuple[InfoGainMetricComparison, ...]
    coverage_tradeoff: CoverageTradeoffReport
    m_track_assessment: str
    f_track_assessment: str
    r_track_assessment: str
    information_gain_assessment: str
    core_criteria: tuple[tuple[str, str], ...]
    multiple_testing_status: str
    production_status: str
    limitations: tuple[str, ...]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "combo_id": self.combo_id,
            "combo_definition_version": self.combo_definition_version,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "strongest_m20_member_factor_id": self.strongest_m20_member_factor_id,
            "metric_comparisons": [item.to_dict() for item in self.metric_comparisons],
            "coverage_tradeoff": self.coverage_tradeoff.to_dict(),
            "m_track_assessment": self.m_track_assessment,
            "f_track_assessment": self.f_track_assessment,
            "r_track_assessment": self.r_track_assessment,
            "information_gain_assessment": self.information_gain_assessment,
            "core_criteria": dict(self.core_criteria),
            "multiple_testing_status": self.multiple_testing_status,
            "production_status": self.production_status,
            "limitations": list(self.limitations),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP3InfoGainAudit:
    gate_status: str
    errors: tuple[InfoGainIssue, ...]
    warnings: tuple[InfoGainIssue, ...]
    combo_count: int
    accepted_combination_input: bool
    accepted_member_baseline_input: bool
    same_sample_enforced: bool
    contract_hash: str
    combination_output_fingerprint: str
    member_baseline_output_fingerprint: str
    input_fingerprint: str
    output_fingerprint: str
    information_gain_assessment: str
    research_scope: str
    admission_status: str
    production_status: str
    production_gates: tuple[tuple[str, str], ...]
    dynamic_weighting_performed: bool
    best_horizon_selected: bool
    cross_track_composite_calculated: bool
    conclusion_boundary: str
    schema_version: str
    audit_schema_version: str
    policy_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_status": self.gate_status,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
            "combo_count": self.combo_count,
            "accepted_combination_input": self.accepted_combination_input,
            "accepted_member_baseline_input": self.accepted_member_baseline_input,
            "same_sample_enforced": self.same_sample_enforced,
            "contract_hash": self.contract_hash,
            "combination_output_fingerprint": self.combination_output_fingerprint,
            "member_baseline_output_fingerprint": (
                self.member_baseline_output_fingerprint
            ),
            "input_fingerprint": self.input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "information_gain_assessment": self.information_gain_assessment,
            "research_scope": self.research_scope,
            "admission_status": self.admission_status,
            "production_status": self.production_status,
            "production_gates": dict(self.production_gates),
            "dynamic_weighting_performed": self.dynamic_weighting_performed,
            "best_horizon_selected": self.best_horizon_selected,
            "cross_track_composite_calculated": self.cross_track_composite_calculated,
            "conclusion_boundary": self.conclusion_boundary,
            "schema_version": self.schema_version,
            "audit_schema_version": self.audit_schema_version,
            "policy_version": self.policy_version,
            "hash_contract_version": self.hash_contract_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP3InfoGainResult:
    combinations: tuple[ComboInfoGainResult, ...]
    audit: FinancialP3InfoGainAudit

    def to_dict(self) -> dict[str, Any]:
        return {
            "combinations": [item.to_dict() for item in self.combinations],
            "audit": self.audit.to_dict(),
        }


def evaluate_financial_p3_info_gain(
    combinations: FinancialP3CombinationsResult,
    member_baselines: CommonSampleMemberBaselineResult,
    *,
    configuration: FinancialP3InfoGainRunConfig,
) -> FinancialP3InfoGainResult:
    if not isinstance(combinations, FinancialP3CombinationsResult):
        raise TypeError("combinations must be FinancialP3CombinationsResult")
    if not isinstance(member_baselines, CommonSampleMemberBaselineResult):
        raise TypeError("member_baselines must be CommonSampleMemberBaselineResult")
    if not isinstance(configuration, FinancialP3InfoGainRunConfig):
        raise TypeError("configuration must be FinancialP3InfoGainRunConfig")
    errors: list[InfoGainIssue] = []
    warnings: list[InfoGainIssue] = []
    contract = configuration.contract
    combo_audit = combinations.combinations_audit
    member_audit = member_baselines.audit
    if combo_audit.gate_status != "ready":
        errors.append(_issue("COMBINATION_INPUT_NOT_ACCEPTED", "FIN-P3-COMBOS input is not ready"))
    if combo_audit.output_fingerprint != configuration.combination_output_fingerprint:
        errors.append(_issue("COMBINATION_OUTPUT_DRIFT", "FIN-P3-COMBOS output fingerprint drifted"))
    if member_audit.gate_status != "ready":
        errors.append(_issue("MEMBER_BASELINE_INPUT_NOT_ACCEPTED", "INFO-GAIN-02 input is not ready"))
    if member_audit.info_gain_contract_hash != contract.content_hash:
        errors.append(_issue("CONTRACT_HASH_MISMATCH", "member baselines use a different INFO-GAIN-01 contract"))
    if member_audit.failed_member_count != 0 or member_audit.completed_member_count != 11:
        errors.append(_issue("MEMBER_BASELINES_INCOMPLETE", "all 11 frozen member baselines must complete"))
    experiments = {item.definition.combination_id: item for item in combinations.experiments}
    bundles = {item.combo_id: item for item in member_baselines.bundles}
    if set(experiments) != set(INFO_GAIN_COMBO_ORDER):
        errors.append(_issue("COMBINATION_SET_MISMATCH", "combination input must be exactly VQ, QG, CASHQ"))
    if set(bundles) != set(INFO_GAIN_COMBO_ORDER):
        errors.append(_issue("BASELINE_BUNDLE_SET_MISMATCH", "baseline bundles must be exactly VQ, QG, CASHQ"))
    input_fingerprint = _hash(
        "p3_info_gain_inputs",
        {
            "configuration": configuration.to_dict(),
            "combinations": combinations.to_dict(),
            "member_baselines": member_baselines.to_dict(),
        },
    )
    if errors:
        return _blocked(configuration, errors, input_fingerprint, combo_audit.output_fingerprint, member_audit.output_fingerprint)
    outputs: list[ComboInfoGainResult] = []
    for combo_id in INFO_GAIN_COMBO_ORDER:
        output, combo_errors, combo_warnings = _evaluate_combo(
            combo_id,
            experiments[combo_id],
            bundles[combo_id],
            contract,
        )
        errors.extend(combo_errors)
        warnings.extend(combo_warnings)
        if output is not None:
            outputs.append(output)
    if errors:
        return _blocked(
            configuration,
            errors,
            input_fingerprint,
            combo_audit.output_fingerprint,
            member_audit.output_fingerprint,
            outputs=tuple(outputs),
            warnings=warnings,
        )
    output_fingerprint = _hash("p3_info_gain_output", [item.to_dict() for item in outputs])
    audit = _audit(
        configuration=configuration,
        gate_status="ready",
        errors=(),
        warnings=tuple(_deduplicate(warnings)),
        outputs=tuple(outputs),
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
        combo_fingerprint=combo_audit.output_fingerprint,
        member_fingerprint=member_audit.output_fingerprint,
    )
    return FinancialP3InfoGainResult(tuple(outputs), audit)


def serialize_financial_p3_info_gain_result(result: FinancialP3InfoGainResult) -> str:
    if not isinstance(result, FinancialP3InfoGainResult):
        raise TypeError("result must be FinancialP3InfoGainResult")
    return json.dumps(
        _canonical(result.to_dict()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _evaluate_combo(combo_id, experiment, bundle, contract):
    errors: list[InfoGainIssue] = []
    warnings: list[InfoGainIssue] = []
    combo_ref = next(item for item in contract.combination_references if item.combo_id == combo_id)
    sample_ref = next(item for item in contract.common_sample_references if item.combo_id == combo_id)
    if experiment.definition.formula_version != combo_ref.combo_definition_version or experiment.definition.content_hash != combo_ref.definition_hash:
        errors.append(_issue("COMBINATION_DEFINITION_DRIFT", "combination definition drifted", combo_id))
    if experiment.comparison.common_sample_fingerprint != sample_ref.common_sample_fingerprint:
        errors.append(_issue("COMBINATION_SAMPLE_DRIFT", "combination common sample drifted", combo_id))
    if bundle.common_sample_fingerprint != sample_ref.common_sample_fingerprint:
        errors.append(_issue("BASELINE_SAMPLE_DRIFT", "member baseline common sample drifted", combo_id))
    expected_members = tuple(item[0] for item in combo_ref.member_directions)
    actual_members = tuple(item.member_factor_id for item in bundle.member_baselines)
    if actual_members != expected_members:
        errors.append(_issue("MEMBER_ORDER_OR_SET_DRIFT", "member baseline order or set drifted", combo_id))
    if errors:
        return None, errors, warnings
    member_metrics: dict[str, CommonSampleMetrics] = {}
    for run in bundle.member_baselines:
        m20 = next(item for item in run.m_track_results if item.evaluation_context == "20D")
        if m20.calculation_status != "completed" or m20.metrics is None:
            errors.append(_issue("MEMBER_M20_UNAVAILABLE", "member M:20D baseline is unavailable", combo_id, run.member_factor_id))
        else:
            member_metrics[run.member_factor_id] = m20.metrics
    combo_metrics = experiment.comparison.combined_factor_metrics
    primary_metrics = experiment.comparison.single_factor_metrics
    if combo_metrics is None or primary_metrics is None or errors:
        errors.append(_issue("COMBINATION_METRICS_UNAVAILABLE", "accepted combination metrics are unavailable", combo_id))
        return None, errors, warnings
    strongest = sorted(
        member_metrics,
        key=lambda factor_id: (
            -_finite_or_negative_infinity(member_metrics[factor_id].mean_rank_ic),
            factor_id,
        ),
    )[0]
    comparisons: list[InfoGainMetricComparison] = []
    m_track = next(item for item in contract.track_definitions if item.track_id == "M")
    for metric in m_track.metrics:
        for baseline_kind in (
            BaselineKind.STRONGEST_MEMBER.value,
            BaselineKind.MEMBER_AVERAGE.value,
            BaselineKind.PRIMARY_BASELINE.value,
        ):
            comparisons.append(
                _compare_metric(
                    metric,
                    combo_metrics,
                    member_metrics,
                    primary_metrics,
                    baseline_kind,
                    strongest,
                    combo_ref.primary_baseline_factor_id,
                )
            )
    available_strongest = [
        item.absolute_increment
        for item in comparisons
        if item.baseline_kind == BaselineKind.STRONGEST_MEMBER.value
        and item.calculation_status == "completed"
        and item.absolute_increment is not None
    ]
    m_assessment = _directional_assessment(available_strongest)
    coverage = _coverage(experiment, bundle)
    strongest_by_metric = {
        item.metric_id: item.directional_outcome
        for item in comparisons
        if item.baseline_kind == BaselineKind.STRONGEST_MEMBER.value
    }
    criteria = (
        ("better_than_strongest_member_rank_ic", strongest_by_metric.get("rank_ic_mean", "not_evaluable")),
        ("rank_icir_clear_improvement", strongest_by_metric.get("rank_ic_ir", "not_evaluable")),
        ("monotonicity_clear_improvement", strongest_by_metric.get("monotonicity_spearman", "not_evaluable")),
        ("control_adjusted_increment_remains", strongest_by_metric.get("fm_mean_r2", "not_evaluable")),
        ("other_core_metrics_no_material_deterioration", "not_assessed_materiality_threshold_not_frozen"),
        ("period_concentration", "not_run_period_series_unavailable"),
        ("oos_direction_consistency", "not_run_oos_context_not_frozen"),
        ("coverage_loss_explainable", coverage.report_status),
    )
    warnings.extend(
        (
            _issue("OOS_NOT_RUN", "OOS direction consistency is unavailable", combo_id),
            _issue("PERIOD_CONCENTRATION_NOT_RUN", "period-level metric series is unavailable", combo_id),
            _issue("MATERIALITY_NOT_FROZEN", "no materiality threshold is frozen", combo_id),
            _issue("MULTIPLE_TESTING_NOT_RUN", "combo-level OOS hypotheses are unavailable", combo_id),
        )
    )
    payload = {
        "combo_id": combo_id,
        "combo_definition_version": combo_ref.combo_definition_version,
        "common_sample_fingerprint": sample_ref.common_sample_fingerprint,
        "strongest_m20_member_factor_id": strongest,
        "metric_comparisons": [item.to_dict() for item in comparisons],
        "coverage_tradeoff": coverage.to_dict(),
        "m_track_assessment": m_assessment,
        "f_track_assessment": "insufficient",
        "r_track_assessment": "insufficient",
        "information_gain_assessment": InfoGainAssessment.INSUFFICIENT_EVIDENCE.value,
        "core_criteria": dict(criteria),
        "multiple_testing_status": "not_run",
        "production_status": INFO_GAIN_PRODUCTION_STATUS,
        "limitations": [
            "synthetic M:20D common-sample evidence only",
            "M:5D/M:60D and F/R are not frozen and remain not_run",
            "OOS, period concentration, and combo-level multiple testing are not run",
            "materiality thresholds are not frozen",
        ],
    }
    output = ComboInfoGainResult(
        combo_id=combo_id,
        combo_definition_version=combo_ref.combo_definition_version,
        common_sample_fingerprint=sample_ref.common_sample_fingerprint,
        strongest_m20_member_factor_id=strongest,
        metric_comparisons=tuple(comparisons),
        coverage_tradeoff=coverage,
        m_track_assessment=m_assessment,
        f_track_assessment="insufficient",
        r_track_assessment="insufficient",
        information_gain_assessment=InfoGainAssessment.INSUFFICIENT_EVIDENCE.value,
        core_criteria=criteria,
        multiple_testing_status="not_run",
        production_status=INFO_GAIN_PRODUCTION_STATUS,
        limitations=tuple(payload["limitations"]),
        content_hash=_hash("p3_info_gain_combo", payload),
    )
    return output, errors, warnings


def _compare_metric(metric, combo_metrics, member_metrics, primary_metrics, baseline_kind, strongest, primary_factor):
    attribute = _METRIC_ATTRIBUTE.get(metric.metric_id)
    baseline_factor = None
    if baseline_kind == BaselineKind.STRONGEST_MEMBER.value:
        baseline_factor = strongest
    elif baseline_kind == BaselineKind.PRIMARY_BASELINE.value:
        baseline_factor = primary_factor
    if attribute is None:
        return InfoGainMetricComparison(
            "M", "20D", metric.metric_id, baseline_kind, baseline_factor,
            None, None, None, None, "not_run", "not_run", "SOURCE_METRIC_UNAVAILABLE",
        )
    combo_value = getattr(combo_metrics, attribute)
    if baseline_kind == BaselineKind.STRONGEST_MEMBER.value:
        baseline_value = getattr(member_metrics[strongest], attribute)
    elif baseline_kind == BaselineKind.PRIMARY_BASELINE.value:
        baseline_value = getattr(primary_metrics, attribute)
    elif metric.value_kind == "scalar":
        values = [getattr(item, attribute) for item in member_metrics.values()]
        baseline_value = float(np.mean(values)) if all(_finite(item) for item in values) else None
    else:
        baseline_value = None
    if metric.value_kind != "scalar":
        return InfoGainMetricComparison(
            "M", "20D", metric.metric_id, baseline_kind, baseline_factor,
            _json_value(combo_value), _json_value(baseline_value), None, None,
            "completed", "detail_only", None,
        )
    if not _finite(combo_value) or not _finite(baseline_value):
        return InfoGainMetricComparison(
            "M", "20D", metric.metric_id, baseline_kind, baseline_factor,
            _json_value(combo_value), _json_value(baseline_value), None, None,
            "not_applicable", "not_evaluable", "NONFINITE_OR_MISSING_VALUE",
        )
    combo_float = float(combo_value)
    baseline_float = float(baseline_value)
    if metric.better_direction == MetricBetterDirection.HIGHER.value:
        absolute = combo_float - baseline_float
        denominator = abs(baseline_float)
    elif metric.better_direction == MetricBetterDirection.LOWER.value:
        absolute = baseline_float - combo_float
        denominator = abs(baseline_float)
    else:
        target = float(metric.target_value)
        absolute = abs(baseline_float - target) - abs(combo_float - target)
        denominator = abs(baseline_float - target)
    relative = None if denominator <= INFO_GAIN_ZERO_DENOMINATOR_EPSILON else absolute / denominator
    outcome = "positive" if absolute > 0 else "negative" if absolute < 0 else "tie"
    reason = None if relative is not None else "RELATIVE_DENOMINATOR_LTE_EPSILON"
    return InfoGainMetricComparison(
        "M", "20D", metric.metric_id, baseline_kind, baseline_factor,
        combo_float, baseline_float, float(absolute), None if relative is None else float(relative),
        "completed", outcome, reason,
    )


def _coverage(experiment, bundle: ComboMemberBaselineBundle) -> CoverageTradeoffReport:
    audit = experiment.construction_audit
    comparison = experiment.comparison
    eligible = int(audit.eligible_sample_size)
    common = int(comparison.common_sample_size)
    counts = tuple(
        (item.factor_id, int(item.available_observation_count))
        for item in audit.constituent_coverage
    )
    ratios = tuple((factor_id, count / eligible) for factor_id, count in counts)
    return CoverageTradeoffReport(
        eligible_sample_count=eligible,
        member_original_evaluable_sample_counts=counts,
        member_original_coverage_ratios=ratios,
        combo_common_sample_count=common,
        combo_common_sample_coverage_ratio=common / eligible,
        absolute_coverage_loss=eligible - common,
        relative_coverage_loss=float(comparison.coverage_loss),
        per_period_common_sample_counts=bundle.per_period_common_sample_counts,
        per_period_coverage_ratio_status="insufficient_denominator_not_retained",
        valid_period_loss=max(0, 18 - int(comparison.common_period_count)),
        insufficient_sample_periods=max(0, 18 - int(comparison.common_period_count)),
        exclusion_reason_categories=(
            "constituent_unavailable",
            "reference_unavailable",
            "label_or_control_unavailable",
            "intersection_overlap_not_separately_retained",
        ),
        industry_distribution_change_status="not_run_source_distribution_not_retained",
        size_distribution_change_status="not_run_source_distribution_not_retained",
        acceptance_threshold_status="not_frozen_report_facts_only",
        automatic_rejection_applied=False,
        report_status="partial_explanation_source_breakdown_not_retained",
    )


def _directional_assessment(values: Sequence[float]) -> str:
    if not values:
        return "insufficient"
    positive = any(value > 0 for value in values)
    negative = any(value < 0 for value in values)
    if positive and negative:
        return "mixed"
    if positive:
        return "supportive"
    if negative:
        return "unsupportive"
    return "exploratory"


def _blocked(configuration, errors, input_fingerprint, combo_fingerprint, member_fingerprint, *, outputs=(), warnings=()):
    output_fingerprint = _hash("p3_info_gain_output", [item.to_dict() for item in outputs])
    audit = _audit(
        configuration=configuration,
        gate_status="blocked",
        errors=tuple(_deduplicate(errors)),
        warnings=tuple(_deduplicate(warnings)),
        outputs=tuple(outputs),
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
        combo_fingerprint=combo_fingerprint,
        member_fingerprint=member_fingerprint,
    )
    return FinancialP3InfoGainResult(tuple(outputs), audit)


def _audit(*, configuration, gate_status, errors, warnings, outputs, input_fingerprint, output_fingerprint, combo_fingerprint, member_fingerprint):
    production_gates = (
        ("data_gate", "not_passed_synthetic_only"),
        ("signal_gate", "not_assessed_oos_and_materiality_unavailable"),
        ("risk_gate", "not_run_R_context_not_frozen"),
        ("ops_gate", "not_assessed_research_output_only"),
    )
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "combo_count": len(outputs),
        "accepted_combination_input": gate_status == "ready",
        "accepted_member_baseline_input": gate_status == "ready",
        "same_sample_enforced": True,
        "contract_hash": configuration.contract.content_hash,
        "combination_output_fingerprint": combo_fingerprint,
        "member_baseline_output_fingerprint": member_fingerprint,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": output_fingerprint,
        "information_gain_assessment": InfoGainAssessment.INSUFFICIENT_EVIDENCE.value,
        "research_scope": INFO_GAIN_RESEARCH_SCOPE,
        "admission_status": "not_assessed",
        "production_status": INFO_GAIN_PRODUCTION_STATUS,
        "production_gates": dict(production_gates),
        "dynamic_weighting_performed": False,
        "best_horizon_selected": False,
        "cross_track_composite_calculated": False,
        "conclusion_boundary": INFO_GAIN_CONCLUSION_BOUNDARY,
        "schema_version": INFO_GAIN_RESULT_SCHEMA_VERSION,
        "audit_schema_version": INFO_GAIN_AUDIT_SCHEMA_VERSION,
        "policy_version": INFO_GAIN_POLICY_VERSION,
        "hash_contract_version": INFO_GAIN_HASH_CONTRACT_VERSION,
    }
    return FinancialP3InfoGainAudit(
        gate_status=gate_status,
        errors=errors,
        warnings=warnings,
        combo_count=len(outputs),
        accepted_combination_input=gate_status == "ready",
        accepted_member_baseline_input=gate_status == "ready",
        same_sample_enforced=True,
        contract_hash=configuration.contract.content_hash,
        combination_output_fingerprint=combo_fingerprint,
        member_baseline_output_fingerprint=member_fingerprint,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
        information_gain_assessment=InfoGainAssessment.INSUFFICIENT_EVIDENCE.value,
        research_scope=INFO_GAIN_RESEARCH_SCOPE,
        admission_status="not_assessed",
        production_status=INFO_GAIN_PRODUCTION_STATUS,
        production_gates=production_gates,
        dynamic_weighting_performed=False,
        best_horizon_selected=False,
        cross_track_composite_calculated=False,
        conclusion_boundary=INFO_GAIN_CONCLUSION_BOUNDARY,
        schema_version=INFO_GAIN_RESULT_SCHEMA_VERSION,
        audit_schema_version=INFO_GAIN_AUDIT_SCHEMA_VERSION,
        policy_version=INFO_GAIN_POLICY_VERSION,
        hash_contract_version=INFO_GAIN_HASH_CONTRACT_VERSION,
        content_hash=_hash("p3_info_gain_audit", payload),
    )


def _issue(code, message, combo_id=None, field_name=None):
    return InfoGainIssue(code, message, combo_id, field_name)


def _deduplicate(items):
    output = []
    seen = set()
    for item in items:
        key = (item.code, item.message, item.combo_id, item.field_name)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and math.isfinite(float(value))


def _finite_or_negative_infinity(value: Any) -> float:
    return float(value) if _finite(value) else float("-inf")


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [float(item) if _finite(item) else None for item in value]
    if _finite(value):
        return float(value)
    return None


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer):
        return int(value)
    raise TypeError(f"unsupported canonical type: {type(value).__name__}")


def _hash(domain: str, value: Any) -> str:
    payload = json.dumps(
        {"domain": domain, "value": _canonical(value)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
