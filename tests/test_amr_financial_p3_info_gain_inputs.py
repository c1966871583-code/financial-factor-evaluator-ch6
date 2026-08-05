from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from backend.amr.financial_p3_info_gain_inputs import (
    InfoGainInputPreparationConfig,
    prepare_financial_p3_info_gain_inputs,
    serialize_info_gain_input_preparation_result,
)
from tests.fixtures.synthetic_financial_p3_info_gain_input_cases import (
    make_batches,
    make_configuration,
)


def _evaluate(batches=None, configuration=None):
    return prepare_financial_p3_info_gain_inputs(
        make_batches() if batches is None else batches,
        configuration=(
            make_configuration() if configuration is None else configuration
        ),
    )


def _replace_batch(batches, combo_id, **changes):
    return tuple(
        replace(item, **changes) if item.combo_id == combo_id else item
        for item in batches
    )


def test_prepares_three_exact_frozen_common_sample_packages():
    result = _evaluate()
    assert result.audit.gate_status == "ready"
    assert result.audit.errors == ()
    assert [item.combo_id for item in result.packages] == ["VQ", "QG", "CASHQ"]
    assert result.audit.combo_count == 3
    assert result.audit.total_common_sample_rows == 2700
    for package in result.packages:
        assert package.evaluation_period_count == 18
        assert package.common_sample_row_count == 900
        assert len(package.per_period_row_counts) == 18
        assert {count for _, count in package.per_period_row_counts} == {50}
        assert len(package.get_common_sample_manifest()) == 900


def test_members_directions_and_observation_counts_are_frozen():
    result = _evaluate()
    expected = {
        "VQ": {"BP": "positive", "EBIT_EV": "positive", "ROE": "positive", "OCF_NP": "positive"},
        "QG": {"SALES_GROWTH": "positive", "PROFIT_GROWTH": "positive", "ROE": "positive", "OCF_NP": "positive"},
        "CASHQ": {"ROA": "positive", "OCF_SALES": "positive", "ACCRUALS": "negative"},
    }
    for package in result.packages:
        assert dict(package.member_directions) == expected[package.combo_id]
        observations = package.get_member_observations()
        assert len(observations) == 900 * len(expected[package.combo_id])
        assert set(observations["member_factor_id"]) == set(expected[package.combo_id])


def test_track_readiness_exposes_only_frozen_m20_references():
    result = _evaluate()
    for package in result.packages:
        m_track, f_track, r_track = package.track_inputs
        assert m_track.track_id == "M"
        assert m_track.preparation_status == "ready"
        assert m_track.evaluation_contexts == ("M:20D",)
        assert m_track.label_references
        assert m_track.evaluation_config_reference
        for track in (f_track, r_track):
            assert track.preparation_status == "not_run"
            assert track.evaluation_contexts == ()
            assert track.label_references == ()
            assert track.evaluation_config_reference is None
            assert track.reason_code == "CONTEXT_NOT_FROZEN"


def test_scope_audit_confirms_no_calculation_or_selection():
    audit = _evaluate().audit
    assert audit.exact_frozen_samples_verified is True
    assert audit.pit_safe is True
    assert audit.common_input_packages_created is True
    assert audit.sample_reconstructed is False
    assert audit.combination_constructed is False
    assert audit.evaluator_calls_performed is False
    assert audit.metrics_calculated is False
    assert audit.strongest_member_selected is False
    assert audit.information_gain_decision_made is False
    assert audit.production_status == "not production ready"


def test_pit_and_label_alignment_are_preserved():
    for package in _evaluate().packages:
        frame = package.get_member_observations()
        evaluation = pd.to_datetime(frame["evaluation_date"])
        assert (pd.to_datetime(frame["factor_effective_date"]) <= evaluation).all()
        assert (pd.to_datetime(frame["control_effective_date"]) <= evaluation).all()
        assert (pd.to_datetime(frame["return_start_date"]) > evaluation).all()
        for _, group in frame.groupby(["evaluation_date", "security_id"]):
            assert group["forward_return"].nunique(dropna=False) == 1
            assert group["size_control"].nunique(dropna=False) == 1
            assert group["industry_code"].nunique(dropna=False) == 1


def test_serialization_is_deterministic_under_batch_and_row_order_changes():
    batches = make_batches()
    first = _evaluate(batches)
    reordered = []
    for item in reversed(batches):
        reordered.append(
            replace(
                item,
                _common_sample_manifest=item.get_common_sample_manifest().sample(
                    frac=1.0, random_state=11
                ),
                _member_observations=item.get_member_observations().sample(
                    frac=1.0, random_state=13
                ),
            )
        )
    second = _evaluate(tuple(reordered))
    assert serialize_info_gain_input_preparation_result(first) == (
        serialize_info_gain_input_preparation_result(second)
    )
    assert first.audit.input_fingerprint == second.audit.input_fingerprint
    assert first.audit.output_fingerprint == second.audit.output_fingerprint


def test_input_batches_and_output_getters_are_defensive_copies():
    batches = make_batches()
    before_manifest = batches[0].get_common_sample_manifest()
    before_frame = batches[0].get_member_observations()
    result = _evaluate(batches)
    pd.testing.assert_frame_equal(
        batches[0].get_common_sample_manifest(), before_manifest
    )
    pd.testing.assert_frame_equal(
        batches[0].get_member_observations(), before_frame
    )
    returned = result.packages[0].get_common_sample_manifest()
    returned.loc[0, "security_id"] = "MUTATED"
    assert result.packages[0].get_common_sample_manifest().loc[0, "security_id"] != "MUTATED"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("declared_fingerprint", "DECLARED_SAMPLE_FINGERPRINT_MISMATCH"),
        ("actual_key", "ACTUAL_SAMPLE_FINGERPRINT_MISMATCH"),
        ("row_count", "SAMPLE_ROW_COUNT_MISMATCH"),
        ("period_count", "SAMPLE_PERIOD_COUNT_MISMATCH"),
        ("duplicate_key", "DUPLICATE_SAMPLE_KEY"),
        ("missing_member", "MEMBER_SET_MISMATCH"),
        ("forbidden", "FORBIDDEN_DECISION_FIELD"),
    ],
)
def test_structural_or_scope_drift_blocks(mutation, error_code):
    batches = make_batches()
    target = batches[0]
    changes = {}
    if mutation == "declared_fingerprint":
        changes["declared_common_sample_fingerprint"] = "0" * 64
    elif mutation == "actual_key":
        manifest = target.get_common_sample_manifest()
        manifest.loc[0, "security_id"] = "S999"
        changes["_common_sample_manifest"] = manifest
    elif mutation == "row_count":
        changes["_common_sample_manifest"] = target.get_common_sample_manifest().iloc[:-1]
    elif mutation == "period_count":
        manifest = target.get_common_sample_manifest()
        changes["_common_sample_manifest"] = manifest[
            manifest["evaluation_date"] != manifest["evaluation_date"].iloc[0]
        ]
    elif mutation == "duplicate_key":
        manifest = target.get_common_sample_manifest()
        manifest.loc[1, ["evaluation_date", "security_id"]] = manifest.loc[
            0, ["evaluation_date", "security_id"]
        ].values
        changes["_common_sample_manifest"] = manifest
    elif mutation == "missing_member":
        frame = target.get_member_observations()
        changes["_member_observations"] = frame[
            frame["member_factor_id"] != "BP"
        ]
    else:
        frame = target.get_member_observations()
        frame["information_gain_decision"] = "positive"
        changes["_member_observations"] = frame
    result = _evaluate(_replace_batch(batches, "VQ", **changes))
    assert result.audit.gate_status == "blocked"
    assert error_code in {item.code for item in result.audit.errors}


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("label", "LABEL_OR_CONTROL_MISMATCH"),
        ("future_factor", "FUTURE_FACTOR_OR_CONTROL"),
        ("future_control", "FUTURE_FACTOR_OR_CONTROL"),
        ("return_alignment", "INVALID_RETURN_ALIGNMENT"),
        ("nonfinite", "NONFINITE_REQUIRED_VALUE"),
    ],
)
def test_pit_label_or_numeric_drift_blocks(mutation, error_code):
    batches = make_batches()
    target = batches[1]
    frame = target.get_member_observations()
    row = frame.index[frame["member_factor_id"] == "ROE"][0]
    if mutation == "label":
        frame.loc[row, "forward_return"] += 1.0
    elif mutation == "future_factor":
        frame.loc[row, "factor_effective_date"] = "2099-01-01"
    elif mutation == "future_control":
        frame.loc[row, "control_effective_date"] = "2099-01-01"
    elif mutation == "return_alignment":
        frame.loc[row, "return_start_date"] = frame.loc[row, "evaluation_date"]
    else:
        frame.loc[row, "factor_value"] = np.inf
    result = _evaluate(
        _replace_batch(batches, "QG", _member_observations=frame)
    )
    assert result.audit.gate_status == "blocked"
    assert error_code in {item.code for item in result.audit.errors}


def test_member_key_and_reference_set_drift_block():
    batches = make_batches()
    target = batches[2]
    frame = target.get_member_observations()
    row = frame.index[frame["member_factor_id"] == "ROA"][0]
    frame.loc[row, "security_id"] = "S999"
    changed = _replace_batch(
        batches,
        "CASHQ",
        _member_observations=frame,
        member_formula_versions={"ROA": "v1"},
        source_factor_run_references={"ROA": "run"},
    )
    result = _evaluate(changed)
    codes = {item.code for item in result.audit.errors}
    assert result.audit.gate_status == "blocked"
    assert {
        "MEMBER_SAMPLE_KEYS_MISMATCH",
        "FORMULA_VERSION_SET_MISMATCH",
        "SOURCE_RUN_SET_MISMATCH",
    } <= codes


def test_unfrozen_f_or_r_reference_and_m_context_drift_block():
    batches = make_batches()
    target = batches[0]
    references = target.get_track_input_references()
    references["F"]["label_references"] = ["UNAUTHORIZED"]
    references["M"]["evaluation_contexts"] = ["M:5D"]
    result = _evaluate(
        _replace_batch(batches, "VQ", track_input_references=references)
    )
    codes = {item.code for item in result.audit.errors}
    assert result.audit.gate_status == "blocked"
    assert {
        "TRACK_STATUS_OR_CONTEXT_DRIFT",
        "UNFROZEN_TRACK_REFERENCE_PRESENT",
    } <= codes


def test_provenance_and_combo_set_drift_block():
    batches = make_batches()
    changed = _replace_batch(
        batches,
        "VQ",
        provenance={"synthetic_test_only": False},
    )
    result = _evaluate(changed)
    assert "PROVENANCE_SCOPE_MISMATCH" in {
        item.code for item in result.audit.errors
    }
    missing = _evaluate(batches[:2])
    assert "COMBO_SET_MISMATCH" in {item.code for item in missing.audit.errors}


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("sample_reconstruction_allowed", True),
        ("evaluator_execution_allowed", True),
        ("metric_calculation_allowed", True),
        ("information_gain_decision_allowed", True),
    ],
)
def test_configuration_forbidden_capabilities_are_frozen(field_name, value):
    with pytest.raises(ValueError):
        make_configuration(**{field_name: value})


def test_wrong_types_are_rejected():
    with pytest.raises(TypeError):
        prepare_financial_p3_info_gain_inputs(
            make_batches(), configuration=object()
        )
    with pytest.raises(TypeError):
        InfoGainInputPreparationConfig(run_id="x", contract=object())
    with pytest.raises(TypeError):
        serialize_info_gain_input_preparation_result(copy.deepcopy({}))
