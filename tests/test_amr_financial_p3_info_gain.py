from __future__ import annotations

from dataclasses import replace

import pytest

from backend.amr.financial_p3_info_gain import (
    FinancialP3InfoGainRunConfig,
    evaluate_financial_p3_info_gain,
    serialize_financial_p3_info_gain_result,
)
from backend.amr.financial_p3_info_gain_contract import (
    build_financial_p3_info_gain_contract,
)
from tests.fixtures.synthetic_financial_p3_info_gain_cases import (
    make_configuration,
    make_inputs,
)


@pytest.fixture(scope="module")
def golden():
    combinations, baselines = make_inputs()
    return evaluate_financial_p3_info_gain(
        combinations, baselines, configuration=make_configuration()
    )


def test_fin25_evaluates_all_combos_on_the_frozen_m20_samples(golden):
    assert golden.audit.gate_status == "ready"
    assert golden.audit.errors == ()
    assert golden.audit.combo_count == 3
    assert [item.combo_id for item in golden.combinations] == ["VQ", "QG", "CASHQ"]
    for result in golden.combinations:
        assert len(result.metric_comparisons) == 39
        assert result.common_sample_fingerprint
        assert result.information_gain_assessment == "insufficient_evidence"
        assert result.production_status == "not production ready"


def test_strongest_member_rule_is_metric_frozen_and_tie_deterministic(golden):
    assert [item.strongest_m20_member_factor_id for item in golden.combinations] == [
        "EBIT_EV",
        "OCF_NP",
        "OCF_SALES",
    ]
    for result in golden.combinations:
        strongest = {
            item.baseline_factor_id
            for item in result.metric_comparisons
            if item.baseline_kind == "strongest_member"
        }
        assert strongest == {result.strongest_m20_member_factor_id}


def test_primary_baseline_is_predeclared_including_cashq_external_reference(golden):
    expected = {"VQ": "BP", "QG": "ROE", "CASHQ": "OCF_NP"}
    for result in golden.combinations:
        primary_ids = {
            item.baseline_factor_id
            for item in result.metric_comparisons
            if item.baseline_kind == "primary_baseline"
        }
        assert primary_ids == {expected[result.combo_id]}


def test_directional_formulas_and_zero_denominator_semantics(golden):
    for result in golden.combinations:
        completed = [
            item
            for item in result.metric_comparisons
            if item.calculation_status == "completed"
            and item.absolute_increment is not None
        ]
        assert completed
        for item in completed:
            assert item.absolute_increment == pytest.approx(
                item.combo_metric_value - item.baseline_metric_value
            )
            if item.relative_increment is None:
                assert item.reason_code == "RELATIVE_DENOMINATOR_LTE_EPSILON"
            else:
                assert item.relative_increment == pytest.approx(
                    item.absolute_increment / abs(item.baseline_metric_value)
                )


def test_unavailable_contract_metrics_and_contexts_remain_explicit(golden):
    unavailable_ids = {
        "pearson_ic_mean",
        "pearson_ic_ir",
        "rank_ic_hac_t_stat",
        "pearson_ic_hac_t_stat",
        "pearson_ic_positive_ratio",
        "rank_ic_rolling_stability",
    }
    for result in golden.combinations:
        unavailable = {
            item.metric_id
            for item in result.metric_comparisons
            if item.calculation_status == "not_run"
        }
        assert unavailable == unavailable_ids
        assert result.f_track_assessment == "insufficient"
        assert result.r_track_assessment == "insufficient"
        assert result.multiple_testing_status == "not_run"
        criteria = dict(result.core_criteria)
        assert criteria["period_concentration"].startswith("not_run")
        assert criteria["oos_direction_consistency"].startswith("not_run")


def test_coverage_tradeoff_reports_facts_without_inventing_thresholds(golden):
    for result in golden.combinations:
        report = result.coverage_tradeoff
        assert report.eligible_sample_count == 1044
        assert report.combo_common_sample_count == 900
        assert report.absolute_coverage_loss == 144
        assert report.relative_coverage_loss == pytest.approx(144 / 1044)
        assert len(report.per_period_common_sample_counts) == 18
        assert {count for _, count in report.per_period_common_sample_counts} == {50}
        assert report.per_period_coverage_ratio_status == (
            "insufficient_denominator_not_retained"
        )
        assert report.acceptance_threshold_status == (
            "not_frozen_report_facts_only"
        )
        assert report.automatic_rejection_applied is False


def test_positive_in_sample_directions_do_not_upgrade_overall_assessment(golden):
    assert golden.audit.information_gain_assessment == "insufficient_evidence"
    assert golden.audit.admission_status == "not_assessed"
    assert golden.audit.production_status == "not production ready"
    assert dict(golden.audit.production_gates) == {
        "data_gate": "not_passed_synthetic_only",
        "signal_gate": "not_assessed_oos_and_materiality_unavailable",
        "risk_gate": "not_run_R_context_not_frozen",
        "ops_gate": "not_assessed_research_output_only",
    }


def test_no_dynamic_weight_horizon_selection_or_cross_track_score(golden):
    assert golden.audit.dynamic_weighting_performed is False
    assert golden.audit.best_horizon_selected is False
    assert golden.audit.cross_track_composite_calculated is False


def test_serialization_and_hashes_are_deterministic(golden):
    combinations, baselines = make_inputs()
    repeated = evaluate_financial_p3_info_gain(
        combinations, baselines, configuration=make_configuration()
    )
    assert serialize_financial_p3_info_gain_result(golden) == (
        serialize_financial_p3_info_gain_result(repeated)
    )
    assert golden.audit.input_fingerprint == repeated.audit.input_fingerprint
    assert golden.audit.output_fingerprint == repeated.audit.output_fingerprint
    assert golden.audit.content_hash == repeated.audit.content_hash


def test_combination_output_drift_blocks():
    combinations, baselines = make_inputs()
    combinations = replace(
        combinations,
        combinations_audit=replace(
            combinations.combinations_audit, output_fingerprint="0" * 64
        ),
    )
    result = evaluate_financial_p3_info_gain(
        combinations, baselines, configuration=make_configuration()
    )
    assert result.audit.gate_status == "blocked"
    assert "COMBINATION_OUTPUT_DRIFT" in {item.code for item in result.audit.errors}


def test_contract_hash_mismatch_blocks():
    combinations, baselines = make_inputs()
    contract = replace(build_financial_p3_info_gain_contract(), content_hash="0" * 64)
    result = evaluate_financial_p3_info_gain(
        combinations,
        baselines,
        configuration=make_configuration(contract=contract),
    )
    assert result.audit.gate_status == "blocked"
    assert "CONTRACT_HASH_MISMATCH" in {item.code for item in result.audit.errors}


def test_member_baseline_incomplete_blocks():
    combinations, baselines = make_inputs()
    baselines = replace(
        baselines,
        audit=replace(
            baselines.audit,
            completed_member_count=10,
            failed_member_count=1,
        ),
    )
    result = evaluate_financial_p3_info_gain(
        combinations, baselines, configuration=make_configuration()
    )
    assert result.audit.gate_status == "blocked"
    assert "MEMBER_BASELINES_INCOMPLETE" in {
        item.code for item in result.audit.errors
    }


def test_common_sample_drift_blocks():
    combinations, baselines = make_inputs()
    bundles = list(baselines.bundles)
    bundles[0] = replace(bundles[0], common_sample_fingerprint="0" * 64)
    baselines = replace(baselines, bundles=tuple(bundles))
    result = evaluate_financial_p3_info_gain(
        combinations, baselines, configuration=make_configuration()
    )
    assert result.audit.gate_status == "blocked"
    assert "BASELINE_SAMPLE_DRIFT" in {item.code for item in result.audit.errors}


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("dynamic_weighting_allowed", True),
        ("best_horizon_selection_allowed", True),
        ("cross_track_composite_allowed", True),
        ("production_status", "ready"),
    ],
)
def test_run_configuration_boundaries_are_frozen(field_name, value):
    with pytest.raises(ValueError):
        make_configuration(**{field_name: value})


def test_wrong_argument_and_serialization_types_raise():
    combinations, baselines = make_inputs()
    with pytest.raises(TypeError):
        evaluate_financial_p3_info_gain(
            object(), baselines, configuration=make_configuration()
        )
    with pytest.raises(TypeError):
        evaluate_financial_p3_info_gain(
            combinations, object(), configuration=make_configuration()
        )
    with pytest.raises(TypeError):
        evaluate_financial_p3_info_gain(
            combinations, baselines, configuration=object()
        )
    with pytest.raises(TypeError):
        serialize_financial_p3_info_gain_result(object())
    with pytest.raises(TypeError):
        FinancialP3InfoGainRunConfig(run_id="x", contract=object())
