"""FIN-MVP-M-EVAL acceptance tests."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, replace

import pandas as pd
import pytest

from backend.amr.evaluation_core import (
    EvaluationStatus,
    SecurityLevelEvaluationResult,
)
from backend.amr.evaluation_input_contract import (
    ForwardReturnBatch,
    ValueScope,
)
from backend.amr.financial_mvp_batch import (
    SUPPORTED_FACTOR_IDS,
    recompute_observation_content_hash,
)
from backend.amr.financial_mvp_m_evaluation import (
    M_EVAL_AUDIT_SCHEMA_VERSION,
    M_EVAL_FACTOR_AUDIT_SCHEMA_VERSION,
    M_EVAL_FREQUENCY,
    M_EVAL_HASH_CONTRACT_VERSION,
    M_EVAL_HORIZON,
    M_EVAL_MIN_CROSS_SECTION,
    M_EVAL_MIN_PERIODS,
    M_EVAL_POLICY_VERSION,
    M_EVAL_QUANTILES,
    M_EVAL_SCHEMA_VERSION,
    M_EVAL_VALUE_VARIANT,
    FinancialMVPMEvaluationConfig,
    MEvaluationErrorCode,
    evaluate_financial_mvp_m,
)
from tests.fixtures.synthetic_financial_mvp_m_evaluation_cases import (
    EVALUATION_DATES,
    RETURN_SET_ID,
    SECURITY_COUNT,
    make_forward_returns,
    make_golden_case,
)


@pytest.fixture(scope="module")
def golden_inputs():
    return make_golden_case()


@pytest.fixture(scope="module")
def configuration():
    return FinancialMVPMEvaluationConfig(
        evaluation_dates=EVALUATION_DATES,
        evaluation_calendar_reference=(
            "synthetic-calendar://month-end-2024"
        ),
        evaluation_calendar_version="synthetic-month-end-v1",
        hac_max_lag=1,
    )


@pytest.fixture(scope="module")
def golden_result(golden_inputs, configuration):
    return evaluate_financial_mvp_m(
        *golden_inputs,
        configuration=configuration,
    )


def _codes(result):
    return {item.code for item in result.evaluation_audit.errors}


def _returns_with_frame(source, frame, **overrides):
    values = {
        "return_set_id": source.return_set_id,
        "value_scope": source.value_scope,
        "version": source.version,
        "source": source.source,
        "return_definition": source.return_definition,
        "_frame": frame,
        "frequency": source.frequency,
        "universe": source.universe,
        "schema_version": source.schema_version,
        "provenance": source.provenance,
    }
    values.update(overrides)
    return ForwardReturnBatch(**values)


class TestFrozenContract:
    def test_versions_and_scope_constants_are_frozen(self):
        assert M_EVAL_SCHEMA_VERSION == "FinancialMVPMEvaluation-v1.0"
        assert (
            M_EVAL_AUDIT_SCHEMA_VERSION
            == "FinancialMVPMEvaluationAudit-v1.0"
        )
        assert (
            M_EVAL_FACTOR_AUDIT_SCHEMA_VERSION
            == "FinancialMVPMFactorAudit-v1.0"
        )
        assert M_EVAL_HASH_CONTRACT_VERSION == (
            "FIN-MVP-M-EVAL-HASH-v1.0"
        )
        assert M_EVAL_POLICY_VERSION == "FIN-MVP-M-EVAL-POLICY-v1.0"
        assert (
            M_EVAL_FREQUENCY,
            M_EVAL_HORIZON,
            M_EVAL_MIN_CROSS_SECTION,
            M_EVAL_MIN_PERIODS,
            M_EVAL_QUANTILES,
            M_EVAL_VALUE_VARIANT,
        ) == ("month_end", 20, 30, 12, 5, "evaluation_factor_value")

    def test_configuration_is_immutable_and_sorts_dates(self):
        config = FinancialMVPMEvaluationConfig(
            evaluation_dates=tuple(reversed(EVALUATION_DATES)),
            evaluation_calendar_reference="calendar://synthetic",
            evaluation_calendar_version="v1",
            hac_max_lag=0,
        )
        assert config.evaluation_dates == EVALUATION_DATES
        with pytest.raises(FrozenInstanceError):
            config.hac_max_lag = 2
        generator_config = FinancialMVPMEvaluationConfig(
            evaluation_dates=(
                value for value in reversed(EVALUATION_DATES)
            ),
            evaluation_calendar_reference="calendar://synthetic",
            evaluation_calendar_version="v1",
            hac_max_lag=0,
        )
        assert generator_config.evaluation_dates == EVALUATION_DATES

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("return_horizon", 10),
            ("evaluation_frequency", "daily"),
            ("minimum_cross_section_size", 29),
            ("minimum_evaluation_periods", 10),
            ("quantiles", 10),
            ("primary_value_variant", "raw_pit_factor_value"),
            ("schema_version", "v2"),
            ("policy_version", "v2"),
            ("synthetic_test_only", False),
        ],
    )
    def test_frozen_configuration_fields_reject_drift(
        self, field_name, value
    ):
        values = {
            "evaluation_dates": EVALUATION_DATES,
            "evaluation_calendar_reference": "calendar://synthetic",
            "evaluation_calendar_version": "v1",
            "hac_max_lag": 1,
            field_name: value,
        }
        with pytest.raises(ValueError):
            FinancialMVPMEvaluationConfig(**values)

    @pytest.mark.parametrize("value", [True, -1, 12, 1.5, "1"])
    def test_hac_lag_must_be_explicit_and_bounded(self, value):
        with pytest.raises(ValueError):
            FinancialMVPMEvaluationConfig(
                evaluation_dates=EVALUATION_DATES,
                evaluation_calendar_reference="calendar://synthetic",
                evaluation_calendar_version="v1",
                hac_max_lag=value,
            )

    def test_config_requires_twelve_unique_months(self):
        with pytest.raises(ValueError):
            FinancialMVPMEvaluationConfig(
                evaluation_dates=EVALUATION_DATES[:11],
                evaluation_calendar_reference="calendar://synthetic",
                evaluation_calendar_version="v1",
                hac_max_lag=1,
            )
        duplicate_month = EVALUATION_DATES[:-1] + ("2024-11-30",)
        with pytest.raises(ValueError):
            FinancialMVPMEvaluationConfig(
                evaluation_dates=duplicate_month,
                evaluation_calendar_reference="calendar://synthetic",
                evaluation_calendar_version="v1",
                hac_max_lag=1,
            )


class TestGoldenStatistics:
    def test_three_factors_complete_with_exact_rank_statistics(
        self, golden_result
    ):
        assert golden_result.evaluation_audit.gate_status == "ready"
        assert not golden_result.evaluation_audit.errors
        assert tuple(
            item.factor_id for item in golden_result.common_results
        ) == SUPPORTED_FACTOR_IDS
        for result in golden_result.common_results:
            assert result.overall_status is EvaluationStatus.COMPLETED
            assert result.rank_ic_mean == pytest.approx(1.0 / 3.0)
            assert result.rank_ic_positive_ratio == pytest.approx(2.0 / 3.0)
            assert result.rank_ic_t_stat == pytest.approx(
                0.9370425713316363
            )
            assert result.evaluated_dates == 12
            assert result.excluded_dates == 0
            assert result.total_observations == 360

    def test_common_public_identity_and_group_statistics(
        self, golden_result
    ):
        for result in golden_result.common_results:
            assert isinstance(result, SecurityLevelEvaluationResult)
            assert result.return_set_id == RETURN_SET_ID
            assert result.horizon == "20"
            assert result.factor_type == "financial"
            assert result.value_scope == "security_level"
            assert result.quantiles == 5
            assert result.quantile_returns.keys() == {
                "1",
                "2",
                "3",
                "4",
                "5",
            }
            assert result.long_short_mean == pytest.approx(0.008)
            assert result.monotonicity_spearman == pytest.approx(1.0)
            assert result.rank_ic_stability is None
            assert result.pearson_ic_stability is None

    def test_daily_outputs_follow_configured_month_ends(
        self, golden_result
    ):
        for result in golden_result.common_results:
            assert tuple(item.date for item in result.daily_results) == (
                EVALUATION_DATES
            )
            assert tuple(
                item.date for item in result.daily_group_returns
            ) == EVALUATION_DATES
            assert all(
                item.sample_size == SECURITY_COUNT
                for item in result.daily_results
            )

    def test_public_result_field_set_is_unchanged(self, golden_result):
        expected = {
            "factor_id",
            "return_set_id",
            "horizon",
            "factor_type",
            "value_scope",
            "overall_status",
            "rank_ic_mean",
            "rank_ic_std",
            "rank_ic_ir",
            "rank_ic_t_stat",
            "rank_ic_positive_ratio",
            "pearson_ic_mean",
            "pearson_ic_std",
            "pearson_ic_ir",
            "pearson_ic_t_stat",
            "pearson_ic_positive_ratio",
            "rank_ic_stability",
            "pearson_ic_stability",
            "quantiles",
            "quantile_returns",
            "long_short_mean",
            "monotonicity_spearman",
            "daily_group_returns",
            "group_return_issue_codes",
            "total_dates",
            "evaluated_dates",
            "excluded_dates",
            "total_observations",
            "daily_results",
            "issue_codes",
            "gate_status",
            "gate_issue_codes",
        }
        assert set(golden_result.common_results[0].to_dict()) == expected

    def test_audits_bind_samples_labels_outputs_and_configuration(
        self, golden_result
    ):
        audit = golden_result.evaluation_audit
        hashes = (
            audit.configuration_fingerprint,
            audit.mvp_batch_fingerprint,
            audit.preprocessing_fingerprint,
            audit.return_input_fingerprint,
            audit.factor_sample_fingerprint,
            audit.output_fingerprint,
            audit.content_hash,
        )
        assert all(len(value) == 64 for value in hashes)
        assert len(golden_result.factor_audits) == 3
        for factor_audit in golden_result.factor_audits:
            assert factor_audit.factor_sample_count == 360
            assert factor_audit.label_available_count == 360
            assert factor_audit.valid_pair_count == 360
            assert factor_audit.evaluated_date_count == 12
            assert factor_audit.excluded_date_count == 0
            assert len(factor_audit.content_hash) == 64

    def test_lookup_and_serialization_are_deterministic(
        self, golden_result
    ):
        assert golden_result.get_result("ROE").factor_id == "ROE"
        assert golden_result.get_factor_audit("BP").factor_id == "BP"
        with pytest.raises(LookupError):
            golden_result.get_result("NOT_APPROVED")
        assert golden_result.to_dict() == golden_result.to_dict()


class TestLabelIsolation:
    def test_label_change_does_not_change_factor_sample_fingerprint(
        self, golden_inputs, configuration, golden_result
    ):
        mvp, prep, _ = golden_inputs
        changed = evaluate_financial_mvp_m(
            mvp,
            prep,
            make_forward_returns(reverse_all=True),
            configuration=configuration,
        )
        for factor_id in SUPPORTED_FACTOR_IDS:
            before = golden_result.get_factor_audit(factor_id)
            after = changed.get_factor_audit(factor_id)
            assert (
                before.factor_sample_fingerprint
                == after.factor_sample_fingerprint
            )
            assert (
                before.label_alignment_fingerprint
                != after.label_alignment_fingerprint
            )
            assert (
                golden_result.get_result(factor_id).rank_ic_mean
                == pytest.approx(1.0 / 3.0)
            )
            assert changed.get_result(factor_id).rank_ic_mean == pytest.approx(
                -1.0 / 3.0
            )

    def test_missing_label_is_left_joined_without_factor_sample_loss(
        self, golden_inputs, configuration, golden_result
    ):
        mvp, prep, _ = golden_inputs
        missing_key = {(EVALUATION_DATES[0], "SYNME0001")}
        result = evaluate_financial_mvp_m(
            mvp,
            prep,
            make_forward_returns(missing=missing_key),
            configuration=configuration,
        )
        assert result.evaluation_audit.gate_status == "ready"
        for factor_id in SUPPORTED_FACTOR_IDS:
            before = golden_result.get_factor_audit(factor_id)
            after = result.get_factor_audit(factor_id)
            assert after.factor_sample_count == 360
            assert after.label_available_count == 359
            assert (
                before.factor_sample_fingerprint
                == after.factor_sample_fingerprint
            )
            common = result.get_result(factor_id)
            assert common.overall_status is EvaluationStatus.NOT_RUN
            assert common.evaluated_dates == 11
            assert (
                "INSUFFICIENT_VALID_EVALUATION_PERIODS"
                in common.issue_codes
            )
            excluded_group = common.daily_group_returns[0]
            assert excluded_group.evaluated is False
            assert excluded_group.sample_size == 29
            assert (
                "INSUFFICIENT_CROSS_SECTION"
                in excluded_group.issue_codes
            )

    def test_constant_return_month_is_excluded(
        self, golden_inputs, configuration
    ):
        mvp, prep, _ = golden_inputs
        result = evaluate_financial_mvp_m(
            mvp,
            prep,
            make_forward_returns(
                constant_dates={EVALUATION_DATES[0]}
            ),
            configuration=configuration,
        )
        daily = result.get_result("ROE").daily_results[0]
        assert daily.evaluated is False
        assert "CONSTANT_RETURN_CROSS_SECTION" in daily.issue_codes

    def test_extra_return_horizon_is_ignored(
        self, golden_inputs, configuration, golden_result
    ):
        mvp, prep, returns = golden_inputs
        extra = returns.get_frame()
        extra["horizon"] = 10
        extra["forward_return"] = -99.0
        combined = pd.concat(
            [returns.get_frame(), extra], ignore_index=True
        )
        result = evaluate_financial_mvp_m(
            mvp,
            prep,
            _returns_with_frame(returns, combined),
            configuration=configuration,
        )
        assert result.get_result("ROE").rank_ic_mean == (
            golden_result.get_result("ROE").rank_ic_mean
        )


class TestFailClosedBoundaries:
    def test_invalid_input_types_block_as_one_package(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        cases = (
            (None, prep, returns, "INVALID_MVP_BATCH_RESULT"),
            (mvp, None, returns, "INVALID_PREPROCESSING_RESULT"),
            (mvp, prep, None, "INVALID_FORWARD_RETURN_BATCH"),
        )
        for one, two, three, code in cases:
            result = evaluate_financial_mvp_m(
                one, two, three, configuration=configuration
            )
            assert result.common_results == ()
            assert result.factor_audits == ()
            assert code in _codes(result)

    def test_invalid_configuration_object_blocks(self, golden_inputs):
        result = evaluate_financial_mvp_m(
            *golden_inputs,
            configuration=None,
        )
        assert _codes(result) == {"INVALID_CONFIGURATION"}

    def test_upstream_gates_and_missing_reference_block(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        blocked_mvp = replace(
            mvp,
            financial_batch_audit=replace(
                mvp.financial_batch_audit, gate_status="blocked"
            ),
        )
        assert "MVP_BATCH_GATE_BLOCKED" in _codes(
            evaluate_financial_mvp_m(
                blocked_mvp,
                prep,
                returns,
                configuration=configuration,
            )
        )
        missing_reference = replace(mvp, observation_reference=None)
        assert "OBSERVATION_REFERENCE_MISSING" in _codes(
            evaluate_financial_mvp_m(
                missing_reference,
                prep,
                returns,
                configuration=configuration,
            )
        )
        blocked_prep = replace(
            prep,
            preprocessing_audit=replace(
                prep.preprocessing_audit, gate_status="blocked"
            ),
        )
        assert "PREPROCESSING_GATE_BLOCKED" in _codes(
            evaluate_financial_mvp_m(
                mvp,
                blocked_prep,
                returns,
                configuration=configuration,
            )
        )

    def test_observation_hash_tamper_blocks(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        reference = mvp.observation_reference
        records = list(reference.records)
        records[0] = replace(records[0], content_hash="0" * 64)
        tampered = replace(
            mvp,
            observation_reference=replace(
                reference, records=tuple(records)
            ),
        )
        result = evaluate_financial_mvp_m(
            tampered, prep, returns, configuration=configuration
        )
        assert "OBSERVATION_HASH_MISMATCH" in _codes(result)
        assert result.common_results == ()
        false_mask = replace(records[1], factor_sample_mask=False)
        false_mask = replace(
            false_mask,
            content_hash=recompute_observation_content_hash(false_mask),
        )
        records[1] = false_mask
        invalid_sample = replace(
            mvp,
            observation_reference=replace(
                reference, records=tuple(records)
            ),
        )
        assert "FACTOR_BATCH_COVERAGE_INVALID" in _codes(
            evaluate_financial_mvp_m(
                invalid_sample,
                prep,
                returns,
                configuration=configuration,
            )
        )

    def test_factor_batch_coverage_is_exact(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        result = evaluate_financial_mvp_m(
            replace(mvp, batches=mvp.batches[:2]),
            prep,
            returns,
            configuration=configuration,
        )
        assert "FACTOR_BATCH_COVERAGE_INVALID" in _codes(result)

    def test_preprocessing_coverage_and_raw_values_are_bound(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        missing = replace(prep, prepared_inputs=prep.prepared_inputs[1:])
        assert "PREPROCESSING_COVERAGE_MISMATCH" in _codes(
            evaluate_financial_mvp_m(
                mvp, missing, returns, configuration=configuration
            )
        )
        changed_items = list(prep.prepared_inputs)
        changed_items[0] = replace(
            changed_items[0],
            raw_pit_factor_value=(
                changed_items[0].raw_pit_factor_value + 1.0
            ),
        )
        changed = replace(
            prep, prepared_inputs=tuple(changed_items)
        )
        assert "PREPROCESSING_RAW_VALUE_MISMATCH" in _codes(
            evaluate_financial_mvp_m(
                mvp, changed, returns, configuration=configuration
            )
        )

    def test_public_batch_raw_value_is_bound(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        batches = list(mvp.batches)
        frame = batches[0].get_frame()
        frame.loc[0, "factor_value"] += 1.0
        batches[0] = replace(batches[0], _frame=frame)
        result = evaluate_financial_mvp_m(
            replace(mvp, batches=tuple(batches)),
            prep,
            returns,
            configuration=configuration,
        )
        assert "PUBLIC_BATCH_RAW_VALUE_MISMATCH" in _codes(result)
        nonfinite_batches = list(mvp.batches)
        nonfinite_frame = nonfinite_batches[0].get_frame()
        nonfinite_frame.loc[0, "factor_value"] = float("nan")
        nonfinite_batches[0] = replace(
            nonfinite_batches[0], _frame=nonfinite_frame
        )
        nonfinite = evaluate_financial_mvp_m(
            replace(mvp, batches=tuple(nonfinite_batches)),
            prep,
            returns,
            configuration=configuration,
        )
        assert "PUBLIC_BATCH_RAW_VALUE_MISMATCH" in _codes(nonfinite)

    def test_non_synthetic_and_wrong_scope_returns_block(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        non_synthetic = _returns_with_frame(
            returns,
            returns.get_frame(),
            provenance={"synthetic_test_only": False},
        )
        assert "NON_SYNTHETIC_RETURN_INPUT" in _codes(
            evaluate_financial_mvp_m(
                mvp,
                prep,
                non_synthetic,
                configuration=configuration,
            )
        )
        market_frame = returns.get_frame().rename(
            columns={"code": "region_or_market"}
        )
        market = _returns_with_frame(
            returns,
            market_frame,
            value_scope=ValueScope.MARKET_LEVEL,
        )
        assert "INVALID_FORWARD_RETURN_BATCH" in _codes(
            evaluate_financial_mvp_m(
                mvp, prep, market, configuration=configuration
            )
        )

    def test_missing_20d_horizon_blocks(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        frame = returns.get_frame()
        frame["horizon"] = 10
        result = evaluate_financial_mvp_m(
            mvp,
            prep,
            _returns_with_frame(returns, frame),
            configuration=configuration,
        )
        assert "RETURN_HORIZON_MISSING" in _codes(result)

    def test_inputs_are_not_mutated(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        before = (
            copy.deepcopy(mvp.to_dict(include_rows=True)),
            copy.deepcopy(
                [item.to_dict() for item in prep.prepared_inputs]
            ),
            returns.get_frame(),
        )
        evaluate_financial_mvp_m(
            mvp, prep, returns, configuration=configuration
        )
        assert mvp.to_dict(include_rows=True) == before[0]
        assert [
            item.to_dict() for item in prep.prepared_inputs
        ] == before[1]
        pd.testing.assert_frame_equal(returns.get_frame(), before[2])

    def test_no_robustness_or_admission_outputs(self, golden_result):
        payload = golden_result.to_dict()
        forbidden = {
            "raw_vs_mad",
            "subperiod",
            "out_of_sample",
            "fdr",
            "direction_selection",
            "admission",
            "persistence",
        }
        assert forbidden.isdisjoint(payload)
        assert forbidden.isdisjoint(payload["common_results"][0])
