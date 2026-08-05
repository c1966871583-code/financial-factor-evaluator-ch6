"""FIN-P3-INFO-GAIN-01: deterministic information-gain contract.

This module freezes how a later FIN-25 task may compare a preset FIN-24
combination with its members on the accepted FIN-23 common sample.  It is a
configuration-only artifact: it does not evaluate a factor, recompute a
member baseline, select a winner, or make an information-gain or production
decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

from backend.amr.evaluation_core import EvaluationStatus
from backend.amr.financial_mvp_output import EvidenceAssessment
from backend.amr.financial_p3_combinations import (
    CombinationGateStatus,
    FinancialP3CombinationDefinition,
    get_fin24_combination_definitions,
)
from backend.amr.financial_p3_common_sample import (
    COMMON_SAMPLE_POLICY_VERSION,
    CommonSampleEvaluationStatus,
)


INFO_GAIN_CONTRACT_SCHEMA_VERSION = "FinancialP3InfoGainContract-v1.0"
INFO_GAIN_CONTRACT_VERSION = "FIN-P3-INFO-GAIN-CONTRACT-v1.0"
INFO_GAIN_POLICY_VERSION = "FIN-P3-INFO-GAIN-POLICY-v1.0"
INFO_GAIN_HASH_CONTRACT_VERSION = "FIN-P3-INFO-GAIN-HASH-v1.0"
INFO_GAIN_PREDECESSOR_TASK = "FIN-P3-COMBOS"
INFO_GAIN_PREDECESSOR_STATUS = "ACCEPTED"
INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT = (
    "7c8686b44f3842f159b3fbbc45aa9908f3bf81acd5ebec381f8ac4f5c1933fa2"
)
INFO_GAIN_RESEARCH_ASSESSMENT = "exploratory"
INFO_GAIN_ADMISSION_STATUS = "not_assessed"
INFO_GAIN_PRODUCTION_STATUS = "not production ready"
INFO_GAIN_ZERO_DENOMINATOR_EPSILON = 1e-12
INFO_GAIN_COMBO_ORDER = ("VQ", "QG", "CASHQ")
INFO_GAIN_CONCLUSION_BOUNDARY = (
    "Configuration-only FIN-P3-INFO-GAIN-01 contract. No combination or "
    "member result is calculated, no evaluator is executed, no strongest "
    "member or horizon is selected, and no information-gain, admission, "
    "production, empirical-return, fraud, or trading conclusion is made."
)


class MetricBetterDirection(str, Enum):
    HIGHER = "higher"
    LOWER = "lower"
    CLOSER_TO_TARGET = "closer_to_target"
    DETAIL_ONLY = "detail_only"


class BaselineKind(str, Enum):
    STRONGEST_MEMBER = "strongest_member"
    MEMBER_AVERAGE = "member_average"
    PRIMARY_BASELINE = "primary_baseline"


class InfoGainAssessment(str, Enum):
    POSITIVE_INCREMENT = "positive_increment"
    NO_INCREMENT = "no_increment"
    NEGATIVE_INCREMENT = "negative_increment"
    MIXED_INCREMENT = "mixed_increment"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_ASSESSED = "not_assessed"


@dataclass(frozen=True)
class InfoGainCombinationReference:
    combo_id: str
    combo_definition_version: str
    definition_hash: str
    member_directions: tuple[tuple[str, str], ...]
    primary_baseline_factor_id: str

    def __post_init__(self) -> None:
        _required_text(self.combo_id, "combo_id")
        _required_text(
            self.combo_definition_version, "combo_definition_version"
        )
        if not _is_sha256(self.definition_hash):
            raise ValueError("definition_hash must be SHA-256")
        member_ids = [factor_id for factor_id, _ in self.member_directions]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("member_directions contains duplicate members")
        if not member_ids:
            raise ValueError("member_directions must not be empty")
        for factor_id, direction in self.member_directions:
            _required_text(factor_id, "member_factor_id")
            if direction not in {"positive", "negative"}:
                raise ValueError("member direction must be positive or negative")
        if self.primary_baseline_factor_id not in member_ids and self.combo_id != "CASHQ":
            raise ValueError("primary baseline must be a frozen combo member")

    def to_dict(self) -> dict[str, Any]:
        return {
            "combo_id": self.combo_id,
            "combo_definition_version": self.combo_definition_version,
            "definition_hash": self.definition_hash,
            "member_directions": [
                {"factor_id": factor_id, "direction": direction}
                for factor_id, direction in self.member_directions
            ],
            "primary_baseline_factor_id": self.primary_baseline_factor_id,
        }


@dataclass(frozen=True)
class CommonSampleContractReference:
    combo_id: str
    combo_definition_version: str
    common_sample_reference: str
    common_sample_fingerprint: str
    evaluation_period_count: int
    common_sample_row_count: int
    sample_rule_version: str
    available_evaluation_contexts: tuple[str, ...]
    not_run_evaluation_contexts: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "combo_id",
            "combo_definition_version",
            "common_sample_reference",
            "sample_rule_version",
        ):
            _required_text(getattr(self, field_name), field_name)
        if not _is_sha256(self.common_sample_fingerprint):
            raise ValueError("common_sample_fingerprint must be SHA-256")
        if self.evaluation_period_count != 18:
            raise ValueError("evaluation_period_count must be frozen at 18")
        if self.common_sample_row_count != 900:
            raise ValueError("common_sample_row_count must be frozen at 900")
        if tuple(self.available_evaluation_contexts) != ("M:20D",):
            raise ValueError("only the accepted M:20D context is available")
        if tuple(self.not_run_evaluation_contexts) != (
            "M:5D",
            "M:60D",
            "F",
            "R",
        ):
            raise ValueError("unfrozen evaluation contexts must remain not_run")

    def to_dict(self) -> dict[str, Any]:
        return {
            "combo_id": self.combo_id,
            "combo_definition_version": self.combo_definition_version,
            "common_sample_reference": self.common_sample_reference,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "evaluation_period_count": self.evaluation_period_count,
            "common_sample_row_count": self.common_sample_row_count,
            "sample_rule_version": self.sample_rule_version,
            "available_evaluation_contexts": list(
                self.available_evaluation_contexts
            ),
            "not_run_evaluation_contexts": list(
                self.not_run_evaluation_contexts
            ),
        }


@dataclass(frozen=True)
class StrongestMemberRule:
    track_id: str
    metric_id: str
    horizon: str | None
    tie_break_rule: str = "factor_id_lexicographic"
    fixed_members_only: bool = True

    def __post_init__(self) -> None:
        if self.track_id not in {"M", "F", "R"}:
            raise ValueError("track_id must be M, F, or R")
        _required_text(self.metric_id, "metric_id")
        if self.tie_break_rule != "factor_id_lexicographic":
            raise ValueError("tie_break_rule must be factor_id_lexicographic")
        if self.fixed_members_only is not True:
            raise ValueError("strongest-member search must use fixed members only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "metric_id": self.metric_id,
            "horizon": self.horizon,
            "tie_break_rule": self.tie_break_rule,
            "fixed_members_only": self.fixed_members_only,
        }


@dataclass(frozen=True)
class InfoGainBaselineDefinition:
    baseline_id: str
    baseline_kind: str
    combo_id: str | None = None
    primary_baseline_factor_id: str | None = None
    selection_reason: str | None = None
    definition_version: str | None = None
    strongest_member_rules: tuple[StrongestMemberRule, ...] = ()
    member_average_method: str | None = None
    comparable_scalar_metrics_only: bool = True
    all_members_required: bool = True
    unavailable_member_deletion_allowed: bool = False

    def __post_init__(self) -> None:
        _required_text(self.baseline_id, "baseline_id")
        allowed_kinds = {item.value for item in BaselineKind}
        if self.baseline_kind not in allowed_kinds:
            raise ValueError("unknown baseline_kind")
        if self.baseline_kind == BaselineKind.STRONGEST_MEMBER.value:
            if tuple(rule.track_id for rule in self.strongest_member_rules) != (
                "M",
                "F",
                "R",
            ):
                raise ValueError("strongest member rules must freeze M, F, R")
        elif self.strongest_member_rules:
            raise ValueError("strongest_member_rules only apply to strongest member")
        if self.baseline_kind == BaselineKind.MEMBER_AVERAGE.value:
            if self.member_average_method != "simple_arithmetic_mean":
                raise ValueError("member average must be simple arithmetic mean")
            if not self.comparable_scalar_metrics_only:
                raise ValueError("only comparable scalar metrics may be averaged")
            if not self.all_members_required:
                raise ValueError("all frozen members must be required")
            if self.unavailable_member_deletion_allowed:
                raise ValueError("unavailable members must not be deleted")
        if self.baseline_kind == BaselineKind.PRIMARY_BASELINE.value:
            for field_name in (
                "combo_id",
                "primary_baseline_factor_id",
                "selection_reason",
                "definition_version",
            ):
                _required_text(getattr(self, field_name), field_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "baseline_kind": self.baseline_kind,
            "combo_id": self.combo_id,
            "primary_baseline_factor_id": self.primary_baseline_factor_id,
            "selection_reason": self.selection_reason,
            "definition_version": self.definition_version,
            "strongest_member_rules": [
                item.to_dict() for item in self.strongest_member_rules
            ],
            "member_average_method": self.member_average_method,
            "comparable_scalar_metrics_only": self.comparable_scalar_metrics_only,
            "all_members_required": self.all_members_required,
            "unavailable_member_deletion_allowed": (
                self.unavailable_member_deletion_allowed
            ),
        }


@dataclass(frozen=True)
class InfoGainMetricDefinition:
    metric_id: str
    display_name: str
    source_field: str
    better_direction: str
    baseline_rule: str
    absolute_increment_formula: str
    relative_increment_formula: str
    not_evaluable_rule: str
    public_result_allowed: bool
    value_kind: str = "scalar"
    target_value: float | None = None
    frozen_parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "metric_id",
            "display_name",
            "source_field",
            "baseline_rule",
            "absolute_increment_formula",
            "relative_increment_formula",
            "not_evaluable_rule",
        ):
            _required_text(getattr(self, field_name), field_name)
        directions = {item.value for item in MetricBetterDirection}
        if self.better_direction not in directions:
            raise ValueError("metric better direction must be explicit")
        if self.value_kind not in {"scalar", "vector_detail", "object_detail"}:
            raise ValueError("unknown metric value_kind")
        if self.better_direction == MetricBetterDirection.CLOSER_TO_TARGET.value:
            if self.target_value is None:
                raise ValueError("closer_to_target metrics require target_value")
        elif self.target_value is not None:
            raise ValueError("target_value only applies to closer_to_target")
        if self.better_direction == MetricBetterDirection.DETAIL_ONLY.value:
            if self.value_kind == "scalar":
                raise ValueError("detail-only metric must not be scalar")
            if self.absolute_increment_formula != "not_applicable_detail_only":
                raise ValueError("detail-only metric cannot define an increment")

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "display_name": self.display_name,
            "source_field": self.source_field,
            "better_direction": self.better_direction,
            "baseline_rule": self.baseline_rule,
            "absolute_increment_formula": self.absolute_increment_formula,
            "relative_increment_formula": self.relative_increment_formula,
            "not_evaluable_rule": self.not_evaluable_rule,
            "public_result_allowed": self.public_result_allowed,
            "value_kind": self.value_kind,
            "target_value": self.target_value,
            "frozen_parameters": dict(self.frozen_parameters),
        }


@dataclass(frozen=True)
class InfoGainTrackDefinition:
    track_id: str
    evidence_role: str
    evaluator_reference: str
    metrics: tuple[InfoGainMetricDefinition, ...]
    horizons: tuple[str, ...] = ()
    primary_horizon: str | None = None
    replaces_m_track: bool = False

    def __post_init__(self) -> None:
        if self.track_id not in {"M", "F", "R"}:
            raise ValueError("track_id must be M, F, or R")
        expected_role = {"M": "primary", "F": "supporting", "R": "risk"}
        if self.evidence_role != expected_role[self.track_id]:
            raise ValueError("track evidence role is frozen")
        _required_text(self.evaluator_reference, "evaluator_reference")
        metric_ids = [item.metric_id for item in self.metrics]
        if not metric_ids or len(metric_ids) != len(set(metric_ids)):
            raise ValueError("track metrics must be non-empty and unique")
        if self.track_id == "M":
            if self.horizons != ("5D", "20D", "60D"):
                raise ValueError("M horizons must be 5D, 20D, 60D")
            if self.primary_horizon != "20D":
                raise ValueError("M primary horizon must be 20D")
        elif self.horizons or self.primary_horizon is not None:
            raise ValueError("only M freezes return horizons")
        if self.replaces_m_track:
            raise ValueError("F and R must not replace M evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "evidence_role": self.evidence_role,
            "evaluator_reference": self.evaluator_reference,
            "metrics": [item.to_dict() for item in self.metrics],
            "horizons": list(self.horizons),
            "primary_horizon": self.primary_horizon,
            "replaces_m_track": self.replaces_m_track,
        }


@dataclass(frozen=True)
class CoverageTradeoffDefinition:
    required_fields: tuple[str, ...]
    per_period_reporting_required: bool
    exclusion_reason_reporting_required: bool
    industry_size_distribution_if_available: bool
    acceptance_threshold_status: str
    automatic_rejection_allowed: bool

    def __post_init__(self) -> None:
        if len(self.required_fields) != len(set(self.required_fields)):
            raise ValueError("coverage fields must be unique")
        if not self.per_period_reporting_required:
            raise ValueError("coverage must be reported per period")
        if not self.exclusion_reason_reporting_required:
            raise ValueError("coverage exclusions must be classified")
        if self.acceptance_threshold_status != "not_frozen_report_facts_only":
            raise ValueError("coverage threshold is not frozen")
        if self.automatic_rejection_allowed:
            raise ValueError("coverage cannot trigger automatic rejection")

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_fields": list(self.required_fields),
            "per_period_reporting_required": self.per_period_reporting_required,
            "exclusion_reason_reporting_required": (
                self.exclusion_reason_reporting_required
            ),
            "industry_size_distribution_if_available": (
                self.industry_size_distribution_if_available
            ),
            "acceptance_threshold_status": self.acceptance_threshold_status,
            "automatic_rejection_allowed": self.automatic_rejection_allowed,
        }


@dataclass(frozen=True)
class StatusSemanticMapping:
    semantic: str
    project_status: str
    source_enum: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic": self.semantic,
            "project_status": self.project_status,
            "source_enum": self.source_enum,
        }


@dataclass(frozen=True)
class InfoGainStatusPolicy:
    calculation_status_mapping: tuple[StatusSemanticMapping, ...]
    information_gain_assessments: tuple[str, ...]
    track_assessment_values: tuple[str, ...]
    default_information_gain_assessment: str
    materiality_threshold_status: str
    production_status: str
    positive_increment_upgrades_production: bool
    cross_track_composite_score_allowed: bool

    def __post_init__(self) -> None:
        expected_semantics = (
            "success",
            "not_run",
            "not_evaluable",
            "insufficient_data",
            "failed",
        )
        if tuple(item.semantic for item in self.calculation_status_mapping) != expected_semantics:
            raise ValueError("calculation status semantics are incomplete")
        if self.information_gain_assessments != tuple(
            item.value for item in InfoGainAssessment
        ):
            raise ValueError("information gain assessments are not frozen")
        if self.default_information_gain_assessment != "not_assessed":
            raise ValueError("default information gain assessment is not_assessed")
        if self.materiality_threshold_status != "not_frozen":
            raise ValueError("materiality thresholds are not frozen")
        if self.production_status != INFO_GAIN_PRODUCTION_STATUS:
            raise ValueError("production status must remain not production ready")
        if self.positive_increment_upgrades_production:
            raise ValueError("positive increment cannot upgrade production")
        if self.cross_track_composite_score_allowed:
            raise ValueError("M/F/R must not be combined into a composite score")

    def to_dict(self) -> dict[str, Any]:
        return {
            "calculation_status_mapping": [
                item.to_dict() for item in self.calculation_status_mapping
            ],
            "information_gain_assessments": list(
                self.information_gain_assessments
            ),
            "track_assessment_values": list(self.track_assessment_values),
            "default_information_gain_assessment": (
                self.default_information_gain_assessment
            ),
            "materiality_threshold_status": self.materiality_threshold_status,
            "production_status": self.production_status,
            "positive_increment_upgrades_production": (
                self.positive_increment_upgrades_production
            ),
            "cross_track_composite_score_allowed": (
                self.cross_track_composite_score_allowed
            ),
        }


@dataclass(frozen=True)
class DeterministicSerializationPolicy:
    format: str = "canonical_json_utf8"
    key_order: str = "sorted"
    sequence_order: str = "frozen_domain_order"
    hash_algorithm: str = "sha256"
    runtime_timestamp_allowed: bool = False
    random_value_allowed: bool = False

    def __post_init__(self) -> None:
        expected = {
            "format": (self.format, "canonical_json_utf8"),
            "key_order": (self.key_order, "sorted"),
            "sequence_order": (self.sequence_order, "frozen_domain_order"),
            "hash_algorithm": (self.hash_algorithm, "sha256"),
            "runtime_timestamp_allowed": (self.runtime_timestamp_allowed, False),
            "random_value_allowed": (self.random_value_allowed, False),
        }
        for field_name, (actual, frozen) in expected.items():
            if actual != frozen:
                raise ValueError(f"{field_name} must be frozen at {frozen!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class InfoGainEvaluationConfig:
    combination_references: tuple[InfoGainCombinationReference, ...]
    common_sample_references: tuple[CommonSampleContractReference, ...]
    baseline_definitions: tuple[InfoGainBaselineDefinition, ...]
    track_definitions: tuple[InfoGainTrackDefinition, ...]
    coverage_tradeoff_definition: CoverageTradeoffDefinition
    status_policy: InfoGainStatusPolicy
    deterministic_serialization_policy: DeterministicSerializationPolicy
    predecessor_task: str
    predecessor_status: str
    predecessor_output_fingerprint: str
    real_result_computation_allowed: bool
    member_baseline_recalculation_allowed: bool
    evaluation_pipeline_execution_allowed: bool
    dynamic_weighting_allowed: bool
    automatic_best_member_selection_allowed: bool
    automatic_best_horizon_selection_allowed: bool
    cross_track_composite_score_allowed: bool
    research_assessment: str
    admission_status: str
    production_status: str
    conclusion_boundary: str
    schema_version: str
    contract_version: str
    policy_version: str
    hash_contract_version: str
    content_hash: str

    def __post_init__(self) -> None:
        if tuple(item.combo_id for item in self.combination_references) != INFO_GAIN_COMBO_ORDER:
            raise ValueError("combination references must use frozen order")
        if tuple(item.combo_id for item in self.common_sample_references) != INFO_GAIN_COMBO_ORDER:
            raise ValueError("common sample references must use frozen order")
        if tuple(item.track_id for item in self.track_definitions) != ("M", "F", "R"):
            raise ValueError("track definitions must use M, F, R order")
        frozen = {
            "predecessor_task": (self.predecessor_task, INFO_GAIN_PREDECESSOR_TASK),
            "predecessor_status": (
                self.predecessor_status,
                INFO_GAIN_PREDECESSOR_STATUS,
            ),
            "predecessor_output_fingerprint": (
                self.predecessor_output_fingerprint,
                INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT,
            ),
            "real_result_computation_allowed": (
                self.real_result_computation_allowed,
                False,
            ),
            "member_baseline_recalculation_allowed": (
                self.member_baseline_recalculation_allowed,
                False,
            ),
            "evaluation_pipeline_execution_allowed": (
                self.evaluation_pipeline_execution_allowed,
                False,
            ),
            "dynamic_weighting_allowed": (self.dynamic_weighting_allowed, False),
            "automatic_best_member_selection_allowed": (
                self.automatic_best_member_selection_allowed,
                False,
            ),
            "automatic_best_horizon_selection_allowed": (
                self.automatic_best_horizon_selection_allowed,
                False,
            ),
            "cross_track_composite_score_allowed": (
                self.cross_track_composite_score_allowed,
                False,
            ),
            "research_assessment": (
                self.research_assessment,
                INFO_GAIN_RESEARCH_ASSESSMENT,
            ),
            "admission_status": (
                self.admission_status,
                INFO_GAIN_ADMISSION_STATUS,
            ),
            "production_status": (
                self.production_status,
                INFO_GAIN_PRODUCTION_STATUS,
            ),
            "conclusion_boundary": (
                self.conclusion_boundary,
                INFO_GAIN_CONCLUSION_BOUNDARY,
            ),
            "schema_version": (
                self.schema_version,
                INFO_GAIN_CONTRACT_SCHEMA_VERSION,
            ),
            "contract_version": (
                self.contract_version,
                INFO_GAIN_CONTRACT_VERSION,
            ),
            "policy_version": (self.policy_version, INFO_GAIN_POLICY_VERSION),
            "hash_contract_version": (
                self.hash_contract_version,
                INFO_GAIN_HASH_CONTRACT_VERSION,
            ),
        }
        for field_name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{field_name} must be frozen at {expected!r}")
        if not _is_sha256(self.content_hash):
            raise ValueError("content_hash must be SHA-256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "combination_references": [
                item.to_dict() for item in self.combination_references
            ],
            "common_sample_references": [
                item.to_dict() for item in self.common_sample_references
            ],
            "baseline_definitions": [
                item.to_dict() for item in self.baseline_definitions
            ],
            "track_definitions": [
                item.to_dict() for item in self.track_definitions
            ],
            "coverage_tradeoff_definition": (
                self.coverage_tradeoff_definition.to_dict()
            ),
            "status_policy": self.status_policy.to_dict(),
            "deterministic_serialization_policy": (
                self.deterministic_serialization_policy.to_dict()
            ),
            "predecessor_task": self.predecessor_task,
            "predecessor_status": self.predecessor_status,
            "predecessor_output_fingerprint": (
                self.predecessor_output_fingerprint
            ),
            "real_result_computation_allowed": self.real_result_computation_allowed,
            "member_baseline_recalculation_allowed": (
                self.member_baseline_recalculation_allowed
            ),
            "evaluation_pipeline_execution_allowed": (
                self.evaluation_pipeline_execution_allowed
            ),
            "dynamic_weighting_allowed": self.dynamic_weighting_allowed,
            "automatic_best_member_selection_allowed": (
                self.automatic_best_member_selection_allowed
            ),
            "automatic_best_horizon_selection_allowed": (
                self.automatic_best_horizon_selection_allowed
            ),
            "cross_track_composite_score_allowed": (
                self.cross_track_composite_score_allowed
            ),
            "research_assessment": self.research_assessment,
            "admission_status": self.admission_status,
            "production_status": self.production_status,
            "conclusion_boundary": self.conclusion_boundary,
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "policy_version": self.policy_version,
            "hash_contract_version": self.hash_contract_version,
            "content_hash": self.content_hash,
        }


_SAMPLE_SPECS = {
    "VQ": (
        "FIN-24-VQ-v1.0",
        "ab58b5b1cf5e975563838f9e5aecd367f9c70a25d10d2678c69c6fa4a2f037d1",
    ),
    "QG": (
        "FIN-24-QG-v1.0",
        "3e470edf7b8b8e065ec6f373e2e5872e1cabf42e360212928ecc7276834839ae",
    ),
    "CASHQ": (
        "FIN-24-CASHQ-v1.0",
        "c3d21f755aae395d179e23b361948bcb232f4e52625d12e5dd98bf013ebcd4f7",
    ),
}


def get_frozen_common_sample_references(
) -> tuple[CommonSampleContractReference, ...]:
    return tuple(
        CommonSampleContractReference(
            combo_id=combo_id,
            combo_definition_version=_SAMPLE_SPECS[combo_id][0],
            common_sample_reference=(
                f"FIN-P3-COMBOS:experiment:{combo_id}:comparison"
            ),
            common_sample_fingerprint=_SAMPLE_SPECS[combo_id][1],
            evaluation_period_count=18,
            common_sample_row_count=900,
            sample_rule_version=COMMON_SAMPLE_POLICY_VERSION,
            available_evaluation_contexts=("M:20D",),
            not_run_evaluation_contexts=("M:5D", "M:60D", "F", "R"),
        )
        for combo_id in INFO_GAIN_COMBO_ORDER
    )


def build_financial_p3_info_gain_contract(
    *,
    combination_definitions: Sequence[
        FinancialP3CombinationDefinition
    ] | None = None,
    common_sample_references: Sequence[
        CommonSampleContractReference
    ] | None = None,
) -> InfoGainEvaluationConfig:
    definitions = _normalize_definitions(combination_definitions)
    samples = _normalize_samples(common_sample_references)
    combination_references = tuple(
        InfoGainCombinationReference(
            combo_id=definition.combination_id,
            combo_definition_version=definition.formula_version,
            definition_hash=definition.content_hash,
            member_directions=tuple(
                (
                    term.factor_id,
                    "positive" if term.weight > 0 else "negative",
                )
                for term in definition.terms
            ),
            primary_baseline_factor_id=definition.reference_factor_id,
        )
        for definition in definitions
    )
    baselines = _baseline_definitions(definitions)
    tracks = _track_definitions()
    coverage = CoverageTradeoffDefinition(
        required_fields=(
            "member_original_evaluable_sample_count",
            "member_original_coverage_ratio",
            "combo_common_sample_count",
            "combo_common_sample_coverage_ratio",
            "absolute_coverage_loss",
            "relative_coverage_loss",
            "per_period_coverage_ratio",
            "valid_period_loss",
            "insufficient_sample_periods",
            "exclusion_reason_categories",
            "industry_distribution_change_if_available",
            "size_distribution_change_if_available",
        ),
        per_period_reporting_required=True,
        exclusion_reason_reporting_required=True,
        industry_size_distribution_if_available=True,
        acceptance_threshold_status="not_frozen_report_facts_only",
        automatic_rejection_allowed=False,
    )
    status_policy = _status_policy()
    serialization = DeterministicSerializationPolicy()
    payload = {
        "combination_references": [
            item.to_dict() for item in combination_references
        ],
        "common_sample_references": [item.to_dict() for item in samples],
        "baseline_definitions": [item.to_dict() for item in baselines],
        "track_definitions": [item.to_dict() for item in tracks],
        "coverage_tradeoff_definition": coverage.to_dict(),
        "status_policy": status_policy.to_dict(),
        "deterministic_serialization_policy": serialization.to_dict(),
        "predecessor_task": INFO_GAIN_PREDECESSOR_TASK,
        "predecessor_status": INFO_GAIN_PREDECESSOR_STATUS,
        "predecessor_output_fingerprint": (
            INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT
        ),
        "real_result_computation_allowed": False,
        "member_baseline_recalculation_allowed": False,
        "evaluation_pipeline_execution_allowed": False,
        "dynamic_weighting_allowed": False,
        "automatic_best_member_selection_allowed": False,
        "automatic_best_horizon_selection_allowed": False,
        "cross_track_composite_score_allowed": False,
        "research_assessment": INFO_GAIN_RESEARCH_ASSESSMENT,
        "admission_status": INFO_GAIN_ADMISSION_STATUS,
        "production_status": INFO_GAIN_PRODUCTION_STATUS,
        "conclusion_boundary": INFO_GAIN_CONCLUSION_BOUNDARY,
        "schema_version": INFO_GAIN_CONTRACT_SCHEMA_VERSION,
        "contract_version": INFO_GAIN_CONTRACT_VERSION,
        "policy_version": INFO_GAIN_POLICY_VERSION,
        "hash_contract_version": INFO_GAIN_HASH_CONTRACT_VERSION,
    }
    return InfoGainEvaluationConfig(
        combination_references=combination_references,
        common_sample_references=samples,
        baseline_definitions=baselines,
        track_definitions=tracks,
        coverage_tradeoff_definition=coverage,
        status_policy=status_policy,
        deterministic_serialization_policy=serialization,
        predecessor_task=INFO_GAIN_PREDECESSOR_TASK,
        predecessor_status=INFO_GAIN_PREDECESSOR_STATUS,
        predecessor_output_fingerprint=(
            INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT
        ),
        real_result_computation_allowed=False,
        member_baseline_recalculation_allowed=False,
        evaluation_pipeline_execution_allowed=False,
        dynamic_weighting_allowed=False,
        automatic_best_member_selection_allowed=False,
        automatic_best_horizon_selection_allowed=False,
        cross_track_composite_score_allowed=False,
        research_assessment=INFO_GAIN_RESEARCH_ASSESSMENT,
        admission_status=INFO_GAIN_ADMISSION_STATUS,
        production_status=INFO_GAIN_PRODUCTION_STATUS,
        conclusion_boundary=INFO_GAIN_CONCLUSION_BOUNDARY,
        schema_version=INFO_GAIN_CONTRACT_SCHEMA_VERSION,
        contract_version=INFO_GAIN_CONTRACT_VERSION,
        policy_version=INFO_GAIN_POLICY_VERSION,
        hash_contract_version=INFO_GAIN_HASH_CONTRACT_VERSION,
        content_hash=_hash("p3_info_gain_contract", payload),
    )


def serialize_info_gain_contract(
    contract: InfoGainEvaluationConfig,
) -> str:
    if not isinstance(contract, InfoGainEvaluationConfig):
        raise TypeError("contract must be InfoGainEvaluationConfig")
    return json.dumps(
        _canonical(contract.to_dict()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalize_definitions(
    provided: Sequence[FinancialP3CombinationDefinition] | None,
) -> tuple[FinancialP3CombinationDefinition, ...]:
    accepted = get_fin24_combination_definitions()
    values = accepted if provided is None else tuple(provided)
    if any(not isinstance(item, FinancialP3CombinationDefinition) for item in values):
        raise TypeError("combination definitions must be accepted FIN-24 definitions")
    ids = [item.combination_id for item in values]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate combination ID")
    if set(ids) != set(INFO_GAIN_COMBO_ORDER):
        raise ValueError("combination IDs must be exactly VQ, QG, CASHQ")
    by_id = {item.combination_id: item for item in values}
    accepted_by_id = {item.combination_id: item for item in accepted}
    for combo_id in INFO_GAIN_COMBO_ORDER:
        if by_id[combo_id].to_dict() != accepted_by_id[combo_id].to_dict():
            raise ValueError(f"{combo_id} definition drifted from FIN-P3-COMBOS")
    return tuple(by_id[combo_id] for combo_id in INFO_GAIN_COMBO_ORDER)


def _normalize_samples(
    provided: Sequence[CommonSampleContractReference] | None,
) -> tuple[CommonSampleContractReference, ...]:
    accepted = get_frozen_common_sample_references()
    values = accepted if provided is None else tuple(provided)
    if any(not isinstance(item, CommonSampleContractReference) for item in values):
        raise TypeError("common sample references have the wrong type")
    ids = [item.combo_id for item in values]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate common sample combo ID")
    if set(ids) != set(INFO_GAIN_COMBO_ORDER):
        raise ValueError("common samples must be exactly VQ, QG, CASHQ")
    by_id = {item.combo_id: item for item in values}
    accepted_by_id = {item.combo_id: item for item in accepted}
    for combo_id in INFO_GAIN_COMBO_ORDER:
        if by_id[combo_id].to_dict() != accepted_by_id[combo_id].to_dict():
            raise ValueError(f"{combo_id} common sample reference drifted")
    return tuple(by_id[combo_id] for combo_id in INFO_GAIN_COMBO_ORDER)


def _baseline_definitions(
    definitions: tuple[FinancialP3CombinationDefinition, ...],
) -> tuple[InfoGainBaselineDefinition, ...]:
    strongest = InfoGainBaselineDefinition(
        baseline_id="strongest_member_by_track",
        baseline_kind=BaselineKind.STRONGEST_MEMBER.value,
        strongest_member_rules=(
            StrongestMemberRule("M", "rank_ic_mean", "20D"),
            StrongestMemberRule("F", "relative_mae_improvement", None),
            StrongestMemberRule("R", "pr_auc", None),
        ),
    )
    average = InfoGainBaselineDefinition(
        baseline_id="all_member_simple_average",
        baseline_kind=BaselineKind.MEMBER_AVERAGE.value,
        member_average_method="simple_arithmetic_mean",
        comparable_scalar_metrics_only=True,
        all_members_required=True,
        unavailable_member_deletion_allowed=False,
    )
    primary = tuple(
        InfoGainBaselineDefinition(
            baseline_id=f"{item.combination_id.lower()}_primary_baseline",
            baseline_kind=BaselineKind.PRIMARY_BASELINE.value,
            combo_id=item.combination_id,
            primary_baseline_factor_id=item.reference_factor_id,
            selection_reason=(
                "FIN-P3-COMBOS predeclared reference from a completed MVP "
                "factor; not selected from FIN-24 results"
            ),
            definition_version=item.reference_formula_version,
        )
        for item in definitions
    )
    return (strongest, average, *primary)


def _metric(
    metric_id: str,
    display_name: str,
    source_field: str,
    direction: MetricBetterDirection,
    *,
    value_kind: str = "scalar",
    target_value: float | None = None,
    frozen_parameters: tuple[tuple[str, str], ...] = (),
) -> InfoGainMetricDefinition:
    if direction is MetricBetterDirection.HIGHER:
        absolute = "combo_metric_value - baseline_metric_value"
        relative = "absolute_increment / abs(baseline_metric_value)"
    elif direction is MetricBetterDirection.LOWER:
        absolute = "baseline_metric_value - combo_metric_value"
        relative = "absolute_increment / abs(baseline_metric_value)"
    elif direction is MetricBetterDirection.CLOSER_TO_TARGET:
        absolute = (
            "abs(baseline_metric_value - target_value) - "
            "abs(combo_metric_value - target_value)"
        )
        relative = (
            "absolute_increment / abs(baseline_metric_value - target_value)"
        )
    else:
        absolute = "not_applicable_detail_only"
        relative = "not_applicable_detail_only"
    return InfoGainMetricDefinition(
        metric_id=metric_id,
        display_name=display_name,
        source_field=source_field,
        better_direction=direction.value,
        baseline_rule="same_metric_same_common_sample_same_configuration",
        absolute_increment_formula=absolute,
        relative_increment_formula=relative,
        not_evaluable_rule=(
            "nonfinite_or_missing_or_not_run_or_insufficient_or_"
            f"abs_denominator_lte_{INFO_GAIN_ZERO_DENOMINATOR_EPSILON:g}"
        ),
        public_result_allowed=True,
        value_kind=value_kind,
        target_value=target_value,
        frozen_parameters=frozen_parameters,
    )


def _track_definitions() -> tuple[InfoGainTrackDefinition, ...]:
    m_metrics = (
        _metric("rank_ic_mean", "Rank IC mean", "rank_ic_mean", MetricBetterDirection.HIGHER),
        _metric("pearson_ic_mean", "Pearson IC mean", "pearson_ic_mean", MetricBetterDirection.HIGHER),
        _metric("rank_ic_ir", "Rank ICIR", "rank_ic_ir", MetricBetterDirection.HIGHER),
        _metric("pearson_ic_ir", "Pearson ICIR", "pearson_ic_ir", MetricBetterDirection.HIGHER),
        _metric("rank_ic_hac_t_stat", "Rank IC HAC t", "rank_ic_t_stat", MetricBetterDirection.HIGHER, frozen_parameters=(("statistic", "signed_hac_t"),)),
        _metric("pearson_ic_hac_t_stat", "Pearson IC HAC t", "pearson_ic_t_stat", MetricBetterDirection.HIGHER, frozen_parameters=(("statistic", "signed_hac_t"),)),
        _metric("rank_ic_positive_ratio", "Rank IC positive ratio", "rank_ic_positive_ratio", MetricBetterDirection.HIGHER),
        _metric("pearson_ic_positive_ratio", "Pearson IC positive ratio", "pearson_ic_positive_ratio", MetricBetterDirection.HIGHER),
        _metric("quantile_returns", "Grouped returns", "quantile_returns", MetricBetterDirection.DETAIL_ONLY, value_kind="vector_detail"),
        _metric("long_short_mean", "High-Low return", "long_short_mean", MetricBetterDirection.HIGHER),
        _metric("monotonicity_spearman", "Grouped monotonicity", "monotonicity_spearman", MetricBetterDirection.HIGHER),
        _metric("fm_mean_r2", "Control-adjusted mean R-squared", "fm_mean_r2", MetricBetterDirection.HIGHER, frozen_parameters=(("controls", "size+industry"),)),
        _metric("rank_ic_rolling_stability", "Rank IC rolling stability", "rank_ic_stability", MetricBetterDirection.DETAIL_ONLY, value_kind="object_detail"),
    )
    f_metrics = (
        _metric("oos_mae", "Out-of-sample MAE", "oos_mae", MetricBetterDirection.LOWER),
        _metric("relative_mae_improvement", "Relative MAE improvement", "relative_mae_improvement", MetricBetterDirection.HIGHER),
        _metric("residual_rank_ic", "Residual Rank IC", "residual_rank_ic", MetricBetterDirection.HIGHER),
        _metric("interval_coverage", "80% interval coverage", "interval_coverage", MetricBetterDirection.CLOSER_TO_TARGET, target_value=0.80, frozen_parameters=(("interval_level", "0.80"),)),
        _metric("interval_calibration_error", "80% interval calibration error", "abs(interval_coverage - 0.80)", MetricBetterDirection.LOWER, frozen_parameters=(("derivation", "abs(interval_coverage-0.80)"),)),
    )
    r_metrics = (
        _metric("pr_auc", "PR-AUC", "pr_auc", MetricBetterDirection.HIGHER),
        _metric("roc_auc", "ROC-AUC", "roc_auc", MetricBetterDirection.HIGHER),
        _metric("brier_score", "Brier Score", "brier_score", MetricBetterDirection.LOWER),
        _metric("top_k_hit_rate", "Top-K hit rate", "top_k_hit_rate", MetricBetterDirection.HIGHER, frozen_parameters=(("top_k", "10"),)),
        _metric("expected_calibration_error", "Expected calibration error", "expected_calibration_error", MetricBetterDirection.LOWER, frozen_parameters=(("calibration_bins", "5"),)),
    )
    return (
        InfoGainTrackDefinition(
            track_id="M",
            evidence_role="primary",
            evaluator_reference=(
                "backend.amr.financial_p2_m_enhancement."
                "evaluate_financial_p2_m_enhancement"
            ),
            metrics=m_metrics,
            horizons=("5D", "20D", "60D"),
            primary_horizon="20D",
        ),
        InfoGainTrackDefinition(
            track_id="F",
            evidence_role="supporting",
            evaluator_reference=(
                "backend.amr.financial_p2_f_evidence."
                "evaluate_financial_p2_f_evidence"
            ),
            metrics=f_metrics,
        ),
        InfoGainTrackDefinition(
            track_id="R",
            evidence_role="risk",
            evaluator_reference=(
                "backend.amr.financial_p2_r_evidence."
                "evaluate_financial_p2_r_evidence"
            ),
            metrics=r_metrics,
        ),
    )


def _status_policy() -> InfoGainStatusPolicy:
    return InfoGainStatusPolicy(
        calculation_status_mapping=(
            StatusSemanticMapping(
                "success", EvaluationStatus.COMPLETED.value, "EvaluationStatus"
            ),
            StatusSemanticMapping(
                "not_run", EvaluationStatus.NOT_RUN.value, "EvaluationStatus"
            ),
            StatusSemanticMapping(
                "not_evaluable",
                EvaluationStatus.NOT_APPLICABLE.value,
                "EvaluationStatus",
            ),
            StatusSemanticMapping(
                "insufficient_data",
                CommonSampleEvaluationStatus.INSUFFICIENT.value,
                "CommonSampleEvaluationStatus",
            ),
            StatusSemanticMapping(
                "failed",
                CombinationGateStatus.BLOCKED.value,
                "CombinationGateStatus",
            ),
        ),
        information_gain_assessments=tuple(
            item.value for item in InfoGainAssessment
        ),
        track_assessment_values=tuple(item.value for item in EvidenceAssessment),
        default_information_gain_assessment="not_assessed",
        materiality_threshold_status="not_frozen",
        production_status=INFO_GAIN_PRODUCTION_STATUS,
        positive_increment_upgrades_production=False,
        cross_track_composite_score_allowed=False,
    )


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("non-finite values are forbidden")
        return float(value)
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
