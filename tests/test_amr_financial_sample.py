"""FIN-R1C tests for label-independent PIT sample formation."""

import ast
import copy
import json
import sys
import types
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest


# FIN-R1C is pure; avoid importing unrelated optional Flask routes when this
# test module is executed with the minimal factor-lab interpreter.
if "backend.amr" not in sys.modules:
    package = types.ModuleType("backend.amr")
    package.__path__ = [
        str(Path(__file__).resolve().parents[1] / "backend" / "amr")
    ]
    sys.modules["backend.amr"] = package

from backend.amr.financial_sample import (  # noqa: E402
    HASH_CONTRACT_VERSION,
    LABEL_JOIN_SCHEMA_VERSION,
    PAIRING_INDEX_FIELDS,
    SAMPLE_INDEX_FIELDS,
    SAMPLE_SCHEMA_VERSION,
    SampleErrorCode,
    SampleFormationConfig,
    SampleLookupError,
    ValidationTrack,
    compute_sample_fingerprint,
    form_financial_sample,
    recompute_pairing_content_hash,
    recompute_sample_content_hash,
)
from tests.fixtures.synthetic_financial_sample_cases import (  # noqa: E402
    make_synthetic_sample_inputs,
)


def _inputs():
    return make_synthetic_sample_inputs()


def _build(
    *,
    batch=None,
    lineage_reference=None,
    universe=None,
    labels=None,
    configuration=None,
):
    source_batch, source_lineage, source_universe, source_labels, source_config = (
        _inputs()
    )
    return form_financial_sample(
        batch if batch is not None else source_batch,
        (
            lineage_reference
            if lineage_reference is not None
            else source_lineage
        ),
        universe if universe is not None else source_universe,
        labels if labels is not None else source_labels,
        configuration=(
            configuration
            if configuration is not None
            else source_config
        ),
    )


def _codes(result):
    return {item.code for item in result.gate_result.errors}


def _coverage_map(result):
    return {
        (item.evaluation_date, item.validation_track): item
        for item in result.coverage_funnel
    }


class TestFrozenContract:
    def test_schema_keys_tracks_and_reason_codes_are_frozen(self):
        assert SAMPLE_SCHEMA_VERSION == "FinancialSampleFormation-v1.0"
        assert LABEL_JOIN_SCHEMA_VERSION == "FinancialLabelJoinAudit-v1.0"
        assert HASH_CONTRACT_VERSION == "FIN-R1C-HASH-v1.0"
        assert SAMPLE_INDEX_FIELDS == (
            "evaluation_date",
            "code",
            "factor_id",
        )
        assert PAIRING_INDEX_FIELDS == (
            "evaluation_date",
            "code",
            "factor_id",
            "validation_track",
        )
        assert tuple(item.value for item in ValidationTrack) == (
            "M",
            "F",
            "R",
        )
        assert {
            "INDEPENDENT_SAMPLE_DEFINITION_MISSING",
            "LABEL_TIME_LEAKAGE",
            "NON_CONSECUTIVE_FINANCIAL_TARGET",
        } <= {item.value for item in SampleErrorCode}

    def test_configuration_normalizes_dates_and_is_frozen(self):
        config = SampleFormationConfig(
            evaluation_dates=("2024-01-09", "2024-01-08"),
            evaluation_calendar_version="calendar-v1",
            universe_version="universe-v1",
            freshness_max_age_days=10,
        )
        assert config.evaluation_dates == ("2024-01-08", "2024-01-09")
        with pytest.raises(FrozenInstanceError):
            config.universe_version = "changed"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"evaluation_dates": ()},
            {"evaluation_dates": ("2024-01-08", "2024-01-08")},
            {"freshness_max_age_days": -1},
            {"supported_tracks": ("M",)},
        ],
    )
    def test_invalid_configuration_is_rejected(self, overrides):
        values = {
            "evaluation_dates": ("2024-01-08",),
            "evaluation_calendar_version": "calendar-v1",
            "universe_version": "universe-v1",
            "freshness_max_age_days": 10,
        }
        values.update(overrides)
        with pytest.raises(ValueError):
            SampleFormationConfig(**values)


class TestIndependentPITSample:
    def test_happy_path_publishes_sample_and_label_audits(self):
        result = _build()
        assert result.gate_result.overall_status == "ready"
        assert not result.gate_result.errors
        assert result.sample_reference is not None
        assert result.label_join_audit is not None
        assert result.sample_reference.row_count == 8
        assert result.label_join_audit.row_count == 24
        assert len(result.coverage_funnel) == 6
        assert len(result.coverage_content_hash) == 64
        assert result.gate_result.factor_sample_count == 3
        assert result.gate_result.valid_pair_count == 5

    def test_effective_date_is_respected_before_selection(self):
        result = _build()
        row = result.sample_reference.lookup(
            "2024-01-08", "SYN002", "synthetic_financial_factor"
        )
        assert row.pit_available is False
        assert row.factor_sample_mask is False
        assert "PIT_OBSERVATION_NOT_AVAILABLE" in (
            row.exclusion_reason_codes
        )

    def test_original_version_is_used_before_revision(self):
        result = _build()
        row = result.sample_reference.lookup(
            "2024-01-08", "SYN001", "synthetic_financial_factor"
        )
        assert row.raw_pit_factor_value == 1.25
        assert row.effective_date == "2024-01-08"
        assert row.financial_statement_version == "statement-original"

    def test_revision_is_used_only_from_new_effective_date(self):
        result = _build()
        row = result.sample_reference.lookup(
            "2024-01-09", "SYN001", "synthetic_financial_factor"
        )
        assert row.raw_pit_factor_value == 1.5
        assert row.effective_date == "2024-01-09"
        assert row.financial_statement_version == "statement-revision-2"

    def test_different_securities_do_not_share_values_or_lineage(self):
        result = _build()
        first = result.sample_reference.lookup(
            "2024-01-09", "SYN001", "synthetic_financial_factor"
        )
        second = result.sample_reference.lookup(
            "2024-01-09", "SYN002", "synthetic_financial_factor"
        )
        assert first.raw_pit_factor_value == 1.5
        assert second.raw_pit_factor_value == -0.5
        assert first.financial_lineage_id != second.financial_lineage_id

    def test_not_in_universe_is_audited_without_deleting_row(self):
        row = _build().sample_reference.lookup(
            "2024-01-08", "SYN003", "synthetic_financial_factor"
        )
        assert row.in_universe is False
        assert row.factor_sample_mask is False
        assert "SECURITY_NOT_IN_UNIVERSE" in row.exclusion_reason_codes

    def test_factor_applicability_precedes_labels(self):
        _, _, universe, _, _ = _inputs()
        target = next(
            item
            for item in universe
            if item["evaluation_date"] == "2024-01-08"
            and item["code"] == "SYN001"
        )
        target["factor_applicable"] = False
        row = _build(universe=universe).sample_reference.lookup(
            "2024-01-08", "SYN001", "synthetic_financial_factor"
        )
        assert row.pit_available is True
        assert row.factor_sample_mask is False
        assert "FACTOR_NOT_APPLICABLE" in row.exclusion_reason_codes

    def test_stale_observation_is_retained_but_masked(self):
        _, _, universe, _, config = _inputs()
        universe.append(
            {
                "evaluation_date": "2024-01-10",
                "code": "SYN001",
                "universe_record_id": "universe-20240110-SYN001",
                "in_universe": True,
                "factor_applicable": True,
                "listed_date": "2020-01-01",
                "delisted_date": None,
                "synthetic_test_only": True,
            }
        )
        config = replace(
            config,
            evaluation_dates=(
                "2024-01-08",
                "2024-01-09",
                "2024-01-10",
            ),
            freshness_max_age_days=0,
        )
        result = _build(
            universe=universe, labels=[], configuration=config
        )
        row = result.sample_reference.lookup(
            "2024-01-10", "SYN001", "synthetic_financial_factor"
        )
        assert row.financial_age_days == 1
        assert row.freshness_status == "stale"
        assert row.factor_sample_mask is False
        assert "STALE_FINANCIAL_OBSERVATION" in (
            row.exclusion_reason_codes
        )

    def test_every_available_sample_references_verified_r1b_lineage(self):
        result = _build()
        for row in result.sample_records:
            if row.pit_available:
                assert row.financial_lineage_id != "not_applicable"
                assert row.financial_lineage_content_hash != "not_applicable"
                assert row.factor_value_hash != "not_applicable"

    def test_sample_rows_and_hashes_are_immutable(self):
        result = _build()
        row = result.sample_records[0]
        assert row.content_hash == recompute_sample_content_hash(row)
        assert result.sample_reference.sample_fingerprint == (
            compute_sample_fingerprint(result.sample_records)
        )
        with pytest.raises(FrozenInstanceError):
            row.factor_sample_mask = False

    def test_sample_lookup_failure_has_stable_reason(self):
        with pytest.raises(SampleLookupError) as exc_info:
            _build().sample_reference.lookup(
                "2024-01-09", "MISSING", "synthetic_financial_factor"
            )
        assert exc_info.value.code == "OBSERVATION_LINEAGE_INCOMPLETE"


class TestIndependentUniverseGate:
    def test_empty_universe_blocks(self):
        result = _build(universe=[])
        assert result.gate_result.overall_status == "blocked"
        assert "INDEPENDENT_SAMPLE_DEFINITION_MISSING" in _codes(result)
        assert result.sample_reference is None

    def test_duplicate_universe_key_blocks(self):
        _, _, universe, _, _ = _inputs()
        universe.append(copy.deepcopy(universe[0]))
        result = _build(universe=universe)
        assert "DUPLICATE_UNIVERSE_KEY" in _codes(result)

    def test_missing_evaluation_date_universe_blocks(self):
        _, _, universe, _, _ = _inputs()
        universe = [
            item
            for item in universe
            if item["evaluation_date"] != "2024-01-09"
        ]
        result = _build(universe=universe)
        assert "INDEPENDENT_SAMPLE_DEFINITION_MISSING" in _codes(result)

    def test_unknown_evaluation_date_blocks(self):
        _, _, universe, _, _ = _inputs()
        extra = copy.deepcopy(universe[0])
        extra["evaluation_date"] = "2024-01-10"
        extra["universe_record_id"] = "extra-date-row"
        universe.append(extra)
        result = _build(universe=universe)
        assert "INDEPENDENT_SAMPLE_DEFINITION_MISSING" in _codes(result)

    def test_listing_boundary_conflict_blocks(self):
        _, _, universe, _, _ = _inputs()
        universe[0]["listed_date"] = "2024-01-09"
        result = _build(universe=universe)
        assert "INDEPENDENT_SAMPLE_DEFINITION_MISSING" in _codes(result)

    def test_missing_universe_identity_blocks(self):
        _, _, universe, _, _ = _inputs()
        universe[0]["universe_record_id"] = ""
        result = _build(universe=universe)
        assert "INDEPENDENT_SAMPLE_DEFINITION_MISSING" in _codes(result)

    def test_non_synthetic_universe_input_blocks(self):
        _, _, universe, _, _ = _inputs()
        universe[0]["synthetic_test_only"] = False
        result = _build(universe=universe)
        assert "INVALID_SAMPLE_INPUT" in _codes(result)


class TestProvenanceGate:
    def test_missing_selected_lineage_blocks(self):
        _, reference, _, _, _ = _inputs()
        records = tuple(
            item
            for item in reference.records
            if item.source_record_id != "synthetic-record-001"
        )
        broken = replace(reference, records=records, row_count=len(records))
        result = _build(lineage_reference=broken)
        assert "OBSERVATION_LINEAGE_INCOMPLETE" in _codes(result)
        assert result.sample_reference is None

    def test_tampered_lineage_content_blocks(self):
        _, reference, _, _, _ = _inputs()
        tampered = replace(
            reference.records[0], source_provider="tampered-provider"
        )
        broken = replace(
            reference,
            records=(tampered, *reference.records[1:]),
        )
        result = _build(lineage_reference=broken)
        assert "CONTENT_HASH_MISMATCH" in _codes(result)

    def test_duplicate_lineage_observation_key_blocks(self):
        _, reference, _, _, _ = _inputs()
        duplicate = reference.records[0]
        records = (*reference.records, duplicate)
        broken = replace(reference, records=records, row_count=len(records))
        result = _build(lineage_reference=broken)
        assert "PIT_SOURCE_VERSION_CONFLICT" in _codes(result)

    def test_lineage_row_count_mismatch_blocks(self):
        _, reference, _, _, _ = _inputs()
        broken = replace(reference, row_count=999)
        result = _build(lineage_reference=broken)
        assert "PIT_PROVENANCE_INCOMPLETE" in _codes(result)

    def test_factor_value_different_from_lineage_hash_blocks(self):
        batch, _, _, _, _ = _inputs()
        frame = batch.get_frame()
        frame.loc[
            (frame["code"] == "SYN001")
            & (frame["effective_date"] == "2024-01-08"),
            "factor_value",
        ] = 9.9
        changed_batch = replace(batch, _frame=frame)
        result = _build(batch=changed_batch)
        assert "CONTENT_HASH_MISMATCH" in _codes(result)


class TestLabelIsolation:
    def test_missing_labels_are_left_joined_not_row_filtered(self):
        result = _build(labels=[])
        assert result.gate_result.overall_status == "ready"
        assert len(result.sample_records) == 8
        assert len(result.pairing_records) == 24
        assert all(not item.label_available for item in result.pairing_records)
        assert all(not item.valid_pair_mask for item in result.pairing_records)

    def test_deleting_all_labels_does_not_change_factor_sample(self):
        baseline = _build()
        deleted = _build(labels=[])
        assert baseline.sample_records == deleted.sample_records
        assert (
            baseline.sample_reference.sample_fingerprint
            == deleted.sample_reference.sample_fingerprint
        )
        assert (
            baseline.sample_reference.content_hash
            == deleted.sample_reference.content_hash
        )

    def test_perturbing_labels_does_not_change_factor_sample(self):
        _, _, _, labels, _ = _inputs()
        baseline = _build(labels=labels)
        for item in labels:
            if item["validation_track"] == "M":
                item["label_value"] = 123.456
        perturbed = _build(labels=labels)
        assert baseline.sample_records == perturbed.sample_records
        assert (
            baseline.sample_reference.to_dict()
            == perturbed.sample_reference.to_dict()
        )

    def test_one_track_change_does_not_change_other_tracks(self):
        _, _, _, labels, _ = _inputs()
        baseline = _build(labels=labels)
        labels = [
            item for item in labels if item["validation_track"] != "M"
        ]
        changed = _build(labels=labels)
        baseline_other = tuple(
            item for item in baseline.pairing_records
            if item.validation_track in {"F", "R"}
        )
        changed_other = tuple(
            item for item in changed.pairing_records
            if item.validation_track in {"F", "R"}
        )
        assert baseline_other == changed_other
        assert baseline.sample_records == changed.sample_records

    def test_label_order_does_not_change_output(self):
        _, _, _, labels, _ = _inputs()
        forward = _build(labels=labels)
        reverse = _build(labels=list(reversed(labels)))
        assert forward.to_dict() == reverse.to_dict()
        assert forward.pairing_records == reverse.pairing_records

    def test_label_changes_do_not_change_prelabel_coverage_counts(self):
        baseline = _coverage_map(_build())
        no_labels = _coverage_map(_build(labels=[]))
        for key in baseline:
            assert (
                baseline[key].universe_count,
                baseline[key].pit_available_count,
                baseline[key].non_stale_count,
                baseline[key].valid_factor_count,
            ) == (
                no_labels[key].universe_count,
                no_labels[key].pit_available_count,
                no_labels[key].non_stale_count,
                no_labels[key].valid_factor_count,
            )

    def test_label_time_leakage_blocks(self):
        _, _, _, labels, _ = _inputs()
        labels[0]["label_publish_date"] = "2024-01-08"
        labels[0]["label_effective_date"] = "2024-01-08"
        labels[0]["label_available_at"] = "2024-01-08"
        result = _build(labels=labels)
        assert "LABEL_TIME_LEAKAGE" in _codes(result)
        assert result.sample_reference is None

    def test_nonconsecutive_financial_target_blocks(self):
        _, _, _, labels, _ = _inputs()
        financial = next(
            item for item in labels
            if item["validation_track"] == "F"
        )
        financial["target_report_period"] = "2024-03-31"
        result = _build(labels=labels)
        assert "NON_CONSECUTIVE_FINANCIAL_TARGET" in _codes(result)

    def test_duplicate_label_key_blocks(self):
        _, _, _, labels, _ = _inputs()
        duplicate = copy.deepcopy(labels[0])
        duplicate["label_id"] = "duplicate-label"
        labels.append(duplicate)
        result = _build(labels=labels)
        assert "DUPLICATE_LABEL_KEY" in _codes(result)

    def test_extra_right_side_label_is_warning_and_does_not_add_sample(self):
        _, _, _, labels, _ = _inputs()
        baseline = _build(labels=labels)
        extra = copy.deepcopy(labels[0])
        extra["code"] = "NOT-IN-UNIVERSE"
        extra["label_id"] = "extra-right-row"
        labels.append(extra)
        result = _build(labels=labels)
        assert result.gate_result.overall_status == "ready"
        assert "LABEL_REFERENCE_NOT_FOUND" in {
            item.code for item in result.gate_result.warnings
        }
        assert baseline.sample_records == result.sample_records

    def test_invalid_label_track_blocks(self):
        _, _, _, labels, _ = _inputs()
        labels[0]["validation_track"] = "X"
        result = _build(labels=labels)
        assert "INVALID_SAMPLE_INPUT" in _codes(result)

    def test_null_label_value_blocks(self):
        _, _, _, labels, _ = _inputs()
        labels[0]["label_value"] = None
        result = _build(labels=labels)
        assert "INVALID_SAMPLE_INPUT" in _codes(result)

    def test_non_synthetic_label_blocks(self):
        _, _, _, labels, _ = _inputs()
        labels[0]["synthetic_test_only"] = False
        result = _build(labels=labels)
        assert "INVALID_SAMPLE_INPUT" in _codes(result)

    def test_pairing_hashes_and_lookup_are_reproducible(self):
        result = _build()
        pairing = result.label_join_audit.lookup(
            "2024-01-08",
            "SYN001",
            "synthetic_financial_factor",
            "M",
        )
        assert pairing.valid_pair_mask is True
        assert pairing.content_hash == recompute_pairing_content_hash(
            pairing
        )

    def test_pairing_lookup_failure_has_stable_reason(self):
        with pytest.raises(SampleLookupError) as exc_info:
            _build().label_join_audit.lookup(
                "2024-01-08",
                "MISSING",
                "synthetic_financial_factor",
                "M",
            )
        assert exc_info.value.code == "LABEL_REFERENCE_NOT_FOUND"


class TestCoverageDeterminismAndSafety:
    def test_coverage_funnel_counts_are_monotone(self):
        for item in _build().coverage_funnel:
            assert (
                item.universe_count
                >= item.pit_available_count
                >= item.non_stale_count
                >= item.valid_factor_count
                >= item.valid_pair_count
            )

    def test_expected_synthetic_coverage_is_auditable(self):
        coverage = _coverage_map(_build())
        first_m = coverage[("2024-01-08", "M")]
        second_m = coverage[("2024-01-09", "M")]
        assert (
            first_m.universe_count,
            first_m.pit_available_count,
            first_m.valid_factor_count,
            first_m.label_available_count,
            first_m.valid_pair_count,
        ) == (3, 1, 1, 1, 1)
        assert (
            second_m.universe_count,
            second_m.pit_available_count,
            second_m.valid_factor_count,
            second_m.label_available_count,
            second_m.valid_pair_count,
        ) == (3, 2, 2, 2, 2)

    def test_same_input_repeats_identically(self):
        first = _build()
        second = _build()
        assert first.to_dict() == second.to_dict()
        assert first.sample_records == second.sample_records
        assert first.pairing_records == second.pairing_records

    def test_universe_row_order_does_not_change_output(self):
        _, _, universe, _, _ = _inputs()
        forward = _build(universe=universe)
        reverse = _build(universe=list(reversed(universe)))
        assert forward.to_dict() == reverse.to_dict()
        assert forward.sample_records == reverse.sample_records

    def test_inputs_are_not_mutated(self):
        batch, lineage, universe, labels, config = _inputs()
        before_frame = batch.get_frame()
        before_lineage = copy.deepcopy(lineage)
        before_universe = copy.deepcopy(universe)
        before_labels = copy.deepcopy(labels)
        before_config = copy.deepcopy(config)
        _build(
            batch=batch,
            lineage_reference=lineage,
            universe=universe,
            labels=labels,
            configuration=config,
        )
        assert batch.get_frame().equals(before_frame)
        assert lineage == before_lineage
        assert universe == before_universe
        assert labels == before_labels
        assert config == before_config

    def test_outputs_are_json_serializable(self):
        result = _build()
        json.dumps(result.to_dict(), sort_keys=True)
        json.dumps(
            result.sample_reference.to_dict(include_records=True),
            sort_keys=True,
        )
        json.dumps(
            result.label_join_audit.to_dict(include_records=True),
            sort_keys=True,
        )

    def test_module_contains_no_dynamic_execution_or_io_clients(self):
        module_path = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "amr"
            / "financial_sample.py"
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
