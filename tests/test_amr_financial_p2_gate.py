"""Acceptance tests for FIN-P2-GATE."""

from __future__ import annotations

import json

import pytest

from backend.amr.financial_p2_gate import (
    CHECK_SOURCE_TASKS,
    GATE_ADMISSION_STATUS,
    GATE_CHECK_IDS,
    GATE_CONCLUSION_BOUNDARY,
    GATE_OUTPUT_ANCHORS,
    GATE_PRODUCTION_STATUS,
    GATE_RESEARCH_ASSESSMENT,
    GATE_TASK_IDS,
    PRODUCTION_GATE_IDS,
    FinancialP2GateBatch,
    FinancialP2GateConfig,
    FinancialP2GateEvidence,
    compute_research_log_fingerprint,
    evaluate_financial_p2_gate,
)
from tests.fixtures.synthetic_financial_p2_gate_cases import (
    EXECUTION_TIMESTAMP,
    make_batch,
    make_configuration,
    make_evidence_records,
)


@pytest.fixture(scope="module")
def golden():
    return evaluate_financial_p2_gate(
        make_batch(),
        configuration=make_configuration(),
    )


def _error_codes(result) -> set[str]:
    return {item.code for item in result.gate_audit.errors}


def _evaluate(
    *,
    records=None,
    research_log_snapshot_status="archived_in_result",
    declared_research_log_fingerprint=None,
    production_gate_claims=None,
    provenance=None,
):
    return evaluate_financial_p2_gate(
        make_batch(
            records=records,
            research_log_snapshot_status=
                research_log_snapshot_status,
            declared_research_log_fingerprint=
                declared_research_log_fingerprint,
            production_gate_claims=production_gate_claims,
            provenance=provenance,
        ),
        configuration=make_configuration(),
    )


class TestFrozenPolicy:
    def test_exact_predecessor_tasks_and_anchors(self):
        assert GATE_TASK_IDS == (
            "FIN-P2-M-ENH",
            "FIN-P2-F",
            "FIN-P2-R",
            "FIN-P2-INDEP",
            "FIN-P2-OOS-FDR",
        )
        assert set(GATE_OUTPUT_ANCHORS) == set(GATE_TASK_IDS)
        for value in GATE_OUTPUT_ANCHORS.values():
            assert len(value) == 64
            int(value, 16)

    def test_exact_fin_28_checks(self):
        assert GATE_CHECK_IDS == (
            "pit_audit",
            "data_quality",
            "coverage_thresholds",
            "ic_evidence",
            "grouped_evidence",
            "direction_evidence",
            "independence_evidence",
            "robustness_evidence",
            "oos_evidence",
            "research_log_archived",
            "warnings_explained",
        )
        assert set(CHECK_SOURCE_TASKS) == set(GATE_CHECK_IDS)

    def test_exact_four_production_gates(self):
        assert PRODUCTION_GATE_IDS == (
            "independent_label_or_evidence_review",
            "real_time_data_contract_and_authorization",
            "pit_correct_versions_and_historical_universe",
            "net_of_cost_oos_significance_and_reproducibility",
        )

    def test_configuration_freezes_non_admission_policy(self):
        config = make_configuration()
        assert config.effect_threshold_gate_allowed is False
        assert config.automatic_admission_allowed is False
        assert (
            config.synthetic_empirical_conclusion_allowed is False
        )
        assert config.formal_persistence_authorized is False
        assert config.required_research_assessment == "exploratory"
        assert config.required_production_status == (
            "not production ready"
        )
        assert config.required_admission_status == "not_assessed"

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("required_task_ids", ("FIN-P2-OOS-FDR",)),
            ("required_check_ids", ("pit_audit",)),
            ("production_gate_ids", ("fake",)),
            ("effect_threshold_gate_allowed", True),
            ("automatic_admission_allowed", True),
            ("synthetic_empirical_conclusion_allowed", True),
            ("formal_persistence_authorized", True),
            ("required_research_assessment", "supportive"),
            ("required_production_status", "research usable"),
            ("required_admission_status", "admitted"),
            ("policy_version", "drift"),
            ("schema_version", "drift"),
        ],
    )
    def test_configuration_rejects_policy_drift(
        self,
        field_name,
        value,
    ):
        with pytest.raises(ValueError):
            make_configuration(**{field_name: value})

    def test_execution_timestamp_must_be_iso(self):
        with pytest.raises(ValueError):
            FinancialP2GateConfig(
                execution_timestamp="not-a-time"
            )


class TestGoldenGate:
    def test_gate_ready_and_integrity_complete(self, golden):
        audit = golden.gate_audit
        assert audit.gate_status == "ready"
        assert audit.errors == ()
        assert audit.research_integrity_status == "complete"
        assert audit.satisfied_check_count == 11
        assert audit.required_check_count == 11

    def test_every_fin_28_check_is_satisfied(self, golden):
        assert tuple(
            item.check_id for item in golden.integrity_checks
        ) == GATE_CHECK_IDS
        assert all(
            item.check_status == "satisfied"
            for item in golden.integrity_checks
        )
        assert all(
            item.reason_code is None
            for item in golden.integrity_checks
        )

    @pytest.mark.parametrize("check_id", GATE_CHECK_IDS)
    def test_check_sources_are_frozen(self, golden, check_id):
        item = golden.get_check(check_id)
        assert item.source_task_ids == CHECK_SOURCE_TASKS[check_id]

    def test_production_gates_remain_unsatisfied(self, golden):
        audit = golden.gate_audit
        assert audit.production_gate_satisfied_count == 0
        assert audit.production_gate_count == 4
        assert tuple(
            item.production_gate_id
            for item in golden.production_gates
        ) == PRODUCTION_GATE_IDS
        assert all(
            item.gate_status == "not_satisfied"
            for item in golden.production_gates
        )
        assert all(
            item.reason_code and item.detail
            for item in golden.production_gates
        )

    def test_research_production_and_admission_are_separate(
        self,
        golden,
    ):
        audit = golden.gate_audit
        assert audit.research_assessment == GATE_RESEARCH_ASSESSMENT
        assert audit.production_status == GATE_PRODUCTION_STATUS
        assert audit.admission_status == GATE_ADMISSION_STATUS
        assert audit.effect_threshold_gate_used is False
        assert audit.formal_persistence_performed is False

    def test_research_log_has_one_entry_per_predecessor(self, golden):
        assert tuple(
            item.task_id for item in golden.research_log_entries
        ) == GATE_TASK_IDS
        assert all(
            item.archive_scope == "in_result_snapshot_only"
            for item in golden.research_log_entries
        )
        assert all(
            item.source_status == "ACCEPTED"
            for item in golden.research_log_entries
        )

    def test_failed_oos_runs_remain_visible(self, golden):
        oos = next(
            item
            for item in golden.research_log_entries
            if item.task_id == "FIN-P2-OOS-FDR"
        )
        assert oos.retained_run_count == 23
        assert oos.failed_run_count == 3
        assert oos.failed_runs_retained is True

    def test_all_gate_warnings_are_explicit(self, golden):
        assert {
            item.code for item in golden.gate_audit.warnings
        } == {
            "SYNTHETIC_RESEARCH_ONLY",
            "PRODUCTION_GATES_INCOMPLETE",
            "RESULT_NOT_ADMISSION",
            "IN_RESULT_LOG_ONLY",
        }

    def test_conclusion_boundary_is_safe(self, golden):
        audit = golden.gate_audit
        assert audit.conclusion_boundary == GATE_CONCLUSION_BOUNDARY
        assert "not an empirical market conclusion" in (
            audit.conclusion_boundary
        )
        assert audit.synthetic_test_only is True

    def test_output_contains_no_formal_admission_state(self, golden):
        serialized = json.dumps(
            golden.to_dict(),
            sort_keys=True,
        )
        forbidden_values = (
            '"gate_status": "passed"',
            '"gate_status": "conditionally_passed"',
            '"gate_status": "rejected"',
            '"admission_status": "admitted"',
            '"production_status": "research usable"',
        )
        for value in forbidden_values:
            assert value not in serialized

    def test_hashes_are_sha256(self, golden):
        audit = golden.gate_audit
        values = (
            audit.input_fingerprint,
            audit.predecessor_anchor_fingerprint,
            audit.research_log_fingerprint,
            audit.output_fingerprint,
            audit.content_hash,
        )
        for value in values:
            assert len(value) == 64
            int(value, 16)
        for item in golden.integrity_checks:
            assert len(item.content_hash) == 64
        for item in golden.production_gates:
            assert len(item.content_hash) == 64
        for item in golden.research_log_entries:
            assert len(item.content_hash) == 64


class TestIncompleteButValid:
    def test_unarchived_log_is_ready_but_incomplete(self):
        result = _evaluate(
            research_log_snapshot_status="not_archived"
        )
        assert result.gate_audit.gate_status == "ready"
        assert result.gate_audit.research_integrity_status == (
            "incomplete"
        )
        check = result.get_check("research_log_archived")
        assert check.check_status == "not_satisfied"
        assert check.reason_code == "RESEARCH_LOG_NOT_ARCHIVED"
        assert result.gate_audit.satisfied_check_count == 10

    def test_incomplete_warning_explanation_is_not_hidden(self):
        records = make_evidence_records(
            {
                "FIN-P2-F": {
                    "warning_explanations": {
                        "SYNTHETIC_SUPPORTING_ONLY": (
                            "Still synthetic."
                        )
                    }
                }
            }
        )
        result = _evaluate(records=records)
        assert result.gate_audit.gate_status == "ready"
        assert result.gate_audit.research_integrity_status == (
            "incomplete"
        )
        check = result.get_check("warnings_explained")
        assert check.check_status == "not_satisfied"
        assert check.reason_code == (
            "WARNING_EXPLANATION_INCOMPLETE"
        )

    def test_empty_warning_explanation_is_incomplete(self):
        records = make_evidence_records(
            {
                "FIN-P2-R": {
                    "warning_explanations": {
                        "SYNTHETIC_RISK_SCREEN_ONLY": "",
                        "SYNTHETIC_PERFECT_SEPARATION": "explained",
                    }
                }
            }
        )
        result = _evaluate(records=records)
        assert result.get_check(
            "warnings_explained"
        ).check_status == "not_satisfied"


class TestFailClosedAnchors:
    def test_missing_predecessor_blocks(self):
        records = make_evidence_records()[:-1]
        result = _evaluate(records=records)
        assert result.gate_audit.gate_status == "blocked"
        assert "MISSING_TASK" in _error_codes(result)

    def test_duplicate_predecessor_blocks(self):
        records = make_evidence_records()
        result = _evaluate(records=records + (records[0],))
        assert "DUPLICATE_TASK_ID" in _error_codes(result)

    def test_unknown_predecessor_blocks(self):
        records = list(make_evidence_records())
        first = records[0]
        records[0] = FinancialP2GateEvidence(
            **{
                **first.to_dict(),
                "task_id": "UNKNOWN",
            }
        )
        result = _evaluate(records=records)
        assert "UNKNOWN_TASK" in _error_codes(result)
        assert "MISSING_TASK" in _error_codes(result)

    @pytest.mark.parametrize("task_id", GATE_TASK_IDS)
    def test_nonaccepted_predecessor_blocks(self, task_id):
        records = make_evidence_records(
            {task_id: {"status": "PENDING"}}
        )
        result = _evaluate(records=records)
        assert "PREDECESSOR_NOT_ACCEPTED" in _error_codes(result)

    @pytest.mark.parametrize("task_id", GATE_TASK_IDS)
    def test_wrong_output_anchor_blocks(self, task_id):
        records = make_evidence_records(
            {task_id: {"output_fingerprint": "0" * 64}}
        )
        result = _evaluate(records=records)
        assert "OUTPUT_ANCHOR_MISMATCH" in _error_codes(result)

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("research_assessment", "supportive"),
            ("production_status", "research usable"),
            ("synthetic_test_only", False),
        ],
    )
    def test_predecessor_boundary_drift_blocks(
        self,
        field_name,
        value,
    ):
        records = make_evidence_records(
            {"FIN-P2-M-ENH": {field_name: value}}
        )
        result = _evaluate(records=records)
        assert "INVALID_RESEARCH_BOUNDARY" in _error_codes(result)

    def test_removed_failed_run_blocks(self):
        records = make_evidence_records(
            {
                "FIN-P2-OOS-FDR": {
                    "failed_runs_retained": False
                }
            }
        )
        result = _evaluate(records=records)
        assert "INVALID_RESEARCH_BOUNDARY" in _error_codes(result)

    @pytest.mark.parametrize(
        ("metadata_key", "value"),
        [
            ("registered_hypothesis_count", 22),
            ("completed_run_count", 23),
            ("failed_run_count", 0),
            (
                "failed_runs_count_in_family_denominator",
                False,
            ),
            ("robustness_family_status", "completed"),
            ("test_use_policy", "reusable"),
        ],
    )
    def test_oos_contract_drift_blocks(
        self,
        metadata_key,
        value,
    ):
        records = list(make_evidence_records())
        index = GATE_TASK_IDS.index("FIN-P2-OOS-FDR")
        metadata = dict(records[index].metadata)
        metadata[metadata_key] = value
        records[index] = FinancialP2GateEvidence(
            **{
                **records[index].to_dict(),
                "metadata": metadata,
            }
        )
        result = _evaluate(records=records)
        assert "INVALID_EVIDENCE_SET" in _error_codes(result)

    def test_wrong_research_log_fingerprint_blocks(self):
        result = _evaluate(
            declared_research_log_fingerprint="0" * 64
        )
        assert (
            "INVALID_RESEARCH_LOG_FINGERPRINT"
            in _error_codes(result)
        )

    def test_non_synthetic_batch_blocks(self):
        result = _evaluate(
            provenance={
                "synthetic_test_only": False,
                "formal_persistence_performed": False,
            }
        )
        assert "NON_SYNTHETIC_INPUT" in _error_codes(result)

    def test_formal_persistence_claim_blocks(self):
        result = _evaluate(
            provenance={
                "synthetic_test_only": True,
                "formal_persistence_performed": True,
            }
        )
        assert "INVALID_RESEARCH_BOUNDARY" in _error_codes(result)

    @pytest.mark.parametrize(
        "field_name",
        [
            "admission_decision",
            "factor_admitted",
            "passed",
            "conditionally_passed",
            "rejected",
        ],
    )
    def test_admission_like_input_field_blocks(self, field_name):
        result = _evaluate(
            provenance={
                "synthetic_test_only": True,
                "formal_persistence_performed": False,
                field_name: True,
            }
        )
        assert "FORBIDDEN_ADMISSION_FIELD" in _error_codes(result)

    @pytest.mark.parametrize("gate_id", PRODUCTION_GATE_IDS)
    def test_synthetic_production_claim_blocks(self, gate_id):
        claims = {
            value: value == gate_id
            for value in PRODUCTION_GATE_IDS
        }
        result = _evaluate(production_gate_claims=claims)
        assert (
            "UNAUTHORIZED_PRODUCTION_CLAIM"
            in _error_codes(result)
        )

    def test_production_claims_require_exact_four_keys(self):
        with pytest.raises(ValueError):
            make_batch(production_gate_claims={})

    def test_blocked_result_retains_all_check_slots(self):
        result = _evaluate(
            declared_research_log_fingerprint="0" * 64
        )
        assert len(result.integrity_checks) == 11
        assert all(
            item.check_status == "not_satisfied"
            for item in result.integrity_checks
        )
        assert result.research_log_entries == ()
        assert result.gate_audit.production_status == (
            "not production ready"
        )


class TestDeterminismAndImmutability:
    def test_repeated_run_is_identical(self, golden):
        repeated = _evaluate()
        assert repeated.to_dict() == golden.to_dict()

    def test_record_order_is_irrelevant(self, golden):
        reversed_records = tuple(reversed(make_evidence_records()))
        result = _evaluate(records=reversed_records)
        assert result.to_dict() == golden.to_dict()

    def test_batch_defensively_copies_external_mappings(self, golden):
        claims = {key: False for key in PRODUCTION_GATE_IDS}
        provenance = {
            "synthetic_test_only": True,
            "formal_persistence_performed": False,
            "evidence_registry": "FIN-P2-GATE-v1",
        }
        batch = make_batch(
            production_gate_claims=claims,
            provenance=provenance,
        )
        claims[PRODUCTION_GATE_IDS[0]] = True
        provenance["synthetic_test_only"] = False
        result = evaluate_financial_p2_gate(
            batch,
            configuration=make_configuration(),
        )
        assert result.to_dict() == golden.to_dict()
        returned = batch.get_production_gate_claims()
        returned[PRODUCTION_GATE_IDS[0]] = True
        assert not any(
            batch.get_production_gate_claims().values()
        )

    def test_research_log_fingerprint_is_order_invariant(self):
        records = make_evidence_records()
        assert compute_research_log_fingerprint(records) == (
            compute_research_log_fingerprint(tuple(reversed(records)))
        )

    def test_result_lookup_rejects_unknown_key(self, golden):
        with pytest.raises(LookupError):
            golden.get_check("UNKNOWN")
        with pytest.raises(LookupError):
            golden.get_production_gate("UNKNOWN")

    def test_wrong_batch_or_configuration_type_rejected(self):
        with pytest.raises(TypeError):
            evaluate_financial_p2_gate(
                object(),
                configuration=make_configuration(),
            )
        with pytest.raises(TypeError):
            evaluate_financial_p2_gate(
                make_batch(),
                configuration=object(),
            )

    def test_evidence_output_fingerprint_requires_sha(self):
        record = make_evidence_records()[0]
        with pytest.raises(ValueError):
            FinancialP2GateEvidence(
                **{
                    **record.to_dict(),
                    "output_fingerprint": "bad",
                }
            )

    def test_batch_log_fingerprint_requires_sha(self):
        with pytest.raises(ValueError):
            FinancialP2GateBatch(
                batch_id="x",
                version="v1",
                evidence_records=make_evidence_records(),
                research_log_snapshot_status="archived_in_result",
                declared_research_log_fingerprint="bad",
                production_gate_claims={
                    key: False for key in PRODUCTION_GATE_IDS
                },
                provenance={"synthetic_test_only": True},
            )
