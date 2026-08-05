"""FIN-MVP-ROBUST acceptance tests."""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, replace

import pandas as pd
import pytest

from backend.amr.evaluation_input_contract import ForwardReturnBatch
from backend.amr.financial_mvp_batch import SUPPORTED_FACTOR_IDS
from backend.amr.financial_mvp_m_evaluation import (
    FinancialMVPMEvaluationResult,
    evaluate_financial_mvp_m,
)
from backend.amr.financial_mvp_robustness import (
    ROBUSTNESS_AUDIT_SCHEMA_VERSION,
    ROBUSTNESS_CELL_SCHEMA_VERSION,
    ROBUSTNESS_FACTOR_SCHEMA_VERSION,
    ROBUSTNESS_HASH_CONTRACT_VERSION,
    ROBUSTNESS_MIN_SUBPERIODS,
    ROBUSTNESS_POLICY_VERSION,
    ROBUSTNESS_SCHEMA_VERSION,
    ROBUSTNESS_SEGMENTS,
    ROBUSTNESS_SPLIT_POLICY,
    ROBUSTNESS_VARIANTS,
    FinancialMVPRobustnessConfig,
    RobustnessCellStatus,
    RobustnessConsistency,
    RobustnessDirection,
    evaluate_financial_mvp_robustness,
)
from tests.fixtures.synthetic_financial_mvp_m_evaluation_cases import (
    EVALUATION_DATES,
    make_forward_returns,
)
from tests.fixtures.synthetic_financial_mvp_robustness_cases import (
    make_constant_bp_robustness_case,
    make_outlier_robustness_case,
    make_robustness_case,
)


@pytest.fixture(scope="module")
def golden_case():
    return make_robustness_case()


@pytest.fixture(scope="module")
def golden_result(golden_case):
    return evaluate_financial_mvp_robustness(
        *golden_case[:4],
        configuration=golden_case[4],
    )


@pytest.fixture(scope="module")
def outlier_case():
    return make_outlier_robustness_case()


@pytest.fixture(scope="module")
def outlier_result(outlier_case):
    return evaluate_financial_mvp_robustness(
        *outlier_case[:4],
        configuration=outlier_case[4],
    )


def _codes(result):
    return {item.code for item in result.robustness_audit.errors}


def _with_return_frame(source, frame, **overrides):
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
    def test_versions_and_matrix_are_frozen(self):
        assert ROBUSTNESS_SCHEMA_VERSION == (
            "FinancialMVPRobustness-v1.0"
        )
        assert ROBUSTNESS_AUDIT_SCHEMA_VERSION == (
            "FinancialMVPRobustnessAudit-v1.0"
        )
        assert ROBUSTNESS_CELL_SCHEMA_VERSION == (
            "FinancialMVPRobustnessCell-v1.0"
        )
        assert ROBUSTNESS_FACTOR_SCHEMA_VERSION == (
            "FinancialMVPFactorRobustness-v1.0"
        )
        assert ROBUSTNESS_HASH_CONTRACT_VERSION == (
            "FIN-MVP-ROBUST-HASH-v1.0"
        )
        assert ROBUSTNESS_POLICY_VERSION == (
            "FIN-MVP-ROBUST-POLICY-v1.0"
        )
        assert ROBUSTNESS_SPLIT_POLICY == (
            "chronological_equal_halves"
        )
        assert ROBUSTNESS_VARIANTS == (
            "raw_pit_factor_value",
            "evaluation_factor_value",
        )
        assert ROBUSTNESS_SEGMENTS == (
            "full",
            "first_half",
            "second_half",
        )
        assert ROBUSTNESS_MIN_SUBPERIODS == 6

    def test_configuration_freezes_dates_and_halves(self, golden_case):
        config = golden_case[4]
        assert config.evaluation_dates == EVALUATION_DATES
        assert config.first_half_dates == EVALUATION_DATES[:6]
        assert config.second_half_dates == EVALUATION_DATES[6:]
        with pytest.raises(FrozenInstanceError):
            config.split_policy = "changed"

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("split_policy", "rolling"),
            ("minimum_subperiod_evaluation_periods", 5),
            ("variants", tuple(reversed(ROBUSTNESS_VARIANTS))),
            ("segments", tuple(reversed(ROBUSTNESS_SEGMENTS))),
            ("schema_version", "v2"),
            ("policy_version", "v2"),
            ("synthetic_test_only", False),
        ],
    )
    def test_configuration_rejects_scope_drift(
        self, golden_case, field_name, value
    ):
        with pytest.raises(ValueError):
            FinancialMVPRobustnessConfig(
                golden_case[4].m_evaluation_configuration,
                **{field_name: value},
            )


class TestGoldenRobustnessMatrix:
    def test_three_factors_and_six_cells_are_complete(
        self, golden_result
    ):
        assert golden_result.robustness_audit.gate_status == "ready"
        assert not golden_result.robustness_audit.errors
        assert tuple(
            item.factor_id for item in golden_result.factor_summaries
        ) == SUPPORTED_FACTOR_IDS
        for summary in golden_result.factor_summaries:
            assert len(summary.cells) == 6
            assert {
                (item.value_variant, item.segment)
                for item in summary.cells
            } == {
                (variant, segment)
                for variant in ROBUSTNESS_VARIANTS
                for segment in ROBUSTNESS_SEGMENTS
            }
            assert all(
                item.status == RobustnessCellStatus.COMPLETED.value
                for item in summary.cells
            )

    def test_full_sample_matches_exact_m_evaluation_statistics(
        self, golden_result
    ):
        for summary in golden_result.factor_summaries:
            for variant in ROBUSTNESS_VARIANTS:
                full = summary.get_cell(variant, "full")
                assert full.effective_date_count == 12
                assert full.factor_sample_count == 360
                assert full.label_available_count == 360
                assert full.paired_coverage_rate == 1.0
                assert full.rank_ic_mean == pytest.approx(1.0 / 3.0)
                assert full.rank_ic_positive_ratio == pytest.approx(
                    2.0 / 3.0
                )
                assert full.rank_ic_t_stat == pytest.approx(
                    0.9370425713316363
                )
                assert full.long_short_mean == pytest.approx(0.008)
                assert full.monotonicity_spearman == pytest.approx(1.0)

    def test_fixed_halves_expose_direction_change(self, golden_result):
        for summary in golden_result.factor_summaries:
            assert (
                summary.preprocessing_consistency
                == RobustnessConsistency.CONSISTENT.value
            )
            assert (
                summary.subperiod_direction_consistency
                == RobustnessConsistency.MIXED.value
            )
            for variant in ROBUSTNESS_VARIANTS:
                first = summary.get_cell(variant, "first_half")
                second = summary.get_cell(variant, "second_half")
                assert first.evaluation_dates == EVALUATION_DATES[:6]
                assert second.evaluation_dates == EVALUATION_DATES[6:]
                assert first.rank_ic_mean == pytest.approx(1.0)
                assert second.rank_ic_mean == pytest.approx(-1.0 / 3.0)
                assert first.direction == RobustnessDirection.POSITIVE.value
                assert (
                    second.direction
                    == RobustnessDirection.NEGATIVE.value
                )

    def test_no_cell_is_selected_as_best(self, golden_result):
        assert all(
            summary.best_cell_selected is False
            for summary in golden_result.factor_summaries
        )
        payload = golden_result.to_dict()
        assert "selected_cell" not in json.dumps(
            payload, ensure_ascii=False
        )

    def test_factor_and_label_fingerprints_are_bound(
        self, golden_result
    ):
        for summary in golden_result.factor_summaries:
            assert len(summary.raw_factor_sample_fingerprint) == 64
            assert len(summary.mad_factor_sample_fingerprint) == 64
            assert len(summary.label_fingerprint) == 64
            assert (
                summary.get_cell(
                    "raw_pit_factor_value", "full"
                ).label_fingerprint
                == summary.get_cell(
                    "evaluation_factor_value", "full"
                ).label_fingerprint
            )

    def test_lookup_serialization_and_hashes_are_deterministic(
        self, golden_result
    ):
        assert golden_result.get_factor("ROE").factor_id == "ROE"
        with pytest.raises(LookupError):
            golden_result.get_factor("NOT_APPROVED")
        with pytest.raises(LookupError):
            golden_result.get_factor("ROE").get_cell("raw", "full")
        assert golden_result.to_dict() == golden_result.to_dict()
        audit = golden_result.robustness_audit
        assert all(
            len(value) == 64
            for value in (
                audit.configuration_fingerprint,
                audit.m_evaluation_output_fingerprint,
                audit.factor_input_fingerprint,
                audit.label_input_fingerprint,
                audit.output_fingerprint,
                audit.content_hash,
            )
        )


class TestRawMadComparison:
    def test_outlier_case_has_real_raw_mad_contrast(
        self, outlier_result
    ):
        assert outlier_result.robustness_audit.gate_status == "ready"
        assert any(
            summary.raw_factor_sample_fingerprint
            != summary.mad_factor_sample_fingerprint
            for summary in outlier_result.factor_summaries
        )
        assert any(
            summary.raw_vs_mad_pearson_ic_delta is not None
            and not pytest.approx(0.0)
            == summary.raw_vs_mad_pearson_ic_delta
            for summary in outlier_result.factor_summaries
        )

    def test_raw_mad_comparison_never_changes_original_direction(
        self, outlier_result
    ):
        for summary in outlier_result.factor_summaries:
            raw = summary.get_cell("raw_pit_factor_value", "full")
            mad = summary.get_cell("evaluation_factor_value", "full")
            assert raw.direction == RobustnessDirection.POSITIVE.value
            assert mad.direction == RobustnessDirection.POSITIVE.value
            assert (
                summary.preprocessing_consistency
                == RobustnessConsistency.CONSISTENT.value
            )
            assert summary.best_cell_selected is False


class TestCoverageAndDegeneration:
    def test_missing_label_reduces_coverage_without_changing_samples(
        self, golden_case, golden_result
    ):
        mvp, prep, _, _, config = golden_case
        returns = make_forward_returns(
            missing={(EVALUATION_DATES[0], "SYNME0001")}
        )
        m_result = evaluate_financial_mvp_m(
            mvp,
            prep,
            returns,
            configuration=config.m_evaluation_configuration,
        )
        result = evaluate_financial_mvp_robustness(
            mvp,
            prep,
            returns,
            m_result,
            configuration=config,
        )
        for factor_id in SUPPORTED_FACTOR_IDS:
            before = golden_result.get_factor(factor_id)
            after = result.get_factor(factor_id)
            raw = after.get_cell("raw_pit_factor_value", "full")
            mad = after.get_cell("evaluation_factor_value", "full")
            assert raw.factor_sample_count == 360
            assert raw.label_available_count == 359
            assert raw.paired_coverage_rate == pytest.approx(359 / 360)
            assert raw.status == RobustnessCellStatus.NOT_RUN.value
            assert raw.insufficient_cross_section_count == 1
            assert raw.input_fingerprint == (
                before.get_cell(
                    "raw_pit_factor_value", "full"
                ).input_fingerprint
            )
            assert mad.input_fingerprint == (
                before.get_cell(
                    "evaluation_factor_value", "full"
                ).input_fingerprint
            )
            assert after.coverage_consistent is True

    def test_constant_return_degradation_is_reproducible(
        self, golden_case
    ):
        mvp, prep, _, _, config = golden_case
        returns = make_forward_returns(
            constant_dates={EVALUATION_DATES[0]}
        )
        m_result = evaluate_financial_mvp_m(
            mvp,
            prep,
            returns,
            configuration=config.m_evaluation_configuration,
        )
        result = evaluate_financial_mvp_robustness(
            mvp,
            prep,
            returns,
            m_result,
            configuration=config,
        )
        for summary in result.factor_summaries:
            cell = summary.get_cell(
                "evaluation_factor_value", "full"
            )
            assert cell.constant_return_count == 1
            assert cell.status == RobustnessCellStatus.NOT_RUN.value
            assert summary.constant_degradation_detected is True

    def test_constant_factor_is_not_run_not_zero_filled(self):
        mvp, prep, returns, m_result, config = (
            make_constant_bp_robustness_case()
        )
        result = evaluate_financial_mvp_robustness(
            mvp,
            prep,
            returns,
            m_result,
            configuration=config,
        )
        bp = result.get_factor("BP")
        for variant in ROBUSTNESS_VARIANTS:
            full = bp.get_cell(variant, "full")
            assert full.status == RobustnessCellStatus.NOT_RUN.value
            assert full.constant_factor_count == 12
            assert full.rank_ic_mean is None
            assert full.quantile_returns == ()
        assert bp.preprocessing_consistency == (
            RobustnessConsistency.INSUFFICIENT.value
        )
        assert bp.constant_degradation_detected is True

    def test_label_perturbation_does_not_change_factor_fingerprints(
        self, golden_case, golden_result
    ):
        mvp, prep, returns, _, config = golden_case
        frame = returns.get_frame()
        frame["forward_return"] = -frame["forward_return"]
        changed_returns = _with_return_frame(returns, frame)
        changed_m = evaluate_financial_mvp_m(
            mvp,
            prep,
            changed_returns,
            configuration=config.m_evaluation_configuration,
        )
        changed = evaluate_financial_mvp_robustness(
            mvp,
            prep,
            changed_returns,
            changed_m,
            configuration=config,
        )
        for factor_id in SUPPORTED_FACTOR_IDS:
            before = golden_result.get_factor(factor_id)
            after = changed.get_factor(factor_id)
            assert (
                before.raw_factor_sample_fingerprint
                == after.raw_factor_sample_fingerprint
            )
            assert (
                before.mad_factor_sample_fingerprint
                == after.mad_factor_sample_fingerprint
            )
            assert before.label_fingerprint != after.label_fingerprint


class TestFailClosedBoundaries:
    @pytest.mark.parametrize("position", [0, 1, 2, 3])
    def test_invalid_top_level_inputs_block(
        self, golden_case, position
    ):
        inputs = list(golden_case[:4])
        inputs[position] = None
        result = evaluate_financial_mvp_robustness(
            *inputs,
            configuration=golden_case[4],
        )
        assert result.factor_summaries == ()
        assert result.robustness_audit.gate_status == "blocked"
        assert result.robustness_audit.errors

    def test_invalid_configuration_object_blocks(self, golden_case):
        result = evaluate_financial_mvp_robustness(
            *golden_case[:4],
            configuration=None,
        )
        assert _codes(result) == {"INVALID_CONFIGURATION"}

    def test_blocked_or_stale_m_evaluation_blocks(self, golden_case):
        mvp, prep, returns, m_result, config = golden_case
        blocked = replace(
            m_result,
            evaluation_audit=replace(
                m_result.evaluation_audit, gate_status="blocked"
            ),
        )
        result = evaluate_financial_mvp_robustness(
            mvp,
            prep,
            returns,
            blocked,
            configuration=config,
        )
        assert "M_EVALUATION_GATE_BLOCKED" in _codes(result)
        stale = replace(
            m_result,
            evaluation_audit=replace(
                m_result.evaluation_audit,
                output_fingerprint="0" * 64,
            ),
        )
        result = evaluate_financial_mvp_robustness(
            mvp,
            prep,
            returns,
            stale,
            configuration=config,
        )
        assert "M_EVALUATION_OUTPUT_MISMATCH" in _codes(result)

    def test_tampered_primary_statistics_block(self, golden_case):
        mvp, prep, returns, m_result, config = golden_case
        common = list(m_result.common_results)
        common[0] = replace(
            common[0],
            rank_ic_mean=common[0].rank_ic_mean + 0.25,
        )
        tampered = FinancialMVPMEvaluationResult(
            common_results=tuple(common),
            factor_audits=m_result.factor_audits,
            evaluation_audit=m_result.evaluation_audit,
        )
        result = evaluate_financial_mvp_robustness(
            mvp,
            prep,
            returns,
            tampered,
            configuration=config,
        )
        assert "MAD_PRIMARY_STATISTIC_MISMATCH" in _codes(result)

    def test_non_synthetic_returns_block(self, golden_case):
        mvp, prep, returns, m_result, config = golden_case
        invalid = _with_return_frame(
            returns,
            returns.get_frame(),
            provenance={"synthetic_test_only": False},
        )
        result = evaluate_financial_mvp_robustness(
            mvp,
            prep,
            invalid,
            m_result,
            configuration=config,
        )
        assert "INVALID_FORWARD_RETURN_BATCH" in _codes(result)

    def test_inputs_are_not_mutated(self, golden_case):
        mvp, prep, returns, m_result, config = golden_case
        before = (
            copy.deepcopy(mvp.to_dict(include_rows=True)),
            copy.deepcopy(
                [item.to_dict() for item in prep.prepared_inputs]
            ),
            returns.get_frame(),
            copy.deepcopy(m_result.to_dict()),
        )
        evaluate_financial_mvp_robustness(
            mvp,
            prep,
            returns,
            m_result,
            configuration=config,
        )
        assert mvp.to_dict(include_rows=True) == before[0]
        assert [
            item.to_dict() for item in prep.prepared_inputs
        ] == before[1]
        pd.testing.assert_frame_equal(returns.get_frame(), before[2])
        assert m_result.to_dict() == before[3]

    def test_phase_two_and_admission_fields_are_absent(
        self, golden_result
    ):
        payload = json.dumps(
            golden_result.to_dict(), ensure_ascii=False, sort_keys=True
        )
        for forbidden in (
            "out_of_sample",
            "oos",
            "fdr",
            "multiple_testing",
            "direction_selection",
            "admission",
            "production_status",
            "best_cell_id",
        ):
            assert forbidden not in payload
