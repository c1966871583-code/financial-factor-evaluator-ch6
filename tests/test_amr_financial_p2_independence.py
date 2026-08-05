"""Acceptance tests for FIN-P2-INDEP."""

from __future__ import annotations

import copy
import json

import pandas as pd
import pytest

from backend.amr.financial_p2_independence import (
    INDEP_CONCLUSION_BOUNDARY,
    FinancialP2IndependenceBatch,
    FinancialP2IndependenceConfig,
    IndependenceErrorCode,
    evaluate_financial_p2_independence,
)
from tests.fixtures.synthetic_financial_p2_independence_cases import (
    FACTOR_IDS,
    PERIOD_COUNT,
    SECURITY_COUNT,
    TRACK_ANCHORS,
    clone_frame,
    evaluation_dates,
    make_batch,
    make_configuration,
    make_frame,
)


@pytest.fixture(scope="module")
def golden():
    return evaluate_financial_p2_independence(
        make_batch(),
        configuration=make_configuration(),
    )


def _error_codes(result) -> set[str]:
    return {
        item.code
        for item in result.independence_audit.errors
    }


def _all_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_keys(item)


class TestFrozenConfiguration:
    def test_authoritative_defaults(self):
        config = make_configuration()
        assert config.factor_ids == FACTOR_IDS
        assert config.minimum_cross_section == 30
        assert config.minimum_periods == 12
        assert config.minimum_r_hard_positives == 30
        assert config.m_horizon == 20
        assert config.hac_max_lag == 3
        assert config.ordinary_t_stat_public is False
        assert config.oos_status == "not_run"
        assert config.multiple_testing_status == "not_run"
        assert config.track_replacement_allowed is False
        assert (
            config.automatic_best_specification_selection
            is False
        )
        assert config.synthetic_test_only is True

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("factor_ids", ("ROE",)),
            ("minimum_cross_section", 29),
            ("minimum_periods", 11),
            ("minimum_r_hard_positives", 10),
            ("m_horizon", 5),
            ("hac_max_lag", 2),
            ("peer_method", "pearson"),
            ("ordinary_t_stat_public", True),
            ("oos_status", "completed"),
            ("multiple_testing_status", "completed"),
            ("track_replacement_allowed", True),
            ("automatic_best_specification_selection", True),
            ("synthetic_test_only", False),
        ],
    )
    def test_rejects_policy_drift(self, field_name, value):
        with pytest.raises(ValueError):
            make_configuration(**{field_name: value})

    def test_dates_must_be_sorted_unique_and_sufficient(self):
        with pytest.raises(ValueError):
            make_configuration(
                evaluation_dates=tuple(reversed(evaluation_dates()))
            )
        with pytest.raises(ValueError):
            make_configuration(
                evaluation_dates=evaluation_dates()[:11]
            )
        with pytest.raises(ValueError):
            make_configuration(analysis_as_of=evaluation_dates()[-1])


class TestHappyPath:
    def test_gate_ready_and_three_factors(self, golden):
        assert golden.independence_audit.gate_status == "ready"
        assert golden.independence_audit.errors == ()
        assert tuple(
            item.factor_id for item in golden.factor_evidence
        ) == FACTOR_IDS

    def test_common_factor_side_sample(self, golden):
        audit = golden.independence_audit
        assert audit.input_row_count == (
            len(FACTOR_IDS) * PERIOD_COUNT * SECURITY_COUNT
        )
        assert audit.accepted_row_count == audit.input_row_count
        for factor in golden.factor_evidence:
            assert factor.factor_sample_count == (
                PERIOD_COUNT * SECURITY_COUNT
            )
            assert factor.evaluation_periods == PERIOD_COUNT
            assert factor.neutralization_status == "completed"

    def test_peer_correlation_is_reported_not_used_as_gate(self, golden):
        for factor in golden.factor_evidence:
            correlation = (
                factor.same_type_peer_rank_correlation_mean
            )
            assert correlation is not None
            assert 0.40 < correlation < 0.70
            assert factor.peer_correlation_method == "spearman"
            assert factor.conclusion == "exploratory"

    def test_m_fama_macbeth_increment(self, golden):
        for factor in golden.factor_evidence:
            evidence = factor.m_evidence
            assert evidence.validation_track == "M"
            assert evidence.evidence_priority == "primary"
            assert evidence.method == (
                "fama_macbeth_20d_conditional_increment"
            )
            assert evidence.status == "completed"
            assert evidence.effective_periods == PERIOD_COUNT
            assert evidence.paired_count == (
                PERIOD_COUNT * SECURITY_COUNT
            )
            assert evidence.incremental_beta_mean > 0
            assert evidence.incremental_beta_hac_t_stat > 0
            assert evidence.incremental_r2_mean > 0
            assert evidence.conditional_rank_ic_mean > 0
            assert (
                evidence.conditional_rank_ic_positive_ratio == 1.0
            )

    def test_f_residual_increment(self, golden):
        for factor in golden.factor_evidence:
            evidence = factor.f_evidence
            assert evidence.validation_track == "F"
            assert evidence.evidence_priority == "supporting"
            assert evidence.method == (
                "next_quarter_residual_conditional_increment"
            )
            assert evidence.status == "completed"
            assert evidence.incremental_beta_mean > 0
            assert evidence.incremental_beta_hac_t_stat > 0
            assert evidence.incremental_r2_mean > 0
            assert evidence.conditional_rank_ic_mean > 0

    def test_r_hard_label_increment_and_exclusions(
        self,
        golden,
    ):
        frame = make_frame()
        for factor in golden.factor_evidence:
            evidence = factor.r_evidence
            expected = frame[
                frame["factor_id"] == factor.factor_id
            ]["r_label_state"].value_counts()
            assert evidence.validation_track == "R"
            assert evidence.evidence_priority == "risk"
            assert evidence.status == "completed"
            assert evidence.hard_positive_count == int(
                expected.get("hard_positive", 0)
            )
            assert evidence.confirmed_negative_count == int(
                expected.get("confirmed_negative", 0)
            )
            assert evidence.soft_positive_excluded_count == int(
                expected.get("soft_positive", 0)
            )
            assert evidence.unlabeled_excluded_count == int(
                expected.get("unlabeled", 0)
            )
            assert evidence.incremental_pr_auc > 0.10
            assert evidence.incremental_roc_auc > 0.10
            assert evidence.evaluation_scope == (
                "descriptive_in_sample_only"
            )

    def test_track_statuses_cannot_replace_each_other(self, golden):
        for factor in golden.factor_evidence:
            assert factor.track_replacement_allowed is False
            assert (
                factor.automatic_best_specification_selection
                is False
            )
            assert factor.oos_status == "not_run"
            assert factor.multiple_testing_status == "not_run"

    def test_public_result_excludes_ordinary_t_stat(self, golden):
        payload = golden.to_dict()
        keys = tuple(_all_keys(payload))
        assert "ordinary_t_stat" not in keys
        assert "ordinary_t_stat_public" in keys
        assert all(
            evidence.ordinary_t_stat_public is False
            for factor in golden.factor_evidence
            for evidence in (
                factor.m_evidence,
                factor.f_evidence,
            )
        )

    def test_audit_boundaries_and_anchors(self, golden):
        audit = golden.independence_audit
        assert audit.validation_tracks == ("M", "F", "R")
        assert dict(audit.predecessor_anchor_fingerprints) == {
            track: TRACK_ANCHORS[track]["output_fingerprint"]
            for track in ("M", "F", "R")
        }
        assert audit.ordinary_t_stat_public is False
        assert audit.oos_status == "not_run"
        assert audit.multiple_testing_status == "not_run"
        assert audit.synthetic_test_only is True
        assert audit.conclusion_boundary == INDEP_CONCLUSION_BOUNDARY

    def test_all_fingerprints_are_sha256(self, golden):
        audit = golden.independence_audit
        values = [
            audit.configuration_fingerprint,
            audit.input_fingerprint,
            audit.factor_sample_fingerprint,
            audit.control_input_fingerprint,
            audit.m_label_fingerprint,
            audit.f_label_fingerprint,
            audit.r_label_fingerprint,
            audit.output_fingerprint,
            audit.content_hash,
        ]
        for factor in golden.factor_evidence:
            values.extend(
                [
                    factor.neutralized_factor_fingerprint,
                    factor.conditional_factor_fingerprint,
                    factor.content_hash,
                    factor.m_evidence.label_fingerprint,
                    factor.m_evidence.content_hash,
                    factor.f_evidence.label_fingerprint,
                    factor.f_evidence.content_hash,
                    factor.r_evidence.label_fingerprint,
                    factor.r_evidence.content_hash,
                ]
            )
        assert all(
            len(value) == 64
            and set(value) <= set("0123456789abcdef")
            for value in values
        )

    def test_serializable_and_get_factor(self, golden):
        serialized = json.dumps(
            golden.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        assert "FinancialP2Independence-v1.0" in serialized
        assert golden.get_factor("ROE").factor_id == "ROE"
        with pytest.raises(LookupError):
            golden.get_factor("NOT_A_FACTOR")


class TestLabelIndependence:
    def test_deleting_m_labels_changes_only_m_track(self, golden):
        frame = make_frame()
        frame["m_forward_return"] = None
        frame["m_label_available_at"] = None
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert result.independence_audit.gate_status == "ready"
        assert (
            result.independence_audit.factor_sample_fingerprint
            == golden.independence_audit.factor_sample_fingerprint
        )
        assert (
            result.independence_audit.f_label_fingerprint
            == golden.independence_audit.f_label_fingerprint
        )
        assert (
            result.independence_audit.r_label_fingerprint
            == golden.independence_audit.r_label_fingerprint
        )
        for factor_id in FACTOR_IDS:
            before = golden.get_factor(factor_id)
            after = result.get_factor(factor_id)
            assert after.m_evidence.status == "not_run"
            assert (
                after.f_evidence.to_dict()
                == before.f_evidence.to_dict()
            )
            assert (
                after.r_evidence.to_dict()
                == before.r_evidence.to_dict()
            )

    def test_deleting_f_labels_changes_only_f_track(self, golden):
        frame = make_frame()
        frame["f_residual"] = None
        frame["f_label_available_at"] = None
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert (
            result.independence_audit.factor_sample_fingerprint
            == golden.independence_audit.factor_sample_fingerprint
        )
        for factor_id in FACTOR_IDS:
            before = golden.get_factor(factor_id)
            after = result.get_factor(factor_id)
            assert after.f_evidence.status == "not_run"
            assert (
                after.m_evidence.to_dict()
                == before.m_evidence.to_dict()
            )
            assert (
                after.r_evidence.to_dict()
                == before.r_evidence.to_dict()
            )

    def test_unlabeling_r_changes_only_r_track(self, golden):
        frame = make_frame()
        frame["r_label_state"] = "unlabeled"
        frame["r_label_available_at"] = None
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert (
            result.independence_audit.factor_sample_fingerprint
            == golden.independence_audit.factor_sample_fingerprint
        )
        for factor_id in FACTOR_IDS:
            before = golden.get_factor(factor_id)
            after = result.get_factor(factor_id)
            assert after.r_evidence.status == "not_run"
            assert (
                after.m_evidence.to_dict()
                == before.m_evidence.to_dict()
            )
            assert (
                after.f_evidence.to_dict()
                == before.f_evidence.to_dict()
            )

    def test_insufficient_m_periods_is_not_zero_effect(self):
        frame = make_frame()
        removed_dates = set(evaluation_dates()[:7])
        mask = frame["evaluation_date"].isin(removed_dates)
        frame.loc[mask, "m_forward_return"] = None
        frame.loc[mask, "m_label_available_at"] = None
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        evidence = result.get_factor("ROE").m_evidence
        assert evidence.status == "not_run"
        assert evidence.reason_code == "INSUFFICIENT_EFFECTIVE_PERIODS"
        assert evidence.incremental_beta_mean is None
        assert result.get_factor("ROE").f_evidence.status == "completed"

    def test_insufficient_r_hard_labels_is_not_run(self):
        frame = make_frame()
        hard = frame["r_label_state"] == "hard_positive"
        frame.loc[hard, "r_label_state"] = "soft_positive"
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        evidence = result.get_factor("ROE").r_evidence
        assert evidence.status == "not_run"
        assert evidence.reason_code == "INSUFFICIENT_HARD_LABELS"
        assert evidence.incremental_pr_auc is None

    def test_labels_after_analysis_as_of_become_unavailable(self):
        frame = make_frame()
        mask = (
            (frame["factor_id"] == "ROE")
            & (frame["evaluation_date"] == evaluation_dates()[0])
        )
        frame.loc[mask, "m_label_available_at"] = "2026-01-01"
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert result.independence_audit.gate_status == "ready"
        assert any(
            item.code == "LABEL_NOT_AVAILABLE_BY_AS_OF"
            and item.track == "M"
            for item in result.independence_audit.warnings
        )


class TestPITAndInputGates:
    def test_future_control_blocks(self):
        frame = make_frame()
        frame.loc[0, "control_effective_date"] = "2026-01-01"
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert result.independence_audit.gate_status == "blocked"
        assert "CONTROL_PIT_VIOLATION" in _error_codes(result)
        assert result.factor_evidence == ()

    @pytest.mark.parametrize(
        ("value_column", "date_column", "track"),
        [
            ("m_forward_return", "m_label_available_at", "M"),
            ("f_residual", "f_label_available_at", "F"),
        ],
    )
    def test_continuous_label_timing_violation_blocks(
        self,
        value_column,
        date_column,
        track,
    ):
        frame = make_frame()
        frame.loc[0, date_column] = frame.loc[0, "evaluation_date"]
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert "LABEL_TIMING_VIOLATION" in _error_codes(result)
        assert any(
            issue.track == track
            for issue in result.independence_audit.errors
        )

    def test_r_label_timing_violation_blocks(self):
        frame = make_frame()
        row = frame.index[
            frame["r_label_state"] != "unlabeled"
        ][0]
        frame.loc[row, "r_label_available_at"] = frame.loc[
            row,
            "evaluation_date",
        ]
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert "LABEL_TIMING_VIOLATION" in _error_codes(result)

    def test_missing_label_metadata_blocks(self):
        frame = make_frame()
        frame.loc[0, "m_label_available_at"] = None
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert "LABEL_METADATA_MISSING" in _error_codes(result)

    def test_duplicate_key_blocks(self):
        frame = make_frame()
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert "DUPLICATE_FACTOR_KEY" in _error_codes(result)

    def test_missing_column_blocks(self):
        frame = make_frame().drop(columns=["industry_code"])
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert "MISSING_COLUMN" in _error_codes(result)

    def test_unsupported_factor_blocks(self):
        frame = make_frame()
        frame.loc[0, "factor_id"] = "UNKNOWN"
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert "UNSUPPORTED_FACTOR_ID" in _error_codes(result)

    def test_non_synthetic_input_blocks(self):
        result = evaluate_financial_p2_independence(
            make_batch(provenance={"synthetic_test_only": False}),
            configuration=make_configuration(),
        )
        assert "NON_SYNTHETIC_INPUT" in _error_codes(result)

    @pytest.mark.parametrize(
        ("track", "field_name", "value", "expected_code"),
        [
            ("M", "status", "PENDING", "PREDECESSOR_NOT_ACCEPTED"),
            (
                "F",
                "evidence_priority",
                "primary",
                "INVALID_PREDECESSOR_ANCHOR",
            ),
            (
                "R",
                "output_fingerprint",
                "not-a-hash",
                "INVALID_PREDECESSOR_ANCHOR",
            ),
            (
                "M",
                "output_fingerprint",
                "0" * 64,
                "INVALID_PREDECESSOR_ANCHOR",
            ),
        ],
    )
    def test_invalid_predecessor_anchor_blocks(
        self,
        track,
        field_name,
        value,
        expected_code,
    ):
        anchors = copy.deepcopy(TRACK_ANCHORS)
        anchors[track][field_name] = value
        result = evaluate_financial_p2_independence(
            make_batch(anchors=anchors),
            configuration=make_configuration(),
        )
        assert expected_code in _error_codes(result)


class TestDeterminismAndImmutability:
    def test_batch_defensive_copies(self):
        frame = make_frame()
        anchors = copy.deepcopy(TRACK_ANCHORS)
        batch = make_batch(frame=frame, anchors=anchors)
        frame.loc[0, "factor_value"] = 999.0
        anchors["M"]["status"] = "BROKEN"
        assert batch.get_frame().loc[0, "factor_value"] != 999.0
        assert batch.get_track_anchors()["M"]["status"] == "ACCEPTED"

    def test_evaluation_does_not_mutate_inputs(self):
        frame = make_frame()
        before = clone_frame(frame)
        anchors = copy.deepcopy(TRACK_ANCHORS)
        batch = make_batch(frame=frame, anchors=anchors)
        evaluate_financial_p2_independence(
            batch,
            configuration=make_configuration(),
        )
        pd.testing.assert_frame_equal(frame, before)
        assert anchors == TRACK_ANCHORS

    def test_row_order_is_deterministic(self, golden):
        reversed_frame = make_frame().iloc[::-1].reset_index(drop=True)
        result = evaluate_financial_p2_independence(
            make_batch(frame=reversed_frame),
            configuration=make_configuration(),
        )
        assert (
            result.independence_audit.input_fingerprint
            == golden.independence_audit.input_fingerprint
        )
        assert (
            result.independence_audit.output_fingerprint
            == golden.independence_audit.output_fingerprint
        )
        assert result.to_dict() == golden.to_dict()

    def test_repeat_run_is_identical(self, golden):
        repeated = evaluate_financial_p2_independence(
            make_batch(),
            configuration=make_configuration(),
        )
        assert repeated.to_dict() == golden.to_dict()

    def test_control_change_does_not_change_factor_sample_hash(
        self,
        golden,
    ):
        frame = make_frame()
        frame.loc[0, "log_market_cap"] += 0.5
        result = evaluate_financial_p2_independence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert (
            result.independence_audit.factor_sample_fingerprint
            == golden.independence_audit.factor_sample_fingerprint
        )
        assert (
            result.independence_audit.control_input_fingerprint
            != golden.independence_audit.control_input_fingerprint
        )

    def test_type_contracts(self):
        with pytest.raises(TypeError):
            FinancialP2IndependenceBatch(
                dataset_id="x",
                version="v1",
                source="test",
                _frame=[],
                track_anchors=TRACK_ANCHORS,
                provenance={"synthetic_test_only": True},
            )
        with pytest.raises(TypeError):
            evaluate_financial_p2_independence(
                object(),
                configuration=make_configuration(),
            )
        with pytest.raises(TypeError):
            evaluate_financial_p2_independence(
                make_batch(),
                configuration=object(),
            )

    def test_configuration_is_json_serializable(self):
        config = make_configuration()
        assert isinstance(config, FinancialP2IndependenceConfig)
        json.dumps(config.to_dict(), allow_nan=False)
