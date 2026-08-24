"""Strict discriminated contracts for independent financial M/F/R evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .financial_fingerprint import canonicalize_financial_fingerprint
from .financial_p2_f_evidence import P2_F_SCHEMA_VERSION, FinancialP2FEvidenceResult
from .financial_p2_m_enhancement import (
    P2_M_SCHEMA_VERSION,
    FinancialP2MEnhancementResult,
)
from .financial_p2_r_evidence import R_SCHEMA_VERSION, FinancialP2REvidenceResult


class FinancialEvidenceType(str, Enum):
    M = "M"
    F = "F"
    R = "R"


_TYPE_TO_CLASS = {
    FinancialEvidenceType.M: FinancialP2MEnhancementResult,
    FinancialEvidenceType.F: FinancialP2FEvidenceResult,
    FinancialEvidenceType.R: FinancialP2REvidenceResult,
}
_TYPE_TO_SCHEMA = {
    FinancialEvidenceType.M: P2_M_SCHEMA_VERSION,
    FinancialEvidenceType.F: P2_F_SCHEMA_VERSION,
    FinancialEvidenceType.R: R_SCHEMA_VERSION,
}


def serialize_financial_evidence(
    payload: Any, evidence_type: FinancialEvidenceType | str
) -> dict[str, Any]:
    kind = FinancialEvidenceType(evidence_type)
    expected = _TYPE_TO_CLASS[kind]
    if type(payload) is not expected:
        raise TypeError(f"evidence_type={kind.value} requires {expected.__name__}")
    body = payload.to_dict()
    return {
        "evidence_type": kind.value,
        "schema_version": _TYPE_TO_SCHEMA[kind],
        "content_hash": financial_evidence_content_hash(payload, kind),
        "payload": body,
    }


def financial_evidence_content_hash(
    payload: Any, evidence_type: FinancialEvidenceType | str
) -> str:
    kind = FinancialEvidenceType(evidence_type)
    expected = _TYPE_TO_CLASS[kind]
    if type(payload) is not expected:
        raise TypeError(f"evidence_type={kind.value} requires {expected.__name__}")
    canonical = json.dumps(
        {
            "evidence_type": kind.value,
            "schema_version": _TYPE_TO_SCHEMA[kind],
            "payload": payload.to_dict(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FinancialP2ResultReference:
    evidence_id: str
    evidence_type: str
    schema_version: str
    status: str
    content_hash: str
    audit_ref: str

    def __post_init__(self) -> None:
        FinancialEvidenceType(self.evidence_type)
        if len(self.content_hash) != 64 or any(
            c not in "0123456789abcdef" for c in self.content_hash
        ):
            raise ValueError("content_hash must be lowercase SHA-256")

    def to_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class FinancialP2EvidenceGateSummary:
    references: tuple[FinancialP2ResultReference, ...]
    schema_version: str = "FinancialP2EvidenceGateSummary-v1.0"

    def __post_init__(self) -> None:
        kinds = tuple(item.evidence_type for item in self.references)
        if len(kinds) != len(set(kinds)):
            raise ValueError("gate may reference each evidence_type at most once")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "references": [item.to_dict() for item in self.references],
        }


@dataclass(frozen=True)
class FinancialEvidenceStageLog:
    evidence_type: str
    execution_stage: str
    status: str
    reason: str | None
    content_hash: str | None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class FinancialEvidenceGateExecution:
    gate_status: str
    admission_allowed: bool
    archive_allowed: bool
    summary: FinancialP2EvidenceGateSummary
    stage_logs: tuple[FinancialEvidenceStageLog, ...]
    schema_version: str = "FinancialEvidenceGateExecution-v1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gate_status": self.gate_status,
            "admission_allowed": self.admission_allowed,
            "archive_allowed": self.archive_allowed,
            "summary": self.summary.to_dict(),
            "stage_logs": [item.to_dict() for item in self.stage_logs],
        }


def execute_financial_evidence_gate(
    *,
    m_result: FinancialP2MEnhancementResult,
    f_result: FinancialP2FEvidenceResult,
    r_result: FinancialP2REvidenceResult,
) -> FinancialEvidenceGateExecution:
    """Bind real M/F/R execution results to a fail-closed archive gate."""
    supplied = (
        (FinancialEvidenceType.M, m_result, "M_EVALUATION"),
        (FinancialEvidenceType.F, f_result, "F_FORECAST"),
        (FinancialEvidenceType.R, r_result, "R_RISK_EVALUATION"),
    )
    references: list[FinancialP2ResultReference] = []
    logs: list[FinancialEvidenceStageLog] = []
    all_ready = True
    for kind, result, stage in supplied:
        serialized = serialize_financial_evidence(result, kind)
        status, reason = _result_gate_status(result)
        ready = status in {"ready", "accepted", "completed"}
        all_ready = all_ready and ready
        digest = serialized["content_hash"]
        references.append(
            FinancialP2ResultReference(
                evidence_id=f"financial-evidence-{kind.value.lower()}-{digest[:16]}",
                evidence_type=kind.value,
                schema_version=serialized["schema_version"],
                status=status,
                content_hash=digest,
                audit_ref=f"payload://{kind.value}/{digest}",
            )
        )
        logs.append(
            FinancialEvidenceStageLog(
                evidence_type=kind.value,
                execution_stage=stage,
                status=status,
                reason=reason,
                content_hash=digest,
            )
        )
    summary = FinancialP2EvidenceGateSummary(tuple(references))
    return FinancialEvidenceGateExecution(
        gate_status="ready" if all_ready else "blocked",
        admission_allowed=all_ready,
        archive_allowed=all_ready,
        summary=summary,
        stage_logs=tuple(logs),
    )


def serialize_financial_evidence_gate_execution(
    execution: FinancialEvidenceGateExecution,
) -> str:
    if not isinstance(execution, FinancialEvidenceGateExecution):
        raise TypeError("execution must be FinancialEvidenceGateExecution")
    return json.dumps(
        canonicalize_financial_fingerprint(execution.to_dict()),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def deserialize_financial_evidence_gate_execution(
    serialized: str,
) -> FinancialEvidenceGateExecution:
    payload = json.loads(serialized)
    if not isinstance(payload, Mapping):
        raise TypeError("serialized gate execution must contain an object")
    if payload.get("schema_version") != "FinancialEvidenceGateExecution-v1.0":
        raise ValueError("unsupported gate execution schema_version")
    summary_payload = payload.get("summary")
    logs_payload = payload.get("stage_logs")
    if not isinstance(summary_payload, Mapping) or not isinstance(logs_payload, list):
        raise TypeError("gate execution payload is incomplete")
    references = tuple(
        FinancialP2ResultReference(**item)
        for item in summary_payload.get("references", [])
    )
    logs = tuple(FinancialEvidenceStageLog(**item) for item in logs_payload)
    execution = FinancialEvidenceGateExecution(
        gate_status=str(payload.get("gate_status")),
        admission_allowed=payload.get("admission_allowed") is True,
        archive_allowed=payload.get("archive_allowed") is True,
        summary=FinancialP2EvidenceGateSummary(references),
        stage_logs=logs,
    )
    if execution.gate_status == "blocked" and (
        execution.admission_allowed or execution.archive_allowed
    ):
        raise ValueError("blocked gate cannot allow admission or archive")
    return execution


def _result_gate_status(result: Any) -> tuple[str, str | None]:
    body = result.to_dict()
    audit = next(
        (
            value
            for key, value in body.items()
            if key.endswith("audit") and isinstance(value, Mapping)
        ),
        None,
    )
    if audit is None:
        return "blocked", "AUDIT_NOT_FOUND"
    status = str(audit.get("gate_status", "blocked")).lower()
    raw_errors = audit.get("errors", ())
    reason = None
    if status not in {"ready", "accepted", "completed"}:
        reason = json.dumps(
            canonicalize_financial_fingerprint(raw_errors),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return status, reason
