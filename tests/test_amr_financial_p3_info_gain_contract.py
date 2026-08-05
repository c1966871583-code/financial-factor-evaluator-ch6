"""Acceptance tests for FIN-P3-INFO-GAIN-01."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from backend.amr.financial_p3_combinations import (
    get_fin24_combination_definitions,
)
from backend.amr.financial_p3_info_gain_contract import (
    INFO_GAIN_ADMISSION_STATUS,
    INFO_GAIN_COMBO_ORDER,
    INFO_GAIN_CONCLUSION_BOUNDARY,
    INFO_GAIN_CONTRACT_VERSION,
    INFO_GAIN_PRODUCTION_STATUS,
    INFO_GAIN_ZERO_DENOMINATOR_EPSILON,
    BaselineKind,
    CommonSampleContractReference,
    InfoGainAssessment,
    MetricBetterDirection,
    build_financial_p3_info_gain_contract,
    get_frozen_common_sample_references,
    serialize_info_gain_contract,
)
from tests.fixtures.synthetic_financial_p3_info_gain_contract_cases import (
    make_contract,
)


@pytest.fixture(scope="module")
def contract():
    return make_contract()


def _tracks(contract):
    return {item.track_id: item for item in contract.track_definitions}


def _metrics(contract, track_id):
    return {
        item.metric_id: item for item in _tracks(contract)[track_id].metrics
    }


def _baselines(contract, kind):
    return [
        item for item in contract.baseline_definitions
        if item.baseline_kind == kind
    ]


class TestAcceptedPredecessorFacts:
    def test_exact_combo_order(self, contract):
        assert tuple(
            item.combo_id for item in contract.combination_references
        ) == INFO_GAIN_COMBO_ORDER

    def test_exact_members_and_directions(self, contract):
        by_id = {
            item.combo_id: item for item in contract.combination_references
        }
        assert by_id["VQ"].member_directions == (
            ("BP", "positive"),
            ("EBIT_EV", "positive"),
            ("ROE", "positive"),
            ("OCF_NP", "positive"),
        )
        assert by_id["QG"].member_directions == (
            ("SALES_GROWTH", "positive"),
            ("PROFIT_GROWTH", "positive"),
            ("ROE", "positive"),
            ("OCF_NP", "positive"),
        )
        assert by_id["CASHQ"].member_directions == (
            ("ROA", "positive"),
            ("OCF_SALES", "positive"),
            ("ACCRUALS", "negative"),
        )

    def test_definition_hashes_match_upstream(self, contract):
        expected = {
            item.combination_id: item.content_hash
            for item in get_fin24_combination_definitions()
        }
        assert {
            item.combo_id: item.definition_hash
            for item in contract.combination_references
        } == expected

    @pytest.mark.parametrize(
        ("combo_id", "fingerprint"),
        [
            (
                "VQ",
                "ab58b5b1cf5e975563838f9e5aecd367f9c70a25d10d2678c69c6fa4a2f037d1",
            ),
            (
                "QG",
                "3e470edf7b8b8e065ec6f373e2e5872e1cabf42e360212928ecc7276834839ae",
            ),
            (
                "CASHQ",
                "c3d21f755aae395d179e23b361948bcb232f4e52625d12e5dd98bf013ebcd4f7",
            ),
        ],
    )
    def test_common_sample_is_exact(self, contract, combo_id, fingerprint):
        reference = next(
            item for item in contract.common_sample_references
            if item.combo_id == combo_id
        )
        assert reference.evaluation_period_count == 18
        assert reference.common_sample_row_count == 900
        assert reference.common_sample_fingerprint == fingerprint

    def test_only_20d_context_is_currently_available(self, contract):
        for reference in contract.common_sample_references:
            assert reference.available_evaluation_contexts == ("M:20D",)
            assert reference.not_run_evaluation_contexts == (
                "M:5D",
                "M:60D",
                "F",
                "R",
            )

    @pytest.mark.parametrize("field_name,value", [
        ("evaluation_period_count", 17),
        ("common_sample_row_count", 899),
        ("common_sample_fingerprint", "0" * 64),
        ("available_evaluation_contexts", ("M:5D",)),
    ])
    def test_rejects_common_sample_drift(self, field_name, value):
        references = get_frozen_common_sample_references()
        with pytest.raises(ValueError):
            drifted = replace(references[0], **{field_name: value})
            build_financial_p3_info_gain_contract(
                common_sample_references=(drifted, *references[1:])
            )


class TestBaselineContract:
    def test_strongest_member_is_track_specific(self, contract):
        baseline = _baselines(
            contract, BaselineKind.STRONGEST_MEMBER.value
        )[0]
        assert tuple(
            (item.track_id, item.metric_id, item.horizon)
            for item in baseline.strongest_member_rules
        ) == (
            ("M", "rank_ic_mean", "20D"),
            ("F", "relative_mae_improvement", None),
            ("R", "pr_auc", None),
        )
        assert all(
            item.tie_break_rule == "factor_id_lexicographic"
            and item.fixed_members_only
            for item in baseline.strongest_member_rules
        )

    def test_member_average_is_strict_simple_mean(self, contract):
        baseline = _baselines(
            contract, BaselineKind.MEMBER_AVERAGE.value
        )[0]
        assert baseline.member_average_method == "simple_arithmetic_mean"
        assert baseline.comparable_scalar_metrics_only is True
        assert baseline.all_members_required is True
        assert baseline.unavailable_member_deletion_allowed is False

    def test_primary_baselines_are_predeclared(self, contract):
        baselines = {
            item.combo_id: item
            for item in _baselines(
                contract, BaselineKind.PRIMARY_BASELINE.value
            )
        }
        assert {
            combo_id: item.primary_baseline_factor_id
            for combo_id, item in baselines.items()
        } == {"VQ": "BP", "QG": "ROE", "CASHQ": "OCF_NP"}
        assert all(
            "not selected from FIN-24 results" in item.selection_reason
            for item in baselines.values()
        )

    def test_no_automatic_selection_is_authorized(self, contract):
        assert contract.automatic_best_member_selection_allowed is False
        assert contract.automatic_best_horizon_selection_allowed is False
        assert contract.dynamic_weighting_allowed is False


class TestMetricDirectionContract:
    @pytest.mark.parametrize(
        ("track_id", "metric_id"),
        [
            ("M", "rank_ic_mean"),
            ("M", "pearson_ic_mean"),
            ("M", "rank_ic_ir"),
            ("M", "rank_ic_hac_t_stat"),
            ("M", "long_short_mean"),
            ("M", "monotonicity_spearman"),
            ("M", "fm_mean_r2"),
            ("F", "relative_mae_improvement"),
            ("F", "residual_rank_ic"),
            ("R", "pr_auc"),
            ("R", "roc_auc"),
            ("R", "top_k_hit_rate"),
        ],
    )
    def test_higher_is_better(self, contract, track_id, metric_id):
        metric = _metrics(contract, track_id)[metric_id]
        assert metric.better_direction == MetricBetterDirection.HIGHER.value
        assert metric.absolute_increment_formula == (
            "combo_metric_value - baseline_metric_value"
        )

    @pytest.mark.parametrize(
        ("track_id", "metric_id"),
        [
            ("F", "oos_mae"),
            ("F", "interval_calibration_error"),
            ("R", "brier_score"),
            ("R", "expected_calibration_error"),
        ],
    )
    def test_lower_is_better(self, contract, track_id, metric_id):
        metric = _metrics(contract, track_id)[metric_id]
        assert metric.better_direction == MetricBetterDirection.LOWER.value
        assert metric.absolute_increment_formula == (
            "baseline_metric_value - combo_metric_value"
        )

    def test_interval_coverage_is_closer_to_target(self, contract):
        metric = _metrics(contract, "F")["interval_coverage"]
        assert metric.better_direction == "closer_to_target"
        assert metric.target_value == 0.80
        assert metric.absolute_increment_formula == (
            "abs(baseline_metric_value - target_value) - "
            "abs(combo_metric_value - target_value)"
        )

    def test_grouped_returns_are_detail_only(self, contract):
        metric = _metrics(contract, "M")["quantile_returns"]
        assert metric.better_direction == "detail_only"
        assert metric.value_kind == "vector_detail"
        assert metric.absolute_increment_formula == "not_applicable_detail_only"

    def test_hac_is_signed_and_ordinary_t_is_absent(self, contract):
        m_metrics = _metrics(contract, "M")
        assert dict(
            m_metrics["rank_ic_hac_t_stat"].frozen_parameters
        )["statistic"] == "signed_hac_t"
        assert "ordinary_t_stat" not in m_metrics

    def test_m_horizons_are_separate_and_20d_is_primary(self, contract):
        track = _tracks(contract)["M"]
        assert track.horizons == ("5D", "20D", "60D")
        assert track.primary_horizon == "20D"

    def test_f_and_r_frozen_parameters(self, contract):
        f_metrics = _metrics(contract, "F")
        r_metrics = _metrics(contract, "R")
        assert dict(
            f_metrics["interval_calibration_error"].frozen_parameters
        )["derivation"] == "abs(interval_coverage-0.80)"
        assert dict(r_metrics["top_k_hit_rate"].frozen_parameters) == {
            "top_k": "10"
        }
        assert dict(
            r_metrics["expected_calibration_error"].frozen_parameters
        ) == {"calibration_bins": "5"}

    def test_control_adjusted_metric_is_frozen(self, contract):
        metric = _metrics(contract, "M")["fm_mean_r2"]
        assert metric.better_direction == "higher"
        assert dict(metric.frozen_parameters) == {
            "controls": "size+industry"
        }

    def test_relative_increment_and_zero_denominator_are_frozen(self, contract):
        metric = _metrics(contract, "M")["rank_ic_mean"]
        assert metric.relative_increment_formula == (
            "absolute_increment / abs(baseline_metric_value)"
        )
        assert INFO_GAIN_ZERO_DENOMINATOR_EPSILON == 1e-12
        assert "abs_denominator_lte_1e-12" in metric.not_evaluable_rule


class TestStatusCoverageAndBoundary:
    def test_status_mapping_reuses_project_enums(self, contract):
        assert tuple(
            (item.semantic, item.project_status, item.source_enum)
            for item in contract.status_policy.calculation_status_mapping
        ) == (
            ("success", "completed", "EvaluationStatus"),
            ("not_run", "not_run", "EvaluationStatus"),
            ("not_evaluable", "not_applicable", "EvaluationStatus"),
            (
                "insufficient_data",
                "insufficient",
                "CommonSampleEvaluationStatus",
            ),
            ("failed", "blocked", "CombinationGateStatus"),
        )

    def test_information_gain_assessment_is_separate(self, contract):
        assert contract.status_policy.information_gain_assessments == tuple(
            item.value for item in InfoGainAssessment
        )
        assert (
            contract.status_policy.default_information_gain_assessment
            == INFO_GAIN_ADMISSION_STATUS
        )
        assert contract.status_policy.materiality_threshold_status == "not_frozen"

    def test_no_cross_track_score_or_production_upgrade(self, contract):
        assert contract.cross_track_composite_score_allowed is False
        assert contract.status_policy.cross_track_composite_score_allowed is False
        assert contract.status_policy.positive_increment_upgrades_production is False
        assert contract.production_status == INFO_GAIN_PRODUCTION_STATUS

    def test_coverage_is_fact_only_and_per_period(self, contract):
        coverage = contract.coverage_tradeoff_definition
        assert coverage.per_period_reporting_required is True
        assert coverage.exclusion_reason_reporting_required is True
        assert coverage.acceptance_threshold_status == (
            "not_frozen_report_facts_only"
        )
        assert coverage.automatic_rejection_allowed is False
        assert "per_period_coverage_ratio" in coverage.required_fields

    def test_contract_cannot_compute_or_execute(self, contract):
        assert contract.real_result_computation_allowed is False
        assert contract.member_baseline_recalculation_allowed is False
        assert contract.evaluation_pipeline_execution_allowed is False
        assert contract.conclusion_boundary == INFO_GAIN_CONCLUSION_BOUNDARY

    @pytest.mark.parametrize(
        "field_name",
        [
            "real_result_computation_allowed",
            "member_baseline_recalculation_allowed",
            "evaluation_pipeline_execution_allowed",
            "dynamic_weighting_allowed",
            "automatic_best_member_selection_allowed",
            "automatic_best_horizon_selection_allowed",
            "cross_track_composite_score_allowed",
        ],
    )
    def test_rejects_forbidden_capability(self, contract, field_name):
        with pytest.raises(ValueError):
            replace(contract, **{field_name: True})


class TestDeterminismAndValidation:
    def test_reversed_inputs_produce_identical_contract(self):
        normal = make_contract()
        reversed_input = make_contract(
            reverse_definitions=True,
            reverse_samples=True,
        )
        assert reversed_input == normal
        assert reversed_input.content_hash == normal.content_hash
        assert serialize_info_gain_contract(reversed_input) == (
            serialize_info_gain_contract(normal)
        )

    def test_serialization_is_stable_and_valid_json(self, contract):
        first = serialize_info_gain_contract(contract)
        second = serialize_info_gain_contract(contract)
        assert first == second
        parsed = json.loads(first)
        assert parsed["contract_version"] == INFO_GAIN_CONTRACT_VERSION
        assert parsed["content_hash"] == contract.content_hash

    def test_contract_is_frozen(self, contract):
        with pytest.raises(FrozenInstanceError):
            contract.production_status = "ready"

    def test_contract_version_is_hash_bound_and_frozen(self, contract):
        with pytest.raises(ValueError):
            replace(contract, contract_version="drift")

    def test_duplicate_definition_is_rejected(self):
        definitions = get_fin24_combination_definitions()
        with pytest.raises(ValueError, match="duplicate"):
            build_financial_p3_info_gain_contract(
                combination_definitions=(
                    definitions[0], definitions[0], definitions[2]
                )
            )

    def test_missing_common_sample_is_rejected(self):
        with pytest.raises(ValueError, match="exactly"):
            build_financial_p3_info_gain_contract(
                common_sample_references=(
                    get_frozen_common_sample_references()[0],
                )
            )

    def test_unknown_common_sample_is_rejected(self):
        reference = get_frozen_common_sample_references()[0]
        unknown = CommonSampleContractReference(
            combo_id="UNKNOWN",
            combo_definition_version=reference.combo_definition_version,
            common_sample_reference=reference.common_sample_reference,
            common_sample_fingerprint=reference.common_sample_fingerprint,
            evaluation_period_count=18,
            common_sample_row_count=900,
            sample_rule_version=reference.sample_rule_version,
            available_evaluation_contexts=("M:20D",),
            not_run_evaluation_contexts=("M:5D", "M:60D", "F", "R"),
        )
        with pytest.raises(ValueError, match="exactly"):
            build_financial_p3_info_gain_contract(
                common_sample_references=(
                    unknown,
                    *get_frozen_common_sample_references()[1:],
                )
            )

    def test_serialized_contract_has_no_runtime_result_containers(self, contract):
        payload = contract.to_dict()
        forbidden = {
            "combo_metric_value",
            "baseline_metric_value",
            "absolute_increment",
            "relative_increment",
            "best_member",
            "overall_score",
            "execution_timestamp",
        }
        assert forbidden.isdisjoint(payload)
