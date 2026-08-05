"""FIN-P2-M-ENH acceptance tests."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from backend.amr.evaluation_input_contract import (
    EvaluationInputContractError,
    ForwardReturnBatch,
    ValueScope,
)
from backend.amr.financial_mvp_batch import SUPPORTED_FACTOR_IDS
from backend.amr.financial_mvp_m_evaluation import (
    FinancialMVPMEvaluationConfig,
    evaluate_financial_mvp_m,
)
from backend.amr.financial_p2_m_enhancement import (
    P2_M_AUDIT_SCHEMA_VERSION,
    P2_M_EVIDENCE_PRIORITY,
    P2_M_FACTOR_SCHEMA_VERSION,
    P2_M_HASH_CONTRACT_VERSION,
    P2_M_HORIZON_SCHEMA_VERSION,
    P2_M_HORIZONS,
    P2_M_MIN_UNIVERSE,
    P2_M_POLICY_VERSION,
    P2_M_PRIMARY_HORIZON,
    P2_M_ROLLING_SCHEMA_VERSION,
    P2_M_ROLLING_WINDOW,
    P2_M_SCHEMA_VERSION,
    FinancialP2MEnhancementConfig,
    evaluate_financial_p2_m_enhancement,
)
from tests.fixtures.synthetic_financial_p2_m_enhancement_cases import (
    EVALUATION_DATES,
    HORIZONS,
    RETURN_SET_ID,
    SECURITY_COUNT,
    codes,
    make_forward_returns,
    make_golden_case,
)


@pytest.fixture(scope="module")
def golden_inputs():
    return make_golden_case()


@pytest.fixture(scope="module")
def configuration():
    return FinancialP2MEnhancementConfig(
        mvp_configuration=FinancialMVPMEvaluationConfig(
            evaluation_dates=EVALUATION_DATES,
            evaluation_calendar_reference=(
                "synthetic-calendar://expanded-month-end"
            ),
            evaluation_calendar_version="synthetic-expanded-v1",
            hac_max_lag=1,
        ),
        universe_reference="synthetic-universe://60-stable",
        universe_version="synthetic-60-v1",
    )


@pytest.fixture(scope="module")
def golden_result(golden_inputs, configuration):
    return evaluate_financial_p2_m_enhancement(
        *golden_inputs, configuration=configuration
    )


def _codes(result):
    return {item.code for item in result.enhancement_audit.errors}


def _returns_with(
    source: ForwardReturnBatch,
    frame: pd.DataFrame,
    **overrides,
) -> ForwardReturnBatch:
    fields = {
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
    fields.update(overrides)
    return ForwardReturnBatch(**fields)


class TestFrozenContract:
    def test_versions_and_research_scope_are_frozen(self):
        assert P2_M_SCHEMA_VERSION == "FinancialP2MEnhancement-v1.0"
        assert (
            P2_M_AUDIT_SCHEMA_VERSION
            == "FinancialP2MEnhancementAudit-v1.0"
        )
        assert (
            P2_M_HORIZON_SCHEMA_VERSION
            == "FinancialP2MHorizonEvidence-v1.0"
        )
        assert (
            P2_M_ROLLING_SCHEMA_VERSION
            == "FinancialP2MRollingEvidence-v1.0"
        )
        assert (
            P2_M_FACTOR_SCHEMA_VERSION
            == "FinancialP2MFactorEvidence-v1.0"
        )
        assert P2_M_HASH_CONTRACT_VERSION == (
            "FIN-P2-M-ENH-HASH-v1.0"
        )
        assert P2_M_POLICY_VERSION == "FIN-P2-M-ENH-POLICY-v1.0"
        assert P2_M_HORIZONS == (5, 20, 60)
        assert P2_M_PRIMARY_HORIZON == 20
        assert P2_M_MIN_UNIVERSE == 60
        assert P2_M_ROLLING_WINDOW == 6
        assert P2_M_EVIDENCE_PRIORITY == "primary"

    def test_configuration_is_immutable(self, configuration):
        with pytest.raises(FrozenInstanceError):
            configuration.primary_horizon = 5
        assert configuration.horizons == HORIZONS
        assert configuration.mvp_configuration.return_horizon == 20

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("horizons", (20,)),
            ("primary_horizon", 5),
            ("minimum_universe_size", 30),
            ("rolling_window_months", 3),
            ("validation_track", "F"),
            ("evidence_priority", "supporting"),
            ("weighting", "market_cap"),
            ("direction_source", "selected"),
            ("neutralization_status", "completed"),
            ("fama_macbeth_status", "completed"),
            ("oos_status", "completed"),
            ("multiple_testing_status", "completed"),
            ("synthetic_test_only", False),
        ],
    )
    def test_configuration_rejects_scope_drift(
        self, configuration, field_name, value
    ):
        values = {
            "mvp_configuration": configuration.mvp_configuration,
            "universe_reference": "universe://frozen",
            "universe_version": "v1",
            field_name: value,
        }
        with pytest.raises(ValueError):
            FinancialP2MEnhancementConfig(**values)


class TestExpandedMultiHorizonEvidence:
    def test_ready_three_factor_three_horizon_package(
        self, golden_result
    ):
        audit = golden_result.enhancement_audit
        assert audit.gate_status == "ready"
        assert audit.errors == ()
        assert audit.universe_count == SECURITY_COUNT
        assert audit.horizons == HORIZONS
        assert tuple(
            item.factor_id for item in golden_result.factor_evidence
        ) == SUPPORTED_FACTOR_IDS
        for factor in golden_result.factor_evidence:
            assert tuple(
                item.horizon for item in factor.horizon_evidence
            ) == HORIZONS
            assert factor.validation_track == "M"
            assert factor.evidence_priority == "primary"

    def test_exact_registered_horizon_statistics(self, golden_result):
        expected = {
            5: (5.0 / 9.0, 0.026666666666666665),
            20: (1.0 / 3.0, 0.016),
            60: (1.0 / 9.0, 0.005333333333333333),
        }
        for factor in golden_result.factor_evidence:
            for horizon, (rank_ic, long_short) in expected.items():
                result = factor.get_horizon(horizon).common_result
                assert result.return_set_id == RETURN_SET_ID
                assert result.horizon == str(horizon)
                assert result.rank_ic_mean == pytest.approx(rank_ic)
                assert result.long_short_mean == pytest.approx(
                    long_short
                )
                assert result.evaluated_dates == len(EVALUATION_DATES)
                assert result.total_observations == (
                    len(EVALUATION_DATES) * SECURITY_COUNT
                )

    def test_20d_result_exactly_anchors_accepted_mvp(
        self, golden_inputs, configuration, golden_result
    ):
        primary = evaluate_financial_mvp_m(
            *golden_inputs,
            configuration=configuration.mvp_configuration,
        )
        for factor_id in SUPPORTED_FACTOR_IDS:
            enhanced = golden_result.get_factor(
                factor_id
            ).get_horizon(20)
            assert enhanced.is_primary is True
            assert enhanced.common_result.to_dict() == (
                primary.get_result(factor_id).to_dict()
            )

    def test_rolling_windows_and_coverage_are_complete(
        self, golden_result
    ):
        expected_windows = (
            len(EVALUATION_DATES) - P2_M_ROLLING_WINDOW + 1
        )
        for factor in golden_result.factor_evidence:
            assert len(factor.rolling_evidence) == (
                expected_windows * len(HORIZONS)
            )
            for item in factor.rolling_evidence:
                assert item.configured_periods == 6
                assert item.effective_periods == 6
                assert item.paired_observations == 360
                assert item.paired_coverage_rate == 1.0
                assert item.status == "completed"
            assert factor.horizon_direction_consistency == "consistent"
            assert (
                factor.primary_rolling_direction_consistency
                == "consistent"
            )

    def test_expanded_universe_and_factor_samples_are_explicit(
        self, golden_result
    ):
        for factor in golden_result.factor_evidence:
            fingerprints = set()
            for evidence in factor.horizon_evidence:
                assert evidence.universe_count == 60
                assert evidence.factor_sample_count == 1080
                assert evidence.label_available_count == 1080
                assert evidence.paired_coverage_rate == 1.0
                fingerprints.add(evidence.factor_sample_fingerprint)
            assert len(fingerprints) == 1

    def test_serialization_lookup_and_hashes_are_deterministic(
        self, golden_result
    ):
        assert golden_result.get_factor("ROE").factor_id == "ROE"
        with pytest.raises(LookupError):
            golden_result.get_factor("NOT_APPROVED")
        with pytest.raises(TypeError):
            golden_result.get_factor("ROE").get_horizon("20")
        assert golden_result.to_dict() == golden_result.to_dict()
        audit = golden_result.enhancement_audit
        hashes = (
            audit.configuration_fingerprint,
            audit.primary_m_evaluation_fingerprint,
            audit.universe_fingerprint,
            audit.factor_input_fingerprint,
            audit.label_input_fingerprint,
            audit.output_fingerprint,
            audit.content_hash,
        )
        assert all(len(value) == 64 for value in hashes)

    def test_input_order_does_not_change_output(
        self, golden_inputs, configuration, golden_result
    ):
        mvp, prep, returns = golden_inputs
        reversed_returns = _returns_with(
            returns,
            returns.get_frame().iloc[::-1].reset_index(drop=True),
        )
        result = evaluate_financial_p2_m_enhancement(
            mvp,
            prep,
            reversed_returns,
            configuration=configuration,
        )
        assert result.to_dict() == golden_result.to_dict()


class TestIsolationAndFailureStates:
    def test_label_inversion_does_not_change_factor_or_universe(
        self, golden_inputs, configuration, golden_result
    ):
        mvp, prep, _ = golden_inputs
        changed = evaluate_financial_p2_m_enhancement(
            mvp,
            prep,
            make_forward_returns(reverse_all=True),
            configuration=configuration,
        )
        assert (
            changed.enhancement_audit.universe_fingerprint
            == golden_result.enhancement_audit.universe_fingerprint
        )
        assert (
            changed.enhancement_audit.factor_input_fingerprint
            == golden_result.enhancement_audit.factor_input_fingerprint
        )
        assert (
            changed.enhancement_audit.label_input_fingerprint
            != golden_result.enhancement_audit.label_input_fingerprint
        )
        for factor_id in SUPPORTED_FACTOR_IDS:
            before = golden_result.get_factor(
                factor_id
            ).get_horizon(20)
            after = changed.get_factor(factor_id).get_horizon(20)
            assert (
                before.factor_sample_fingerprint
                == after.factor_sample_fingerprint
            )
            assert after.common_result.rank_ic_mean == pytest.approx(
                -before.common_result.rank_ic_mean
            )

    def test_missing_one_label_is_visible_in_coverage(
        self, golden_inputs, configuration
    ):
        mvp, prep, _ = golden_inputs
        missing_key = (EVALUATION_DATES[0], codes()[0], 5)
        result = evaluate_financial_p2_m_enhancement(
            mvp,
            prep,
            make_forward_returns(missing={missing_key}),
            configuration=configuration,
        )
        evidence = result.get_factor("ROE").get_horizon(5)
        assert result.enhancement_audit.gate_status == "ready"
        assert evidence.factor_sample_count == 1080
        assert evidence.label_available_count == 1079
        assert evidence.paired_coverage_rate == pytest.approx(
            1079 / 1080
        )

    def test_missing_registered_horizon_blocks(
        self, golden_inputs, configuration
    ):
        mvp, prep, _ = golden_inputs
        result = evaluate_financial_p2_m_enhancement(
            mvp,
            prep,
            make_forward_returns(horizons=(20, 60)),
            configuration=configuration,
        )
        assert result.factor_evidence == ()
        assert "RETURN_HORIZON_MISSING" in _codes(result)

    def test_duplicate_return_key_blocks(
        self, golden_inputs, configuration
    ):
        key = (EVALUATION_DATES[0], codes()[0], 5)
        with pytest.raises(
            EvaluationInputContractError, match="Duplicate key"
        ) as exc:
            make_forward_returns(duplicate_key=key)
        assert exc.value.code == "DUPLICATE_KEY"

    def test_thirty_name_mvp_is_too_small_for_phase2(
        self, configuration
    ):
        result = evaluate_financial_p2_m_enhancement(
            *make_golden_case(security_count=30),
            configuration=configuration,
        )
        assert result.factor_evidence == ()
        assert "EXPANDED_UNIVERSE_TOO_SMALL" in _codes(result)

    def test_wrong_scope_and_non_synthetic_returns_block(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        market = _returns_with(
            returns,
            returns.get_frame().rename(
                columns={"code": "region_or_market"}
            ),
            value_scope=ValueScope.MARKET_LEVEL,
        )
        assert "INVALID_FORWARD_RETURN_BATCH" in _codes(
            evaluate_financial_p2_m_enhancement(
                mvp, prep, market, configuration=configuration
            )
        )
        non_synthetic = _returns_with(
            returns,
            returns.get_frame(),
            provenance={"synthetic_test_only": False},
        )
        assert "NON_SYNTHETIC_RETURN_INPUT" in _codes(
            evaluate_financial_p2_m_enhancement(
                mvp,
                prep,
                non_synthetic,
                configuration=configuration,
            )
        )

    def test_invalid_top_level_inputs_fail_closed(
        self, golden_inputs, configuration
    ):
        mvp, prep, returns = golden_inputs
        cases = (
            (None, prep, returns, "INVALID_MVP_BATCH_RESULT"),
            (mvp, None, returns, "INVALID_PREPROCESSING_RESULT"),
            (mvp, prep, None, "INVALID_FORWARD_RETURN_BATCH"),
        )
        for one, two, three, code in cases:
            result = evaluate_financial_p2_m_enhancement(
                one, two, three, configuration=configuration
            )
            assert result.factor_evidence == ()
            assert code in _codes(result)
        invalid_config = evaluate_financial_p2_m_enhancement(
            mvp, prep, returns, configuration=None
        )
        assert _codes(invalid_config) == {"INVALID_CONFIGURATION"}

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
        evaluate_financial_p2_m_enhancement(
            mvp, prep, returns, configuration=configuration
        )
        assert mvp.to_dict(include_rows=True) == before[0]
        assert [
            item.to_dict() for item in prep.prepared_inputs
        ] == before[1]
        pd.testing.assert_frame_equal(returns.get_frame(), before[2])

    def test_unimplemented_research_fields_stay_not_run(
        self, golden_result
    ):
        forbidden = {
            "admission",
            "production_ready",
            "selected_horizon",
            "selected_direction",
            "f_track",
            "r_track",
        }
        payload = golden_result.to_dict()
        assert forbidden.isdisjoint(payload)
        for factor in golden_result.factor_evidence:
            assert factor.best_horizon_selection_status == "not_run"
            assert factor.neutralization_status == "not_run"
            assert factor.fama_macbeth_status == "not_run"
            assert factor.oos_status == "not_run"
            assert factor.multiple_testing_status == "not_run"
