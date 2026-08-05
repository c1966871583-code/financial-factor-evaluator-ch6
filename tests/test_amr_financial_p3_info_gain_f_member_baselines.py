"""Contract tests for INFO-GAIN-02C formal F-track not_run baselines."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

import backend.amr.financial_p3_info_gain_f_member_baselines as subject
from backend.amr.financial_p3_info_gain_f_member_baselines import (
    ACCEPTED_F_EVALUATOR_SOURCE_SHA256,
    ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT,
    EXPECTED_MEMBER_DIRECTIONS,
    F_METRICS,
    FMemberBaselineConfig,
    evaluate_financial_p3_info_gain_f_member_baselines,
    serialize_f_member_baseline_result,
)
from tests.fixtures.synthetic_financial_p3_info_gain_f_member_baseline_cases import (
    make_configuration,
    make_prepared_inputs,
)


@pytest.fixture(scope="module")
def prepared():
    return make_prepared_inputs()


@pytest.fixture(scope="module")
def result(prepared):
    return evaluate_financial_p3_info_gain_f_member_baselines(prepared, configuration=make_configuration())


def test_golden_formal_not_run_result(result):
    assert result.audit.gate_status == "ready"
    assert result.audit.input_fingerprint == ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT
    assert result.audit.output_fingerprint == "657bd843d245aa2379105612acfe0cabc7c09da538819a2abd6719352c22e64c"
    assert result.audit.content_hash == "ba48f11804582835a4a7313bd794cf58000e351dc1af23ed2b77c4fc8cb20adb"
    assert result.audit.member_run_count == result.audit.not_run_count == 11
    assert result.audit.completed_run_count == 0


def test_all_frozen_members_have_non_numeric_not_run_metrics(result):
    assert tuple(bundle.combo_id for bundle in result.bundles) == ("VQ", "QG", "CASHQ")
    for bundle in result.bundles:
        assert bundle.calculation_status == "not_run"
        assert tuple((run.member_factor_id, run.frozen_direction) for run in bundle.member_runs) == EXPECTED_MEMBER_DIRECTIONS[bundle.combo_id]
        for run in bundle.member_runs:
            assert run.calculation_status == "not_run"
            assert run.not_run_reason == "F_CONTEXT_NOT_FROZEN"
            assert dict(run.metric_statuses) == {metric: "not_run" for metric in F_METRICS}
            assert dict(run.metric_values) == {metric: None for metric in F_METRICS}
            assert run.issue_codes == ("F_CONTEXT_NOT_FROZEN",)


def test_no_evaluator_or_cross_track_work_is_performed(result):
    audit = result.audit
    assert audit.f_evaluator_call_count == audit.m_evaluator_call_count == audit.r_evaluator_call_count == 0
    assert audit.existing_F_evaluator_identified is True
    assert audit.forecast_input_constructed is False
    assert audit.metrics_calculated is False
    assert audit.combination_evaluated is False
    assert audit.strongest_member_selected is False
    assert audit.information_gain_calculated is False
    assert audit.production_status == "not production ready"


def test_existing_f_evaluator_hash_is_pinned(result):
    assert result.audit.evaluator_source_sha256 == ACCEPTED_F_EVALUATOR_SOURCE_SHA256
    assert subject._evaluator_source_sha256() == ACCEPTED_F_EVALUATOR_SOURCE_SHA256


def test_input_is_not_mutated_and_serialization_is_deterministic(prepared, result):
    before = prepared.to_dict()
    repeated = evaluate_financial_p3_info_gain_f_member_baselines(prepared, configuration=make_configuration())
    assert prepared.to_dict() == before
    serialized = serialize_f_member_baseline_result(result)
    assert serialized == serialize_f_member_baseline_result(repeated)
    assert json.loads(serialized)["audit"]["gate_status"] == "ready"
    assert "NaN" not in serialized and "Infinity" not in serialized


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("run_id", ""),
        ("accepted_02a_output_fingerprint", "0" * 64),
        ("accepted_contract_hash", "0" * 64),
        ("expected_evaluator_source_sha256", "0" * 64),
        ("synthetic_test_only", False),
    ],
)
def test_configuration_rejects_drift(field_name, value):
    with pytest.raises(ValueError):
        make_configuration(**{field_name: value})


def test_type_checks(prepared):
    with pytest.raises(TypeError):
        evaluate_financial_p3_info_gain_f_member_baselines(object(), configuration=make_configuration())
    with pytest.raises(TypeError):
        evaluate_financial_p3_info_gain_f_member_baselines(prepared, configuration=object())
    with pytest.raises(TypeError):
        serialize_f_member_baseline_result(object())


def test_02a_fingerprint_drift_blocks_before_any_evaluator_call(prepared):
    drifted = dataclasses.replace(prepared, audit=dataclasses.replace(prepared.audit, output_fingerprint="0" * 64))
    result = evaluate_financial_p3_info_gain_f_member_baselines(drifted, configuration=make_configuration())
    assert result.audit.gate_status == "blocked"
    assert result.audit.f_evaluator_call_count == 0
    assert "INFO_GAIN_02A_FINGERPRINT_MISMATCH" in {item.code for item in result.audit.errors}


def test_f_context_ready_drift_is_blocked_not_evaluated(prepared):
    package = prepared.packages[0]
    f_track = next(track for track in package.track_inputs if track.track_id == "F")
    changed_track = dataclasses.replace(f_track, preparation_status="ready", evaluation_contexts=("F",), label_references=("synthetic",), evaluation_config_reference="forbidden")
    changed_tracks = tuple(changed_track if item.track_id == "F" else item for item in package.track_inputs)
    changed_package = dataclasses.replace(package, track_inputs=changed_tracks)
    drifted = dataclasses.replace(prepared, packages=(changed_package, *prepared.packages[1:]))
    result = evaluate_financial_p3_info_gain_f_member_baselines(drifted, configuration=make_configuration())
    assert result.audit.gate_status == "blocked"
    assert result.audit.f_evaluator_call_count == 0
    assert "F_CONTEXT_STATE_DRIFT" in {item.code for item in result.audit.errors}


def test_f_evaluator_hash_drift_blocks(prepared, monkeypatch):
    monkeypatch.setattr(subject, "_evaluator_source_sha256", lambda: "0" * 64)
    result = evaluate_financial_p3_info_gain_f_member_baselines(prepared, configuration=make_configuration())
    assert result.audit.gate_status == "blocked"
    assert "F_EVALUATOR_HASH_MISMATCH" in {item.code for item in result.audit.errors}


def test_no_f_evaluator_call_even_if_it_would_fail(prepared, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("F evaluator must not be called without frozen F context")

    monkeypatch.setattr(subject, "evaluate_financial_p2_f_evidence", forbidden)
    monkeypatch.setattr(subject, "_evaluator_source_sha256", lambda: ACCEPTED_F_EVALUATOR_SOURCE_SHA256)
    result = evaluate_financial_p3_info_gain_f_member_baselines(prepared, configuration=make_configuration())
    assert result.audit.gate_status == "ready"
    assert result.audit.f_evaluator_call_count == 0


def test_adapter_does_not_import_or_construct_forecast_data():
    source = Path(subject.__file__).read_text(encoding="utf-8")
    assert "FinancialP2FForecastBatch" not in source
    assert "FinancialP2FEvidenceConfig" not in source
    assert "evaluate_financial_p2_f_evidence(" not in source.replace("def evaluate_financial_p3_info_gain_f_member_baselines(", "")


def test_config_is_frozen():
    config = FMemberBaselineConfig(run_id="frozen")
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.run_id = "changed"
