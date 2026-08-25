"""FIN-MVP-DATA tests for three-factor public FinancialBatch integration."""

import ast
import copy
import json
import sys
import types
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import ClassVar

import pandas as pd
import pytest

if "backend.amr" not in sys.modules:
    package = types.ModuleType("backend.amr")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "backend" / "amr")]
    sys.modules["backend.amr"] = package

from backend.amr.evaluation_input_contract import FinancialBatch
from backend.amr.financial_lineage import (
    recompute_lineage_content_hash,
)
from backend.amr.financial_mvp_batch import (
    FORMULA_REGISTRY,
    FORMULA_REGISTRY_VERSION,
    HASH_CONTRACT_VERSION,
    INTEGRATION_KEY_FIELDS,
    MVP_AUDIT_SCHEMA_VERSION,
    MVP_BATCH_SCHEMA_VERSION,
    PUBLIC_BATCH_SORT_FIELDS,
    SUPPORTED_FACTOR_IDS,
    MVPBatchConfig,
    MVPBatchLookupError,
    build_mvp_financial_batches,
    calculate_registered_mvp_formula,
    compute_formula_input_hash,
    formula_definition_for,
    recompute_observation_content_hash,
)
from backend.amr.financial_sample import (
    compute_sample_fingerprint,
    recompute_sample_content_hash,
)
from tests.fixtures.synthetic_financial_mvp_batch_cases import (
    CODE,
    EVALUATION_DATE,
    EXPECTED_FACTOR_VALUES,
    FORMULA_INPUTS,
    make_mvp_batch_inputs,
)


def _inputs(path_type="A"):
    return make_mvp_batch_inputs(path_type)


def _build(
    path_type="A",
    *,
    records=None,
    lineage_references=None,
    sample_references=None,
    configuration=None,
    future_labels=None,
):
    source_records, source_lineages, source_samples, source_config, labels = _inputs(
        path_type
    )
    return build_mvp_financial_batches(
        records if records is not None else source_records,
        lineage_references=(
            lineage_references if lineage_references is not None else source_lineages
        ),
        sample_references=(
            sample_references if sample_references is not None else source_samples
        ),
        configuration=(configuration if configuration is not None else source_config),
        future_labels=(future_labels if future_labels is not None else labels),
    )


def _codes(result):
    return {item.code for item in result.financial_batch_audit.errors}


def _warning_codes(result):
    return {item.code for item in result.financial_batch_audit.warnings}


class _ExposureBatchStub:
    schema_version = "ExposureBatch-v1"
    source = "platform-exposure-service"
    version = "synthetic-exposure-v1"
    provenance: ClassVar[dict[str, str]] = {
        "source": source,
        "data_version": version,
        "industry_mapping_version": "synthetic-sector-map-v1",
        "snapshot_hash": "b" * 64,
    }

    def __init__(self, *, sector_type="NON_FINANCIAL", market_cap=200.0):
        self._frame = pd.DataFrame(
            [
                {
                    "security_id": CODE,
                    "start_date": "2020-01-01",
                    "cancel_date": "2025-01-01",
                    "industry_code": sector_type,
                    "industry_type": sector_type,
                    "total_market_cap": market_cap,
                    "market_cap_date": EVALUATION_DATE,
                }
            ]
        )

    def get_frame(self):
        return self._frame.copy(deep=True)


class TestFrozenContractAndRegistry:
    def test_contract_versions_keys_and_factor_ids(self):
        assert MVP_BATCH_SCHEMA_VERSION == "FinancialMVPBatch-v1.0"
        assert MVP_AUDIT_SCHEMA_VERSION == "FinancialBatchAudit-v1.0"
        assert HASH_CONTRACT_VERSION == "FIN-MVP-DATA-HASH-v1.0"
        assert FORMULA_REGISTRY_VERSION == ("FIN-MVP-FORMULA-REGISTRY-v2.0")
        assert SUPPORTED_FACTOR_IDS == ("ROE", "BP", "OCF_NP")
        assert INTEGRATION_KEY_FIELDS == (
            "evaluation_date",
            "code",
            "factor_id",
        )
        assert PUBLIC_BATCH_SORT_FIELDS == (
            "code",
            "report_period",
            "effective_date",
        )

    def test_registry_contains_exactly_three_frozen_formulas(self):
        assert tuple(item.factor_id for item in FORMULA_REGISTRY) == (
            "ROE",
            "BP",
            "OCF_NP",
        )
        assert all(
            item.registry_version == FORMULA_REGISTRY_VERSION
            for item in FORMULA_REGISTRY
        )
        assert formula_definition_for("ROE").required_input_fields == (
            "parent_net_profit_ttm",
            "average_parent_equity",
        )

    def test_unsupported_formula_lookup_is_rejected(self):
        with pytest.raises(ValueError, match="unsupported"):
            formula_definition_for("GPM")

    def test_configuration_is_frozen_and_version_guarded(self):
        config = MVPBatchConfig(
            universe="ALL_A_SHARE",
            universe_version="test-all-a-v1",
            universe_filter="listed_and_pit_eligible",
        )
        with pytest.raises(FrozenInstanceError):
            config.batch_version = "changed"
        with pytest.raises(ValueError):
            MVPBatchConfig(
                universe="ALL_A_SHARE",
                universe_version="test-all-a-v1",
                universe_filter="listed_and_pit_eligible",
                formula_registry_version="unknown",
            )

    def test_universe_scope_is_explicit(self):
        with pytest.raises(TypeError):
            MVPBatchConfig()


class TestPathA:
    def test_three_precomputed_factors_enter_public_batches(self):
        result = _build("A")
        assert result.financial_batch_audit.gate_status == "ready"
        assert len(result.batches) == 3
        assert all(isinstance(item, FinancialBatch) for item in result.batches)
        assert tuple(item.factor_id for item in result.batches) == (
            "ROE",
            "BP",
            "OCF_NP",
        )
        for factor_id, expected in EXPECTED_FACTOR_VALUES.items():
            frame = result.get_batch(factor_id).get_frame()
            assert len(frame) == 1
            assert frame.iloc[0]["factor_value"] == expected

    def test_path_a_audit_counts_and_proofs(self):
        result = _build("A")
        audit = result.financial_batch_audit
        assert audit.path_a_count == 3
        assert audit.path_b_count == 0
        assert audit.accepted_count == 3
        assert audit.rejected_count == 0
        for item in result.observation_reference.records:
            assert item.path_type == "A"
            assert item.upstream_calculation_reference != "not_applicable"
            assert item.upstream_calculation_version != "not_applicable"
            assert len(item.upstream_calculation_hash) == 64
            assert item.formula_id == "not_applicable"

    @pytest.mark.parametrize(
        "field_name",
        [
            "upstream_calculation_reference",
            "upstream_calculation_version",
            "upstream_calculation_hash",
        ],
    )
    def test_missing_path_a_proof_blocks_all_batches(self, field_name):
        records, _, _, _, _ = _inputs("A")
        records[0][field_name] = ""
        result = _build("A", records=records)
        assert "PATH_A_UPSTREAM_PROOF_MISSING" in _codes(result)
        assert result.batches == ()
        assert result.observation_reference is None

    def test_upstream_reference_must_match_r1b(self):
        records, _, _, _, _ = _inputs("A")
        records[0]["upstream_calculation_reference"] = "wrong-reference"
        result = _build("A", records=records)
        assert "PATH_A_UPSTREAM_PROOF_MISSING" in _codes(result)

    @pytest.mark.parametrize("value", ["not-a-number", True])
    def test_invalid_path_a_value_blocks(self, value):
        records, _, _, _, _ = _inputs("A")
        records[0]["factor_value"] = value
        result = _build("A", records=records)
        assert "INVALID_FACTOR_VALUE" in _codes(result)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_nonfinite_path_a_value_blocks(self, value):
        records, _, _, _, _ = _inputs("A")
        records[0]["factor_value"] = value
        result = _build("A", records=records)
        assert "NONFINITE_FACTOR_VALUE" in _codes(result)


class TestPathB:
    @pytest.mark.parametrize(
        ("factor_id", "expected"),
        [("ROE", 0.2), ("BP", 0.25), ("OCF_NP", 1.5)],
    )
    def test_fixed_formula_cases(self, factor_id, expected):
        assert (
            calculate_registered_mvp_formula(
                factor_id,
                FORMULA_INPUTS[factor_id],
                sector_type="NON_FINANCIAL",
                market_cap_as_of=(EVALUATION_DATE if factor_id == "BP" else None),
                evaluation_date=EVALUATION_DATE,
            )
            == expected
        )

    def test_three_registered_formulas_enter_same_public_semantics(self):
        path_a = _build("A")
        path_b = _build("B")
        assert path_b.financial_batch_audit.gate_status == "ready"
        assert path_b.financial_batch_audit.path_a_count == 0
        assert path_b.financial_batch_audit.path_b_count == 3
        for factor_id in SUPPORTED_FACTOR_IDS:
            assert (
                path_a.get_batch(factor_id)
                .get_frame()
                .equals(path_b.get_batch(factor_id).get_frame())
            )

    def test_missing_sector_classification_blocks_path_b(self):
        records, _, _, _, _ = _inputs("B")
        records[0].pop("sector_type")
        result = _build("B", records=records)
        assert "SECTOR_CLASSIFICATION_MISSING" in _codes(result)

    def test_financial_sector_ocf_np_is_not_calculated(self):
        records, _, _, _, _ = _inputs("B")
        ocf_np = next(item for item in records if item["factor_id"] == "OCF_NP")
        ocf_np["sector_type"] = "BANK"
        result = _build("B", records=records)
        assert result.financial_batch_audit.gate_status == "ready"
        assert "FORMULA_NOT_APPLICABLE" in _warning_codes(result)
        assert "FORMULA_NOT_APPLICABLE" not in _codes(result)
        assert result.financial_batch_audit.successful_count == 2
        assert result.financial_batch_audit.not_applicable_count == 1
        assert result.financial_batch_audit.missing_count == 0
        assert result.financial_batch_audit.failure_count == 0
        assert result.get_batch("OCF_NP").get_frame().empty
        assert not any(
            item.factor_id == "OCF_NP"
            for item in result.observation_reference.records
        )

    def test_public_exposure_batch_routes_mixed_formula_applicability(self):
        records, lineages, samples, config, labels = _inputs("B")
        for record in records:
            record.pop("sector_type", None)
        result = build_mvp_financial_batches(
            records,
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=labels,
            exposure_batch=_ExposureBatchStub(sector_type="BANK"),
        )
        assert result.financial_batch_audit.gate_status == "ready"
        assert result.financial_batch_audit.successful_count == 2
        assert result.financial_batch_audit.not_applicable_count == 1
        assert "FORMULA_NOT_APPLICABLE" in _warning_codes(result)
        for batch in result.batches:
            provenance = batch.provenance
            assert provenance["exposure_contract_version"] == "ExposureBatch-v1"
            assert provenance["exposure_data_version"] == "synthetic-exposure-v1"
            assert provenance["industry_mapping_version"] == "synthetic-sector-map-v1"
            assert provenance["exposure_snapshot_hash"] == "b" * 64

    def test_public_exposure_market_cap_mismatch_blocks(self):
        records, lineages, samples, config, labels = _inputs("B")
        result = build_mvp_financial_batches(
            records,
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=labels,
            exposure_batch=_ExposureBatchStub(market_cap=201.0),
        )
        assert result.financial_batch_audit.gate_status == "blocked"
        assert "EXPOSURE_VALUE_MISMATCH" in _codes(result)

    def test_formula_version_and_inputs_are_retraceable(self):
        result = _build("B")
        for item in result.observation_reference.records:
            definition = formula_definition_for(item.factor_id)
            assert item.formula_id == definition.formula_id
            assert item.formula_version == definition.formula_version
            assert item.formula_reference == definition.formula_reference
            assert item.formula_input_references
            assert len(item.formula_input_hash) == 64
            assert item.upstream_calculation_reference == "not_applicable"

    def test_formula_input_hash_is_order_independent(self):
        values = FORMULA_INPUTS["ROE"]
        reverse_values = dict(reversed(list(values.items())))
        assert compute_formula_input_hash(
            "ROE", values, ("b", "a")
        ) == compute_formula_input_hash("ROE", reverse_values, ("a", "b"))

    @pytest.mark.parametrize(
        "field_name",
        ["formula_id", "formula_version", "formula_input_references"],
    )
    def test_missing_formula_reference_blocks(self, field_name):
        records, _, _, _, _ = _inputs("B")
        records[0][field_name] = (
            "" if field_name != ("formula_input_references") else ()
        )
        result = _build("B", records=records)
        assert {
            "PATH_B_FORMULA_REFERENCE_MISSING",
            "FORMULA_INPUT_REFERENCE_MISSING",
        } & _codes(result)

    def test_wrong_registered_formula_identity_blocks(self):
        records, _, _, _, _ = _inputs("B")
        records[0]["formula_id"] = "FIN-MVP-BP"
        result = _build("B", records=records)
        assert "PATH_B_FORMULA_REFERENCE_MISSING" in _codes(result)

    def test_missing_or_extra_formula_fields_block(self):
        records, _, _, _, _ = _inputs("B")
        records[0]["formula_inputs"]["unexpected"] = 1.0
        result = _build("B", records=records)
        assert "FORMULA_INPUT_REFERENCE_MISSING" in _codes(result)

    @pytest.mark.parametrize("denominator", [0.0, -1.0])
    def test_denominator_anomaly_is_deferred_to_r2_prep(self, denominator):
        records, _, _, _, _ = _inputs("B")
        records[0]["formula_inputs"]["average_parent_equity"] = denominator
        result = _build("B", records=records)
        assert "FORMULA_INPUT_REQUIRES_FIN_R2_PREP" in _codes(result)

    def test_nonfinite_formula_input_is_deferred_to_r2_prep(self):
        records, _, _, _, _ = _inputs("B")
        records[0]["formula_inputs"]["average_parent_equity"] = float("nan")
        result = _build("B", records=records)
        assert "FORMULA_INPUT_REQUIRES_FIN_R2_PREP" in _codes(result)

    @pytest.mark.parametrize(
        "dynamic_field",
        ["formula", "expression", "code_text", "executable_code"],
    )
    def test_dynamic_formula_is_rejected(self, dynamic_field):
        records, _, _, _, _ = _inputs("B")
        records[0][dynamic_field] = "numerator / denominator"
        result = _build("B", records=records)
        assert "DYNAMIC_FORMULA_NOT_ALLOWED" in _codes(result)

    def test_provided_value_must_equal_fixed_formula(self):
        records, _, _, _, _ = _inputs("B")
        records[0]["factor_value"] = 999.0
        result = _build("B", records=records)
        assert "FACTOR_VALUE_HASH_MISMATCH" in _codes(result)


class TestUpstreamReferencesAndConflicts:
    def test_effective_date_after_evaluation_date_blocks(self):
        records, _, _, _, _ = _inputs("A")
        records[0]["evaluation_date"] = "2024-01-07"
        result = _build("A", records=records)
        assert "EFFECTIVE_DATE_AFTER_EVALUATION_DATE" in _codes(result)

    def test_false_sample_mask_cannot_enter_batch(self):
        records, lineages, samples, config, labels = _inputs("A")
        reference = samples["ROE"]
        original = reference.records[0]
        changed = replace(original, factor_sample_mask=False)
        changed = replace(
            changed,
            content_hash=recompute_sample_content_hash(changed),
        )
        samples["ROE"] = replace(
            reference,
            records=(changed,),
            sample_fingerprint=compute_sample_fingerprint((changed,)),
        )
        result = build_mvp_financial_batches(
            records,
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=labels,
        )
        assert "SAMPLE_MASK_REFERENCE_MISSING" in _codes(result)

    def test_missing_factor_sample_reference_blocks(self):
        records, lineages, samples, config, labels = _inputs("A")
        samples.pop("ROE")
        result = build_mvp_financial_batches(
            records,
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=labels,
        )
        assert "SAMPLE_MASK_REFERENCE_MISSING" in _codes(result)

    def test_missing_factor_lineage_reference_blocks(self):
        records, lineages, samples, config, labels = _inputs("A")
        lineages.pop("BP")
        result = build_mvp_financial_batches(
            records,
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=labels,
        )
        assert "LINEAGE_REFERENCE_MISSING" in _codes(result)

    def test_tampered_lineage_content_blocks(self):
        records, lineages, samples, config, labels = _inputs("A")
        reference = lineages["ROE"]
        changed = replace(reference.records[0], source_provider="tampered")
        lineages["ROE"] = replace(reference, records=(changed,))
        result = build_mvp_financial_batches(
            records,
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=labels,
        )
        assert "LINEAGE_CONTENT_HASH_MISMATCH" in _codes(result)

    def test_tampered_sample_content_blocks(self):
        records, lineages, samples, config, labels = _inputs("A")
        reference = samples["ROE"]
        changed = replace(reference.records[0], universe_version="tampered")
        samples["ROE"] = replace(reference, records=(changed,))
        result = build_mvp_financial_batches(
            records,
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=labels,
        )
        assert "SAMPLE_CONTENT_HASH_MISMATCH" in _codes(result)

    def test_source_snapshot_mismatch_blocks(self):
        records, _, _, _, _ = _inputs("A")
        records[0]["source_snapshot_fingerprint"] = "wrong-snapshot"
        result = _build("A", records=records)
        assert "SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH" in _codes(result)

    def test_exact_duplicate_integration_key_blocks(self):
        records, _, _, _, _ = _inputs("A")
        records.append(copy.deepcopy(records[0]))
        result = _build("A", records=records)
        assert "DUPLICATE_FINANCIAL_OBSERVATION" in _codes(result)
        assert result.financial_batch_audit.conflict_count >= 1

    def test_same_key_different_proof_blocks_as_conflict(self):
        records, _, _, _, _ = _inputs("A")
        duplicate = copy.deepcopy(records[0])
        duplicate["upstream_calculation_hash"] = "f" * 64
        records.append(duplicate)
        result = _build("A", records=records)
        assert "FINANCIAL_OBSERVATION_CONFLICT" in _codes(result)

    def test_missing_one_approved_factor_blocks(self):
        records, _, _, _, _ = _inputs("A")
        records = [item for item in records if item["factor_id"] != "OCF_NP"]
        result = _build("A", records=records)
        assert "MVP_FACTOR_COVERAGE_INCOMPLETE" in _codes(result)

    def test_factor_outside_mvp_scope_is_rejected(self):
        records, _, _, _, _ = _inputs("A")
        extra = copy.deepcopy(records[0])
        extra["factor_id"] = "GPM"
        records.append(extra)
        result = _build("A", records=records)
        assert "UNSUPPORTED_MVP_FACTOR" in _codes(result)

    def test_cross_security_upstream_reference_is_blocked(self):
        records, lineages, samples, config, labels = _inputs("A")
        source_record = copy.deepcopy(records[0])
        source_record["code"] = "SYNMVP002"

        lineage_reference = lineages["ROE"]
        original_lineage = lineage_reference.records[0]
        second_lineage = replace(
            original_lineage,
            code="SYNMVP002",
            lineage_id="synthetic-second-lineage",
        )
        second_lineage = replace(
            second_lineage,
            content_hash=recompute_lineage_content_hash(second_lineage),
        )
        lineages["ROE"] = replace(
            lineage_reference,
            records=(original_lineage, second_lineage),
            row_count=2,
        )

        sample_reference = samples["ROE"]
        original_sample = sample_reference.records[0]
        second_sample = replace(
            original_sample,
            code="SYNMVP002",
            sample_id="synthetic-second-sample",
            financial_lineage_id=second_lineage.lineage_id,
            financial_lineage_content_hash=second_lineage.content_hash,
        )
        second_sample = replace(
            second_sample,
            content_hash=recompute_sample_content_hash(second_sample),
        )
        sample_records = (original_sample, second_sample)
        samples["ROE"] = replace(
            sample_reference,
            records=sample_records,
            row_count=2,
            sample_fingerprint=compute_sample_fingerprint(sample_records),
        )
        records.append(source_record)
        result = build_mvp_financial_batches(
            records,
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=labels,
        )
        assert "CROSS_SECURITY_FACTOR_VALUE_DETECTED" in _codes(result)


class TestDeterminismLabelsAndSafety:
    def test_batch_fingerprints_match_public_provenance(self):
        result = _build("A")
        fingerprints = dict(result.financial_batch_audit.batch_fingerprints)
        for batch in result.batches:
            assert (
                batch.provenance["batch_fingerprint"] == (fingerprints[batch.factor_id])
            )
            assert batch.provenance["future_labels_consumed"] is False

    def test_observation_reference_lookup_and_hash(self):
        result = _build("A")
        record = result.observation_reference.lookup("2024-01-08", CODE, "ROE")
        assert record.factor_value == EXPECTED_FACTOR_VALUES["ROE"]
        assert record.content_hash == recompute_observation_content_hash(record)

    def test_lookup_failures_have_stable_codes(self):
        result = _build("A")
        with pytest.raises(MVPBatchLookupError) as exc_info:
            result.observation_reference.lookup("2024-01-08", "MISSING", "ROE")
        assert exc_info.value.code == "LINEAGE_REFERENCE_MISSING"
        with pytest.raises(MVPBatchLookupError):
            result.get_batch("GPM")

    def test_input_order_does_not_change_output_or_fingerprints(self):
        records, _, _, _, _ = _inputs("A")
        forward = _build("A", records=records)
        reverse = _build("A", records=list(reversed(records)))
        assert forward.to_dict(include_rows=True) == (
            reverse.to_dict(include_rows=True)
        )

    def test_same_input_repeats_identically(self):
        first = _build("B")
        second = _build("B")
        assert first.to_dict(include_rows=True) == (second.to_dict(include_rows=True))

    def test_deleting_or_perturbing_future_labels_changes_nothing(self):
        baseline = _build("A")
        deleted = _build("A", future_labels=[])
        perturbed = _build(
            "A",
            future_labels=[
                {
                    "future_return": -999,
                    "target": 10**12,
                    "risk_label": "changed",
                }
            ],
        )
        assert baseline.to_dict(include_rows=True) == (
            deleted.to_dict(include_rows=True)
        )
        assert baseline.to_dict(include_rows=True) == (
            perturbed.to_dict(include_rows=True)
        )

    def test_future_label_iterable_is_never_consumed(self):
        class ExplodingLabels:
            def __iter__(self):
                raise AssertionError("future labels must not be consumed")

        result = _build("A", future_labels=ExplodingLabels())
        assert result.financial_batch_audit.gate_status == "ready"

    def test_inputs_are_not_mutated(self):
        records, lineages, samples, config, labels = _inputs("B")
        before_records = copy.deepcopy(records)
        before_lineages = copy.deepcopy(lineages)
        before_samples = copy.deepcopy(samples)
        before_config = copy.deepcopy(config)
        before_labels = copy.deepcopy(labels)
        build_mvp_financial_batches(
            records,
            lineage_references=lineages,
            sample_references=samples,
            configuration=config,
            future_labels=labels,
        )
        assert records == before_records
        assert lineages == before_lineages
        assert samples == before_samples
        assert config == before_config
        assert labels == before_labels

    def test_public_batch_frame_is_returned_by_copy(self):
        result = _build("A")
        batch = result.get_batch("ROE")
        frame = batch.get_frame()
        frame.loc[:, "factor_value"] = 999
        assert batch.get_frame().iloc[0]["factor_value"] == 0.2

    def test_result_is_json_serializable(self):
        result = _build("B")
        json.dumps(result.to_dict(include_rows=True), sort_keys=True)
        json.dumps(
            result.observation_reference.to_dict(include_records=True),
            sort_keys=True,
        )

    def test_core_module_has_no_dynamic_execution_or_io_clients(self):
        module_path = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "amr"
            / "financial_mvp_batch.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not {"eval", "exec", "compile"} & calls
        assert (
            not {
                "requests",
                "httpx",
                "socket",
                "supabase",
                "sqlalchemy",
            }
            & imports
        )
