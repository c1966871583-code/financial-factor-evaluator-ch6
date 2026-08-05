"""Acceptance tests for FIN-P3-COMMON-SAMPLE."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.amr.financial_p3_common_sample import (
    COMMON_SAMPLE_CONCLUSION_BOUNDARY,
    COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT,
    FinancialP3CommonSampleBatch,
    FinancialP3CommonSampleConfig,
    compute_common_sample_manifest_fingerprint,
    evaluate_financial_p3_common_sample,
)
from tests.fixtures.synthetic_financial_p3_common_sample_cases import (
    EXECUTION_TIMESTAMP,
    GATE_ANCHOR,
    evaluation_dates,
    make_batch,
    make_configuration,
    make_frame,
    make_manifest,
)


@pytest.fixture(scope="module")
def golden():
    return evaluate_financial_p3_common_sample(
        make_batch(),
        configuration=make_configuration(),
    )


def _error_codes(result) -> set[str]:
    return {item.code for item in result.common_sample_audit.errors}


def _evaluate(
    *,
    manifest=None,
    frame=None,
    declared_manifest_fingerprint=None,
    gate_anchor=None,
    provenance=None,
):
    frozen_manifest = make_manifest() if manifest is None else manifest
    complete = {
        "evaluation_date",
        "security_id",
        "eligible",
    }.issubset(frozen_manifest.columns)
    fingerprint = (
        compute_common_sample_manifest_fingerprint(frozen_manifest)
        if complete
        else "0" * 64
    )
    batch = make_batch(
        manifest=frozen_manifest,
        frame=frame,
        declared_manifest_fingerprint=(
            fingerprint
            if declared_manifest_fingerprint is None
            else declared_manifest_fingerprint
        ),
        gate_anchor=gate_anchor,
        provenance=provenance,
    )
    config = FinancialP3CommonSampleConfig(
        comparison_id="SYNTHETIC-ROE-VS-COMBINED-01",
        single_factor_id="ROE_SYNTHETIC",
        combined_factor_id="SYNTHETIC_COMBINED_CANDIDATE",
        single_formula_version="synthetic-single-v1",
        combined_formula_version="synthetic-predeclared-combined-v1",
        expected_manifest_fingerprint=fingerprint,
        execution_timestamp=EXECUTION_TIMESTAMP,
    )
    return evaluate_financial_p3_common_sample(
        batch,
        configuration=config,
    )


class TestFrozenPolicy:
    def test_fin23_output_contract_is_present(self, golden):
        comparison = golden.comparison.to_dict()
        for key in (
            "common_sample_size",
            "single_factor_metrics",
            "combined_factor_metrics",
            "delta_ic",
            "delta_icir",
            "delta_monotonicity",
            "delta_fm_r2",
            "coverage_loss",
        ):
            assert key in comparison

    def test_configuration_freezes_comparison_semantics(self):
        config = make_configuration()
        assert config.holding_period == 20
        assert config.group_count == 5
        assert config.minimum_cross_section == 30
        assert config.minimum_periods == 12
        assert config.group_weighting == "equal_weight"
        assert config.ic_method == "spearman_rank"
        assert config.fm_controls == ("size", "industry")
        assert config.sample_policy == "frozen_manifest_intersection"
        assert config.comparison_policy == "predeclared_pair_only"
        assert config.automatic_best_single_selection is False
        assert config.information_gain_decision_allowed is False
        assert config.fin24_combination_construction_allowed is False
        assert config.synthetic_test_only is True

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("holding_period", 5),
            ("group_count", 10),
            ("minimum_cross_section", 20),
            ("minimum_periods", 6),
            ("group_weighting", "value_weight"),
            ("ic_method", "pearson"),
            ("fm_controls", ("size",)),
            ("sample_policy", "separate_samples"),
            ("comparison_policy", "best_of_many"),
            ("automatic_best_single_selection", True),
            ("information_gain_decision_allowed", True),
            ("fin24_combination_construction_allowed", True),
            ("synthetic_test_only", False),
            ("gate_output_fingerprint", "0" * 64),
            ("policy_version", "drift"),
            ("schema_version", "drift"),
        ],
    )
    def test_rejects_policy_drift(self, field_name, value):
        with pytest.raises(ValueError):
            make_configuration(**{field_name: value})

    def test_pair_ids_must_differ(self):
        with pytest.raises(ValueError):
            make_configuration(
                single_factor_id="SAME",
                combined_factor_id="SAME",
            )

    def test_manifest_fingerprint_must_be_sha(self):
        with pytest.raises(ValueError):
            FinancialP3CommonSampleConfig(
                comparison_id="x",
                single_factor_id="a",
                combined_factor_id="b",
                single_formula_version="v1",
                combined_formula_version="v1",
                expected_manifest_fingerprint="bad",
                execution_timestamp=EXECUTION_TIMESTAMP,
            )


class TestGoldenComparison:
    def test_gate_ready_and_evaluation_completed(self, golden):
        audit = golden.common_sample_audit
        assert audit.gate_status == "ready"
        assert audit.errors == ()
        assert audit.evaluation_status == "completed"
        assert golden.comparison.evaluation_status == "completed"

    def test_exact_sample_accounting(self, golden):
        comparison = golden.comparison
        assert comparison.eligible_sample_size == 1044
        assert comparison.single_available_size == 954
        assert comparison.combined_available_size == 936
        assert comparison.common_sample_size == 900
        assert comparison.common_period_count == 18
        assert comparison.coverage_loss == pytest.approx(144 / 1044)

    def test_both_sides_use_identical_rows(self, golden):
        comparison = golden.comparison
        single = comparison.single_factor_metrics
        combined = comparison.combined_factor_metrics
        assert single.common_observation_count == 900
        assert combined.common_observation_count == 900
        assert single.valid_period_count == 18
        assert combined.valid_period_count == 18
        assert single.common_sample_fingerprint == (
            combined.common_sample_fingerprint
        )
        assert single.common_sample_fingerprint == (
            comparison.common_sample_fingerprint
        )
        assert golden.common_sample_audit.same_sample_enforced is True

    def test_rank_ic_and_icir_are_reported(self, golden):
        single = golden.comparison.single_factor_metrics
        combined = golden.comparison.combined_factor_metrics
        for metrics in (single, combined):
            assert -1 <= metrics.mean_rank_ic <= 1
            assert metrics.rank_ic_std > 0
            assert metrics.icir is not None
            assert 0 <= metrics.positive_ic_ratio <= 1

    def test_group_metrics_use_five_equal_weight_groups(self, golden):
        for metrics in (
            golden.comparison.single_factor_metrics,
            golden.comparison.combined_factor_metrics,
        ):
            assert len(metrics.group_returns) == 5
            assert metrics.long_short_spread == pytest.approx(
                metrics.group_returns[-1] - metrics.group_returns[0]
            )
            assert -1 <= metrics.monotonicity <= 1

    def test_fama_macbeth_r2_is_reported_on_common_sample(self, golden):
        single = golden.comparison.single_factor_metrics
        combined = golden.comparison.combined_factor_metrics
        assert 0 <= single.fm_mean_r2 <= 1
        assert 0 <= combined.fm_mean_r2 <= 1

    @pytest.mark.parametrize(
        ("delta_name", "metric_name"),
        [
            ("delta_ic", "mean_rank_ic"),
            ("delta_icir", "icir"),
            ("delta_monotonicity", "monotonicity"),
            ("delta_fm_r2", "fm_mean_r2"),
        ],
    )
    def test_delta_is_combined_minus_single(
        self,
        golden,
        delta_name,
        metric_name,
    ):
        comparison = golden.comparison
        expected = (
            getattr(comparison.combined_factor_metrics, metric_name)
            - getattr(comparison.single_factor_metrics, metric_name)
        )
        assert getattr(comparison, delta_name) == pytest.approx(expected)

    def test_no_information_gain_or_admission_decision(self, golden):
        audit = golden.common_sample_audit
        assert audit.information_gain_decision_made is False
        assert audit.fin24_combination_constructed is False
        assert audit.research_assessment == "exploratory"
        assert audit.production_status == "not production ready"
        assert audit.admission_status == "not_assessed"
        assert audit.conclusion_boundary == COMMON_SAMPLE_CONCLUSION_BOUNDARY

    def test_all_warnings_are_explicit(self, golden):
        assert {
            warning.code
            for warning in golden.common_sample_audit.warnings
        } == {
            "SYNTHETIC_COMPARATOR_ONLY",
            "COVERAGE_LOSS_REPORTED",
            "INFORMATION_GAIN_NOT_DECIDED",
            "PRODUCTION_GATES_NOT_EVALUATED",
        }

    def test_output_has_no_fin24_or_fin25_result_field(self, golden):
        serialized = json.dumps(golden.to_dict(), sort_keys=True)
        for forbidden in (
            '"information_gain_decision":',
            '"best_single_factor":',
            '"selected_combination":',
            '"admission_decision":',
            '"production_status": "research usable"',
        ):
            assert forbidden not in serialized

    def test_hashes_are_sha256(self, golden):
        audit = golden.common_sample_audit
        values = (
            audit.manifest_fingerprint,
            audit.input_fingerprint,
            audit.common_sample_fingerprint,
            audit.output_fingerprint,
            audit.content_hash,
            golden.comparison.content_hash,
            golden.comparison.single_factor_metrics.content_hash,
            golden.comparison.combined_factor_metrics.content_hash,
        )
        for value in values:
            assert len(value) == 64
            int(value, 16)


class TestCommonSampleBehavior:
    def test_single_value_change_does_not_change_combined_metrics(
        self,
        golden,
    ):
        frame = make_frame()
        mask = (
            (frame["security_id"] == "S010")
            & (frame["evaluation_date"] == evaluation_dates()[0])
        )
        frame.loc[mask, "single_factor_value"] = 99.0
        changed = _evaluate(frame=frame)
        assert changed.comparison.common_sample_fingerprint == (
            golden.comparison.common_sample_fingerprint
        )
        assert changed.comparison.combined_factor_metrics == (
            golden.comparison.combined_factor_metrics
        )
        assert changed.comparison.single_factor_metrics != (
            golden.comparison.single_factor_metrics
        )

    def test_single_missingness_changes_both_comparison_samples(self):
        frame = make_frame()
        mask = frame["security_id"] == "S010"
        frame.loc[mask, "single_factor_value"] = np.nan
        result = _evaluate(frame=frame)
        comparison = result.comparison
        assert comparison.common_sample_size == 882
        assert comparison.single_factor_metrics.common_observation_count == 882
        assert comparison.combined_factor_metrics.common_observation_count == 882
        assert (
            comparison.single_factor_metrics.common_sample_fingerprint
            == comparison.combined_factor_metrics.common_sample_fingerprint
        )

    def test_restoring_combined_coverage_increases_common_sample(self):
        frame = make_frame()
        frame.loc[
            frame["security_id"] == "S002",
            "combined_factor_value",
        ] = 0.0
        result = _evaluate(frame=frame)
        assert result.comparison.common_sample_size == 918
        assert result.comparison.coverage_loss < 144 / 1044

    def test_ineligible_value_changes_do_not_change_output(self, golden):
        frame = make_frame()
        mask = frame["security_id"].isin(["S058", "S059"])
        frame.loc[mask, "single_factor_value"] = 999.0
        frame.loc[mask, "combined_factor_value"] = -999.0
        frame.loc[mask, "forward_return"] = 999.0
        result = _evaluate(frame=frame)
        assert result.comparison == golden.comparison
        assert result.common_sample_audit.output_fingerprint == (
            golden.common_sample_audit.output_fingerprint
        )
        assert result.common_sample_audit.input_fingerprint != (
            golden.common_sample_audit.input_fingerprint
        )

    def test_one_small_period_is_excluded_symmetrically(self):
        frame = make_frame()
        first = evaluation_dates()[0]
        mask = (
            (frame["evaluation_date"] == first)
            & frame["security_id"].isin(
                [f"S{index:03d}" for index in range(8, 35)]
            )
        )
        frame.loc[mask, "combined_factor_value"] = np.nan
        result = _evaluate(frame=frame)
        assert result.common_sample_audit.gate_status == "ready"
        assert result.comparison.evaluation_status == "completed"
        assert result.comparison.common_period_count == 17
        assert result.comparison.common_sample_size == 850
        assert (
            result.comparison.single_factor_metrics.common_observation_count
            == result.comparison.combined_factor_metrics.common_observation_count
        )

    def test_fewer_than_twelve_periods_is_insufficient_not_blocked(self):
        keep_dates = set(evaluation_dates()[:11])
        manifest = make_manifest()
        manifest = manifest[manifest["evaluation_date"].isin(keep_dates)]
        frame = make_frame()
        frame = frame[frame["evaluation_date"].isin(keep_dates)]
        result = _evaluate(manifest=manifest, frame=frame)
        assert result.common_sample_audit.gate_status == "ready"
        assert result.comparison.evaluation_status == "insufficient"
        assert result.comparison.common_period_count == 11
        assert result.comparison.single_factor_metrics is not None

    def test_no_period_meets_cross_section_is_insufficient(self):
        manifest = make_manifest()
        manifest["eligible"] = manifest["security_id"].isin(
            [f"S{index:03d}" for index in range(20)]
        )
        result = _evaluate(manifest=manifest)
        assert result.common_sample_audit.gate_status == "ready"
        assert result.comparison.evaluation_status == "insufficient"
        assert result.comparison.common_period_count == 0
        assert result.comparison.common_sample_size == 0
        assert result.comparison.single_factor_metrics is None
        assert result.comparison.delta_ic is None


class TestFailClosedValidation:
    @pytest.mark.parametrize(
        "change",
        [
            {"task_id": "WRONG"},
            {"status": "PENDING"},
            {"output_fingerprint": "0" * 64},
            {"research_integrity_status": "incomplete"},
            {"production_status": "research usable"},
        ],
    )
    def test_invalid_gate_anchor_blocks(self, change):
        anchor = dict(GATE_ANCHOR)
        anchor.update(change)
        result = _evaluate(gate_anchor=anchor)
        assert result.common_sample_audit.gate_status == "blocked"
        assert "INVALID_GATE_ANCHOR" in _error_codes(result)

    def test_non_synthetic_input_blocks(self):
        result = _evaluate(provenance={"synthetic_test_only": False})
        assert "NON_SYNTHETIC_INPUT" in _error_codes(result)

    @pytest.mark.parametrize(
        "field_name",
        [
            "selected_single_factor",
            "selected_combination",
            "selected_metric",
            "best_single_factor",
            "information_gain_decision",
            "admission_decision",
        ],
    )
    def test_forbidden_frame_field_blocks(self, field_name):
        frame = make_frame()
        frame[field_name] = "forbidden"
        result = _evaluate(frame=frame)
        assert "FORBIDDEN_SELECTION_FIELD" in _error_codes(result)

    def test_forbidden_provenance_field_blocks(self):
        result = _evaluate(
            provenance={
                "synthetic_test_only": True,
                "information_gain_decision": "yes",
            }
        )
        assert "FORBIDDEN_SELECTION_FIELD" in _error_codes(result)

    @pytest.mark.parametrize(
        "column",
        ["evaluation_date", "security_id", "eligible"],
    )
    def test_missing_manifest_column_blocks(self, column):
        manifest = make_manifest().drop(columns=[column])
        result = _evaluate(manifest=manifest)
        assert "MISSING_COLUMN" in _error_codes(result)

    @pytest.mark.parametrize(
        "column",
        [
            "factor_effective_date",
            "control_effective_date",
            "return_start_date",
            "single_factor_value",
            "combined_factor_value",
            "forward_return",
            "size_control",
            "industry_code",
        ],
    )
    def test_missing_frame_column_blocks(self, column):
        frame = make_frame().drop(columns=[column])
        result = _evaluate(frame=frame)
        assert "MISSING_COLUMN" in _error_codes(result)

    def test_duplicate_manifest_key_blocks(self):
        manifest = make_manifest()
        manifest = pd.concat([manifest, manifest.iloc[[0]]], ignore_index=True)
        result = _evaluate(manifest=manifest)
        assert "DUPLICATE_MANIFEST_KEY" in _error_codes(result)

    def test_duplicate_observation_key_blocks(self):
        frame = make_frame()
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
        result = _evaluate(frame=frame)
        assert "DUPLICATE_OBSERVATION_KEY" in _error_codes(result)

    def test_observation_outside_manifest_blocks(self):
        frame = make_frame()
        frame.loc[0, "security_id"] = "OUTSIDE"
        result = _evaluate(frame=frame)
        assert "OBSERVATION_OUTSIDE_MANIFEST" in _error_codes(result)

    def test_declared_manifest_fingerprint_mismatch_blocks(self):
        result = _evaluate(declared_manifest_fingerprint="0" * 64)
        assert "MANIFEST_FINGERPRINT_MISMATCH" in _error_codes(result)

    def test_configuration_manifest_fingerprint_mismatch_blocks(self):
        batch = make_batch()
        config = make_configuration()
        wrong = FinancialP3CommonSampleConfig(
            **{
                **config.to_dict(),
                "expected_manifest_fingerprint": "0" * 64,
            }
        )
        result = evaluate_financial_p3_common_sample(
            batch,
            configuration=wrong,
        )
        assert "MANIFEST_FINGERPRINT_MISMATCH" in _error_codes(result)

    @pytest.mark.parametrize(
        "column",
        ["factor_effective_date", "control_effective_date"],
    )
    def test_future_factor_or_control_blocks(self, column):
        frame = make_frame()
        frame.loc[0, column] = "2099-01-01"
        result = _evaluate(frame=frame)
        assert "FUTURE_FACTOR_OR_CONTROL" in _error_codes(result)

    def test_return_start_not_after_evaluation_blocks(self):
        frame = make_frame()
        frame.loc[0, "return_start_date"] = frame.loc[0, "evaluation_date"]
        result = _evaluate(frame=frame)
        assert "INVALID_RETURN_ALIGNMENT" in _error_codes(result)

    @pytest.mark.parametrize(
        ("target", "column"),
        [("manifest", "evaluation_date"), ("frame", "evaluation_date")],
    )
    def test_invalid_key_date_blocks(self, target, column):
        manifest = make_manifest()
        frame = make_frame()
        if target == "manifest":
            manifest.loc[0, column] = "not-a-date"
        else:
            frame.loc[0, column] = "not-a-date"
        result = _evaluate(manifest=manifest, frame=frame)
        assert "INVALID_KEY" in _error_codes(result)

    def test_invalid_eligible_type_blocks(self):
        manifest = make_manifest()
        manifest["eligible"] = "yes"
        result = _evaluate(manifest=manifest)
        assert "INVALID_KEY" in _error_codes(result)

    def test_blocked_result_has_no_comparison(self):
        result = _evaluate(declared_manifest_fingerprint="0" * 64)
        assert result.comparison is None
        audit = result.common_sample_audit
        assert audit.evaluation_status == "not_run"
        assert audit.production_status == "not production ready"
        assert audit.information_gain_decision_made is False


class TestDeterminismAndImmutability:
    def test_repeated_run_is_identical(self, golden):
        repeated = _evaluate()
        assert repeated.to_dict() == golden.to_dict()

    def test_row_order_is_irrelevant(self, golden):
        manifest = make_manifest().sample(frac=1, random_state=11)
        frame = make_frame().sample(frac=1, random_state=13)
        result = _evaluate(manifest=manifest, frame=frame)
        assert result.to_dict() == golden.to_dict()

    def test_manifest_fingerprint_is_order_invariant(self):
        manifest = make_manifest()
        shuffled = manifest.sample(frac=1, random_state=3)
        assert compute_common_sample_manifest_fingerprint(manifest) == (
            compute_common_sample_manifest_fingerprint(shuffled)
        )

    def test_batch_defensively_copies_inputs(self, golden):
        manifest = make_manifest()
        frame = make_frame()
        anchor = dict(GATE_ANCHOR)
        provenance = {
            "synthetic_test_only": True,
            "provider": "deterministic_fixture",
            "universe_policy": "independent_frozen_manifest",
        }
        batch = make_batch(
            manifest=manifest,
            frame=frame,
            gate_anchor=anchor,
            provenance=provenance,
        )
        manifest.loc[:, "eligible"] = False
        frame.loc[:, "single_factor_value"] = np.nan
        anchor["status"] = "PENDING"
        provenance["synthetic_test_only"] = False
        result = evaluate_financial_p3_common_sample(
            batch,
            configuration=make_configuration(),
        )
        assert result.to_dict() == golden.to_dict()
        returned = batch.get_frame()
        returned.loc[:, "single_factor_value"] = np.nan
        assert batch.get_frame()["single_factor_value"].notna().any()

    def test_wrong_argument_types_rejected(self):
        with pytest.raises(TypeError):
            evaluate_financial_p3_common_sample(
                object(),
                configuration=make_configuration(),
            )
        with pytest.raises(TypeError):
            evaluate_financial_p3_common_sample(
                make_batch(),
                configuration=object(),
            )

    def test_batch_requires_dataframes(self):
        with pytest.raises(TypeError):
            FinancialP3CommonSampleBatch(
                dataset_id="x",
                version="v1",
                _manifest=[],
                _frame=make_frame(),
                declared_manifest_fingerprint="0" * 64,
                gate_anchor=GATE_ANCHOR,
                provenance={"synthetic_test_only": True},
            )

    def test_manifest_fingerprint_helper_requires_columns(self):
        with pytest.raises(ValueError):
            compute_common_sample_manifest_fingerprint(
                make_manifest().drop(columns=["eligible"])
            )
