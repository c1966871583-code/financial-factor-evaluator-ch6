"""Acceptance tests for FIN-P3-COMBOS."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.amr.financial_p3_combinations import (
    COMBINATIONS_CONCLUSION_BOUNDARY,
    FinancialP3CombinationsBatch,
    FinancialP3CombinationsConfig,
    evaluate_financial_p3_combinations,
    get_fin24_combination_definitions,
)
from backend.amr.financial_p3_common_sample import (
    compute_common_sample_manifest_fingerprint,
)
from tests.fixtures.synthetic_financial_p3_combination_cases import (
    EXECUTION_TIMESTAMP,
    PREDECESSOR_ANCHOR,
    evaluation_dates,
    make_batch,
    make_configuration,
    make_frame,
    make_manifest,
)


@pytest.fixture(scope="module")
def golden():
    return evaluate_financial_p3_combinations(
        make_batch(), configuration=make_configuration()
    )


def _experiments(result):
    return {
        item.definition.combination_id: item for item in result.experiments
    }


def _error_codes(result) -> set[str]:
    return {item.code for item in result.combinations_audit.errors}


def _evaluate(
    *,
    manifest=None,
    frame=None,
    declared_manifest_fingerprint=None,
    predecessor_anchor=None,
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
        predecessor_anchor=predecessor_anchor,
        provenance=provenance,
    )
    config = FinancialP3CombinationsConfig(
        run_id="SYNTHETIC-FIN24-COMBOS-01",
        expected_manifest_fingerprint=fingerprint,
        execution_timestamp=EXECUTION_TIMESTAMP,
    )
    return evaluate_financial_p3_combinations(
        batch, configuration=config
    )


class TestFrozenFin24Policy:
    def test_exact_three_definitions_and_order(self):
        definitions = get_fin24_combination_definitions()
        assert tuple(item.combination_id for item in definitions) == (
            "VQ",
            "QG",
            "CASHQ",
        )

    def test_vq_definition_is_exact(self):
        definition = get_fin24_combination_definitions()[0]
        assert definition.formula_expression == (
            "(z(BP)+z(EBIT_EV)+z(ROE)+z(OCF_NP))/4"
        )
        assert tuple(
            (item.factor_id, item.weight) for item in definition.terms
        ) == (
            ("BP", 0.25),
            ("EBIT_EV", 0.25),
            ("ROE", 0.25),
            ("OCF_NP", 0.25),
        )
        assert definition.reference_factor_id == "BP"

    def test_qg_definition_is_exact(self):
        definition = get_fin24_combination_definitions()[1]
        assert definition.formula_expression == (
            "(z(SALES_GROWTH)+z(PROFIT_GROWTH)+z(ROE)+z(OCF_NP))/4"
        )
        assert tuple(
            (item.factor_id, item.weight) for item in definition.terms
        ) == (
            ("SALES_GROWTH", 0.25),
            ("PROFIT_GROWTH", 0.25),
            ("ROE", 0.25),
            ("OCF_NP", 0.25),
        )
        assert definition.reference_factor_id == "ROE"

    def test_cashq_definition_has_negative_accruals(self):
        definition = get_fin24_combination_definitions()[2]
        assert definition.formula_expression == (
            "(z(ROA)+z(OCF_SALES)-z(ACCRUALS))/3"
        )
        assert tuple(
            (item.factor_id, item.weight) for item in definition.terms
        ) == (
            ("ROA", pytest.approx(1 / 3)),
            ("OCF_SALES", pytest.approx(1 / 3)),
            ("ACCRUALS", pytest.approx(-1 / 3)),
        )
        assert definition.reference_factor_id == "OCF_NP"

    def test_definition_hashes_are_frozen(self):
        assert tuple(
            item.content_hash for item in get_fin24_combination_definitions()
        ) == (
            "eb82365b95e2a38ab163e47caffa952e6758e822540befcb507bb10421968b49",
            "a81fbc2b67ec1f0287fcac42c6f651531cfc5b79f0fe1bfb333d2ce5872b9160",
            "121c7592353fccc00e94da6331e511db974f6a44937460bd369c81466cf8934a",
        )

    def test_configuration_freezes_construction_semantics(self):
        config = make_configuration()
        assert config.minimum_cross_section == 30
        assert config.minimum_periods == 12
        assert config.standardization_method == "population_zscore_ddof0"
        assert config.standardization_scope == "eligible_manifest_before_labels"
        assert config.combination_policy == "exact_fin24_three"
        assert config.weighting == "equal_weight"
        assert config.missing_value_policy == "preserve_no_imputation"
        assert config.automatic_reference_selection is False
        assert config.dynamic_weighting_allowed is False
        assert config.information_gain_decision_allowed is False
        assert config.synthetic_test_only is True

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("minimum_cross_section", 20),
            ("minimum_periods", 6),
            ("standardization_method", "sample_zscore_ddof1"),
            ("standardization_scope", "valid_return_rows"),
            ("combination_policy", "search_many"),
            ("weighting", "dynamic_ic"),
            ("missing_value_policy", "fill_zero"),
            ("automatic_reference_selection", True),
            ("dynamic_weighting_allowed", True),
            ("information_gain_decision_allowed", True),
            ("synthetic_test_only", False),
            ("predecessor_output_fingerprint", "0" * 64),
            ("policy_version", "drift"),
            ("schema_version", "drift"),
        ],
    )
    def test_rejects_policy_drift(self, field_name, value):
        with pytest.raises(ValueError):
            make_configuration(**{field_name: value})

    def test_manifest_fingerprint_must_be_sha256(self):
        with pytest.raises(ValueError):
            FinancialP3CombinationsConfig(
                run_id="x",
                expected_manifest_fingerprint="bad",
                execution_timestamp=EXECUTION_TIMESTAMP,
            )


class TestGoldenExperiments:
    def test_gate_ready_and_exact_three_experiments(self, golden):
        audit = golden.combinations_audit
        assert audit.gate_status == "ready"
        assert audit.errors == ()
        assert audit.experiment_count == 3
        assert audit.fin24_combinations_constructed is True
        assert tuple(
            item.definition.combination_id for item in golden.experiments
        ) == ("VQ", "QG", "CASHQ")

    def test_audit_separates_research_and_production(self, golden):
        audit = golden.combinations_audit
        assert audit.exact_formulas_frozen is True
        assert audit.equal_weight_only is True
        assert audit.pit_safe is True
        assert audit.return_label_independent_construction is True
        assert audit.common_sample_comparator_used is True
        assert audit.automatic_reference_selection_performed is False
        assert audit.dynamic_weighting_performed is False
        assert audit.information_gain_decision_made is False
        assert audit.synthetic_test_only is True
        assert audit.research_assessment == "exploratory"
        assert audit.production_status == "not production ready"
        assert audit.admission_status == "not_assessed"
        assert audit.conclusion_boundary == COMBINATIONS_CONCLUSION_BOUNDARY

    def test_warning_set_is_explicit(self, golden):
        assert {
            item.code for item in golden.combinations_audit.warnings
        } == {
            "SYNTHETIC_COMBINATIONS_ONLY",
            "EXACT_FIN24_FORMULAS",
            "PREDECLARED_REFERENCES_NOT_BEST",
            "INFORMATION_GAIN_NOT_DECIDED",
            "PRODUCTION_GATES_NOT_EVALUATED",
        }

    @pytest.mark.parametrize(
        ("combination_id", "reference", "constructed_size"),
        [
            ("VQ", "BP", 954),
            ("QG", "ROE", 954),
            ("CASHQ", "OCF_NP", 972),
        ],
    )
    def test_exact_construction_accounting(
        self, golden, combination_id, reference, constructed_size
    ):
        audit = _experiments(golden)[combination_id].construction_audit
        assert audit.reference_factor_id == reference
        assert audit.eligible_sample_size == 1044
        assert audit.reference_available_size == 1026
        assert audit.combination_available_size == constructed_size
        assert audit.constructed_period_count == 18

    @pytest.mark.parametrize("combination_id", ["VQ", "QG", "CASHQ"])
    def test_each_experiment_uses_fin23_common_sample(
        self, golden, combination_id
    ):
        experiment = _experiments(golden)[combination_id]
        comparison = experiment.comparison
        assert experiment.common_sample_audit.gate_status == "ready"
        assert comparison.evaluation_status == "completed"
        assert comparison.eligible_sample_size == 1044
        assert comparison.common_sample_size == 900
        assert comparison.common_period_count == 18
        assert comparison.coverage_loss == pytest.approx(144 / 1044)
        assert (
            comparison.single_factor_metrics.common_observation_count == 900
        )
        assert (
            comparison.combined_factor_metrics.common_observation_count == 900
        )
        assert (
            comparison.single_factor_metrics.common_sample_fingerprint
            == comparison.combined_factor_metrics.common_sample_fingerprint
            == comparison.common_sample_fingerprint
        )

    @pytest.mark.parametrize(
        ("combination_id", "mean_ic", "fm_r2"),
        [
            ("VQ", 0.9485981059090304, 0.9255336413253887),
            ("QG", 0.953672135520875, 0.9391525458913801),
            ("CASHQ", 0.9411017740429506, 0.9111925725581346),
        ],
    )
    def test_golden_composite_metrics(
        self, golden, combination_id, mean_ic, fm_r2
    ):
        metrics = _experiments(golden)[
            combination_id
        ].comparison.combined_factor_metrics
        assert metrics.mean_rank_ic == pytest.approx(mean_ic)
        assert metrics.fm_mean_r2 == pytest.approx(fm_r2)
        assert len(metrics.group_returns) == 5

    @pytest.mark.parametrize("combination_id", ["VQ", "QG", "CASHQ"])
    def test_deltas_remain_descriptive(self, golden, combination_id):
        comparison = _experiments(golden)[combination_id].comparison
        assert comparison.delta_ic == pytest.approx(
            comparison.combined_factor_metrics.mean_rank_ic
            - comparison.single_factor_metrics.mean_rank_ic
        )
        assert comparison.delta_icir == pytest.approx(
            comparison.combined_factor_metrics.icir
            - comparison.single_factor_metrics.icir
        )
        assert comparison.delta_fm_r2 == pytest.approx(
            comparison.combined_factor_metrics.fm_mean_r2
            - comparison.single_factor_metrics.fm_mean_r2
        )

    def test_output_has_no_fin25_or_admission_decision(self, golden):
        serialized = json.dumps(golden.to_dict(), sort_keys=True)
        for forbidden in (
            '"information_gain_decision":',
            '"best_single_factor":',
            '"best_combination":',
            '"selected_combination":',
            '"admission_decision":',
            '"production_status": "research usable"',
        ):
            assert forbidden not in serialized

    def test_all_hashes_are_sha256(self, golden):
        values = [
            golden.combinations_audit.manifest_fingerprint,
            golden.combinations_audit.input_fingerprint,
            golden.combinations_audit.output_fingerprint,
            golden.combinations_audit.content_hash,
        ]
        for experiment in golden.experiments:
            values.extend(
                [
                    experiment.definition.content_hash,
                    experiment.construction_audit.construction_fingerprint,
                    experiment.construction_audit.content_hash,
                    experiment.content_hash,
                ]
            )
        for value in values:
            assert len(value) == 64
            int(value, 16)


class TestConstructionBehavior:
    def test_return_value_does_not_change_construction(self, golden):
        frame = make_frame()
        mask = (
            (frame["evaluation_date"] == evaluation_dates()[0])
            & (frame["security_id"] == "S020")
        )
        frame.loc[mask, "forward_return"] = 99.0
        changed = _evaluate(frame=frame)
        for original, updated in zip(
            golden.experiments, changed.experiments, strict=True
        ):
            assert (
                original.construction_audit.construction_fingerprint
                == updated.construction_audit.construction_fingerprint
            )
        assert changed.combinations_audit.input_fingerprint != (
            golden.combinations_audit.input_fingerprint
        )

    def test_return_missingness_does_not_change_construction(self, golden):
        frame = make_frame()
        frame.loc[frame["security_id"] == "S020", "forward_return"] = np.nan
        changed = _evaluate(frame=frame)
        for original, updated in zip(
            golden.experiments, changed.experiments, strict=True
        ):
            assert (
                original.construction_audit.construction_fingerprint
                == updated.construction_audit.construction_fingerprint
            )
            assert updated.comparison.common_sample_size == 882

    def test_control_missingness_does_not_change_construction(self, golden):
        frame = make_frame()
        frame.loc[frame["security_id"] == "S020", "size_control"] = np.nan
        changed = _evaluate(frame=frame)
        for original, updated in zip(
            golden.experiments, changed.experiments, strict=True
        ):
            assert (
                original.construction_audit.construction_fingerprint
                == updated.construction_audit.construction_fingerprint
            )
            assert updated.comparison.common_sample_size == 882

    def test_ineligible_values_do_not_affect_experiments(self, golden):
        frame = make_frame()
        frame.loc[frame["security_id"] == "S059", "bp"] = 1_000_000.0
        changed = _evaluate(frame=frame)
        assert changed.experiments == golden.experiments
        assert changed.combinations_audit.output_fingerprint == (
            golden.combinations_audit.output_fingerprint
        )

    def test_component_missingness_only_affects_relevant_formula(self, golden):
        frame = make_frame()
        frame.loc[frame["security_id"] == "S020", "ebit_ev"] = np.nan
        changed = _evaluate(frame=frame)
        original = _experiments(golden)
        updated = _experiments(changed)
        assert updated["VQ"] != original["VQ"]
        assert updated["VQ"].comparison.common_sample_size == 882
        assert updated["QG"] == original["QG"]
        assert updated["CASHQ"] == original["CASHQ"]

    def test_zero_variance_period_is_omitted_symmetrically(self, golden):
        frame = make_frame()
        date = evaluation_dates()[0]
        frame.loc[frame["evaluation_date"] == date, "ebit_ev"] = 1.0
        changed = _evaluate(frame=frame)
        experiments = _experiments(changed)
        assert experiments["VQ"].comparison.common_period_count == 17
        assert experiments["VQ"].comparison.common_sample_size == 850
        assert experiments["QG"] == _experiments(golden)["QG"]
        assert experiments["CASHQ"] == _experiments(golden)["CASHQ"]

    def test_small_factor_cross_sections_yield_insufficient_not_blocked(self):
        frame = make_frame()
        frame.loc[frame["security_id"].str.slice(1).astype(int) >= 25, "ebit_ev"] = np.nan
        result = _evaluate(frame=frame)
        assert result.combinations_audit.gate_status == "ready"
        vq = _experiments(result)["VQ"]
        assert vq.construction_audit.constructed_period_count == 0
        assert vq.comparison.evaluation_status == "insufficient"
        assert vq.comparison.common_sample_size == 0


class TestFailClosedValidation:
    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("task_id", "WRONG"),
            ("status", "PENDING"),
            ("output_fingerprint", "0" * 64),
            ("same_sample_enforced", False),
            ("research_assessment", "supportive"),
            ("production_status", "production ready"),
        ],
    )
    def test_invalid_predecessor_anchor_blocks(self, field_name, value):
        anchor = dict(PREDECESSOR_ANCHOR)
        anchor[field_name] = value
        result = _evaluate(predecessor_anchor=anchor)
        assert result.combinations_audit.gate_status == "blocked"
        assert "INVALID_PREDECESSOR_ANCHOR" in _error_codes(result)
        assert result.experiments == ()

    def test_non_synthetic_provenance_blocks(self):
        result = _evaluate(provenance={"synthetic_test_only": False})
        assert "NON_SYNTHETIC_INPUT" in _error_codes(result)
        assert result.experiments == ()

    @pytest.mark.parametrize(
        "field_name",
        [
            "selected_combination",
            "selected_reference_factor",
            "best_single_factor",
            "best_combination",
            "dynamic_weight",
            "optimized_weight",
            "information_gain_decision",
            "admission_decision",
        ],
    )
    def test_forbidden_provenance_fields_block(self, field_name):
        result = _evaluate(
            provenance={
                "synthetic_test_only": True,
                field_name: "forbidden",
            }
        )
        assert "FORBIDDEN_SELECTION_FIELD" in _error_codes(result)

    @pytest.mark.parametrize(
        "column", ["evaluation_date", "security_id", "eligible"]
    )
    def test_missing_manifest_columns_block(self, column):
        result = _evaluate(manifest=make_manifest().drop(columns=[column]))
        assert "MISSING_COLUMN" in _error_codes(result)
        assert result.experiments == ()

    @pytest.mark.parametrize(
        "column",
        [
            "evaluation_date",
            "security_id",
            "bp",
            "ebit_ev",
            "roe",
            "ocf_np",
            "sales_growth",
            "profit_growth",
            "roa",
            "ocf_sales",
            "accruals",
            "bp_effective_date",
            "ebit_ev_effective_date",
            "roe_effective_date",
            "ocf_np_effective_date",
            "sales_growth_effective_date",
            "profit_growth_effective_date",
            "roa_effective_date",
            "ocf_sales_effective_date",
            "accruals_effective_date",
            "control_effective_date",
            "return_start_date",
            "forward_return",
            "size_control",
            "industry_code",
        ],
    )
    def test_missing_observation_columns_block(self, column):
        result = _evaluate(frame=make_frame().drop(columns=[column]))
        assert "MISSING_COLUMN" in _error_codes(result)
        assert result.experiments == ()

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
        config = make_configuration()
        wrong = FinancialP3CombinationsConfig(
            **{
                **config.to_dict(),
                "expected_manifest_fingerprint": "0" * 64,
            }
        )
        result = evaluate_financial_p3_combinations(
            make_batch(), configuration=wrong
        )
        assert "MANIFEST_FINGERPRINT_MISMATCH" in _error_codes(result)

    @pytest.mark.parametrize(
        "column",
        [
            "bp",
            "ebit_ev",
            "roe",
            "ocf_np",
            "sales_growth",
            "profit_growth",
            "roa",
            "ocf_sales",
            "accruals",
            "forward_return",
            "size_control",
        ],
    )
    def test_non_numeric_value_blocks(self, column):
        frame = make_frame()
        frame[column] = frame[column].astype(object)
        frame.loc[0, column] = "bad"
        result = _evaluate(frame=frame)
        assert "INVALID_NUMERIC" in _error_codes(result)

    @pytest.mark.parametrize(
        "column",
        [
            "bp_effective_date",
            "ebit_ev_effective_date",
            "roe_effective_date",
            "ocf_np_effective_date",
            "sales_growth_effective_date",
            "profit_growth_effective_date",
            "roa_effective_date",
            "ocf_sales_effective_date",
            "accruals_effective_date",
            "control_effective_date",
            "return_start_date",
        ],
    )
    def test_invalid_date_blocks(self, column):
        frame = make_frame()
        frame.loc[0, column] = "not-a-date"
        result = _evaluate(frame=frame)
        assert "INVALID_DATE" in _error_codes(result)

    @pytest.mark.parametrize(
        "column",
        [
            "bp_effective_date",
            "ebit_ev_effective_date",
            "roe_effective_date",
            "ocf_np_effective_date",
            "sales_growth_effective_date",
            "profit_growth_effective_date",
            "roa_effective_date",
            "ocf_sales_effective_date",
            "accruals_effective_date",
        ],
    )
    def test_future_factor_date_blocks(self, column):
        frame = make_frame()
        frame.loc[0, column] = "2099-01-01"
        result = _evaluate(frame=frame)
        assert "FUTURE_FACTOR_OR_CONTROL" in _error_codes(result)

    def test_future_control_date_blocks(self):
        frame = make_frame()
        frame.loc[0, "control_effective_date"] = "2099-01-01"
        result = _evaluate(frame=frame)
        assert "FUTURE_FACTOR_OR_CONTROL" in _error_codes(result)

    def test_non_future_return_start_blocks(self):
        frame = make_frame()
        frame.loc[0, "return_start_date"] = frame.loc[0, "evaluation_date"]
        result = _evaluate(frame=frame)
        assert "INVALID_RETURN_ALIGNMENT" in _error_codes(result)

    @pytest.mark.parametrize(
        "column",
        [
            "selected_combination",
            "best_single_factor",
            "dynamic_weight",
            "information_gain_decision",
        ],
    )
    def test_forbidden_frame_columns_block(self, column):
        frame = make_frame()
        frame[column] = "forbidden"
        result = _evaluate(frame=frame)
        assert "FORBIDDEN_SELECTION_FIELD" in _error_codes(result)

    def test_invalid_manifest_key_blocks(self):
        manifest = make_manifest()
        manifest.loc[0, "security_id"] = ""
        result = _evaluate(manifest=manifest)
        assert "INVALID_KEY" in _error_codes(result)

    def test_invalid_eligible_type_blocks(self):
        manifest = make_manifest()
        manifest["eligible"] = manifest["eligible"].astype(object)
        manifest.loc[0, "eligible"] = "yes"
        result = _evaluate(manifest=manifest)
        assert "INVALID_KEY" in _error_codes(result)


class TestDeterminismAndImmutability:
    def test_repeated_run_is_identical(self, golden):
        repeated = _evaluate()
        assert repeated.to_dict() == golden.to_dict()

    def test_row_order_is_irrelevant(self, golden):
        manifest = make_manifest().sample(frac=1, random_state=11)
        frame = make_frame().sample(frac=1, random_state=13)
        result = _evaluate(manifest=manifest, frame=frame)
        assert result.to_dict() == golden.to_dict()

    def test_batch_defensively_copies_inputs(self, golden):
        manifest = make_manifest()
        frame = make_frame()
        batch = make_batch(manifest=manifest, frame=frame)
        manifest.loc[:, "eligible"] = False
        frame.loc[:, "bp"] = 999.0
        result = evaluate_financial_p3_combinations(
            batch, configuration=make_configuration()
        )
        assert result.to_dict() == golden.to_dict()

    def test_batch_accessors_return_copies(self):
        batch = make_batch()
        manifest = batch.get_manifest()
        frame = batch.get_frame()
        manifest.loc[:, "eligible"] = False
        frame.loc[:, "bp"] = 999.0
        assert bool(batch.get_manifest()["eligible"].any())
        assert not bool((batch.get_frame()["bp"] == 999.0).all())

    def test_runtime_mutation_guard_blocks(self, monkeypatch):
        original = FinancialP3CombinationsBatch.get_frame
        calls = {"count": 0}

        def drifting(self):
            calls["count"] += 1
            frame = original(self)
            if calls["count"] >= 3:
                frame.loc[0, "bp"] = 999.0
            return frame

        monkeypatch.setattr(FinancialP3CombinationsBatch, "get_frame", drifting)
        result = evaluate_financial_p3_combinations(
            make_batch(), configuration=make_configuration()
        )
        assert result.combinations_audit.gate_status == "blocked"
        assert "INPUT_MUTATED" in _error_codes(result)
        assert result.experiments == ()

    def test_wrong_argument_types_raise(self):
        with pytest.raises(TypeError):
            evaluate_financial_p3_combinations(
                object(), configuration=make_configuration()
            )
        with pytest.raises(TypeError):
            evaluate_financial_p3_combinations(
                make_batch(), configuration=object()
            )

    def test_batch_requires_dataframes(self):
        with pytest.raises(TypeError):
            FinancialP3CombinationsBatch(
                dataset_id="x",
                version="v1",
                _manifest=[],
                _frame=make_frame(),
                declared_manifest_fingerprint="0" * 64,
                predecessor_anchor=PREDECESSOR_ANCHOR,
                provenance={"synthetic_test_only": True},
            )
        with pytest.raises(TypeError):
            FinancialP3CombinationsBatch(
                dataset_id="x",
                version="v1",
                _manifest=make_manifest(),
                _frame=[],
                declared_manifest_fingerprint="0" * 64,
                predecessor_anchor=PREDECESSOR_ANCHOR,
                provenance={"synthetic_test_only": True},
            )
