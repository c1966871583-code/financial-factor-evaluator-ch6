"""FIN-R2-PREP tests for deterministic three-factor preparation."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from backend.amr.financial_mvp_batch import build_mvp_financial_batches
from backend.amr.financial_preprocessing import (
    MAD_POLICY_VERSION,
    MAD_SCALE,
    MAD_THRESHOLD,
    PREPROCESSING_AUDIT_SCHEMA_VERSION,
    PREPROCESSING_HASH_CONTRACT_VERSION,
    PREPROCESSING_POLICY_VERSION,
    PREPROCESSING_SCHEMA_VERSION,
    FinancialPreprocessingConfig,
    MADStatus,
    PreprocessingErrorCode,
    PreprocessingGateStatus,
    prepare_financial_formula_inputs,
)
from tests.fixtures.synthetic_financial_preprocessing_cases import (
    make_annual_preprocessing_record,
    make_mad_cross_section,
    make_mvp_compatible_preprocessing_case,
    make_preprocessing_record,
)


def _prepare(records, *, minimum=2, future_labels=None):
    return prepare_financial_formula_inputs(
        records,
        configuration=FinancialPreprocessingConfig(
            minimum_cross_section_size=minimum
        ),
        future_labels=future_labels,
    )


def _error_codes(result):
    return {
        issue.code for issue in result.preprocessing_audit.errors
    }


class _ExplodingFutureLabels:
    def __iter__(self):
        raise AssertionError("future labels must not be iterated")

    def __deepcopy__(self, memo):
        raise AssertionError("future labels must not be copied")

    def __repr__(self):
        raise AssertionError("future labels must not be serialized")


class TestFrozenContract:
    def test_versions_are_frozen(self):
        assert PREPROCESSING_SCHEMA_VERSION == "FinancialPreprocessing-v1.0"
        assert (
            PREPROCESSING_AUDIT_SCHEMA_VERSION
            == "FinancialPreprocessingAudit-v1.0"
        )
        assert PREPROCESSING_HASH_CONTRACT_VERSION == "FIN-R2-PREP-HASH-v1.0"
        assert PREPROCESSING_POLICY_VERSION == "FIN-R2-PREP-POLICY-v1.0"
        assert MAD_POLICY_VERSION == "FIN-R2-PREP-MAD-v1.0"

    def test_mad_main_policy_is_frozen(self):
        assert MAD_THRESHOLD == 3.0
        assert MAD_SCALE == 1.4826

    @pytest.mark.parametrize("value", [True, 0, 1, -2, 2.5])
    def test_minimum_cross_section_size_must_be_explicit_integer(self, value):
        with pytest.raises(ValueError):
            FinancialPreprocessingConfig(minimum_cross_section_size=value)

    def test_mad_threshold_cannot_drift(self):
        with pytest.raises(ValueError):
            FinancialPreprocessingConfig(
                minimum_cross_section_size=5,
                mad_threshold=2.5,
            )

    def test_mad_scale_cannot_drift(self):
        with pytest.raises(ValueError):
            FinancialPreprocessingConfig(
                minimum_cross_section_size=5,
                mad_scale=1.0,
            )

    def test_non_synthetic_configuration_is_rejected(self):
        with pytest.raises(ValueError):
            FinancialPreprocessingConfig(
                minimum_cross_section_size=5,
                synthetic_test_only=False,
            )


class TestFinancialStatementPreparation:
    def test_interim_ttm_and_average_equity(self):
        result = _prepare([make_preprocessing_record()])
        assert (
            result.preprocessing_audit.gate_status
            == PreprocessingGateStatus.READY.value
        )
        roe = result.get("2024-01-08", "SYNPREP001", "ROE")
        bp = result.get("2024-01-08", "SYNPREP001", "BP")
        ocf_np = result.get("2024-01-08", "SYNPREP001", "OCF_NP")
        assert roe.formula_inputs == {
            "average_parent_equity": 100.0,
            "parent_net_profit_ttm": 20.0,
        }
        assert bp.formula_inputs == {
            "market_cap": 200.0,
            "parent_equity": 110.0,
        }
        assert ocf_np.formula_inputs == {
            "operating_cash_flow_ttm": 30.0,
            "parent_net_profit_ttm": 20.0,
        }
        assert roe.raw_pit_factor_value == 0.2
        assert bp.raw_pit_factor_value == 0.55
        assert ocf_np.raw_pit_factor_value == 1.5

    def test_annual_ttm_uses_current_annual_cumulative_value(self):
        result = _prepare([make_annual_preprocessing_record()])
        assert not result.preprocessing_audit.errors
        assert (
            result.get("2024-04-01", "SYNPREP001", "ROE")
            .formula_inputs["parent_net_profit_ttm"]
            == 20.0
        )
        assert (
            result.get("2024-04-01", "SYNPREP001", "OCF_NP")
            .formula_inputs["operating_cash_flow_ttm"]
            == 30.0
        )

    def test_three_factors_are_emitted_in_frozen_order(self):
        result = _prepare([make_preprocessing_record()])
        assert [item.factor_id for item in result.prepared_inputs] == [
            "ROE",
            "BP",
            "OCF_NP",
        ]

    def test_output_is_all_or_none(self):
        record = make_preprocessing_record(market_cap=0.0)
        result = _prepare([record])
        assert result.prepared_inputs == ()
        assert result.mad_audits == ()
        assert (
            result.preprocessing_audit.gate_status
            == PreprocessingGateStatus.BLOCKED.value
        )

    @pytest.mark.parametrize(
        ("overrides", "factor_id"),
        [
            (
                {
                    "parent_equity": -100.0,
                    "prior_year_same_period_parent_equity": -100.0,
                },
                "ROE",
            ),
            ({"market_cap": 0.0}, "BP"),
            ({"parent_net_profit_ttm": 0.0}, "OCF_NP"),
        ],
    )
    def test_nonpositive_denominators_are_blocked(
        self, overrides, factor_id
    ):
        result = _prepare([make_preprocessing_record(**overrides)])
        assert (
            PreprocessingErrorCode.NONPOSITIVE_FORMULA_DENOMINATOR.value
            in _error_codes(result)
        )
        assert any(
            factor_id in issue.message
            for issue in result.preprocessing_audit.errors
        )

    def test_negative_numerator_is_not_silently_removed(self):
        record = make_preprocessing_record(
            operating_cash_flow_ttm=-10.0
        )
        result = _prepare([record])
        assert not result.preprocessing_audit.errors
        assert (
            result.get("2024-01-08", "SYNPREP001", "OCF_NP")
            .raw_pit_factor_value
            == -0.5
        )

    def test_market_cap_is_consumed_as_pit_input(self):
        low = _prepare(
            [make_preprocessing_record(market_cap=100.0)]
        )
        high = _prepare(
            [make_preprocessing_record(market_cap=400.0)]
        )
        assert (
            low.get("2024-01-08", "SYNPREP001", "BP")
            .raw_pit_factor_value
            == 1.1
        )
        assert (
            high.get("2024-01-08", "SYNPREP001", "BP")
            .raw_pit_factor_value
            == 0.275
        )


class TestMADPreprocessing:
    def test_mad_is_applied_per_evaluation_date_and_factor(self):
        result = _prepare(make_mad_cross_section(), minimum=5)
        roe_audit = next(
            item for item in result.mad_audits if item.factor_id == "ROE"
        )
        assert roe_audit.status == MADStatus.APPLIED.value
        assert roe_audit.median == pytest.approx(0.12)
        assert roe_audit.raw_mad == pytest.approx(0.01)
        assert roe_audit.scaled_mad == pytest.approx(0.014826)
        assert roe_audit.upper_bound == pytest.approx(0.164478)
        assert roe_audit.clipped_count == 1
        outlier = result.get("2024-01-08", "SYNPREP005", "ROE")
        assert outlier.raw_pit_factor_value == 1.0
        assert outlier.evaluation_factor_value == pytest.approx(0.164478)
        assert outlier.was_winsorized is True

    def test_mad_zero_returns_raw_and_records_warning(self):
        result = _prepare(make_mad_cross_section(), minimum=5)
        audit = next(
            item for item in result.mad_audits if item.factor_id == "OCF_NP"
        )
        assert audit.status == MADStatus.MAD_ZERO_NO_WINSOR.value
        assert audit.raw_mad == 0
        assert audit.clipped_count == 0
        assert (
            PreprocessingErrorCode.MAD_ZERO_NO_WINSOR.value
            in {
                item.code for item in result.preprocessing_audit.warnings
            }
        )

    def test_insufficient_cross_section_returns_raw_and_warns(self):
        result = _prepare([make_preprocessing_record()], minimum=5)
        assert len(result.mad_audits) == 3
        assert all(
            item.status == MADStatus.SKIPPED_INSUFFICIENT.value
            for item in result.mad_audits
        )
        assert all(
            item.raw_pit_factor_value == item.evaluation_factor_value
            for item in result.prepared_inputs
        )
        assert len(result.preprocessing_audit.warnings) == 3

    def test_neutralized_value_is_explicitly_not_produced(self):
        result = _prepare([make_preprocessing_record()])
        assert all(
            item.to_dict()["neutralized_factor_value"] is None
            for item in result.prepared_inputs
        )

    def test_mvp_records_keep_raw_formula_inputs_not_mad_value(self):
        result = _prepare(make_mad_cross_section(), minimum=5)
        record = next(
            item
            for item in result.to_mvp_path_b_records()
            if item["code"] == "SYNPREP005"
            and item["factor_id"] == "ROE"
        )
        assert record["formula_inputs"]["parent_net_profit_ttm"] == 100.0
        assert "factor_value" not in record
        assert result.get(
            "2024-01-08", "SYNPREP005", "ROE"
        ).evaluation_factor_value < 1.0


class TestValidationAndIsolation:
    def test_future_labels_are_not_touched(self):
        result = _prepare(
            [make_preprocessing_record()],
            future_labels=_ExplodingFutureLabels(),
        )
        assert (
            result.preprocessing_audit.gate_status
            == PreprocessingGateStatus.READY.value
        )

    def test_deleting_future_labels_preserves_all_outputs(self):
        records = [make_preprocessing_record()]
        with_labels = _prepare(records, future_labels=[{"return": 99.0}])
        without_labels = _prepare(records, future_labels=None)
        assert with_labels == without_labels

    def test_input_objects_are_not_mutated(self):
        records = make_mad_cross_section()
        before = deepcopy(records)
        _prepare(records, minimum=5)
        assert records == before

    def test_deterministic_under_input_order_reversal(self):
        records = make_mad_cross_section()
        forward = _prepare(records, minimum=5)
        reverse = _prepare(list(reversed(records)), minimum=5)
        assert forward == reverse

    def test_duplicate_preparation_key_blocks(self):
        record = make_preprocessing_record()
        result = _prepare([record, deepcopy(record)])
        assert (
            PreprocessingErrorCode.DUPLICATE_PREPARATION_KEY.value
            in _error_codes(result)
        )

    @pytest.mark.parametrize(
        "field_name",
        [
            "parent_net_profit_ytd",
            "operating_cash_flow_ytd",
            "parent_equity",
            "market_cap",
            "prior_fy_parent_net_profit",
            "prior_fy_operating_cash_flow",
            "prior_year_same_period_parent_net_profit_ytd",
            "prior_year_same_period_operating_cash_flow_ytd",
            "prior_year_same_period_parent_equity",
        ],
    )
    def test_nonfinite_financial_input_blocks(self, field_name):
        record = make_preprocessing_record()
        record[field_name] = math.inf
        result = _prepare([record])
        assert (
            PreprocessingErrorCode.NONFINITE_FINANCIAL_INPUT.value
            in _error_codes(result)
        )

    def test_missing_interim_history_blocks(self):
        record = make_preprocessing_record()
        record.pop("prior_fy_parent_net_profit")
        result = _prepare([record])
        assert (
            PreprocessingErrorCode.MISSING_REQUIRED_FIELD.value
            in _error_codes(result)
        )

    def test_annual_record_does_not_require_interim_ttm_history(self):
        result = _prepare([make_annual_preprocessing_record()])
        assert not result.preprocessing_audit.errors

    def test_unsupported_report_period_blocks(self):
        record = make_preprocessing_record(report_period="2023-05-31")
        result = _prepare([record])
        assert (
            PreprocessingErrorCode.UNSUPPORTED_REPORT_PERIOD.value
            in _error_codes(result)
        )

    def test_future_effective_date_blocks(self):
        record = make_preprocessing_record(
            effective_date="2024-01-09",
            evaluation_date="2024-01-08",
        )
        result = _prepare([record])
        assert (
            PreprocessingErrorCode.INVALID_DATE_ORDER.value
            in _error_codes(result)
        )

    def test_invalid_snapshot_blocks(self):
        record = make_preprocessing_record()
        record["source_snapshot_fingerprint"] = "not-a-hash"
        result = _prepare([record])
        assert (
            PreprocessingErrorCode.INVALID_SOURCE_SNAPSHOT.value
            in _error_codes(result)
        )

    def test_missing_input_references_blocks(self):
        record = make_preprocessing_record()
        record["input_record_references"] = []
        result = _prepare([record])
        assert (
            PreprocessingErrorCode.MISSING_INPUT_REFERENCE.value
            in _error_codes(result)
        )

    def test_string_input_references_blocks(self):
        record = make_preprocessing_record()
        record["input_record_references"] = "not-an-iterable-of-ids"
        result = _prepare([record])
        assert (
            PreprocessingErrorCode.MISSING_INPUT_REFERENCE.value
            in _error_codes(result)
        )

    def test_non_synthetic_record_blocks(self):
        record = make_preprocessing_record()
        record["synthetic_test_only"] = False
        result = _prepare([record])
        assert (
            PreprocessingErrorCode.NON_SYNTHETIC_INPUT.value
            in _error_codes(result)
        )

    def test_nonmapping_record_blocks(self):
        result = _prepare(["invalid"])
        assert (
            PreprocessingErrorCode.INVALID_INPUT_RECORD.value
            in _error_codes(result)
        )

    def test_invalid_input_container_blocks(self):
        result = prepare_financial_formula_inputs(
            None,
            configuration=FinancialPreprocessingConfig(
                minimum_cross_section_size=2
            ),
        )
        assert (
            PreprocessingErrorCode.INVALID_INPUT_CONTAINER.value
            in _error_codes(result)
        )

    def test_invalid_configuration_object_blocks(self):
        result = prepare_financial_formula_inputs(
            [make_preprocessing_record()],
            configuration="invalid",
        )
        assert (
            PreprocessingErrorCode.INVALID_CONFIGURATION.value
            in _error_codes(result)
        )


class TestAuditAndIntegration:
    def test_audit_counts_close(self):
        result = _prepare(make_mad_cross_section(), minimum=5)
        audit = result.preprocessing_audit
        assert audit.input_record_count == 5
        assert audit.prepared_record_count == 5
        assert audit.factor_observation_count == 15
        assert audit.blocked_record_count == 0
        assert len(audit.errors) == 0
        assert len(audit.content_hash) == 64
        assert len(audit.output_fingerprint) == 64

    def test_prepared_input_is_frozen(self):
        result = _prepare([make_preprocessing_record()])
        item = result.prepared_inputs[0]
        with pytest.raises(FrozenInstanceError):
            item.code = "MUTATED"

    def test_formula_input_property_returns_copy(self):
        result = _prepare([make_preprocessing_record()])
        item = result.prepared_inputs[0]
        copied = item.formula_inputs
        copied[next(iter(copied))] = 999.0
        assert item.formula_inputs != copied

    def test_get_missing_key_raises(self):
        result = _prepare([make_preprocessing_record()])
        with pytest.raises(LookupError):
            result.get("2024-01-08", "MISSING", "ROE")

    def test_output_fingerprint_changes_with_financial_input(self):
        first = _prepare(
            [make_preprocessing_record(parent_net_profit_ttm=20.0)]
        )
        second = _prepare(
            [make_preprocessing_record(parent_net_profit_ttm=21.0)]
        )
        assert (
            first.preprocessing_audit.output_fingerprint
            != second.preprocessing_audit.output_fingerprint
        )

    def test_path_b_records_integrate_with_fin_mvp_data(self):
        (
            record,
            lineage_references,
            sample_references,
            mvp_configuration,
            future_labels,
            snapshots,
        ) = make_mvp_compatible_preprocessing_case()
        prep = _prepare([record], minimum=2)
        assert not prep.preprocessing_audit.errors
        mvp = build_mvp_financial_batches(
            prep.to_mvp_path_b_records(
                source_snapshot_fingerprints=snapshots
            ),
            lineage_references=lineage_references,
            sample_references=sample_references,
            configuration=mvp_configuration,
            future_labels=future_labels,
        )
        assert mvp.financial_batch_audit.gate_status == "ready"
        assert [
            mvp.get_batch(factor_id)
            .get_frame()
            .iloc[0]["factor_value"]
            for factor_id in ("ROE", "BP", "OCF_NP")
        ] == [0.2, 0.25, 1.5]
