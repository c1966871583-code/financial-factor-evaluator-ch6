"""Acceptance tests for FIN-P2-OOS-FDR."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from backend.amr.financial_p2_oos_fdr import (
    FAMILY_F,
    FAMILY_M,
    FAMILY_R_HARD,
    FAMILY_R_SOFT,
    FAMILY_ROBUSTNESS,
    FROZEN_HYPOTHESES,
    FROZEN_HYPOTHESIS_IDS,
    OOS_ALPHA,
    OOS_CONCLUSION_BOUNDARY,
    OOS_FAMILY_IDS,
    OOS_INDEPENDENCE_OUTPUT_FINGERPRINT,
    FinancialP2OOSFDRConfig,
    compute_partition_fingerprint,
    evaluate_financial_p2_oos_fdr,
)
from tests.fixtures.synthetic_financial_p2_oos_fdr_cases import (
    EXECUTION_TIMESTAMP,
    INDEPENDENCE_ANCHOR,
    make_batch,
    make_configuration,
    make_frame,
    make_partition_manifest,
)


@pytest.fixture(scope="module")
def golden():
    return evaluate_financial_p2_oos_fdr(
        make_batch(),
        configuration=make_configuration(),
    )


def _error_codes(result) -> set[str]:
    return {
        item.code
        for item in result.oos_fdr_audit.errors
    }


def _evaluate(
    *,
    frame: pd.DataFrame | None = None,
    manifest: pd.DataFrame | None = None,
    anchor=None,
    provenance=None,
    declared_partition_fingerprint: str | None = None,
):
    frozen_manifest = (
        make_partition_manifest()
        if manifest is None
        else manifest
    )
    fingerprint = (
        compute_partition_fingerprint(frozen_manifest)
        if {
            "observation_id",
            "split",
            "period",
            "company_id",
        }.issubset(frozen_manifest.columns)
        else "0" * 64
    )
    return evaluate_financial_p2_oos_fdr(
        make_batch(
            frame=frame,
            manifest=frozen_manifest,
            anchor=anchor,
            provenance=provenance,
            declared_partition_fingerprint=
                (
                    fingerprint
                    if declared_partition_fingerprint is None
                    else declared_partition_fingerprint
                ),
        ),
        configuration=FinancialP2OOSFDRConfig(
            expected_partition_fingerprint=fingerprint,
            execution_timestamp=EXECUTION_TIMESTAMP,
        ),
    )


class TestFrozenRegistryAndPolicy:
    def test_registry_has_exact_named_hypotheses(self):
        assert FROZEN_HYPOTHESIS_IDS == (
            "F-P01", "F-P02", "F-P03", "F-P04", "F-P05", "F-P06",
            "R-H01", "R-H02", "R-H03", "R-H04", "R-H05",
            "R-S01", "R-S02", "R-S03", "R-S04", "R-S05",
            "M-E01", "M-E02", "M-E03", "M-E04", "M-E05", "M-E06",
            "M-E07",
        )
        assert len(FROZEN_HYPOTHESES) == 23

    def test_registry_has_exact_family_counts(self):
        counts = {
            family: sum(
                item.test_family_id == family
                for item in FROZEN_HYPOTHESES
            )
            for family in OOS_FAMILY_IDS
        }
        assert counts == {
            FAMILY_F: 6,
            FAMILY_R_HARD: 5,
            FAMILY_R_SOFT: 5,
            FAMILY_M: 7,
            FAMILY_ROBUSTNESS: 0,
        }

    def test_registry_freezes_track_class_direction_and_method(self):
        lookup = {
            item.hypothesis_id: item
            for item in FROZEN_HYPOTHESES
        }
        assert lookup["F-P01"].hypothesis_class == "primary"
        assert lookup["F-P05"].prior_direction == "negative"
        assert lookup["R-H01"].test_method == (
            "pr_auc_increment_permutation"
        )
        assert lookup["R-S01"].hypothesis_class == "secondary"
        assert lookup["M-E01"].prior_direction == "two_sided"
        assert all(
            item.test_period == "latest_20pct_one_shot"
            or item.test_period
            == "latest_20pct_one_shot_company_disjoint"
            for item in FROZEN_HYPOTHESES
        )

    def test_configuration_freezes_authoritative_policy(self):
        config = make_configuration()
        assert config.alpha == OOS_ALPHA
        assert config.split == (0.60, 0.20, 0.20)
        assert config.adjustment_method == "benjamini_hochberg"
        assert config.adjustment_scope == "within_frozen_family"
        assert config.permutation_count == 199
        assert config.random_seed == 20260731
        assert config.test_selection_allowed is False
        assert config.failed_runs_retained is True
        assert config.failed_runs_count_in_family_denominator is True
        assert config.synthetic_test_only is True

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("alpha", 0.10),
            ("split", (0.70, 0.10, 0.20)),
            ("adjustment_method", "bonferroni"),
            ("adjustment_scope", "global"),
            ("permutation_count", 999),
            ("random_seed", 1),
            ("minimum_effect_observations", 8),
            ("minimum_r_positives", 10),
            ("minimum_r_negatives", 10),
            ("test_use_policy", "reusable_test"),
            ("test_selection_allowed", True),
            ("failed_runs_retained", False),
            ("failed_runs_count_in_family_denominator", False),
            ("registry_version", "drift"),
            ("matrix_version", "drift"),
            ("synthetic_test_only", False),
        ],
    )
    def test_configuration_rejects_policy_drift(
        self,
        field_name,
        value,
    ):
        with pytest.raises(ValueError):
            make_configuration(**{field_name: value})

    def test_configuration_requires_frozen_partition_sha(self):
        with pytest.raises(ValueError):
            FinancialP2OOSFDRConfig(
                expected_partition_fingerprint="not-a-sha",
                execution_timestamp=EXECUTION_TIMESTAMP,
            )


class TestReadyEvaluation:
    def test_ready_and_all_named_runs_retained(self, golden):
        audit = golden.oos_fdr_audit
        assert audit.gate_status == "ready"
        assert audit.errors == ()
        assert audit.registered_hypothesis_count == 23
        assert audit.retained_run_count == 23
        assert audit.completed_run_count == 20
        assert audit.failed_run_count == 3
        assert tuple(
            item.hypothesis_id
            for item in golden.hypothesis_results
        ) == FROZEN_HYPOTHESIS_IDS

    def test_family_statuses_and_full_denominators(self, golden):
        expected = {
            FAMILY_F: (6, 5, 1, 6, "partial"),
            FAMILY_R_HARD: (5, 4, 1, 5, "partial"),
            FAMILY_R_SOFT: (5, 4, 1, 5, "partial"),
            FAMILY_M: (7, 7, 0, 7, "completed"),
            FAMILY_ROBUSTNESS: (0, 0, 0, 0, "not_run"),
        }
        for family_id, values in expected.items():
            family = golden.get_family(family_id)
            assert (
                family.registered_hypothesis_count,
                family.completed_hypothesis_count,
                family.failed_hypothesis_count,
                family.fdr_denominator_count,
                family.family_status,
            ) == values

    def test_robustness_family_is_explicitly_not_run(self, golden):
        family = golden.get_family(FAMILY_ROBUSTNESS)
        assert family.reason_code == "NO_NAMED_HYPOTHESES_REGISTERED"
        assert family.rejected_hypothesis_ids == ()

    def test_expected_failed_runs_are_retained(self, golden):
        expected = {
            "F-P06": (
                "insufficient_sample",
                "INSUFFICIENT_TEST_OBSERVATIONS",
            ),
            "R-H05": (
                "insufficient_label",
                "INSUFFICIENT_HARD_TEST_LABELS",
            ),
            "R-S05": (
                "insufficient_sample",
                "INSUFFICIENT_TEST_OBSERVATIONS",
            ),
        }
        for hypothesis_id, pair in expected.items():
            result = golden.get_hypothesis(hypothesis_id)
            assert (
                result.run_status,
                result.failure_reason_code,
            ) == pair
            assert result.raw_p_value is None
            assert result.adjusted_q_value is None
            assert (
                result.null_hypothesis_rejected_after_adjustment
                is False
            )

    def test_directional_f_tests_use_registered_tail(self, golden):
        positive = golden.get_hypothesis("F-P01")
        negative = golden.get_hypothesis("F-P05")
        assert positive.estimate > 0
        assert positive.direction_aligned is True
        assert negative.estimate < 0
        assert negative.direction_aligned is True
        assert positive.raw_p_value == pytest.approx(
            negative.raw_p_value
        )

    def test_r_hard_uses_only_confirmed_binary_labels(self, golden):
        item = golden.get_hypothesis("R-H01")
        assert item.test_observation_count == 60
        assert item.test_positive_count == 30
        assert item.test_negative_count == 30
        assert item.estimate > 0
        assert item.raw_p_value == pytest.approx(0.005)

    def test_r_hard_failure_exposes_class_counts(self, golden):
        item = golden.get_hypothesis("R-H05")
        assert item.test_positive_count == 10
        assert item.test_negative_count == 50

    def test_m_family_keeps_non_rejections(self, golden):
        assert golden.get_hypothesis(
            "M-E03"
        ).null_hypothesis_rejected_after_adjustment is False
        assert golden.get_hypothesis(
            "M-E06"
        ).null_hypothesis_rejected_after_adjustment is False
        assert golden.get_family(FAMILY_M).rejected_hypothesis_ids == (
            "M-E01",
            "M-E02",
            "M-E04",
            "M-E05",
            "M-E07",
        )

    def test_raw_p_and_adjusted_q_are_both_preserved(self, golden):
        for item in golden.hypothesis_results:
            if item.run_status != "completed":
                continue
            assert 0 <= item.raw_p_value <= 1
            assert 0 <= item.adjusted_q_value <= 1
            assert item.adjusted_q_value >= item.raw_p_value

    def test_bh_uses_registered_not_completed_denominator(self, golden):
        family = [
            item
            for item in golden.hypothesis_results
            if item.test_family_id == FAMILY_F
            and item.raw_p_value is not None
        ]
        ordered = sorted(family, key=lambda item: item.raw_p_value)

        def adjusted_with_denominator(denominator):
            candidates = [
                min(1.0, item.raw_p_value * denominator / rank)
                for rank, item in enumerate(ordered, start=1)
            ]
            adjusted = [0.0] * len(candidates)
            running = 1.0
            for index in range(len(candidates) - 1, -1, -1):
                running = min(running, candidates[index])
                adjusted[index] = running
            return adjusted

        actual = [item.adjusted_q_value for item in ordered]
        expected_six = adjusted_with_denominator(6)
        counterfactual_five = adjusted_with_denominator(5)
        assert actual == pytest.approx(expected_six, abs=1e-25)
        assert max(
            abs(left - right)
            for left, right in zip(actual, counterfactual_five)
        ) > 1e-14

    def test_audit_freezes_one_shot_and_failure_policy(self, golden):
        audit = golden.oos_fdr_audit
        assert audit.test_use_policy == (
            "latest_20pct_one_shot_read_only"
        )
        assert audit.test_selection_allowed is False
        assert audit.failed_runs_retained is True
        assert audit.failed_runs_count_in_family_denominator is True
        assert audit.independence_output_fingerprint == (
            OOS_INDEPENDENCE_OUTPUT_FINGERPRINT
        )

    def test_conclusion_boundary_is_non_production(self, golden):
        audit = golden.oos_fdr_audit
        assert audit.research_conclusion == "exploratory"
        assert audit.production_status == "not production ready"
        assert audit.conclusion_boundary == OOS_CONCLUSION_BOUNDARY
        serialized = json.dumps(golden.to_dict(), sort_keys=True)
        for forbidden in (
            '"production_status": "production ready"',
            '"research_conclusion": "supportive"',
            '"admission": true',
            '"fraud": true',
        ):
            assert forbidden not in serialized

    def test_warning_contract_is_explicit(self, golden):
        assert {
            warning.code
            for warning in golden.oos_fdr_audit.warnings
        } == {
            "SYNTHETIC_OOS_ONLY",
            "FAILED_RUNS_RETAINED",
            "ROBUSTNESS_FAMILY_NOT_NAMED",
            "FDR_NOT_ADMISSION",
        }


class TestNoTestSelectionAndDeterminism:
    def test_train_and_calibration_values_cannot_change_results(
        self,
        golden,
    ):
        frame = make_frame()
        mask = frame["split"].isin(["train", "calibration"])
        frame.loc[mask, "effect_value"] = 999.0
        frame.loc[mask, "baseline_score"] = -999.0
        frame.loc[mask, "augmented_score"] = 999.0
        changed = _evaluate(frame=frame)
        assert changed.oos_fdr_audit.gate_status == "ready"
        assert changed.hypothesis_results == golden.hypothesis_results
        assert changed.family_results == golden.family_results
        assert changed.oos_fdr_audit.output_fingerprint == (
            golden.oos_fdr_audit.output_fingerprint
        )
        assert changed.oos_fdr_audit.test_input_fingerprint == (
            golden.oos_fdr_audit.test_input_fingerprint
        )
        assert changed.oos_fdr_audit.input_fingerprint != (
            golden.oos_fdr_audit.input_fingerprint
        )

    def test_test_value_changes_one_shot_output(self, golden):
        frame = make_frame()
        mask = (
            (frame["hypothesis_id"] == "M-E03")
            & (frame["split"] == "test")
        )
        frame.loc[mask, "effect_value"] = (
            pd.to_numeric(frame.loc[mask, "effect_value"]) + 0.20
        )
        changed = _evaluate(frame=frame)
        assert changed.get_hypothesis("M-E03").estimate > 0.20
        assert changed.oos_fdr_audit.output_fingerprint != (
            golden.oos_fdr_audit.output_fingerprint
        )

    def test_repeated_run_is_byte_stable(self, golden):
        repeated = _evaluate()
        assert repeated.to_dict() == golden.to_dict()

    def test_row_order_does_not_change_fingerprints(self, golden):
        frame = make_frame().sample(frac=1, random_state=7)
        manifest = make_partition_manifest().sample(
            frac=1,
            random_state=9,
        )
        result = _evaluate(frame=frame, manifest=manifest)
        assert result.to_dict() == golden.to_dict()

    def test_batch_defensively_copies_inputs(self, golden):
        frame = make_frame()
        manifest = make_partition_manifest()
        batch = make_batch(frame=frame, manifest=manifest)
        frame.loc[:, "split"] = "test"
        manifest.loc[:, "split"] = "test"
        result = evaluate_financial_p2_oos_fdr(
            batch,
            configuration=make_configuration(),
        )
        assert result.to_dict() == golden.to_dict()
        returned = batch.get_frame()
        returned.loc[:, "split"] = "test"
        assert set(batch.get_frame()["split"]) == {
            "train",
            "calibration",
            "test",
        }

    def test_partition_fingerprint_is_order_invariant(self):
        manifest = make_partition_manifest()
        shuffled = manifest.sample(frac=1, random_state=42)
        assert compute_partition_fingerprint(manifest) == (
            compute_partition_fingerprint(shuffled)
        )

    def test_hashes_are_sha256(self, golden):
        audit = golden.oos_fdr_audit
        values = (
            audit.registry_fingerprint,
            audit.configuration_fingerprint,
            audit.input_fingerprint,
            audit.partition_fingerprint,
            audit.test_input_fingerprint,
            audit.output_fingerprint,
            audit.content_hash,
        )
        for value in values:
            assert len(value) == 64
            int(value, 16)
        for item in golden.hypothesis_results:
            assert len(item.content_hash) == 64
        for item in golden.family_results:
            assert len(item.content_hash) == 64


class TestFailClosedValidation:
    @pytest.mark.parametrize(
        ("anchor_change",),
        [
            ({"task_id": "WRONG"},),
            ({"status": "PENDING"},),
            ({"output_fingerprint": "0" * 64},),
        ],
    )
    def test_invalid_independence_anchor_blocks(
        self,
        anchor_change,
    ):
        anchor = dict(INDEPENDENCE_ANCHOR)
        anchor.update(anchor_change)
        result = _evaluate(anchor=anchor)
        assert result.oos_fdr_audit.gate_status == "blocked"
        assert "INVALID_INDEPENDENCE_ANCHOR" in _error_codes(result)

    def test_non_synthetic_input_blocks(self):
        result = _evaluate(provenance={"synthetic_test_only": False})
        assert result.oos_fdr_audit.gate_status == "blocked"
        assert "NON_SYNTHETIC_INPUT" in _error_codes(result)

    def test_missing_manifest_column_blocks(self):
        manifest = make_partition_manifest().drop(
            columns=["company_id"]
        )
        result = _evaluate(manifest=manifest)
        assert result.oos_fdr_audit.gate_status == "blocked"
        assert "MISSING_COLUMN" in _error_codes(result)

    def test_missing_frame_column_blocks(self):
        frame = make_frame().drop(columns=["effect_value"])
        result = _evaluate(frame=frame)
        assert result.oos_fdr_audit.gate_status == "blocked"
        assert "MISSING_COLUMN" in _error_codes(result)

    def test_duplicate_manifest_observation_blocks(self):
        manifest = make_partition_manifest()
        manifest = pd.concat(
            [manifest, manifest.iloc[[0]]],
            ignore_index=True,
        )
        result = _evaluate(manifest=manifest)
        assert "DUPLICATE_OBSERVATION_ID" in _error_codes(result)

    def test_duplicate_hypothesis_observation_blocks(self):
        frame = make_frame()
        frame = pd.concat(
            [frame, frame.iloc[[0]]],
            ignore_index=True,
        )
        result = _evaluate(frame=frame)
        assert (
            "DUPLICATE_HYPOTHESIS_OBSERVATION"
            in _error_codes(result)
        )

    def test_unknown_hypothesis_blocks(self):
        frame = make_frame()
        frame.loc[0, "hypothesis_id"] = "POST-HOC-01"
        result = _evaluate(frame=frame)
        assert "UNKNOWN_HYPOTHESIS" in _error_codes(result)

    @pytest.mark.parametrize(
        "field_name",
        [
            "selected_direction",
            "selected_threshold",
            "selected_model",
            "selected_family",
            "selected_sample",
        ],
    )
    def test_test_selection_fields_block(self, field_name):
        frame = make_frame()
        frame[field_name] = "forbidden"
        result = _evaluate(frame=frame)
        assert "TEST_SELECTION_FIELD_PRESENT" in _error_codes(result)

    def test_frame_manifest_partition_mismatch_blocks(self):
        frame = make_frame()
        frame.loc[0, "split"] = "test"
        result = _evaluate(frame=frame)
        assert "PARTITION_MISMATCH" in _error_codes(result)

    def test_declared_partition_hash_mismatch_blocks(self):
        result = _evaluate(
            declared_partition_fingerprint="0" * 64
        )
        assert (
            "PARTITION_FINGERPRINT_MISMATCH"
            in _error_codes(result)
        )

    def test_configuration_partition_hash_mismatch_blocks(self):
        batch = make_batch()
        config = make_configuration()
        wrong = FinancialP2OOSFDRConfig(
            expected_partition_fingerprint="0" * 64,
            execution_timestamp=config.execution_timestamp,
        )
        result = evaluate_financial_p2_oos_fdr(
            batch,
            configuration=wrong,
        )
        assert (
            "PARTITION_FINGERPRINT_MISMATCH"
            in _error_codes(result)
        )

    def test_non_60_20_20_partition_blocks(self):
        manifest = make_partition_manifest()
        manifest.loc[
            manifest["observation_id"] == "PERIOD-047",
            "split",
        ] = "train"
        frame = make_frame()
        frame.loc[
            frame["observation_id"] == "PERIOD-047",
            "split",
        ] = "train"
        result = _evaluate(frame=frame, manifest=manifest)
        assert "SPLIT_RATIO_MISMATCH" in _error_codes(result)

    def test_time_order_violation_blocks(self):
        manifest = make_partition_manifest()
        train_id = "PERIOD-000"
        test_id = "PERIOD-059"
        train_period = manifest.loc[
            manifest["observation_id"] == train_id,
            "period",
        ].iloc[0]
        test_period = manifest.loc[
            manifest["observation_id"] == test_id,
            "period",
        ].iloc[0]
        manifest.loc[
            manifest["observation_id"] == train_id,
            "period",
        ] = test_period
        manifest.loc[
            manifest["observation_id"] == test_id,
            "period",
        ] = train_period
        frame = make_frame()
        frame.loc[frame["observation_id"] == train_id, "period"] = (
            test_period
        )
        frame.loc[frame["observation_id"] == test_id, "period"] = (
            train_period
        )
        result = _evaluate(frame=frame, manifest=manifest)
        assert "TIME_ORDER_VIOLATION" in _error_codes(result)

    def test_r_company_overlap_blocks(self):
        manifest = make_partition_manifest()
        manifest.loc[
            manifest["observation_id"] == "RH-240",
            "company_id",
        ] = "RH-COMPANY-000"
        frame = make_frame()
        frame.loc[
            frame["observation_id"] == "RH-240",
            "company_id",
        ] = "RH-COMPANY-000"
        result = _evaluate(frame=frame, manifest=manifest)
        assert "R_COMPANY_OVERLAP" in _error_codes(result)

    def test_invalid_split_blocks(self):
        manifest = make_partition_manifest()
        manifest.loc[0, "split"] = "holdout"
        frame = make_frame()
        frame.loc[
            frame["observation_id"] == manifest.loc[0, "observation_id"],
            "split",
        ] = "holdout"
        result = _evaluate(frame=frame, manifest=manifest)
        assert "INVALID_SPLIT" in _error_codes(result)

    def test_blocked_result_runs_no_hypothesis(self):
        result = _evaluate(provenance={"synthetic_test_only": False})
        assert result.hypothesis_results == ()
        assert result.oos_fdr_audit.retained_run_count == 0
        assert result.oos_fdr_audit.production_status == (
            "not production ready"
        )


def test_result_lookup_rejects_unknown_key(golden):
    with pytest.raises(LookupError):
        golden.get_hypothesis("UNKNOWN")
    with pytest.raises(LookupError):
        golden.get_family("UNKNOWN")
