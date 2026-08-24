"""Contract and regression tests for INFO-GAIN-02B."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pandas as pd
import pytest

import backend.amr.financial_p3_info_gain_m_member_baselines as subject
from backend.amr.financial_mvp_m_evaluation import (
    FinancialMVPMEvaluationConfig,
    _evaluate_one_factor,
)
from backend.amr.financial_p3_info_gain_m_member_baselines import (
    ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT,
    ACCEPTED_M_EVALUATOR_SOURCE_SHA256,
    EXPECTED_COMMON_SAMPLE_FINGERPRINTS,
    EXPECTED_MEMBER_DIRECTIONS,
    M_EVALUATOR_REFERENCE,
    M_METRIC_SET,
    MMemberBaselineConfig,
    evaluate_financial_p3_info_gain_m_member_baselines,
    serialize_m_member_baseline_result,
)
from tests.fixtures.synthetic_financial_p3_info_gain_m_member_baseline_cases import (
    make_configuration,
    make_prepared_inputs,
)


@pytest.fixture(scope="module")
def prepared():
    return make_prepared_inputs()


@pytest.fixture(scope="module")
def result(prepared):
    return evaluate_financial_p3_info_gain_m_member_baselines(
        prepared,
        configuration=make_configuration(),
    )


def test_golden_gate_and_fingerprints(result):
    assert result.audit.gate_status == "ready"
    assert not result.audit.errors
    assert result.audit.input_fingerprint == ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT
    assert result.audit.output_fingerprint == "6a60ae604713997965de4322a2c3b0b5e83619ae92b3cb2ca8c0b3eade8baa2f"
    assert result.audit.content_hash == "80014488e67e5cb68221c4c363fde010e5d752af845553081cafb42778beee2c"


def test_all_eleven_combo_member_runs_are_completed(result):
    assert tuple(bundle.combo_id for bundle in result.bundles) == ("VQ", "QG", "CASHQ")
    assert result.audit.combo_count == 3
    assert result.audit.member_run_count == 11
    assert result.audit.completed_run_count == 11
    assert result.audit.partial_run_count == 0
    assert result.audit.not_run_count == 0
    for bundle in result.bundles:
        assert bundle.calculation_status == "completed"
        assert tuple((run.member_factor_id, run.frozen_direction) for run in bundle.member_runs) == EXPECTED_MEMBER_DIRECTIONS[bundle.combo_id]


def test_each_run_uses_exact_common_sample_and_m20(result):
    for bundle in result.bundles:
        assert bundle.common_sample_fingerprint == EXPECTED_COMMON_SAMPLE_FINGERPRINTS[bundle.combo_id]
        assert bundle.evaluation_period_count == 18
        assert bundle.common_sample_row_count == 900
        for run in bundle.member_runs:
            assert run.common_sample_fingerprint == bundle.common_sample_fingerprint
            assert run.evaluation_context == "M:20D"
            assert run.evaluation_result.horizon == "20"
            assert run.evaluation_result.total_dates == 18
            assert run.evaluation_result.evaluated_dates == 18
            assert run.evaluation_result.excluded_dates == 0
            assert run.evaluation_result.total_observations == 900


def test_existing_evaluator_and_metric_set_are_frozen(result):
    assert result.audit.existing_m_evaluator_reused is True
    assert result.audit.evaluator_source_sha256 == ACCEPTED_M_EVALUATOR_SOURCE_SHA256
    assert result.audit.m_evaluator_call_count == 11
    assert result.audit.f_evaluator_call_count == 0
    assert result.audit.r_evaluator_call_count == 0
    for bundle in result.bundles:
        for run in bundle.member_runs:
            assert run.evaluator_reference == M_EVALUATOR_REFERENCE
            assert run.evaluator_source_sha256 == ACCEPTED_M_EVALUATOR_SOURCE_SHA256
            assert run.metric_set == M_METRIC_SET


def test_m_metrics_include_ic_hac_group_and_monotonicity(result):
    for bundle in result.bundles:
        for run in bundle.member_runs:
            evaluated = run.evaluation_result
            assert evaluated.rank_ic_mean is not None
            assert evaluated.rank_ic_ir is not None
            assert evaluated.rank_ic_t_stat is not None
            assert evaluated.rank_ic_positive_ratio is not None
            assert evaluated.pearson_ic_mean is not None
            assert evaluated.pearson_ic_ir is not None
            assert evaluated.pearson_ic_t_stat is not None
            assert evaluated.pearson_ic_positive_ratio is not None
            assert set(evaluated.quantile_returns) == {"1", "2", "3", "4", "5"}
            assert evaluated.long_short_mean is not None
            assert evaluated.monotonicity_spearman is not None
            assert len(evaluated.daily_results) == 18
            assert len(evaluated.daily_group_returns) == 18


def test_representative_golden_metrics(result):
    runs = {(bundle.combo_id, run.member_factor_id): run for bundle in result.bundles for run in bundle.member_runs}
    assert runs[("VQ", "BP")].evaluation_result.rank_ic_mean == pytest.approx(0.8342745981709474)
    assert runs[("VQ", "BP")].evaluation_result.long_short_mean == pytest.approx(0.031904917391810055)
    assert runs[("QG", "PROFIT_GROWTH")].evaluation_result.rank_ic_mean == pytest.approx(0.8584018940909696)
    assert runs[("CASHQ", "ACCRUALS")].evaluation_result.rank_ic_mean == pytest.approx(0.8726797385620914)


def test_positive_member_matches_direct_existing_evaluator(prepared, result):
    package = prepared.packages[0]
    observations = package.get_member_observations()
    member = observations[observations["member_factor_id"] == "BP"]
    frame = pd.DataFrame({
        "date": member["evaluation_date"].astype(str),
        "factor_value": pd.to_numeric(member["factor_value"]),
        "forward_return": pd.to_numeric(member["forward_return"]),
    }).sort_values(["date"], kind="mergesort").reset_index(drop=True)
    config = FinancialMVPMEvaluationConfig(
        evaluation_dates=tuple(sorted(frame["date"].unique())),
        evaluation_calendar_reference="synthetic-calendar://month-end-2024",
        evaluation_calendar_version="synthetic-month-end-v1",
        hac_max_lag=1,
    )
    run = result.bundles[0].member_runs[0]
    direct = _evaluate_one_factor(
        factor_id="BP",
        factor_frame=frame,
        return_set_id=run.return_set_id,
        configuration=config,
    )
    assert run.evaluation_result.to_dict() == direct.to_dict()


def test_negative_accruals_direction_is_applied(prepared, result):
    package = prepared.packages[2]
    observations = package.get_member_observations()
    member = observations[observations["member_factor_id"] == "ACCRUALS"]
    frame = pd.DataFrame({
        "date": member["evaluation_date"].astype(str),
        "factor_value": pd.to_numeric(member["factor_value"]),
        "forward_return": pd.to_numeric(member["forward_return"]),
    }).sort_values(["date"], kind="mergesort").reset_index(drop=True)
    config = FinancialMVPMEvaluationConfig(
        evaluation_dates=tuple(sorted(frame["date"].unique())),
        evaluation_calendar_reference="synthetic-calendar://month-end-2024",
        evaluation_calendar_version="synthetic-month-end-v1",
        hac_max_lag=1,
    )
    raw = _evaluate_one_factor(
        factor_id="ACCRUALS",
        factor_frame=frame,
        return_set_id="raw-direction-control",
        configuration=config,
    )
    accepted = result.bundles[2].member_runs[2]
    assert accepted.direction_multiplier == -1
    assert accepted.evaluation_result.rank_ic_mean == pytest.approx(-raw.rank_ic_mean)
    assert accepted.evaluation_result.long_short_mean == pytest.approx(-raw.long_short_mean)


def test_no_selection_increment_or_other_track_work(result):
    audit = result.audit
    assert audit.combination_evaluated is False
    assert audit.strongest_member_selected is False
    assert audit.information_gain_calculated is False
    assert audit.f_evaluator_call_count == audit.r_evaluator_call_count == 0
    assert audit.production_status == "not production ready"


def test_input_is_not_mutated(prepared):
    before = prepared.to_dict()
    evaluate_financial_p3_info_gain_m_member_baselines(
        prepared,
        configuration=make_configuration(),
    )
    assert prepared.to_dict() == before


def test_serialization_is_deterministic_and_strict_json(prepared, result):
    repeated = evaluate_financial_p3_info_gain_m_member_baselines(
        prepared,
        configuration=make_configuration(),
    )
    first = serialize_m_member_baseline_result(result)
    assert first == serialize_m_member_baseline_result(repeated)
    decoded = json.loads(first)
    assert decoded["audit"]["gate_status"] == "ready"
    assert "NaN" not in first and "Infinity" not in first


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("hac_max_lag", 0),
        ("accepted_02a_output_fingerprint", "0" * 64),
        ("accepted_contract_hash", "0" * 64),
        ("expected_evaluator_source_sha256", "0" * 64),
        ("synthetic_test_only", False),
        ("run_id", ""),
    ],
)
def test_configuration_rejects_policy_drift(field_name, value):
    with pytest.raises(ValueError):
        make_configuration(**{field_name: value})


def test_wrong_argument_types_are_rejected(prepared):
    with pytest.raises(TypeError):
        evaluate_financial_p3_info_gain_m_member_baselines(
            object(), configuration=make_configuration()
        )
    with pytest.raises(TypeError):
        evaluate_financial_p3_info_gain_m_member_baselines(
            prepared, configuration=object()
        )
    with pytest.raises(TypeError):
        serialize_m_member_baseline_result(object())


def test_02a_fingerprint_drift_blocks_before_calls(prepared):
    drifted_audit = dataclasses.replace(prepared.audit, output_fingerprint="0" * 64)
    drifted = dataclasses.replace(prepared, audit=drifted_audit)
    result = evaluate_financial_p3_info_gain_m_member_baselines(
        drifted,
        configuration=make_configuration(),
    )
    assert result.audit.gate_status == "blocked"
    assert result.audit.m_evaluator_call_count == 0
    assert "INFO_GAIN_02A_FINGERPRINT_MISMATCH" in {item.code for item in result.audit.errors}


def test_package_content_drift_blocks_before_calls(prepared):
    package = prepared.packages[0]
    frame = package.get_member_observations()
    frame.loc[0, "factor_value"] += 1.0
    drifted_package = dataclasses.replace(package, _member_observations=frame)
    drifted = dataclasses.replace(prepared, packages=(drifted_package, *prepared.packages[1:]))
    result = evaluate_financial_p3_info_gain_m_member_baselines(
        drifted,
        configuration=make_configuration(),
    )
    assert result.audit.gate_status == "blocked"
    assert result.audit.m_evaluator_call_count == 0
    assert "INFO_GAIN_02A_CONTENT_MISMATCH" in {item.code for item in result.audit.errors}


def test_evaluator_source_drift_blocks_before_calls(prepared, monkeypatch):
    monkeypatch.setattr(subject, "_evaluator_source_sha256", lambda: "0" * 64)
    result = evaluate_financial_p3_info_gain_m_member_baselines(
        prepared,
        configuration=make_configuration(),
    )
    assert result.audit.gate_status == "blocked"
    assert result.audit.m_evaluator_call_count == 0
    assert "M_EVALUATOR_HASH_MISMATCH" in {item.code for item in result.audit.errors}


def test_evaluator_calls_are_one_per_combo_member(prepared, monkeypatch):
    original = subject._evaluate_one_factor
    calls = []

    def spy(**kwargs):
        calls.append(kwargs["factor_id"])
        return original(**kwargs)

    monkeypatch.setattr(subject, "_evaluate_one_factor", spy)
    monkeypatch.setattr(subject, "_evaluator_source_sha256", lambda: ACCEPTED_M_EVALUATOR_SOURCE_SHA256)
    result = evaluate_financial_p3_info_gain_m_member_baselines(
        prepared,
        configuration=make_configuration(),
    )
    assert result.audit.gate_status == "ready"
    assert calls == ["BP", "EBIT_EV", "ROE", "OCF_NP", "SALES_GROWTH", "PROFIT_GROWTH", "ROE", "OCF_NP", "ROA", "OCF_SALES", "ACCRUALS"]


def test_evaluator_failure_is_retained_and_blocks(prepared, monkeypatch):
    original = subject._evaluate_one_factor

    def fail_one(**kwargs):
        if kwargs["factor_id"] == "EBIT_EV":
            raise RuntimeError("synthetic evaluator failure")
        return original(**kwargs)

    monkeypatch.setattr(subject, "_evaluate_one_factor", fail_one)
    monkeypatch.setattr(subject, "_evaluator_source_sha256", lambda: ACCEPTED_M_EVALUATOR_SOURCE_SHA256)
    result = evaluate_financial_p3_info_gain_m_member_baselines(
        prepared,
        configuration=make_configuration(),
    )
    assert result.audit.gate_status == "blocked"
    assert result.audit.m_evaluator_call_count == 11
    assert result.audit.member_run_count == 10
    assert result.audit.not_run_count == 1
    assert "M_EVALUATOR_CALL_FAILED" in {item.code for item in result.audit.errors}


def test_adapter_contains_no_statistical_reimplementation():
    source = Path(subject.__file__).read_text(encoding="utf-8")
    assert "scipy" not in source
    assert "spearmanr" not in source
    assert "pearsonr" not in source
    assert "hac_t_stat" not in source
    assert "evaluate_group_returns" not in source
    assert "_evaluate_one_factor(" in source


def test_source_hash_pin_matches_protected_evaluator():
    assert subject._evaluator_source_sha256() == ACCEPTED_M_EVALUATOR_SOURCE_SHA256


def test_dataclasses_are_frozen():
    config = MMemberBaselineConfig(run_id="frozen")
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.hac_max_lag = 2
