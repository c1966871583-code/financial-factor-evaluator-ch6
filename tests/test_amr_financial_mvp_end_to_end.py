"""FIN-MVP-TEST: targeted and minimal end-to-end acceptance."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backend.amr.financial_mvp_batch import (
    SUPPORTED_FACTOR_IDS,
    build_mvp_financial_batches,
    recompute_observation_content_hash,
)
from backend.amr.financial_preprocessing import (
    FinancialPreprocessingConfig,
    prepare_financial_formula_inputs,
)
from tests.fixtures.synthetic_financial_mvp_batch_cases import (
    make_mvp_batch_inputs,
)
from tests.fixtures.synthetic_financial_mvp_end_to_end_cases import (
    FIXTURE_ID,
    FIXTURE_SCHEMA_VERSION,
    GOLDEN_SNAPSHOT_SCHEMA_VERSION,
    ExplodingFutureLabels,
    SyntheticFinancialMVPFixtureProvider,
    build_golden_snapshot,
)
from tests.fixtures.synthetic_financial_preprocessing_cases import (
    make_preprocessing_record,
)


GOLDEN_PATH = (
    Path(__file__).parent
    / "golden"
    / "financial_mvp_end_to_end_snapshot.json"
)


@pytest.fixture(scope="module")
def provider():
    return SyntheticFinancialMVPFixtureProvider()


@pytest.fixture(scope="module")
def golden_case(provider):
    return provider.load()


@pytest.fixture(scope="module")
def inverse_label_case(provider):
    return provider.load(label_multiplier=-1.0)


class TestFixtureAndRouting:
    def test_fixture_identity_and_all_gates_are_ready(
        self, golden_case
    ):
        assert golden_case.fixture_schema_version == (
            FIXTURE_SCHEMA_VERSION
        )
        assert golden_case.fixture_id == FIXTURE_ID
        assert golden_case.mvp_batch_result.financial_batch_audit.gate_status == (
            "ready"
        )
        assert golden_case.preprocessing_result.preprocessing_audit.gate_status == (
            "ready"
        )
        assert golden_case.m_evaluation_result.evaluation_audit.gate_status == (
            "ready"
        )
        assert golden_case.robustness_result.robustness_audit.gate_status == (
            "ready"
        )
        assert golden_case.output_result.output_audit.gate_status == "ready"

    def test_exact_three_factor_route_at_every_stage(self, golden_case):
        assert tuple(
            item.factor_id
            for item in golden_case.mvp_batch_result.batches
        ) == SUPPORTED_FACTOR_IDS
        assert {
            item.factor_id
            for item in golden_case.preprocessing_result.prepared_inputs
        } == set(SUPPORTED_FACTOR_IDS)
        assert tuple(
            item.factor_id
            for item in golden_case.m_evaluation_result.common_results
        ) == SUPPORTED_FACTOR_IDS
        assert tuple(
            item.factor_id
            for item in golden_case.robustness_result.factor_summaries
        ) == SUPPORTED_FACTOR_IDS
        assert tuple(
            item.factor_id
            for item in (
                golden_case.output_result
                .factor_evaluation_summaries
            )
        ) == SUPPORTED_FACTOR_IDS

    def test_batch_sidecar_and_preprocessing_counts_close(
        self, golden_case
    ):
        mvp = golden_case.mvp_batch_result
        reference = mvp.observation_reference
        assert len(mvp.batches) == 3
        assert {
            item.factor_id: len(item.get_frame())
            for item in mvp.batches
        } == {"ROE": 30, "BP": 30, "OCF_NP": 30}
        assert reference.row_count == 1080
        assert len(reference.records) == 1080
        assert len(
            golden_case.preprocessing_result.prepared_inputs
        ) == 1080
        assert len(
            golden_case.preprocessing_result.mad_audits
        ) == 36

    def test_every_observation_has_valid_hash_and_unique_route_key(
        self, golden_case
    ):
        records = (
            golden_case.mvp_batch_result.observation_reference.records
        )
        keys = {
            (item.evaluation_date, item.code, item.factor_id)
            for item in records
        }
        assert len(keys) == len(records)
        assert all(
            recompute_observation_content_hash(item)
            == item.content_hash
            for item in records
        )

    def test_public_batch_raw_values_match_sidecar(
        self, golden_case
    ):
        mvp = golden_case.mvp_batch_result
        reference = mvp.observation_reference
        for factor_id in SUPPORTED_FACTOR_IDS:
            frame = mvp.get_batch(factor_id).get_frame()
            public = {
                (
                    str(row["code"]),
                    str(row["report_period"])[:10],
                    str(row["effective_date"])[:10],
                ): float(row["factor_value"])
                for row in frame.to_dict(orient="records")
            }
            for item in reference.records:
                if item.factor_id != factor_id:
                    continue
                key = (
                    item.code,
                    item.report_period,
                    item.effective_date,
                )
                assert public[key] == item.factor_value


class TestPITAndAntiFuture:
    def test_all_dates_obey_pit_order(self, golden_case):
        records = (
            golden_case.mvp_batch_result.observation_reference.records
        )
        assert all(
            item.report_period
            <= item.publish_date
            <= item.effective_date
            <= item.evaluation_date
            for item in records
        )
        assert all(item.factor_sample_mask is True for item in records)

    def test_return_labels_start_at_configured_evaluation_dates(
        self, golden_case
    ):
        frame = golden_case.forward_returns.get_frame()
        assert set(frame["date"]) == set(
            golden_case.m_evaluation_configuration.evaluation_dates
        )
        assert set(frame["horizon"].astype(str)) == {"20"}
        assert not frame[["date", "code", "horizon"]].duplicated().any()

    def test_preprocessing_cannot_observe_future_labels(self):
        record = make_preprocessing_record()
        config = FinancialPreprocessingConfig(
            minimum_cross_section_size=2
        )
        without_labels = prepare_financial_formula_inputs(
            [copy.deepcopy(record)],
            configuration=config,
        )
        with_bomb = prepare_financial_formula_inputs(
            [copy.deepcopy(record)],
            configuration=config,
            future_labels=ExplodingFutureLabels(),
        )
        assert with_bomb == without_labels

    def test_mvp_batch_cannot_observe_future_labels(self):
        records, lineages, samples, config, _ = (
            make_mvp_batch_inputs("B")
        )
        without_labels = build_mvp_financial_batches(
            copy.deepcopy(records),
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
        )
        with_bomb = build_mvp_financial_batches(
            copy.deepcopy(records),
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=ExplodingFutureLabels(),
        )
        assert with_bomb.to_dict(include_rows=True) == (
            without_labels.to_dict(include_rows=True)
        )

    def test_label_perturbation_cannot_change_upstream_samples(
        self, golden_case, inverse_label_case
    ):
        original_mvp = golden_case.mvp_batch_result
        changed_mvp = inverse_label_case.mvp_batch_result
        assert original_mvp.to_dict(include_rows=True) == (
            changed_mvp.to_dict(include_rows=True)
        )
        assert [
            item.to_dict()
            for item in (
                golden_case.preprocessing_result.prepared_inputs
            )
        ] == [
            item.to_dict()
            for item in (
                inverse_label_case.preprocessing_result.prepared_inputs
            )
        ]
        original_records = (
            original_mvp.observation_reference.to_dict(
                include_records=True
            )
        )
        changed_records = (
            changed_mvp.observation_reference.to_dict(
                include_records=True
            )
        )
        assert original_records == changed_records

    def test_label_perturbation_changes_only_downstream_label_evidence(
        self, golden_case, inverse_label_case
    ):
        for factor_id in SUPPORTED_FACTOR_IDS:
            original_audit = (
                golden_case.m_evaluation_result.get_factor_audit(
                    factor_id
                )
            )
            changed_audit = (
                inverse_label_case.m_evaluation_result.get_factor_audit(
                    factor_id
                )
            )
            assert (
                original_audit.factor_sample_fingerprint
                == changed_audit.factor_sample_fingerprint
            )
            assert (
                original_audit.label_alignment_fingerprint
                != changed_audit.label_alignment_fingerprint
            )
            original_robust = (
                golden_case.robustness_result.get_factor(factor_id)
            )
            changed_robust = (
                inverse_label_case.robustness_result.get_factor(
                    factor_id
                )
            )
            assert (
                original_robust.raw_factor_sample_fingerprint
                == changed_robust.raw_factor_sample_fingerprint
            )
            assert (
                original_robust.mad_factor_sample_fingerprint
                == changed_robust.mad_factor_sample_fingerprint
            )
            assert (
                original_robust.label_fingerprint
                != changed_robust.label_fingerprint
            )

    def test_label_sign_flip_changes_statistics_not_factor_direction(
        self, golden_case, inverse_label_case
    ):
        for factor_id in SUPPORTED_FACTOR_IDS:
            original = golden_case.m_evaluation_result.get_result(
                factor_id
            )
            changed = inverse_label_case.m_evaluation_result.get_result(
                factor_id
            )
            assert changed.rank_ic_mean == pytest.approx(
                -original.rank_ic_mean
            )
            assert (
                golden_case.output_result.get_summary(
                    factor_id
                ).factor_direction_source
                == "original_direction_only"
            )
            assert (
                inverse_label_case.output_result.get_summary(
                    factor_id
                ).factor_direction_source
                == "original_direction_only"
            )


class TestDeterminismAndGoldenSnapshot:
    def test_complete_chain_does_not_mutate_inputs(self, golden_case):
        assert golden_case.inputs_unchanged is True
        assert golden_case.mutation_guard_before == (
            golden_case.mutation_guard_after
        )

    def test_two_provider_loads_are_deterministic(
        self, provider, golden_case
    ):
        repeated = provider.load()
        assert repeated.output_result.to_dict() == (
            golden_case.output_result.to_dict()
        )
        assert build_golden_snapshot(repeated) == (
            build_golden_snapshot(golden_case)
        )

    def test_generated_snapshot_matches_reviewed_golden(
        self, golden_case
    ):
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        actual = build_golden_snapshot(golden_case)
        assert expected == actual
        assert expected["snapshot_schema_version"] == (
            GOLDEN_SNAPSHOT_SCHEMA_VERSION
        )

    def test_golden_output_hashes_are_exact(self, golden_case):
        snapshot = build_golden_snapshot(golden_case)
        assert snapshot["output"] == {
            "run_id": "fin-mvp-output-68150aa59b7d17c779648f5b",
            "run_content_hash": (
                "fcae2be3e10b74444922c8e04f7b6ea9"
                "09b7e8bea05b5eb2440bf9d17f8b5c0e"
            ),
            "output_audit_hash": (
                "78db368794899ca6287d7ab2e0df5eea"
                "641ad99af8826c6e682f402aa5f7983d"
            ),
            "summary_hashes": {
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
            },
            "summary_statuses": snapshot["output"][
                "summary_statuses"
            ],
        }

    def test_missing_label_path_is_explicit_not_run(self, provider):
        case = provider.load(
            missing_labels={("2024-01-31", "SYNME0001")}
        )
        assert case.output_result.output_audit.gate_status == "ready"
        for summary in (
            case.output_result.factor_evaluation_summaries
        ):
            assert summary.status_summary.calculation_status == "not_run"
            assert summary.status_summary.evidence_assessment == (
                "insufficient"
            )
            assert summary.primary_statistics.rank_ic_mean is None
            assert summary.sample_summary.valid_factor_count == 360
            assert summary.sample_summary.paired_count == 359

    def test_golden_snapshot_is_review_sized(self):
        payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        assert set(payload) == {
            "snapshot_schema_version",
            "fixture_schema_version",
            "fixture_id",
            "factor_ids",
            "evaluation_dates",
            "return_horizon",
            "counts",
            "gates",
            "m_evaluation",
            "robustness",
            "output",
            "input_mutation_guard",
        }
        assert GOLDEN_PATH.stat().st_size < 20_000


class TestMVPScopeBoundaries:
    def test_summary_remains_research_only(self, golden_case):
        payload = json.dumps(
            golden_case.output_result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
        ).lower()
        assert '"evidence_assessment": "exploratory"' in payload
        assert '"production_status": "not production ready"' in payload
        for forbidden in (
            '"approved"',
            '"admitted"',
            '"rejected"',
            "conditionally_passed",
            "research_log_reference",
            "supabase",
        ):
            assert forbidden not in payload

    def test_phase_two_outputs_are_not_mvp_requirements(
        self, golden_case
    ):
        payload = json.dumps(
            build_golden_snapshot(golden_case),
            sort_keys=True,
        ).lower()
        for forbidden in (
            "fama_macbeth",
            "out_of_sample",
            "multiple_testing",
            "fdr",
            "validation_track_f",
            "validation_track_r",
        ):
            assert forbidden not in payload
