"""FIN-MVP-OUTPUT acceptance tests."""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, replace

import pandas as pd
import pytest

from backend.amr.financial_mvp_batch import SUPPORTED_FACTOR_IDS
from backend.amr.financial_mvp_output import (
    FACTOR_IDENTITIES,
    FACTOR_SUMMARY_SCHEMA_VERSION,
    FINANCIAL_RUN_SCHEMA_VERSION,
    OUTPUT_AUDIT_SCHEMA_VERSION,
    OUTPUT_DIRECTION_SOURCE,
    OUTPUT_EVIDENCE_PRIORITY,
    OUTPUT_HASH_CONTRACT_VERSION,
    OUTPUT_OOS_STATUS,
    OUTPUT_PHASE,
    OUTPUT_POLICY_VERSION,
    OUTPUT_PRODUCTION_STATUS,
    OUTPUT_VALIDATION_TRACK,
    EvidenceAssessment,
    FinancialEvaluationRun,
    FinancialMVPOutputConfig,
    build_financial_mvp_output,
    project_factor_evaluation_summaries,
    recompute_financial_evaluation_run_content_hash,
)
from tests.fixtures.synthetic_financial_mvp_output_cases import (
    make_insufficient_bp_output_case,
    make_output_case,
)


@pytest.fixture(scope="module")
def output_case():
    return make_output_case()


@pytest.fixture(scope="module")
def output_result(output_case):
    return build_financial_mvp_output(
        *output_case[:5],
        configuration=output_case[5],
    )


def _codes(result):
    return {item.code for item in result.output_audit.errors}


class TestFrozenContract:
    def test_versions_statuses_and_identities_are_frozen(self):
        assert FINANCIAL_RUN_SCHEMA_VERSION == (
            "FinancialEvaluationRun-v1.0"
        )
        assert FACTOR_SUMMARY_SCHEMA_VERSION == (
            "FactorEvaluationSummary-v1.0"
        )
        assert OUTPUT_AUDIT_SCHEMA_VERSION == (
            "FinancialMVPOutputAudit-v1.0"
        )
        assert OUTPUT_HASH_CONTRACT_VERSION == (
            "FIN-MVP-OUTPUT-HASH-v1.0"
        )
        assert OUTPUT_POLICY_VERSION == "FIN-MVP-OUTPUT-POLICY-v1.0"
        assert OUTPUT_PHASE == "phase1_mvp"
        assert OUTPUT_VALIDATION_TRACK == "M"
        assert OUTPUT_EVIDENCE_PRIORITY == "primary"
        assert OUTPUT_PRODUCTION_STATUS == "not production ready"
        assert OUTPUT_DIRECTION_SOURCE == "original_direction_only"
        assert OUTPUT_OOS_STATUS == "not_run"
        assert tuple(item[0] for item in FACTOR_IDENTITIES) == (
            SUPPORTED_FACTOR_IDS
        )

    def test_configuration_is_immutable_and_cross_bound(
        self, output_case
    ):
        config = output_case[5]
        assert (
            config.robustness_configuration
            .m_evaluation_configuration
            == config.m_evaluation_configuration
        )
        with pytest.raises(FrozenInstanceError):
            config.phase = "changed"

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("phase", "phase2"),
            ("validation_track", "F"),
            ("evidence_priority", "secondary"),
            ("production_status", "research usable"),
            ("factor_direction_source", "selected_by_result"),
            ("oos_consistency", "consistent"),
            ("run_schema_version", "v2"),
            ("summary_schema_version", "v2"),
            ("policy_version", "v2"),
            ("synthetic_test_only", False),
        ],
    )
    def test_configuration_rejects_status_or_scope_drift(
        self, output_case, field_name, value
    ):
        config = output_case[5]
        with pytest.raises(ValueError):
            FinancialMVPOutputConfig(
                config.m_evaluation_configuration,
                config.robustness_configuration,
                **{field_name: value},
            )


class TestFinancialEvaluationRun:
    def test_run_contains_complete_engineering_audit(
        self, output_result
    ):
        assert output_result.output_audit.gate_status == "ready"
        run = output_result.financial_evaluation_run
        assert isinstance(run, FinancialEvaluationRun)
        assert run.phase == "phase1_mvp"
        assert run.validation_track == "M"
        assert run.evidence_priority == "primary"
        assert run.evaluation_period == (
            "2024-01-31",
            "2024-12-31",
        )
        assert run.evaluation_frequency == "month_end"
        assert run.return_horizon == "20"
        assert run.supported_factor_ids == SUPPORTED_FACTOR_IDS
        assert len(run.common_evaluation_results) == 3
        assert len(run.alignment_reports) == 3
        assert len(run.coverage_reports) == 3
        assert len(run.financial_evidence) == 3
        assert len(run.evidence_assessments) == 3
        assert run.observation_lineage_reference.row_count == 1080
        assert run.preprocessing_audit.gate_status == "ready"
        assert run.provenance_audit.gate_status == "ready"
        assert run.gate_result.overall_status == "ready"

    def test_run_uses_deterministic_content_addressed_identity(
        self, output_result
    ):
        run = output_result.financial_evaluation_run
        assert run.run_id == (
            "fin-mvp-output-68150aa59b7d17c779648f5b"
        )
        assert run.content_hash == (
            "fcae2be3e10b74444922c8e04f7b6ea9"
            "09b7e8bea05b5eb2440bf9d17f8b5c0e"
        )
        assert (
            recompute_financial_evaluation_run_content_hash(run)
            == run.content_hash
        )
        payload = run.to_dict()
        assert "created_at" not in payload
        assert "updated_at" not in payload

    def test_common_results_are_preserved_without_public_field_changes(
        self, output_case, output_result
    ):
        source = output_case[3]
        run = output_result.financial_evaluation_run
        assert [
            item.to_dict() for item in run.common_evaluation_results
        ] == [item.to_dict() for item in source.common_results]
        assert run.get_common_result("ROE").factor_type == "financial"
        with pytest.raises(LookupError):
            run.get_common_result("NOT_APPROVED")

    def test_fingerprints_and_sidecar_references_are_retained(
        self, output_case, output_result
    ):
        m_result = output_case[3]
        robust = output_case[4]
        run = output_result.financial_evaluation_run
        fingerprints = dict(run.input_fingerprints)
        assert fingerprints["m_evaluation_output"] == (
            m_result.evaluation_audit.output_fingerprint
        )
        assert fingerprints["robustness_output"] == (
            robust.robustness_audit.output_fingerprint
        )
        assert run.timing_audit
        assert run.provenance_audit.provenance_references
        assert run.observation_lineage_reference.location.startswith(
            "memory://"
        )

    def test_universe_coverage_is_not_invented(self, output_result):
        run = output_result.financial_evaluation_run
        for report in run.coverage_reports:
            assert report.universe_count is None
            assert report.factor_coverage_rate is None
            assert report.paired_coverage_rate is None
            assert report.valid_factor_count == 360
            assert report.paired_count == 360
            assert report.label_to_factor_alignment_rate == 1.0
            assert report.universe_denominator_status == "not_available"
        assert (
            run.gate_result.warnings[0].code
            == "UNIVERSE_DENOMINATOR_UNAVAILABLE"
        )


class TestFactorSummaryProjection:
    def test_three_summaries_are_projection_only(self, output_result):
        run = output_result.financial_evaluation_run
        projected = project_factor_evaluation_summaries(run)
        assert projected == output_result.factor_evaluation_summaries
        assert tuple(item.factor_id for item in projected) == (
            SUPPORTED_FACTOR_IDS
        )
        assert all(
            item.source_run_content_hash == run.content_hash
            for item in projected
        )

    def test_summary_fields_follow_authoritative_candidate(
        self, output_result
    ):
        expected = {
            "summary_schema_version",
            "run_id",
            "factor_id",
            "factor_name",
            "factor_category",
            "validation_track",
            "evidence_priority",
            "evaluation_period",
            "evaluation_frequency",
            "return_horizon",
            "factor_direction_source",
            "sample_summary",
            "primary_statistics",
            "robustness_summary",
            "status_summary",
            "key_findings",
            "warnings",
            "limitations",
            "source_run_content_hash",
            "content_hash",
        }
        assert set(
            output_result.factor_evaluation_summaries[0].to_dict()
        ) == expected

    def test_summary_statistics_are_direct_run_values(
        self, output_result
    ):
        run = output_result.financial_evaluation_run
        for summary in output_result.factor_evaluation_summaries:
            common = run.get_common_result(summary.factor_id)
            primary = summary.primary_statistics
            assert primary.rank_ic_mean == common.rank_ic_mean
            assert primary.pearson_ic_mean == common.pearson_ic_mean
            assert primary.rank_ic_ir == common.rank_ic_ir
            assert primary.rank_ic_t_stat == common.rank_ic_t_stat
            assert primary.long_short_mean == common.long_short_mean
            assert (
                primary.monotonicity_spearman
                == common.monotonicity_spearman
            )

    def test_mvp_status_is_exploratory_not_admission(
        self, output_result
    ):
        for summary in output_result.factor_evaluation_summaries:
            status = summary.status_summary
            assert status.calculation_status == "completed"
            assert status.gate_status == "ready"
            assert status.evidence_assessment == (
                EvidenceAssessment.EXPLORATORY.value
            )
            assert status.production_status == "not production ready"
            assert summary.factor_direction_source == (
                "original_direction_only"
            )
            assert summary.robustness_summary.oos_consistency == (
                "not_run"
            )

    def test_summary_coverage_keeps_unknown_denominator_null(
        self, output_result
    ):
        for summary in output_result.factor_evaluation_summaries:
            sample = summary.sample_summary
            assert sample.universe_count is None
            assert sample.factor_coverage_rate is None
            assert sample.paired_coverage_rate is None
            assert sample.valid_factor_count == 360
            assert sample.paired_count == 360
            assert (
                "UNIVERSE_DENOMINATOR_UNAVAILABLE"
                in summary.warnings
            )

    def test_robustness_summary_is_projected(self, output_result):
        run = output_result.financial_evaluation_run
        for summary in output_result.factor_evaluation_summaries:
            source = run.get_robustness(summary.factor_id)
            projected = summary.robustness_summary
            assert projected.preprocessing_consistency == (
                source.preprocessing_consistency
            )
            assert projected.subperiod_direction_consistency == (
                source.subperiod_direction_consistency
            )
            assert projected.oos_consistency == "not_run"

    def test_summary_hashes_match_golden_snapshot(
        self, output_result
    ):
        expected = {
            "ROE": (
                "eebbeeb72332da92f96d44ad7497c34d"
                "a9c7700bf92ae1e7f84a0addefe72de1"
            ),
            "BP": (
                "25aca1e716a95e5c6410865bfa6e682a"
                "dc3847121b99a5f538e47dd3c4d0ca7e"
            ),
            "OCF_NP": (
                "b844ef0effe0eea534fc872b484f70ab"
                "f708ab58a1a4f965f6ab2101b6fa3aa9"
            ),
        }
        assert {
            item.factor_id: item.content_hash
            for item in output_result.factor_evaluation_summaries
        } == expected

    def test_insufficient_factor_is_not_zero_filled(self):
        case = make_insufficient_bp_output_case()
        result = build_financial_mvp_output(
            *case[:5], configuration=case[5]
        )
        bp = result.get_summary("BP")
        assert bp.status_summary.calculation_status == "not_run"
        assert bp.status_summary.evidence_assessment == "insufficient"
        assert bp.primary_statistics.rank_ic_mean is None
        assert bp.primary_statistics.long_short_mean is None
        assert "CALCULATION_NOT_COMPLETED" in bp.warnings

    def test_tampered_run_cannot_be_projected(self, output_result):
        run = output_result.financial_evaluation_run
        with pytest.raises(ValueError, match="hash mismatch"):
            project_factor_evaluation_summaries(
                replace(run, content_hash="0" * 64)
            )


class TestDeterminismAndBoundaries:
    def test_repeated_build_is_byte_deterministic(
        self, output_case, output_result
    ):
        repeated = build_financial_mvp_output(
            *output_case[:5],
            configuration=output_case[5],
        )
        assert repeated.to_dict() == output_result.to_dict()
        encoded_once = json.dumps(
            output_result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded_twice = json.dumps(
            repeated.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert encoded_once == encoded_twice

    def test_output_audit_binds_run_and_summaries(
        self, output_result
    ):
        audit = output_result.output_audit
        run = output_result.financial_evaluation_run
        assert audit.run_content_hash == run.content_hash
        assert audit.content_hash == (
            "78db368794899ca6287d7ab2e0df5eea"
            "641ad99af8826c6e682f402aa5f7983d"
        )
        assert all(
            len(value) == 64
            for value in (
                audit.configuration_fingerprint,
                audit.upstream_fingerprint,
                audit.run_content_hash,
                audit.summaries_fingerprint,
                audit.content_hash,
            )
        )

    @pytest.mark.parametrize("position", [0, 1, 2, 3, 4])
    def test_invalid_inputs_block_complete_package(
        self, output_case, position
    ):
        inputs = list(output_case[:5])
        inputs[position] = None
        result = build_financial_mvp_output(
            *inputs,
            configuration=output_case[5],
        )
        assert result.financial_evaluation_run is None
        assert result.factor_evaluation_summaries == ()
        assert result.output_audit.gate_status == "blocked"
        assert result.output_audit.errors

    def test_invalid_configuration_blocks(self, output_case):
        result = build_financial_mvp_output(
            *output_case[:5],
            configuration=None,
        )
        assert _codes(result) == {"INVALID_CONFIGURATION"}

    def test_stale_robustness_result_blocks(self, output_case):
        inputs = list(output_case[:5])
        robustness = inputs[4]
        inputs[4] = replace(
            robustness,
            robustness_audit=replace(
                robustness.robustness_audit,
                output_fingerprint="0" * 64,
            ),
        )
        result = build_financial_mvp_output(
            *inputs,
            configuration=output_case[5],
        )
        assert "ROBUSTNESS_RECOMPUTATION_MISMATCH" in _codes(result)

    def test_upstream_blocked_gate_blocks(self, output_case):
        inputs = list(output_case[:5])
        m_result = inputs[3]
        inputs[3] = replace(
            m_result,
            evaluation_audit=replace(
                m_result.evaluation_audit,
                gate_status="blocked",
            ),
        )
        result = build_financial_mvp_output(
            *inputs,
            configuration=output_case[5],
        )
        assert "UPSTREAM_GATE_BLOCKED" in _codes(result)

    def test_inputs_are_not_mutated(self, output_case):
        mvp, prep, returns, m_result, robust, config = output_case
        before = (
            copy.deepcopy(mvp.to_dict(include_rows=True)),
            copy.deepcopy(
                [item.to_dict() for item in prep.prepared_inputs]
            ),
            returns.get_frame(),
            copy.deepcopy(m_result.to_dict()),
            copy.deepcopy(robust.to_dict()),
        )
        build_financial_mvp_output(
            mvp,
            prep,
            returns,
            m_result,
            robust,
            configuration=config,
        )
        assert mvp.to_dict(include_rows=True) == before[0]
        assert [
            item.to_dict() for item in prep.prepared_inputs
        ] == before[1]
        pd.testing.assert_frame_equal(returns.get_frame(), before[2])
        assert m_result.to_dict() == before[3]
        assert robust.to_dict() == before[4]

    def test_no_admission_persistence_or_research_log_claims(
        self, output_result
    ):
        payload = json.dumps(
            output_result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
        ).lower()
        for forbidden in (
            '"approved"',
            '"admitted"',
            '"rejected"',
            "conditionally_passed",
            "supabase",
            "database_write",
            "research_log_reference",
            "production_ready",
        ):
            assert forbidden not in payload
