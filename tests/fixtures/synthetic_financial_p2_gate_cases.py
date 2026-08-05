"""Deterministic synthetic evidence bundle for FIN-P2-GATE."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any, Mapping, Sequence

from backend.amr.financial_p2_gate import (
    GATE_OUTPUT_ANCHORS,
    GATE_PRODUCTION_STATUS,
    GATE_RESEARCH_ASSESSMENT,
    GATE_TASK_IDS,
    PRODUCTION_GATE_IDS,
    FinancialP2GateBatch,
    FinancialP2GateConfig,
    FinancialP2GateEvidence,
    compute_research_log_fingerprint,
)


EXECUTION_TIMESTAMP = "2026-07-31T11:15:00+08:00"


_WARNINGS = {
    "FIN-P2-M-ENH": {
        "SYNTHETIC_RESEARCH_ONLY": (
            "M enhancement is deterministic synthetic research evidence."
        ),
        "DETACHED_UNCOMMITTED_WORKSPACE": (
            "The isolated detached workspace is intentional and not "
            "production deployment."
        ),
    },
    "FIN-P2-F": {
        "SYNTHETIC_SUPPORTING_ONLY": (
            "F is supporting evidence and not a business forecast promise."
        ),
        "EXPERIMENTAL_TARGETS": (
            "All four forecast targets remain experimental."
        ),
    },
    "FIN-P2-R": {
        "SYNTHETIC_RISK_SCREEN_ONLY": (
            "R ranks review priority and is not a fraud determination."
        ),
        "SYNTHETIC_PERFECT_SEPARATION": (
            "Perfect separation is fixture behavior, not empirical evidence."
        ),
    },
    "FIN-P2-INDEP": {
        "SYNTHETIC_RESEARCH_ONLY": (
            "Independence evidence is synthetic and exploratory."
        ),
        "OOS_FDR_DEFERRED": (
            "This source warning is retained; OOS/FDR is supplied by the "
            "accepted downstream task."
        ),
    },
    "FIN-P2-OOS-FDR": {
        "SYNTHETIC_OOS_ONLY": (
            "OOS/FDR evidence validates only the synthetic contract."
        ),
        "FAILED_RUNS_RETAINED": (
            "Three failed runs remain in their frozen family denominators."
        ),
        "ROBUSTNESS_FAMILY_NOT_NAMED": (
            "The unnamed robustness family remains explicitly not_run."
        ),
        "FDR_NOT_ADMISSION": (
            "Raw p-values and BH rejections do not create admission."
        ),
    },
}


def make_evidence_records(
    changes: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[FinancialP2GateEvidence, ...]:
    changes = dict(changes or {})
    records = []
    for task_id in GATE_TASK_IDS:
        warnings = _WARNINGS[task_id]
        retained = {
            "FIN-P2-M-ENH": 3,
            "FIN-P2-F": 4,
            "FIN-P2-R": 120,
            "FIN-P2-INDEP": 3,
            "FIN-P2-OOS-FDR": 23,
        }[task_id]
        failed = 3 if task_id == "FIN-P2-OOS-FDR" else 0
        metadata = (
            {
                "registered_hypothesis_count": 23,
                "completed_run_count": 20,
                "failed_run_count": 3,
                "failed_runs_count_in_family_denominator": True,
                "robustness_family_status": "not_run",
                "test_use_policy":
                    "latest_20pct_one_shot_read_only",
            }
            if task_id == "FIN-P2-OOS-FDR"
            else {
                "evidence_scope": task_id,
                "accepted_synthetic_contract": True,
            }
        )
        record = FinancialP2GateEvidence(
            task_id=task_id,
            status="ACCEPTED",
            output_fingerprint=GATE_OUTPUT_ANCHORS[task_id],
            research_assessment=GATE_RESEARCH_ASSESSMENT,
            production_status=GATE_PRODUCTION_STATUS,
            synthetic_test_only=True,
            warning_codes=tuple(warnings),
            warning_explanations=warnings,
            research_log_entry_status="completed",
            retained_run_count=retained,
            failed_run_count=failed,
            failed_runs_retained=True,
            metadata=metadata,
        )
        if task_id in changes:
            record = replace(record, **dict(changes[task_id]))
        records.append(record)
    return tuple(records)


def make_batch(
    *,
    records: Sequence[FinancialP2GateEvidence] | None = None,
    research_log_snapshot_status: str = "archived_in_result",
    declared_research_log_fingerprint: str | None = None,
    production_gate_claims: Mapping[str, bool] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> FinancialP2GateBatch:
    frozen_records = tuple(
        make_evidence_records() if records is None else records
    )
    return FinancialP2GateBatch(
        batch_id="synthetic-financial-p2-gate",
        version="v1",
        evidence_records=frozen_records,
        research_log_snapshot_status=
            research_log_snapshot_status,
        declared_research_log_fingerprint=(
            compute_research_log_fingerprint(frozen_records)
            if declared_research_log_fingerprint is None
            else declared_research_log_fingerprint
        ),
        production_gate_claims=(
            {gate_id: False for gate_id in PRODUCTION_GATE_IDS}
            if production_gate_claims is None
            else copy.deepcopy(dict(production_gate_claims))
        ),
        provenance=(
            {
                "synthetic_test_only": True,
                "formal_persistence_performed": False,
                "evidence_registry": "FIN-P2-GATE-v1",
            }
            if provenance is None
            else copy.deepcopy(dict(provenance))
        ),
    )


def make_configuration(
    **changes: Any,
) -> FinancialP2GateConfig:
    values = {"execution_timestamp": EXECUTION_TIMESTAMP}
    values.update(changes)
    return FinancialP2GateConfig(**values)
