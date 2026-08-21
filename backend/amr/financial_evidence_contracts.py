"""Strict discriminated contracts for independent financial M/F/R evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

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
