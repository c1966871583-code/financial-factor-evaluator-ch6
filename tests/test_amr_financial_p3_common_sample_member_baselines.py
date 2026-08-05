from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from backend.amr.financial_p3_common_sample_member_baselines import (
    CommonSampleMemberBaselineConfig,
    evaluate_common_sample_member_baselines,
    serialize_common_sample_member_baseline_result,
)
from backend.amr.financial_p3_info_gain_contract import (
    build_financial_p3_info_gain_contract,
)
from tests.fixtures.synthetic_financial_p3_common_sample_member_baseline_cases import (
    make_batches,
    make_configuration,
)


def _evaluate():
    return evaluate_common_sample_member_baselines(
        make_batches(), configuration=make_configuration()
    )


def _replace_batch(batches, combo_id, **changes):
    return tuple(
        replace(item, **changes) if item.combo_id == combo_id else item
        for item in batches
    )


def test_all_frozen_members_complete_on_exact_common_samples():
    result = _evaluate()
    assert result.audit.gate_status == "ready"
    assert result.audit.errors == ()
    assert result.audit.combo_count == 3
    assert result.audit.expected_member_count == 11
    assert result.audit.completed_member_count == 11
    assert result.audit.failed_member_count == 0
    assert [item.combo_id for item in result.bundles] == ["VQ", "QG", "CASHQ"]
    assert [item.expected_member_count for item in result.bundles] == [4, 4, 3]
    assert all(item.bundle_status == "completed" for item in result.bundles)
    for bundle in result.bundles:
        assert bundle.common_sample_fingerprint
        for run in bundle.member_baselines:
            assert run.common_sample_fingerprint == bundle.common_sample_fingerprint
            assert run.evaluation_period_count == 18
            assert run.common_sample_row_count == 900
            assert run.calculation_status == "completed"
            assert [item.evaluation_context for item in run.m_track_results] == [
                "5D",
                "20D",
                "60D",
            ]
            assert [item.calculation_status for item in run.m_track_results] == [
                "not_run",
                "completed",
                "not_run",
            ]
            assert run.m_track_results[1].metrics is not None
            assert run.f_track_result.calculation_status == "not_run"
            assert run.r_track_result.calculation_status == "not_run"


def test_member_order_and_negative_accruals_direction_are_frozen():
    result = _evaluate()
    members = {
        item.combo_id: [run.member_factor_id for run in item.member_baselines]
        for item in result.bundles
    }
    assert members == {
        "VQ": ["BP", "EBIT_EV", "ROE", "OCF_NP"],
        "QG": ["SALES_GROWTH", "PROFIT_GROWTH", "ROE", "OCF_NP"],
        "CASHQ": ["ROA", "OCF_SALES", "ACCRUALS"],
    }
    accruals = result.bundles[2].member_baselines[2]
    assert accruals.member_direction == "negative"
    assert accruals.m_track_results[1].metrics.mean_rank_ic > 0


def test_scope_audit_forbids_premature_information_gain_conclusions():
    result = _evaluate()
    audit = result.audit
    assert audit.same_sample_enforced is True
    assert audit.member_full_sample_reused is False
    assert audit.existing_evaluator_reused is True
    assert audit.combination_reconstructed is False
    assert audit.information_gain_delta_calculated is False
    assert audit.information_gain_decision_made is False
    assert audit.production_status == "not production ready"


def test_serialization_and_hashes_are_deterministic_under_input_order_changes():
    batches = make_batches()
    first = evaluate_common_sample_member_baselines(
        batches, configuration=make_configuration()
    )
    shuffled = []
    for batch in reversed(batches):
        shuffled.append(
            replace(
                batch,
                _common_sample_manifest=batch.get_common_sample_manifest().sample(
                    frac=1.0, random_state=7
                ),
                _member_frame=batch.get_member_frame().sample(
                    frac=1.0, random_state=9
                ),
            )
        )
    second = evaluate_common_sample_member_baselines(
        shuffled, configuration=make_configuration()
    )
    assert serialize_common_sample_member_baseline_result(first) == (
        serialize_common_sample_member_baseline_result(second)
    )
    assert first.audit.input_fingerprint == second.audit.input_fingerprint
    assert first.audit.output_fingerprint == second.audit.output_fingerprint


def test_inputs_are_defensively_copied_and_not_mutated():
    batches = make_batches()
    manifests = [item.get_common_sample_manifest() for item in batches]
    frames = [item.get_member_frame() for item in batches]
    evaluate_common_sample_member_baselines(
        batches, configuration=make_configuration()
    )
    for index, item in enumerate(batches):
        pd.testing.assert_frame_equal(item.get_common_sample_manifest(), manifests[index])
        pd.testing.assert_frame_equal(item.get_member_frame(), frames[index])


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("fingerprint", "SAMPLE_FINGERPRINT_MISMATCH"),
        ("row", "SAMPLE_ROW_COUNT_MISMATCH"),
        ("period", "SAMPLE_PERIOD_COUNT_MISMATCH"),
        ("duplicate", "DUPLICATE_SAMPLE_KEY"),
        ("member", "MEMBER_SET_MISMATCH"),
        ("forbidden", "FORBIDDEN_DECISION_FIELD"),
    ],
)
def test_structural_drift_blocks_the_batch(mutation, expected_code):
    batches = make_batches()
    target = batches[0]
    changes = {}
    if mutation == "fingerprint":
        changes["declared_common_sample_fingerprint"] = "0" * 64
    elif mutation == "row":
        changes["_common_sample_manifest"] = target.get_common_sample_manifest().iloc[:-1]
    elif mutation == "period":
        manifest = target.get_common_sample_manifest()
        first_date = manifest["evaluation_date"].iloc[0]
        changes["_common_sample_manifest"] = manifest[
            manifest["evaluation_date"] != first_date
        ]
    elif mutation == "duplicate":
        manifest = target.get_common_sample_manifest()
        changes["_common_sample_manifest"] = pd.concat(
            [manifest.iloc[:-1], manifest.iloc[[0]]], ignore_index=True
        )
    elif mutation == "member":
        frame = target.get_member_frame()
        changes["_member_frame"] = frame[frame["member_factor_id"] != "BP"]
    else:
        frame = target.get_member_frame()
        frame["best_member"] = False
        changes["_member_frame"] = frame
    result = evaluate_common_sample_member_baselines(
        _replace_batch(batches, "VQ", **changes),
        configuration=make_configuration(),
    )
    assert result.audit.gate_status == "blocked"
    assert expected_code in {item.code for item in result.audit.errors}


def test_label_or_control_mismatch_blocks_before_evaluation():
    batches = make_batches()
    target = batches[1]
    frame = target.get_member_frame()
    row = frame.index[frame["member_factor_id"] == "ROE"][0]
    frame.loc[row, "forward_return"] += 1.0
    result = evaluate_common_sample_member_baselines(
        _replace_batch(batches, "QG", _member_frame=frame),
        configuration=make_configuration(),
    )
    assert result.audit.gate_status == "blocked"
    assert "LABEL_OR_CONTROL_MISMATCH" in {item.code for item in result.audit.errors}


def test_member_evaluator_failure_is_retained_as_partial_not_zero_filled():
    batches = make_batches()
    target = batches[2]
    frame = target.get_member_frame()
    row = frame.index[frame["member_factor_id"] == "ROA"][0]
    frame.loc[row, "factor_value"] = np.inf
    result = evaluate_common_sample_member_baselines(
        _replace_batch(batches, "CASHQ", _member_frame=frame),
        configuration=make_configuration(),
    )
    assert result.audit.gate_status == "ready"
    bundle = result.bundles[2]
    assert bundle.bundle_status == "partial"
    assert bundle.completed_member_count == 2
    assert bundle.failed_member_count == 1
    failed = bundle.member_baselines[0]
    assert failed.member_factor_id == "ROA"
    assert failed.calculation_status == "blocked"
    assert failed.m_track_results[1].metrics is None


def test_combo_version_and_sample_reference_drift_block():
    batches = make_batches()
    changed = _replace_batch(
        batches,
        "CASHQ",
        combo_definition_version="DRIFT",
        common_sample_reference="DRIFT",
    )
    result = evaluate_common_sample_member_baselines(
        changed, configuration=make_configuration()
    )
    codes = {item.code for item in result.audit.errors}
    assert result.audit.gate_status == "blocked"
    assert {"COMBO_VERSION_MISMATCH", "SAMPLE_REFERENCE_MISMATCH"} <= codes


def test_exact_combo_batch_set_is_required():
    result = evaluate_common_sample_member_baselines(
        make_batches()[:2], configuration=make_configuration()
    )
    assert result.audit.gate_status == "blocked"
    assert "COMBO_SET_MISMATCH" in {item.code for item in result.audit.errors}


def test_contract_type_and_scope_fields_are_frozen():
    with pytest.raises(TypeError):
        CommonSampleMemberBaselineConfig(
            run_id="x",
            execution_timestamp="2026-08-03T13:00:00+08:00",
            evaluation_config_reference="x",
            info_gain_contract=object(),
        )
    with pytest.raises(ValueError):
        make_configuration(information_gain_decision_allowed=True)
    with pytest.raises(ValueError):
        make_configuration(best_member_selection_allowed=True)
    with pytest.raises(ValueError):
        make_configuration(f_track_status="completed")


def test_serialization_rejects_wrong_type():
    with pytest.raises(TypeError):
        serialize_common_sample_member_baseline_result(copy.deepcopy({}))


def test_all_baseline_metric_payloads_are_finite_or_null():
    payload = _evaluate().to_dict()

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, float):
            assert np.isfinite(value)

    walk(payload)
