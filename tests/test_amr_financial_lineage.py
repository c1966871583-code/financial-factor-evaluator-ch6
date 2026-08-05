"""FIN-R1B tests for immutable, PIT-safe financial provenance."""

import ast
import copy
import json
import sys
import types
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest


# The repository's ``backend.amr.__init__`` wires optional Flask routes.  The
# FIN-R1B unit boundary is a pure module, so tests load the package namespace
# without importing those unrelated optional routes.
if "backend.amr" not in sys.modules:
    package = types.ModuleType("backend.amr")
    package.__path__ = [
        str(Path(__file__).resolve().parents[1] / "backend" / "amr")
    ]
    sys.modules["backend.amr"] = package

from backend.amr.financial_lineage import (  # noqa: E402
    FINANCIAL_OBSERVATION_KEY_FIELDS,
    HASH_CONTRACT_VERSION,
    LINEAGE_INDEX_FIELDS,
    LINEAGE_SCHEMA_VERSION,
    NOT_APPLICABLE,
    FinancialObservationLineage,
    LineageLookupError,
    PathType,
    ProvenanceErrorCode,
    build_financial_provenance,
    compute_configuration_hash,
    compute_factor_value_hash,
    compute_source_input_hash,
    compute_source_snapshot_fingerprint,
    recompute_lineage_content_hash,
    verify_lineage_hashes,
)
from tests.fixtures.synthetic_financial_lineage_cases import (  # noqa: E402
    CONFIGURATION,
    SNAPSHOT_MANIFEST,
    make_synthetic_financial_inputs,
)


def _inputs():
    return make_synthetic_financial_inputs()


def _build(records=None, configuration=None, batch=None):
    fixture_batch, fixture_records, fixture_configuration = _inputs()
    return build_financial_provenance(
        batch or fixture_batch,
        records if records is not None else fixture_records,
        configuration=(
            configuration
            if configuration is not None
            else fixture_configuration
        ),
    )


def _codes(result):
    return {issue.code for issue in result.provenance_audit.errors}


class TestLineageContract:
    def test_frozen_versions_keys_and_reason_codes(self):
        assert LINEAGE_SCHEMA_VERSION == "FinancialObservationLineage-v1.0"
        assert HASH_CONTRACT_VERSION == "FIN-R1B-HASH-v1.0"
        assert LINEAGE_INDEX_FIELDS == (
            "evaluation_date",
            "code",
            "factor_id",
        )
        assert FINANCIAL_OBSERVATION_KEY_FIELDS == (
            "code",
            "factor_id",
            "report_period",
            "effective_date",
        )
        assert NOT_APPLICABLE == "not_applicable"
        assert {
            "SOURCE_PROVIDER_MISSING",
            "REVISION_CHAIN_BROKEN",
            "MULTISOURCE_CONFLICT",
            "FACTOR_VALUE_HASH_MISMATCH",
        }.issubset({item.value for item in ProvenanceErrorCode})

    def test_happy_path_publishes_complete_sidecar(self):
        result = _build()
        audit = result.provenance_audit
        reference = result.observation_lineage_reference

        assert audit.gate_status == "ready"
        assert not audit.errors
        assert audit.total_observations == 3
        assert audit.lineage_complete_count == 3
        assert audit.lineage_incomplete_count == 0
        assert audit.revision_count == 1
        assert reference is not None
        assert reference.row_count == 3
        assert reference.records == result.lineage_records
        assert reference.location.endswith(f"{reference.content_hash}.json")
        assert (
            result.source_snapshot_fingerprint
            == result.source_snapshot_fingerprints
        )
        assert "source_snapshot_fingerprint" in result.to_dict()

    def test_every_row_traces_provider_dataset_snapshot_and_version(self):
        result = _build()
        for row in result.lineage_records:
            assert row.source_provider == "synthetic-provider"
            assert row.source_dataset == "synthetic-financial-statements"
            assert row.source_snapshot_id == "snapshot-2024-01-10"
            assert row.source_as_of_version
            assert row.source_snapshot_fingerprint
            assert row.financial_statement_version
            assert (
                row.source_record_id != NOT_APPLICABLE
                or row.announcement_id != NOT_APPLICABLE
            )

    def test_path_a_has_upstream_proof_and_no_fake_formula(self):
        rows = [
            row for row in _build().lineage_records
            if row.path_type == PathType.UPSTREAM_COMPUTED.value
        ]
        assert rows
        assert all(
            row.upstream_calculation_reference != NOT_APPLICABLE
            for row in rows
        )
        assert all(row.formula_reference == NOT_APPLICABLE for row in rows)

    def test_path_b_has_registered_formula_reference(self):
        row = next(
            row for row in _build().lineage_records
            if row.path_type == PathType.REGISTERED_FORMULA.value
        )
        assert row.formula_reference == "registered-formula://synthetic/v1"
        assert row.upstream_calculation_reference == NOT_APPLICABLE

    def test_lineage_row_is_frozen(self):
        row = _build().lineage_records[0]
        with pytest.raises(FrozenInstanceError):
            row.code = "CHANGED"

    @pytest.mark.parametrize(
        ("field_name", "code"),
        [
            ("source_provider", "SOURCE_PROVIDER_MISSING"),
            ("source_dataset", "SOURCE_DATASET_MISSING"),
            ("source_snapshot_id", "SOURCE_SNAPSHOT_MISSING"),
            ("source_as_of_version", "SOURCE_SNAPSHOT_MISSING"),
            ("financial_statement_version", "FINANCIAL_VERSION_MISSING"),
            ("revision_version", "FINANCIAL_VERSION_MISSING"),
        ],
    )
    def test_missing_governed_field_blocks(self, field_name, code):
        _, records, _ = _inputs()
        records[0][field_name] = ""
        result = _build(records=records)
        assert result.provenance_audit.gate_status == "blocked"
        assert code in _codes(result)
        assert result.observation_lineage_reference is None
        assert result.lineage_records == ()

    def test_missing_source_record_and_announcement_blocks(self):
        _, records, _ = _inputs()
        records[0]["source_record_id"] = ""
        records[0]["announcement_id"] = ""
        result = _build(records=records)
        assert "SOURCE_RECORD_REFERENCE_MISSING" in _codes(result)

    @pytest.mark.parametrize(
        ("path_type", "missing_field"),
        [("A", "upstream_calculation_reference"), ("B", "formula_reference")],
    )
    def test_missing_path_proof_blocks(self, path_type, missing_field):
        _, records, _ = _inputs()
        records[0]["path_type"] = path_type
        records[0][missing_field] = NOT_APPLICABLE
        result = _build(records=records)
        assert "PATH_PROOF_MISSING" in _codes(result)


class TestSnapshotAndHashes:
    def test_snapshot_fingerprint_is_recomputable(self):
        row = _build().lineage_records[0]
        assert row.source_snapshot_fingerprint == (
            compute_source_snapshot_fingerprint(
                row.source_provider,
                row.source_dataset,
                row.source_snapshot_id,
                row.source_as_of_version,
                SNAPSHOT_MANIFEST,
            )
        )

    def test_hash_canonicalization_is_mapping_order_independent(self):
        left = {"a": 1, "b": {"x": 2, "y": None}}
        right = {"b": {"y": None, "x": 2}, "a": 1}
        assert compute_source_input_hash(left) == compute_source_input_hash(
            right
        )

    def test_factor_value_hash_rejects_non_finite_and_boolean(self):
        with pytest.raises(ValueError):
            compute_factor_value_hash(float("nan"))
        with pytest.raises(TypeError):
            compute_factor_value_hash(True)

    def test_expected_source_input_hash_mismatch_blocks(self):
        _, records, _ = _inputs()
        records[0]["expected_source_input_hash"] = "0" * 64
        result = _build(records=records)
        assert "SOURCE_INPUT_HASH_MISMATCH" in _codes(result)
        assert result.provenance_audit.hash_mismatch_count >= 1

    def test_expected_factor_value_hash_mismatch_blocks(self):
        _, records, _ = _inputs()
        records[0]["expected_factor_value_hash"] = "0" * 64
        result = _build(records=records)
        assert "FACTOR_VALUE_HASH_MISMATCH" in _codes(result)

    def test_expected_snapshot_fingerprint_mismatch_blocks(self):
        _, records, _ = _inputs()
        records[0]["expected_source_snapshot_fingerprint"] = "0" * 64
        result = _build(records=records)
        assert "SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH" in _codes(result)

    def test_silent_snapshot_switch_blocks_entire_sidecar(self):
        _, records, _ = _inputs()
        records[1]["source_snapshot_id"] = "silent-newer-snapshot"
        result = _build(records=records)
        assert "SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH" in _codes(result)
        assert result.observation_lineage_reference is None

    def test_all_lineage_hashes_recompute(self):
        result = _build()
        _, records, config = _inputs()
        by_id = {item["source_record_id"]: item for item in records}
        for row in result.lineage_records:
            source = by_id[row.source_record_id]
            assert verify_lineage_hashes(
                row,
                source_input_payload=source["source_input_payload"],
                factor_value=source["factor_value"],
                configuration=config,
                source_snapshot_manifest=source[
                    "source_snapshot_manifest"
                ],
            ) == ()
            assert row.content_hash == recompute_lineage_content_hash(row)

    def test_source_input_tamper_is_detected(self):
        row = _build().lineage_records[0]
        _, records, config = _inputs()
        source = next(
            item for item in records
            if item["source_record_id"] == row.source_record_id
        )
        payload = copy.deepcopy(source["source_input_payload"])
        payload["raw_record"]["financial_value"] += 1
        issues = verify_lineage_hashes(
            row,
            source_input_payload=payload,
            factor_value=source["factor_value"],
            configuration=config,
            source_snapshot_manifest=source["source_snapshot_manifest"],
        )
        assert "SOURCE_INPUT_HASH_MISMATCH" in {
            item.code for item in issues
        }

    def test_factor_value_tamper_is_detected(self):
        row = _build().lineage_records[0]
        _, records, config = _inputs()
        source = next(
            item for item in records
            if item["source_record_id"] == row.source_record_id
        )
        issues = verify_lineage_hashes(
            row,
            source_input_payload=source["source_input_payload"],
            factor_value=source["factor_value"] + 0.01,
            configuration=config,
            source_snapshot_manifest=source["source_snapshot_manifest"],
        )
        assert "FACTOR_VALUE_HASH_MISMATCH" in {
            item.code for item in issues
        }

    def test_content_and_configuration_tamper_are_detected(self):
        row = _build().lineage_records[0]
        _, records, config = _inputs()
        source = next(
            item for item in records
            if item["source_record_id"] == row.source_record_id
        )
        tampered = replace(row, transformation_reference="changed")
        changed_config = {**config, "normalization": "changed"}
        issues = verify_lineage_hashes(
            tampered,
            source_input_payload=source["source_input_payload"],
            factor_value=source["factor_value"],
            configuration=changed_config,
            source_snapshot_manifest=source["source_snapshot_manifest"],
        )
        assert {"CONTENT_HASH_MISMATCH", "CONFIGURATION_HASH_MISMATCH"} <= {
            item.code for item in issues
        }

    def test_configuration_hash_binds_fin_r1a_versions(self):
        base = compute_configuration_hash(
            CONFIGURATION,
            timing_policy_version="policy-v1",
            trading_calendar_version="calendar-v1",
            timezone="Asia/Shanghai",
        )
        changed = compute_configuration_hash(
            CONFIGURATION,
            timing_policy_version="policy-v1",
            trading_calendar_version="calendar-v2",
            timezone="Asia/Shanghai",
        )
        assert base != changed


class TestRevisionConflictAndIsolation:
    def test_revision_chain_is_preserved(self):
        result = _build()
        revision = next(
            row for row in result.lineage_records
            if row.revision_version == "revision-2"
        )
        assert revision.supersedes_reference == "synthetic-record-001"
        assert revision.effective_date == "2024-01-09"

    def test_revision_before_effective_date_is_blocked(self):
        _, records, _ = _inputs()
        revision = next(
            item for item in records
            if item["revision_version"] == "revision-2"
        )
        revision["evaluation_date"] = "2024-01-08"
        result = _build(records=records)
        assert "FUTURE_REVISION_BACKFILL_DETECTED" in _codes(result)

    def test_broken_supersedes_reference_is_blocked(self):
        _, records, _ = _inputs()
        revision = next(
            item for item in records
            if item["revision_version"] == "revision-2"
        )
        revision["supersedes_reference"] = "missing-history"
        result = _build(records=records)
        assert "REVISION_CHAIN_BROKEN" in _codes(result)

    def test_missing_historical_version_cannot_be_backfilled(self):
        _, records, _ = _inputs()
        records = [
            item for item in records
            if item["source_record_id"] != "synthetic-record-001"
        ]
        result = _build(records=records)
        assert {"REVISION_CHAIN_BROKEN", "LINEAGE_REFERENCE_NOT_FOUND"} <= (
            _codes(result)
        )

    def test_old_version_after_revision_effective_date_is_blocked(self):
        _, records, _ = _inputs()
        original = next(
            item for item in records
            if item["source_record_id"] == "synthetic-record-001"
        )
        original["evaluation_date"] = "2024-01-09"
        result = _build(records=records)
        assert "FUTURE_REVISION_BACKFILL_DETECTED" in _codes(result)

    def test_multisource_conflict_is_not_silently_resolved(self):
        _, records, _ = _inputs()
        duplicate = copy.deepcopy(records[0])
        duplicate["source_provider"] = "synthetic-provider-two"
        duplicate["source_record_id"] = "synthetic-conflict-record"
        duplicate["timing_audit"] = replace(
            duplicate["timing_audit"],
            source_record_id="synthetic-conflict-record",
        )
        records.append(duplicate)
        result = _build(records=records)
        assert result.provenance_audit.gate_status == "blocked"
        assert "MULTISOURCE_CONFLICT" in _codes(result)
        assert result.provenance_audit.conflict_count >= 1
        assert result.observation_lineage_reference is None

    def test_cross_security_source_reference_is_blocked(self):
        _, records, _ = _inputs()
        second = next(item for item in records if item["code"] == "SYN002")
        second["source_record_id"] = "synthetic-record-001"
        result = _build(records=records)
        assert "CROSS_SECURITY_LINEAGE_DETECTED" in _codes(result)

    def test_similar_ids_remain_security_isolated(self):
        result = _build()
        first = result.observation_lineage_reference.lookup(
            "2024-01-08", "SYN001", result.lineage_records[0].factor_id
        )
        second = result.observation_lineage_reference.lookup(
            "2024-01-09", "SYN002", first.factor_id
        )
        assert first.code == "SYN001"
        assert second.code == "SYN002"
        assert first.lineage_id != second.lineage_id

    def test_timing_audit_mismatch_blocks_without_recomputing_date(self):
        _, records, _ = _inputs()
        records[0]["effective_date"] = "2024-01-09"
        result = _build(records=records)
        assert "PIT_TIMING_AUDIT_MISMATCH" in _codes(result)
        assert result.observation_lineage_reference is None


class TestLookupDeterminismAndSafety:
    def test_lookup_uses_frozen_public_key(self):
        result = _build()
        reference = result.observation_lineage_reference
        row = reference.lookup(
            "2024-01-09", "SYN002", "synthetic_financial_factor"
        )
        assert row.source_record_id == "synthetic-record-002"

    def test_missing_lookup_returns_stable_code(self):
        reference = _build().observation_lineage_reference
        with pytest.raises(LineageLookupError) as exc_info:
            reference.lookup(
                "2024-01-10", "MISSING", "synthetic_financial_factor"
            )
        assert exc_info.value.code == "LINEAGE_REFERENCE_NOT_FOUND"

    def test_same_input_repeats_identically(self):
        first = _build()
        second = _build()
        assert first.to_dict() == second.to_dict()
        assert first.provenance_audit.run_id == second.provenance_audit.run_id
        assert (
            first.observation_lineage_reference.content_hash
            == second.observation_lineage_reference.content_hash
        )

    def test_source_row_order_does_not_change_output(self):
        _, records, config = _inputs()
        forward = _build(records=records, configuration=config)
        reverse = _build(
            records=list(reversed(records)),
            configuration=config,
        )
        assert forward.to_dict() == reverse.to_dict()
        assert forward.lineage_records == reverse.lineage_records

    def test_top_level_future_labels_do_not_enter_lineage(self):
        _, records, config = _inputs()
        baseline = _build(records=records, configuration=config)
        for index, item in enumerate(records):
            item["future_label"] = 1000 + index
            item["forward_return"] = -999
        perturbed = _build(records=records, configuration=config)
        assert baseline.to_dict() == perturbed.to_dict()
        assert baseline.lineage_records == perturbed.lineage_records

    def test_future_label_inside_source_payload_blocks(self):
        _, records, _ = _inputs()
        records[0]["source_input_payload"]["future_return"] = 0.9
        result = _build(records=records)
        assert "FUTURE_LABEL_INPUT_NOT_ALLOWED" in _codes(result)

    def test_future_label_inside_configuration_blocks(self):
        _, records, config = _inputs()
        config["target"] = "future_return"
        result = _build(records=records, configuration=config)
        assert "FUTURE_LABEL_INPUT_NOT_ALLOWED" in _codes(result)

    def test_builder_does_not_mutate_inputs(self):
        batch, records, config = _inputs()
        before_records = copy.deepcopy(records)
        before_config = copy.deepcopy(config)
        before_frame = batch.get_frame()
        _build(records=records, configuration=config, batch=batch)
        assert records == before_records
        assert config == before_config
        assert batch.get_frame().equals(before_frame)

    def test_outputs_are_json_serializable(self):
        result = _build()
        json.dumps(result.to_dict(), sort_keys=True)
        json.dumps(
            result.observation_lineage_reference.to_dict(
                include_records=True
            ),
            sort_keys=True,
        )

    def test_module_contains_no_dynamic_execution_or_io_clients(self):
        module_path = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "amr"
            / "financial_lineage.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not {"eval", "exec", "compile"} & calls
        assert not {
            "requests",
            "httpx",
            "socket",
            "supabase",
            "sqlalchemy",
        } & imports
