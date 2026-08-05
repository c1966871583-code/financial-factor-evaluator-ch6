"""FIN-P2-F supporting-evidence acceptance tests."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from backend.amr.financial_p2_f_evidence import (
    P2_F_AUDIT_SCHEMA_VERSION,
    P2_F_BASELINE,
    P2_F_EVIDENCE_PRIORITY,
    P2_F_HASH_CONTRACT_VERSION,
    P2_F_INTERVAL_LEVEL,
    P2_F_MIN_CALIBRATION_RESIDUALS,
    P2_F_MODEL,
    P2_F_POLICY_VERSION,
    P2_F_PREDICTION_SCHEMA_VERSION,
    P2_F_SCHEMA_VERSION,
    P2_F_SPLIT,
    P2_F_TARGET_SCHEMA_VERSION,
    P2_F_TARGETS,
    FinancialP2FEvidenceConfig,
    FinancialP2FForecastBatch,
    evaluate_financial_p2_f_evidence,
)
from tests.fixtures.synthetic_financial_p2_f_evidence_cases import (
    AS_OF,
    QUARTER_COUNT,
    SECURITY_COUNT,
    make_batch,
    make_configuration,
    make_forecast_frame,
    make_golden_case,
)


@pytest.fixture(scope="module")
def golden_inputs():
    return make_golden_case()


@pytest.fixture(scope="module")
def golden_result(golden_inputs):
    batch, configuration = golden_inputs
    return evaluate_financial_p2_f_evidence(
        batch, configuration=configuration
    )


def _codes(result):
    return {item.code for item in result.evidence_audit.errors}


class TestFrozenResearchContract:
    def test_schema_policy_and_target_constants_are_frozen(self):
        assert P2_F_SCHEMA_VERSION == "FinancialP2FEvidence-v1.0"
        assert (
            P2_F_AUDIT_SCHEMA_VERSION
            == "FinancialP2FEvidenceAudit-v1.0"
        )
        assert (
            P2_F_TARGET_SCHEMA_VERSION
            == "FinancialP2FTargetEvidence-v1.0"
        )
        assert (
            P2_F_PREDICTION_SCHEMA_VERSION
            == "FinancialP2FPrediction-v1.0"
        )
        assert P2_F_HASH_CONTRACT_VERSION == "FIN-P2-F-HASH-v1.0"
        assert P2_F_POLICY_VERSION == "FIN-P2-F-POLICY-v1.0"
        assert P2_F_SPLIT == (0.60, 0.20, 0.20)
        assert P2_F_INTERVAL_LEVEL == 0.80
        assert P2_F_MIN_CALIBRATION_RESIDUALS == 20
        assert P2_F_TARGETS == (
            "next_quarter_revenue",
            "next_quarter_parent_net_profit",
            "next_quarter_operating_cash_flow",
            "next_quarter_gross_margin",
        )

    def test_configuration_is_immutable_and_supporting_only(self):
        configuration = make_configuration()
        with pytest.raises(FrozenInstanceError):
            configuration.evidence_priority = "primary"
        assert configuration.validation_track == "F"
        assert configuration.evidence_priority == "supporting"
        assert configuration.m_replacement_allowed is False
        assert configuration.stock_price_forecast_allowed is False
        assert configuration.investment_advice_allowed is False

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("train_fraction", 0.50),
            ("calibration_fraction", 0.25),
            ("test_fraction", 0.25),
            ("interval_level", 0.95),
            ("minimum_calibration_residuals", 19),
            ("validation_track", "M"),
            ("evidence_priority", "primary"),
            ("baseline", "mean"),
            ("model", "test_selected"),
            ("test_selection_policy", "tune_on_test"),
            ("m_replacement_allowed", True),
            ("stock_price_forecast_allowed", True),
            ("investment_advice_allowed", True),
            ("synthetic_test_only", False),
        ],
    )
    def test_configuration_rejects_scope_drift(
        self, field_name, value
    ):
        with pytest.raises(ValueError):
            make_configuration(**{field_name: value})

    def test_batch_owns_a_deep_frame_copy(self):
        frame = make_forecast_frame()
        batch = make_batch(frame=frame)
        frame.loc[0, "revenue"] = -999.0
        assert batch.get_frame().loc[0, "revenue"] != -999.0
        returned = batch.get_frame()
        returned.loc[0, "revenue"] = -888.0
        assert batch.get_frame().loc[0, "revenue"] != -888.0


class TestGoldenSupportingEvidence:
    def test_ready_four_target_supporting_package(self, golden_result):
        audit = golden_result.evidence_audit
        assert audit.gate_status == "ready"
        assert audit.errors == ()
        assert audit.validation_track == "F"
        assert audit.evidence_priority == "supporting"
        assert audit.m_replacement_allowed is False
        assert audit.synthetic_test_only is True
        assert tuple(
            item.target for item in golden_result.target_evidence
        ) == P2_F_TARGETS

    def test_strict_quarter_level_60_20_20_split(self, golden_result):
        for item in golden_result.target_evidence:
            assert (
                len(item.train_periods),
                len(item.calibration_periods),
                len(item.test_periods),
            ) == (13, 5, 5)
            assert (
                item.train_count,
                item.calibration_count,
                item.test_count,
            ) == (260, 100, 100)
            all_periods = (
                item.train_periods
                + item.calibration_periods
                + item.test_periods
            )
            assert tuple(sorted(all_periods)) == all_periods
            assert not (
                set(item.train_periods)
                & set(item.calibration_periods)
            )
            assert not (
                set(item.calibration_periods)
                & set(item.test_periods)
            )

    def test_model_improves_oos_mae_for_every_target(
        self, golden_result
    ):
        for item in golden_result.target_evidence:
            assert item.baseline == P2_F_BASELINE
            assert item.model == P2_F_MODEL
            assert item.oos_mae < item.baseline_mae
            assert item.relative_mae_improvement > 0.99
            assert item.improvement_positive_period_ratio == 1.0
            assert item.direction_stability == "consistent_positive"

    def test_residual_rank_ic_is_positive_and_period_explicit(
        self, golden_result
    ):
        for item in golden_result.target_evidence:
            assert item.residual_rank_ic == pytest.approx(1.0)
            assert item.evaluated_rank_ic_periods == 5

    def test_calibration_interval_uses_calibration_only(
        self, golden_result
    ):
        for item in golden_result.target_evidence:
            assert item.calibration_residual_count == 100
            assert item.interval_level == 0.80
            assert item.interval_status == "calibrated"
            assert item.interval_half_width is not None
            assert item.interval_half_width >= 0
            assert 0 <= item.interval_coverage <= 1
            for prediction in item.predictions:
                assert prediction.interval_low_80 is not None
                assert prediction.interval_high_80 is not None
                assert (
                    prediction.interval_low_80
                    <= prediction.prediction
                    <= prediction.interval_high_80
                )

    def test_reliability_mapping_matches_registered_policy(
        self, golden_result
    ):
        assert (
            golden_result.get_target(
                "next_quarter_revenue"
            ).reliability
            == "experimental"
        )
        assert (
            golden_result.get_target(
                "next_quarter_parent_net_profit"
            ).reliability
            == "experimental"
        )
        assert (
            golden_result.get_target(
                "next_quarter_operating_cash_flow"
            ).reliability
            == "reliable_research"
        )
        assert (
            golden_result.get_target(
                "next_quarter_gross_margin"
            ).reliability
            == "reliable_research"
        )

    def test_predictions_are_strictly_next_natural_quarter(
        self, golden_result
    ):
        for item in golden_result.target_evidence:
            assert len(item.predictions) == 100
            for prediction in item.predictions:
                feature = pd.Period(
                    prediction.feature_report_period, freq="Q"
                )
                target = pd.Period(
                    prediction.target_report_period, freq="Q"
                )
                assert target == feature + 1
                assert (
                    pd.Timestamp(prediction.feature_visible_at)
                    < pd.Timestamp(prediction.label_available_at)
                )
                assert prediction.target == item.target
                assert prediction.model == P2_F_MODEL
                assert prediction.as_of == pd.Timestamp(
                    AS_OF
                ).isoformat()

    def test_deterministic_serialization_lookup_and_hashes(
        self, golden_result
    ):
        assert golden_result.to_dict() == golden_result.to_dict()
        assert (
            golden_result.get_target(P2_F_TARGETS[0]).target
            == P2_F_TARGETS[0]
        )
        with pytest.raises(LookupError):
            golden_result.get_target("stock_price")
        audit = golden_result.evidence_audit
        fingerprints = (
            audit.input_fingerprint,
            audit.selected_input_fingerprint,
            audit.configuration_fingerprint,
            audit.output_fingerprint,
            audit.content_hash,
        )
        assert all(len(value) == 64 for value in fingerprints)
        for item in golden_result.target_evidence:
            assert len(item.model_fingerprint) == 64
            assert len(item.split_fingerprint) == 64
            assert len(item.content_hash) == 64
            assert all(
                len(prediction.content_hash) == 64
                for prediction in item.predictions
            )

    def test_input_row_order_does_not_change_result(
        self, golden_inputs, golden_result
    ):
        batch, configuration = golden_inputs
        reversed_batch = make_batch(
            frame=batch.get_frame().iloc[::-1].reset_index(drop=True)
        )
        reversed_result = evaluate_financial_p2_f_evidence(
            reversed_batch, configuration=configuration
        )
        assert reversed_result.to_dict() == golden_result.to_dict()

    def test_payload_has_no_price_advice_or_m_replacement(
        self, golden_result
    ):
        payload = golden_result.to_dict()
        serialized = repr(payload).lower()
        assert "stock_price_prediction" not in serialized
        assert "buy_signal" not in serialized
        assert "sell_signal" not in serialized
        assert "admission_decision" not in serialized
        assert payload["evidence_audit"]["m_replacement_allowed"] is False
        for item in golden_result.target_evidence:
            assert item.evidence_priority == "supporting"
            assert item.test_selection_policy == "one_shot_no_test_tuning"


class TestPITAndOneShotIsolation:
    def test_rows_after_as_of_are_excluded_without_output_change(
        self, golden_result
    ):
        batch = make_batch(
            frame=make_forecast_frame(add_future_version=True)
        )
        changed = evaluate_financial_p2_f_evidence(
            batch, configuration=make_configuration()
        )
        assert changed.target_evidence == golden_result.target_evidence
        assert changed.evidence_audit.excluded_after_as_of_count == 1
        assert changed.evidence_audit.raw_row_count == (
            SECURITY_COUNT * QUARTER_COUNT + 1
        )

    def test_revision_after_feature_origin_is_not_a_feature(
        self, golden_result
    ):
        frame = make_forecast_frame()
        target_symbol = frame.iloc[0]["symbol"]
        feature_period = pd.Period(
            golden_result.get_target(P2_F_TARGETS[0])
            .predictions[0]
            .feature_report_period,
            freq="Q",
        )
        mask = (
            (frame["symbol"] == target_symbol)
            & (
                pd.to_datetime(frame["report_period"])
                .dt.to_period("Q")
                == feature_period
            )
        )
        original = frame.loc[mask].iloc[0].to_dict()
        revision = dict(original)
        revision["version_at"] = (
            pd.Timestamp(original["version_at"])
            + pd.Timedelta(days=90)
        ).date().isoformat()
        revision["revenue"] = float(revision["revenue"]) * 50.0
        changed = evaluate_financial_p2_f_evidence(
            make_batch(frame=pd.concat(
                [frame, pd.DataFrame([revision])],
                ignore_index=True,
            )),
            configuration=make_configuration(),
        )
        prediction = next(
            item
            for item in changed.get_target(
                "next_quarter_revenue"
            ).predictions
            if item.symbol == target_symbol
            and item.feature_report_period == str(feature_period)
        )
        assert prediction.feature_visible_at == pd.Timestamp(
            original["version_at"]
        ).isoformat()

    def test_latest_test_labels_do_not_change_fitted_model(self):
        original_frame = make_forecast_frame()
        original = evaluate_financial_p2_f_evidence(
            make_batch(frame=original_frame),
            configuration=make_configuration(),
        )
        latest_period = pd.to_datetime(
            original_frame["report_period"]
        ).max()
        changed_frame = original_frame.copy(deep=True)
        mask = (
            pd.to_datetime(changed_frame["report_period"])
            == latest_period
        )
        changed_frame.loc[mask, "revenue"] *= 1.8
        changed_frame.loc[mask, "parent_net_profit"] *= -1.5
        changed_frame.loc[mask, "operating_cash_flow"] *= 2.2
        changed_frame.loc[mask, "operating_cost"] *= 1.4
        changed = evaluate_financial_p2_f_evidence(
            make_batch(frame=changed_frame),
            configuration=make_configuration(),
        )
        for target in P2_F_TARGETS:
            before = original.get_target(target)
            after = changed.get_target(target)
            assert before.model_fingerprint == after.model_fingerprint
            assert before.split_fingerprint == after.split_fingerprint
            assert before.test_periods == after.test_periods

    def test_evaluator_does_not_mutate_inputs(self, golden_inputs):
        batch, configuration = golden_inputs
        frame_before = batch.get_frame()
        config_before = copy.deepcopy(configuration.to_dict())
        evaluate_financial_p2_f_evidence(
            batch, configuration=configuration
        )
        pd.testing.assert_frame_equal(batch.get_frame(), frame_before)
        assert configuration.to_dict() == config_before


class TestIntervalsAndFailureStates:
    def test_fewer_than_twenty_calibration_residuals_has_no_interval(
        self,
    ):
        result = evaluate_financial_p2_f_evidence(
            make_batch(
                frame=make_forecast_frame(security_count=3)
            ),
            configuration=make_configuration(
                minimum_training_rows=10
            ),
        )
        assert result.evidence_audit.gate_status == "ready"
        assert {
            item.code for item in result.evidence_audit.warnings
        } == {"INTERVAL_NOT_RUN_INSUFFICIENT_CALIBRATION"}
        for item in result.target_evidence:
            assert item.status == "partial"
            assert item.calibration_residual_count == 15
            assert (
                item.interval_status
                == "not_run_insufficient_calibration_residuals"
            )
            assert item.interval_half_width is None
            assert item.interval_coverage is None
            assert all(
                prediction.interval_low_80 is None
                and prediction.interval_high_80 is None
                for prediction in item.predictions
            )

    @pytest.mark.parametrize(
        ("mutation", "expected_code"),
        [
            (
                lambda frame: frame.drop(columns=["announced_at"]),
                "MISSING_COLUMN",
            ),
            (
                lambda frame: frame.assign(
                    report_period=lambda value: value[
                        "report_period"
                    ].mask(value.index == 0, "not-a-date")
                ),
                "INVALID_DATE",
            ),
            (
                lambda frame: frame.assign(
                    revenue=lambda value: value["revenue"].mask(
                        value.index == 0, float("nan")
                    )
                ),
                "INVALID_NUMERIC",
            ),
            (
                lambda frame: frame.assign(
                    report_period=lambda value: value[
                        "report_period"
                    ].mask(value.index == 0, "2018-03-30")
                ),
                "INVALID_DATE",
            ),
            (
                lambda frame: frame.assign(
                    total_assets=lambda value: value[
                        "total_assets"
                    ].mask(value.index == 0, 0.0)
                ),
                "NON_POSITIVE_SCALE",
            ),
        ],
    )
    def test_schema_and_value_failures_block(
        self, mutation, expected_code
    ):
        result = evaluate_financial_p2_f_evidence(
            make_batch(frame=mutation(make_forecast_frame())),
            configuration=make_configuration(),
        )
        assert result.target_evidence == ()
        assert expected_code in _codes(result)

    def test_version_before_announcement_blocks(self):
        frame = make_forecast_frame()
        frame.loc[0, "version_at"] = (
            pd.Timestamp(frame.loc[0, "announced_at"])
            - pd.Timedelta(days=1)
        ).date().isoformat()
        result = evaluate_financial_p2_f_evidence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert "VERSION_BEFORE_ANNOUNCEMENT" in _codes(result)

    def test_duplicate_version_key_blocks(self):
        frame = make_forecast_frame()
        frame = pd.concat(
            [frame, frame.iloc[[0]].copy()], ignore_index=True
        )
        result = evaluate_financial_p2_f_evidence(
            make_batch(frame=frame),
            configuration=make_configuration(),
        )
        assert "DUPLICATE_VERSION_KEY" in _codes(result)

    def test_non_synthetic_input_blocks(self):
        result = evaluate_financial_p2_f_evidence(
            make_batch(synthetic_test_only=False),
            configuration=make_configuration(),
        )
        assert result.target_evidence == ()
        assert _codes(result) == {"NON_SYNTHETIC_INPUT"}

    def test_too_few_quarters_blocks(self):
        result = evaluate_financial_p2_f_evidence(
            make_batch(
                frame=make_forecast_frame(quarter_count=9)
            ),
            configuration=make_configuration(
                minimum_training_rows=1,
                minimum_training_periods=2,
            ),
        )
        assert result.target_evidence == ()
        assert "INSUFFICIENT_PERIODS" in _codes(result)

    def test_too_few_training_rows_blocks(self):
        result = evaluate_financial_p2_f_evidence(
            make_batch(
                frame=make_forecast_frame(security_count=3)
            ),
            configuration=make_configuration(
                minimum_training_rows=100
            ),
        )
        assert result.target_evidence == ()
        assert "INSUFFICIENT_TRAINING" in _codes(result)

    def test_invalid_top_level_inputs_fail_closed(self):
        valid_batch = make_batch()
        valid_config = make_configuration()
        invalid_batch = evaluate_financial_p2_f_evidence(
            None, configuration=valid_config
        )
        assert _codes(invalid_batch) == {"INVALID_FORECAST_BATCH"}
        invalid_config = evaluate_financial_p2_f_evidence(
            valid_batch, configuration=None
        )
        assert _codes(invalid_config) == {"INVALID_CONFIGURATION"}

    def test_constructors_reject_invalid_contracts(self):
        with pytest.raises(TypeError):
            FinancialP2FForecastBatch(
                dataset_id="dataset",
                version="v1",
                source="synthetic",
                _frame=[],
                provenance={"synthetic_test_only": True},
            )
        with pytest.raises(ValueError):
            FinancialP2FEvidenceConfig(
                as_of=AS_OF,
                minimum_training_rows=0,
            )
        with pytest.raises(ValueError):
            FinancialP2FEvidenceConfig(
                as_of=AS_OF,
                minimum_training_periods=1,
            )
