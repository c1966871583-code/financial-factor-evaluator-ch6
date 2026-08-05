"""FIN-P2-GATE: Phase 2 research-integrity quality gate.

The gate aggregates accepted, deterministic synthetic evidence from the M, F,
R, independence, and frozen OOS/FDR tasks.  It checks FIN-28 research
completeness without applying an effect-size or return threshold.  Research
integrity, evidence assessment, production readiness, and human admission are
kept as separate concepts.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence


GATE_SCHEMA_VERSION = "FinancialP2Gate-v1.0"
GATE_AUDIT_SCHEMA_VERSION = "FinancialP2GateAudit-v1.0"
GATE_CHECK_SCHEMA_VERSION = "FinancialP2GateCheck-v1.0"
GATE_LOG_SCHEMA_VERSION = "FinancialP2GateResearchLog-v1.0"
GATE_POLICY_VERSION = "FIN-P2-GATE-POLICY-v1.0"
GATE_HASH_CONTRACT_VERSION = "FIN-P2-GATE-HASH-v1.0"
GATE_RESEARCH_ASSESSMENT = "exploratory"
GATE_PRODUCTION_STATUS = "not production ready"
GATE_ADMISSION_STATUS = "not_assessed"
GATE_CONCLUSION_BOUNDARY = (
    "Synthetic Phase 2 research-integrity evidence only; not an empirical "
    "market conclusion, factor admission or rejection, production approval, "
    "return promise, fraud or misstatement determination, no-risk "
    "determination, or trading instruction."
)

TASK_M = "FIN-P2-M-ENH"
TASK_F = "FIN-P2-F"
TASK_R = "FIN-P2-R"
TASK_INDEP = "FIN-P2-INDEP"
TASK_OOS = "FIN-P2-OOS-FDR"
GATE_TASK_IDS = (TASK_M, TASK_F, TASK_R, TASK_INDEP, TASK_OOS)

GATE_OUTPUT_ANCHORS = MappingProxyType(
    {
        TASK_M: (
            "7496da71a9a4b6e429201c3173d903efd28e422acf07786a0"
            "c7d4d532be5b4d1"
        ),
        TASK_F: (
            "01f82894b9b327ed661b9fe3d9fe96fcc605a3df9502cee6"
            "1d6c9c0becf11282"
        ),
        TASK_R: (
            "dd376c087244dc57098828ee5a14b840ebe7404ddc48693e"
            "bb70a609035f0327"
        ),
        TASK_INDEP: (
            "34048940ea418305b51ff36072d41ea7bd4c6220dbf479383"
            "77ed331811c9ae7"
        ),
        TASK_OOS: (
            "b55ec436712231f359976442a9364b19dfd8c017aa309d79a"
            "112df442030d53d"
        ),
    }
)

CHECK_PIT = "pit_audit"
CHECK_DATA_QUALITY = "data_quality"
CHECK_COVERAGE = "coverage_thresholds"
CHECK_IC = "ic_evidence"
CHECK_GROUPED = "grouped_evidence"
CHECK_DIRECTION = "direction_evidence"
CHECK_INDEPENDENCE = "independence_evidence"
CHECK_ROBUSTNESS = "robustness_evidence"
CHECK_OOS = "oos_evidence"
CHECK_LOG = "research_log_archived"
CHECK_WARNINGS = "warnings_explained"
GATE_CHECK_IDS = (
    CHECK_PIT,
    CHECK_DATA_QUALITY,
    CHECK_COVERAGE,
    CHECK_IC,
    CHECK_GROUPED,
    CHECK_DIRECTION,
    CHECK_INDEPENDENCE,
    CHECK_ROBUSTNESS,
    CHECK_OOS,
    CHECK_LOG,
    CHECK_WARNINGS,
)

CHECK_SOURCE_TASKS = MappingProxyType(
    {
        CHECK_PIT: (TASK_M, TASK_F, TASK_R),
        CHECK_DATA_QUALITY: (TASK_M, TASK_F, TASK_R),
        CHECK_COVERAGE: (TASK_M, TASK_F, TASK_R),
        CHECK_IC: (TASK_M,),
        CHECK_GROUPED: (TASK_M,),
        CHECK_DIRECTION: (TASK_M, TASK_F, TASK_R),
        CHECK_INDEPENDENCE: (TASK_INDEP,),
        CHECK_ROBUSTNESS: (TASK_M,),
        CHECK_OOS: (TASK_OOS,),
        CHECK_LOG: GATE_TASK_IDS,
        CHECK_WARNINGS: GATE_TASK_IDS,
    }
)

PRODUCTION_GATE_IDS = (
    "independent_label_or_evidence_review",
    "real_time_data_contract_and_authorization",
    "pit_correct_versions_and_historical_universe",
    "net_of_cost_oos_significance_and_reproducibility",
)


class GateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class IntegrityStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class CheckStatus(str, Enum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"


class GateErrorCode(str, Enum):
    INVALID_EVIDENCE_SET = "INVALID_EVIDENCE_SET"
    DUPLICATE_TASK_ID = "DUPLICATE_TASK_ID"
    MISSING_TASK = "MISSING_TASK"
    UNKNOWN_TASK = "UNKNOWN_TASK"
    PREDECESSOR_NOT_ACCEPTED = "PREDECESSOR_NOT_ACCEPTED"
    OUTPUT_ANCHOR_MISMATCH = "OUTPUT_ANCHOR_MISMATCH"
    NON_SYNTHETIC_INPUT = "NON_SYNTHETIC_INPUT"
    INVALID_RESEARCH_BOUNDARY = "INVALID_RESEARCH_BOUNDARY"
    INVALID_RESEARCH_LOG_FINGERPRINT = (
        "INVALID_RESEARCH_LOG_FINGERPRINT"
    )
    UNAUTHORIZED_PRODUCTION_CLAIM = (
        "UNAUTHORIZED_PRODUCTION_CLAIM"
    )
    FORBIDDEN_ADMISSION_FIELD = "FORBIDDEN_ADMISSION_FIELD"
    INPUT_MUTATED = "INPUT_MUTATED"


class GateWarningCode(str, Enum):
    SYNTHETIC_RESEARCH_ONLY = "SYNTHETIC_RESEARCH_ONLY"
    PRODUCTION_GATES_INCOMPLETE = "PRODUCTION_GATES_INCOMPLETE"
    RESULT_NOT_ADMISSION = "RESULT_NOT_ADMISSION"
    IN_RESULT_LOG_ONLY = "IN_RESULT_LOG_ONLY"


@dataclass(frozen=True)
class GateIssue:
    code: str
    message: str
    field_name: str | None = None
    record_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_name": self.field_name,
            "record_key": self.record_key,
        }


@dataclass(frozen=True)
class FinancialP2GateEvidence:
    task_id: str
    status: str
    output_fingerprint: str
    research_assessment: str
    production_status: str
    synthetic_test_only: bool
    warning_codes: tuple[str, ...]
    warning_explanations: Mapping[str, str]
    research_log_entry_status: str
    retained_run_count: int = 1
    failed_run_count: int = 0
    failed_runs_retained: bool = True
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "task_id",
            _required_text(self.task_id, "task_id"),
        )
        object.__setattr__(
            self,
            "status",
            _required_text(self.status, "status"),
        )
        if not _is_sha256(self.output_fingerprint):
            raise ValueError("output_fingerprint must be SHA-256")
        object.__setattr__(
            self,
            "research_assessment",
            _required_text(
                self.research_assessment,
                "research_assessment",
            ),
        )
        object.__setattr__(
            self,
            "production_status",
            _required_text(
                self.production_status,
                "production_status",
            ),
        )
        warning_codes = tuple(
            _required_text(value, "warning_code")
            for value in self.warning_codes
        )
        if len(set(warning_codes)) != len(warning_codes):
            raise ValueError("warning_codes must be unique")
        explanations = {
            _required_text(key, "warning_code"): (
                value
                if isinstance(value, str)
                else value
            )
            for key, value in dict(self.warning_explanations).items()
        }
        object.__setattr__(self, "warning_codes", warning_codes)
        object.__setattr__(
            self,
            "warning_explanations",
            MappingProxyType(copy.deepcopy(explanations)),
        )
        object.__setattr__(
            self,
            "research_log_entry_status",
            _required_text(
                self.research_log_entry_status,
                "research_log_entry_status",
            ),
        )
        if self.retained_run_count < 0 or self.failed_run_count < 0:
            raise ValueError("run counts must be non-negative")
        if self.failed_run_count > self.retained_run_count:
            raise ValueError(
                "failed_run_count cannot exceed retained_run_count"
            )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(
                copy.deepcopy(dict(self.metadata or {}))
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "output_fingerprint": self.output_fingerprint,
            "research_assessment": self.research_assessment,
            "production_status": self.production_status,
            "synthetic_test_only": self.synthetic_test_only,
            "warning_codes": list(self.warning_codes),
            "warning_explanations": dict(self.warning_explanations),
            "research_log_entry_status":
                self.research_log_entry_status,
            "retained_run_count": self.retained_run_count,
            "failed_run_count": self.failed_run_count,
            "failed_runs_retained": self.failed_runs_retained,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FinancialP2GateBatch:
    batch_id: str
    version: str
    evidence_records: tuple[FinancialP2GateEvidence, ...]
    research_log_snapshot_status: str
    declared_research_log_fingerprint: str
    production_gate_claims: Mapping[str, bool]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "batch_id",
            _required_text(self.batch_id, "batch_id"),
        )
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, "version"),
        )
        records = tuple(self.evidence_records)
        if any(
            not isinstance(item, FinancialP2GateEvidence)
            for item in records
        ):
            raise TypeError(
                "evidence_records must contain FinancialP2GateEvidence"
            )
        object.__setattr__(self, "evidence_records", records)
        object.__setattr__(
            self,
            "research_log_snapshot_status",
            _required_text(
                self.research_log_snapshot_status,
                "research_log_snapshot_status",
            ),
        )
        if not _is_sha256(self.declared_research_log_fingerprint):
            raise ValueError(
                "declared_research_log_fingerprint must be SHA-256"
            )
        claims = dict(self.production_gate_claims)
        if set(claims) != set(PRODUCTION_GATE_IDS):
            raise ValueError(
                "production gate claims must cover exactly four gates"
            )
        if any(type(value) is not bool for value in claims.values()):
            raise TypeError("production gate claims must be booleans")
        object.__setattr__(
            self,
            "production_gate_claims",
            MappingProxyType(copy.deepcopy(claims)),
        )
        object.__setattr__(
            self,
            "provenance",
            MappingProxyType(copy.deepcopy(dict(self.provenance))),
        )

    def get_evidence_records(
        self,
    ) -> tuple[FinancialP2GateEvidence, ...]:
        return tuple(self.evidence_records)

    def get_production_gate_claims(self) -> dict[str, bool]:
        return copy.deepcopy(dict(self.production_gate_claims))

    def get_provenance(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.provenance))


@dataclass(frozen=True)
class FinancialP2GateConfig:
    execution_timestamp: str
    required_task_ids: tuple[str, ...] = GATE_TASK_IDS
    required_check_ids: tuple[str, ...] = GATE_CHECK_IDS
    production_gate_ids: tuple[str, ...] = PRODUCTION_GATE_IDS
    effect_threshold_gate_allowed: bool = False
    automatic_admission_allowed: bool = False
    synthetic_empirical_conclusion_allowed: bool = False
    formal_persistence_authorized: bool = False
    required_research_assessment: str = GATE_RESEARCH_ASSESSMENT
    required_production_status: str = GATE_PRODUCTION_STATUS
    required_admission_status: str = GATE_ADMISSION_STATUS
    policy_version: str = GATE_POLICY_VERSION
    schema_version: str = GATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _datetime_text(self.execution_timestamp, "execution_timestamp")
        frozen = {
            "required_task_ids": (
                tuple(self.required_task_ids),
                GATE_TASK_IDS,
            ),
            "required_check_ids": (
                tuple(self.required_check_ids),
                GATE_CHECK_IDS,
            ),
            "production_gate_ids": (
                tuple(self.production_gate_ids),
                PRODUCTION_GATE_IDS,
            ),
            "effect_threshold_gate_allowed": (
                self.effect_threshold_gate_allowed,
                False,
            ),
            "automatic_admission_allowed": (
                self.automatic_admission_allowed,
                False,
            ),
            "synthetic_empirical_conclusion_allowed": (
                self.synthetic_empirical_conclusion_allowed,
                False,
            ),
            "formal_persistence_authorized": (
                self.formal_persistence_authorized,
                False,
            ),
            "required_research_assessment": (
                self.required_research_assessment,
                GATE_RESEARCH_ASSESSMENT,
            ),
            "required_production_status": (
                self.required_production_status,
                GATE_PRODUCTION_STATUS,
            ),
            "required_admission_status": (
                self.required_admission_status,
                GATE_ADMISSION_STATUS,
            ),
            "policy_version": (
                self.policy_version,
                GATE_POLICY_VERSION,
            ),
            "schema_version": (
                self.schema_version,
                GATE_SCHEMA_VERSION,
            ),
        }
        for name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(
                    f"{name} must be frozen at {expected!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["required_task_ids"] = list(self.required_task_ids)
        values["required_check_ids"] = list(self.required_check_ids)
        values["production_gate_ids"] = list(
            self.production_gate_ids
        )
        return values


@dataclass(frozen=True)
class FinancialP2GateCheck:
    check_id: str
    check_status: str
    source_task_ids: tuple[str, ...]
    reason_code: str | None
    detail: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["source_task_ids"] = list(self.source_task_ids)
        return values


@dataclass(frozen=True)
class FinancialP2ProductionGate:
    production_gate_id: str
    gate_status: str
    reason_code: str
    detail: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class FinancialP2GateResearchLogEntry:
    task_id: str
    source_status: str
    source_output_fingerprint: str
    research_assessment: str
    production_status: str
    warning_codes: tuple[str, ...]
    retained_run_count: int
    failed_run_count: int
    failed_runs_retained: bool
    archive_scope: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["warning_codes"] = list(self.warning_codes)
        return values


@dataclass(frozen=True)
class FinancialP2GateAudit:
    gate_status: str
    errors: tuple[GateIssue, ...]
    warnings: tuple[GateIssue, ...]
    research_integrity_status: str
    satisfied_check_count: int
    required_check_count: int
    production_gate_satisfied_count: int
    production_gate_count: int
    research_assessment: str
    production_status: str
    admission_status: str
    synthetic_test_only: bool
    effect_threshold_gate_used: bool
    formal_persistence_performed: bool
    input_fingerprint: str
    predecessor_anchor_fingerprint: str
    research_log_fingerprint: str
    output_fingerprint: str
    conclusion_boundary: str
    schema_version: str
    audit_schema_version: str
    policy_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["errors"] = [item.to_dict() for item in self.errors]
        values["warnings"] = [
            item.to_dict() for item in self.warnings
        ]
        return values


@dataclass(frozen=True)
class FinancialP2GateResult:
    integrity_checks: tuple[FinancialP2GateCheck, ...]
    production_gates: tuple[FinancialP2ProductionGate, ...]
    research_log_entries: tuple[
        FinancialP2GateResearchLogEntry,
        ...,
    ]
    gate_audit: FinancialP2GateAudit

    def get_check(self, check_id: Any) -> FinancialP2GateCheck:
        normalized = _required_text(check_id, "check_id")
        matches = [
            item
            for item in self.integrity_checks
            if item.check_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(f"expected one check for {normalized}")
        return matches[0]

    def get_production_gate(
        self,
        gate_id: Any,
    ) -> FinancialP2ProductionGate:
        normalized = _required_text(gate_id, "gate_id")
        matches = [
            item
            for item in self.production_gates
            if item.production_gate_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one production gate for {normalized}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "integrity_checks": [
                item.to_dict() for item in self.integrity_checks
            ],
            "production_gates": [
                item.to_dict() for item in self.production_gates
            ],
            "research_log_entries": [
                item.to_dict() for item in self.research_log_entries
            ],
            "gate_audit": self.gate_audit.to_dict(),
        }


def compute_research_log_fingerprint(
    records: Sequence[FinancialP2GateEvidence],
) -> str:
    """Compute the deterministic in-result Research Log fingerprint."""

    if any(
        not isinstance(item, FinancialP2GateEvidence)
        for item in records
    ):
        raise TypeError(
            "records must contain FinancialP2GateEvidence"
        )
    ordered = sorted(records, key=lambda item: item.task_id)
    payload = [
        {
            "task_id": item.task_id,
            "source_status": item.status,
            "source_output_fingerprint": item.output_fingerprint,
            "research_assessment": item.research_assessment,
            "production_status": item.production_status,
            "warning_codes": list(item.warning_codes),
            "retained_run_count": item.retained_run_count,
            "failed_run_count": item.failed_run_count,
            "failed_runs_retained": item.failed_runs_retained,
            "research_log_entry_status":
                item.research_log_entry_status,
        }
        for item in ordered
    ]
    return _hash("p2_gate_research_log", payload)


def evaluate_financial_p2_gate(
    batch: FinancialP2GateBatch,
    *,
    configuration: FinancialP2GateConfig,
) -> FinancialP2GateResult:
    if not isinstance(batch, FinancialP2GateBatch):
        raise TypeError("batch must be FinancialP2GateBatch")
    if not isinstance(configuration, FinancialP2GateConfig):
        raise TypeError(
            "configuration must be FinancialP2GateConfig"
        )

    records = batch.get_evidence_records()
    provenance = batch.get_provenance()
    production_claims = batch.get_production_gate_claims()
    guard = _batch_guard(batch)
    errors: list[GateIssue] = []
    warnings = [
        _warning(
            GateWarningCode.SYNTHETIC_RESEARCH_ONLY,
            "Only deterministic synthetic Phase 2 evidence is in scope.",
        ),
        _warning(
            GateWarningCode.PRODUCTION_GATES_INCOMPLETE,
            "All four production gates remain not satisfied.",
        ),
        _warning(
            GateWarningCode.RESULT_NOT_ADMISSION,
            "Research-integrity completeness is not factor admission.",
        ),
        _warning(
            GateWarningCode.IN_RESULT_LOG_ONLY,
            "The Research Log is archived only in the returned result; "
            "formal persistence is not authorized.",
        ),
    ]

    _validate_records(records, errors)
    if not bool(provenance.get("synthetic_test_only")):
        errors.append(
            _error(
                GateErrorCode.NON_SYNTHETIC_INPUT,
                "provenance.synthetic_test_only must be true",
            )
        )
    if bool(provenance.get("formal_persistence_performed")):
        errors.append(
            _error(
                GateErrorCode.INVALID_RESEARCH_BOUNDARY,
                "formal persistence is not authorized",
            )
        )
    forbidden = {
        "admission_decision",
        "factor_admitted",
        "passed",
        "conditionally_passed",
        "rejected",
    } & set(str(key) for key in provenance)
    if forbidden:
        errors.append(
            _error(
                GateErrorCode.FORBIDDEN_ADMISSION_FIELD,
                "admission-like fields are forbidden",
                field_name=",".join(sorted(forbidden)),
            )
        )
    if any(production_claims.values()):
        errors.append(
            _error(
                GateErrorCode.UNAUTHORIZED_PRODUCTION_CLAIM,
                "synthetic evidence cannot satisfy a production gate",
            )
        )

    calculated_log_fingerprint = (
        compute_research_log_fingerprint(records)
    )
    if calculated_log_fingerprint != (
        batch.declared_research_log_fingerprint
    ):
        errors.append(
            _error(
                GateErrorCode.INVALID_RESEARCH_LOG_FINGERPRINT,
                "declared Research Log fingerprint does not match",
            )
        )

    input_fingerprint = _hash(
        "p2_gate_input",
        {
            "records": [
                item.to_dict()
                for item in sorted(
                    records,
                    key=lambda value: value.task_id,
                )
            ],
            "research_log_snapshot_status":
                batch.research_log_snapshot_status,
            "declared_research_log_fingerprint":
                batch.declared_research_log_fingerprint,
            "production_gate_claims": production_claims,
            "provenance": provenance,
        },
    )
    predecessor_anchor_fingerprint = _hash(
        "p2_gate_predecessor_anchors",
        dict(GATE_OUTPUT_ANCHORS),
    )

    if errors:
        return _blocked_result(
            errors=errors,
            warnings=warnings,
            configuration=configuration,
            input_fingerprint=input_fingerprint,
            predecessor_anchor_fingerprint=
                predecessor_anchor_fingerprint,
            research_log_fingerprint=
                calculated_log_fingerprint,
        )

    checks = _build_integrity_checks(
        records,
        research_log_snapshot_status=
            batch.research_log_snapshot_status,
    )
    production_gates = _build_production_gates()
    log_entries = _build_research_log_entries(records)
    output_fingerprint = _hash(
        "p2_gate_output",
        {
            "checks": [item.to_dict() for item in checks],
            "production_gates": [
                item.to_dict() for item in production_gates
            ],
            "research_log_entries": [
                item.to_dict() for item in log_entries
            ],
        },
    )
    if _batch_guard(batch) != guard:
        return _blocked_result(
            errors=[
                _error(
                    GateErrorCode.INPUT_MUTATED,
                    "input batch changed during evaluation",
                )
            ],
            warnings=warnings,
            configuration=configuration,
            input_fingerprint=input_fingerprint,
            predecessor_anchor_fingerprint=
                predecessor_anchor_fingerprint,
            research_log_fingerprint=
                calculated_log_fingerprint,
        )

    satisfied = sum(
        item.check_status == CheckStatus.SATISFIED.value
        for item in checks
    )
    integrity_status = (
        IntegrityStatus.COMPLETE.value
        if satisfied == len(GATE_CHECK_IDS)
        else IntegrityStatus.INCOMPLETE.value
    )
    audit = _build_audit(
        gate_status=GateStatus.READY.value,
        errors=(),
        warnings=_deduplicate(warnings),
        research_integrity_status=integrity_status,
        satisfied_check_count=satisfied,
        configuration=configuration,
        input_fingerprint=input_fingerprint,
        predecessor_anchor_fingerprint=
            predecessor_anchor_fingerprint,
        research_log_fingerprint=
            calculated_log_fingerprint,
        output_fingerprint=output_fingerprint,
    )
    return FinancialP2GateResult(
        integrity_checks=tuple(checks),
        production_gates=tuple(production_gates),
        research_log_entries=tuple(log_entries),
        gate_audit=audit,
    )


def _validate_records(
    records: Sequence[FinancialP2GateEvidence],
    errors: list[GateIssue],
) -> None:
    task_ids = [item.task_id for item in records]
    if len(set(task_ids)) != len(task_ids):
        errors.append(
            _error(
                GateErrorCode.DUPLICATE_TASK_ID,
                "each predecessor task must appear once",
            )
        )
    unknown = sorted(set(task_ids) - set(GATE_TASK_IDS))
    if unknown:
        errors.append(
            _error(
                GateErrorCode.UNKNOWN_TASK,
                f"unknown predecessor tasks: {unknown}",
            )
        )
    missing = sorted(set(GATE_TASK_IDS) - set(task_ids))
    if missing:
        errors.append(
            _error(
                GateErrorCode.MISSING_TASK,
                f"missing predecessor tasks: {missing}",
            )
        )
    for record in records:
        if record.task_id not in GATE_OUTPUT_ANCHORS:
            continue
        if record.status.upper() != "ACCEPTED":
            errors.append(
                _error(
                    GateErrorCode.PREDECESSOR_NOT_ACCEPTED,
                    "predecessor status must be ACCEPTED",
                    record_key=record.task_id,
                )
            )
        if record.output_fingerprint != (
            GATE_OUTPUT_ANCHORS[record.task_id]
        ):
            errors.append(
                _error(
                    GateErrorCode.OUTPUT_ANCHOR_MISMATCH,
                    "predecessor output fingerprint does not match",
                    record_key=record.task_id,
                )
            )
        if (
            record.research_assessment
            != GATE_RESEARCH_ASSESSMENT
            or record.production_status
            != GATE_PRODUCTION_STATUS
            or not record.synthetic_test_only
        ):
            errors.append(
                _error(
                    GateErrorCode.INVALID_RESEARCH_BOUNDARY,
                    "predecessor research boundary does not match",
                    record_key=record.task_id,
                )
            )
        if (
            record.failed_run_count > 0
            and not record.failed_runs_retained
        ):
            errors.append(
                _error(
                    GateErrorCode.INVALID_RESEARCH_BOUNDARY,
                    "failed predecessor runs must remain retained",
                    record_key=record.task_id,
                )
            )
    oos = [
        item for item in records if item.task_id == TASK_OOS
    ]
    if oos:
        metadata = dict(oos[0].metadata)
        expected = {
            "registered_hypothesis_count": 23,
            "completed_run_count": 20,
            "failed_run_count": 3,
            "failed_runs_count_in_family_denominator": True,
            "robustness_family_status": "not_run",
            "test_use_policy":
                "latest_20pct_one_shot_read_only",
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            errors.append(
                _error(
                    GateErrorCode.INVALID_EVIDENCE_SET,
                    "OOS/FDR retained-run contract does not match",
                    record_key=TASK_OOS,
                )
            )


def _build_integrity_checks(
    records: Sequence[FinancialP2GateEvidence],
    *,
    research_log_snapshot_status: str,
) -> list[FinancialP2GateCheck]:
    by_task = {item.task_id: item for item in records}
    output: list[FinancialP2GateCheck] = []
    for check_id in GATE_CHECK_IDS:
        sources = CHECK_SOURCE_TASKS[check_id]
        satisfied = True
        reason_code: str | None = None
        detail = (
            "Accepted predecessor anchors provide the registered "
            f"{check_id} evidence."
        )
        if check_id == CHECK_LOG:
            satisfied = (
                research_log_snapshot_status
                == "archived_in_result"
                and all(
                    by_task[task_id].research_log_entry_status
                    == "completed"
                    for task_id in sources
                )
            )
            if not satisfied:
                reason_code = "RESEARCH_LOG_NOT_ARCHIVED"
                detail = (
                    "All five predecessor log entries must be completed "
                    "and archived in the returned result."
                )
        elif check_id == CHECK_WARNINGS:
            for task_id in sources:
                record = by_task[task_id]
                explanations = dict(record.warning_explanations)
                if set(explanations) != set(record.warning_codes):
                    satisfied = False
                    break
                if any(
                    not isinstance(value, str) or not value.strip()
                    for value in explanations.values()
                ):
                    satisfied = False
                    break
            if not satisfied:
                reason_code = "WARNING_EXPLANATION_INCOMPLETE"
                detail = (
                    "Every predecessor warning requires one non-empty "
                    "explanation."
                )
        output.append(
            _make_check(
                check_id=check_id,
                status=(
                    CheckStatus.SATISFIED.value
                    if satisfied
                    else CheckStatus.NOT_SATISFIED.value
                ),
                source_task_ids=sources,
                reason_code=reason_code,
                detail=detail,
            )
        )
    return output


def _build_production_gates(
) -> list[FinancialP2ProductionGate]:
    reasons = {
        PRODUCTION_GATE_IDS[0]: (
            "REAL_INDEPENDENT_REVIEW_MISSING",
            "No authorized real-label independent review is present.",
        ),
        PRODUCTION_GATE_IDS[1]: (
            "REAL_TIME_DATA_CONTRACT_MISSING",
            "No authorized real-time production data contract is present.",
        ),
        PRODUCTION_GATE_IDS[2]: (
            "REAL_PIT_UNIVERSE_MISSING",
            "No real PIT version history or historical universe is present.",
        ),
        PRODUCTION_GATE_IDS[3]: (
            "NET_COST_OOS_EVIDENCE_MISSING",
            "No real net-of-cost OOS significance evidence is present.",
        ),
    }
    output = []
    for gate_id in PRODUCTION_GATE_IDS:
        reason_code, detail = reasons[gate_id]
        payload = {
            "production_gate_id": gate_id,
            "gate_status": CheckStatus.NOT_SATISFIED.value,
            "reason_code": reason_code,
            "detail": detail,
        }
        output.append(
            FinancialP2ProductionGate(
                **payload,
                content_hash=_hash(
                    "p2_gate_production_gate",
                    payload,
                ),
            )
        )
    return output


def _build_research_log_entries(
    records: Sequence[FinancialP2GateEvidence],
) -> list[FinancialP2GateResearchLogEntry]:
    output = []
    for record in sorted(records, key=lambda item: GATE_TASK_IDS.index(
        item.task_id
    )):
        payload = {
            "task_id": record.task_id,
            "source_status": record.status,
            "source_output_fingerprint": record.output_fingerprint,
            "research_assessment": record.research_assessment,
            "production_status": record.production_status,
            "warning_codes": list(record.warning_codes),
            "retained_run_count": record.retained_run_count,
            "failed_run_count": record.failed_run_count,
            "failed_runs_retained": record.failed_runs_retained,
            "archive_scope": "in_result_snapshot_only",
            "schema_version": GATE_LOG_SCHEMA_VERSION,
        }
        output.append(
            FinancialP2GateResearchLogEntry(
                task_id=record.task_id,
                source_status=record.status,
                source_output_fingerprint=
                    record.output_fingerprint,
                research_assessment=record.research_assessment,
                production_status=record.production_status,
                warning_codes=record.warning_codes,
                retained_run_count=record.retained_run_count,
                failed_run_count=record.failed_run_count,
                failed_runs_retained=record.failed_runs_retained,
                archive_scope="in_result_snapshot_only",
                schema_version=GATE_LOG_SCHEMA_VERSION,
                content_hash=_hash(
                    "p2_gate_research_log_entry",
                    payload,
                ),
            )
        )
    return output


def _make_check(
    *,
    check_id: str,
    status: str,
    source_task_ids: tuple[str, ...],
    reason_code: str | None,
    detail: str,
) -> FinancialP2GateCheck:
    payload = {
        "check_id": check_id,
        "check_status": status,
        "source_task_ids": list(source_task_ids),
        "reason_code": reason_code,
        "detail": detail,
        "schema_version": GATE_CHECK_SCHEMA_VERSION,
    }
    return FinancialP2GateCheck(
        check_id=check_id,
        check_status=status,
        source_task_ids=source_task_ids,
        reason_code=reason_code,
        detail=detail,
        schema_version=GATE_CHECK_SCHEMA_VERSION,
        content_hash=_hash("p2_gate_check", payload),
    )


def _blocked_result(
    *,
    errors: Sequence[GateIssue],
    warnings: Sequence[GateIssue],
    configuration: FinancialP2GateConfig,
    input_fingerprint: str,
    predecessor_anchor_fingerprint: str,
    research_log_fingerprint: str,
) -> FinancialP2GateResult:
    checks = [
        _make_check(
            check_id=check_id,
            status=CheckStatus.NOT_SATISFIED.value,
            source_task_ids=CHECK_SOURCE_TASKS[check_id],
            reason_code="BLOCKED_BY_CONTRACT",
            detail="The gate did not evaluate research integrity.",
        )
        for check_id in GATE_CHECK_IDS
    ]
    production_gates = _build_production_gates()
    output_fingerprint = _hash(
        "p2_gate_blocked_output",
        {
            "errors": [
                item.to_dict() for item in _deduplicate(errors)
            ],
            "checks": [item.to_dict() for item in checks],
        },
    )
    audit = _build_audit(
        gate_status=GateStatus.BLOCKED.value,
        errors=_deduplicate(errors),
        warnings=_deduplicate(warnings),
        research_integrity_status=IntegrityStatus.INCOMPLETE.value,
        satisfied_check_count=0,
        configuration=configuration,
        input_fingerprint=input_fingerprint,
        predecessor_anchor_fingerprint=
            predecessor_anchor_fingerprint,
        research_log_fingerprint=research_log_fingerprint,
        output_fingerprint=output_fingerprint,
    )
    return FinancialP2GateResult(
        integrity_checks=tuple(checks),
        production_gates=tuple(production_gates),
        research_log_entries=(),
        gate_audit=audit,
    )


def _build_audit(
    *,
    gate_status: str,
    errors: Sequence[GateIssue],
    warnings: Sequence[GateIssue],
    research_integrity_status: str,
    satisfied_check_count: int,
    configuration: FinancialP2GateConfig,
    input_fingerprint: str,
    predecessor_anchor_fingerprint: str,
    research_log_fingerprint: str,
    output_fingerprint: str,
) -> FinancialP2GateAudit:
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "research_integrity_status": research_integrity_status,
        "satisfied_check_count": satisfied_check_count,
        "required_check_count": len(GATE_CHECK_IDS),
        "production_gate_satisfied_count": 0,
        "production_gate_count": len(PRODUCTION_GATE_IDS),
        "research_assessment": GATE_RESEARCH_ASSESSMENT,
        "production_status": GATE_PRODUCTION_STATUS,
        "admission_status": GATE_ADMISSION_STATUS,
        "synthetic_test_only": True,
        "effect_threshold_gate_used": False,
        "formal_persistence_performed": False,
        "input_fingerprint": input_fingerprint,
        "predecessor_anchor_fingerprint":
            predecessor_anchor_fingerprint,
        "research_log_fingerprint": research_log_fingerprint,
        "output_fingerprint": output_fingerprint,
        "conclusion_boundary": GATE_CONCLUSION_BOUNDARY,
        "schema_version": GATE_SCHEMA_VERSION,
        "audit_schema_version": GATE_AUDIT_SCHEMA_VERSION,
        "policy_version": configuration.policy_version,
        "hash_contract_version": GATE_HASH_CONTRACT_VERSION,
    }
    return FinancialP2GateAudit(
        gate_status=gate_status,
        errors=tuple(errors),
        warnings=tuple(warnings),
        research_integrity_status=research_integrity_status,
        satisfied_check_count=satisfied_check_count,
        required_check_count=len(GATE_CHECK_IDS),
        production_gate_satisfied_count=0,
        production_gate_count=len(PRODUCTION_GATE_IDS),
        research_assessment=GATE_RESEARCH_ASSESSMENT,
        production_status=GATE_PRODUCTION_STATUS,
        admission_status=GATE_ADMISSION_STATUS,
        synthetic_test_only=True,
        effect_threshold_gate_used=False,
        formal_persistence_performed=False,
        input_fingerprint=input_fingerprint,
        predecessor_anchor_fingerprint=
            predecessor_anchor_fingerprint,
        research_log_fingerprint=research_log_fingerprint,
        output_fingerprint=output_fingerprint,
        conclusion_boundary=GATE_CONCLUSION_BOUNDARY,
        schema_version=GATE_SCHEMA_VERSION,
        audit_schema_version=GATE_AUDIT_SCHEMA_VERSION,
        policy_version=configuration.policy_version,
        hash_contract_version=GATE_HASH_CONTRACT_VERSION,
        content_hash=_hash("p2_gate_audit", payload),
    )


def _batch_guard(batch: FinancialP2GateBatch) -> str:
    return _hash(
        "p2_gate_batch_guard",
        {
            "batch_id": batch.batch_id,
            "version": batch.version,
            "evidence_records": [
                item.to_dict()
                for item in sorted(
                    batch.get_evidence_records(),
                    key=lambda value: value.task_id,
                )
            ],
            "research_log_snapshot_status":
                batch.research_log_snapshot_status,
            "declared_research_log_fingerprint":
                batch.declared_research_log_fingerprint,
            "production_gate_claims":
                batch.get_production_gate_claims(),
            "provenance": batch.get_provenance(),
        },
    )


def _error(
    code: GateErrorCode,
    message: str,
    *,
    field_name: str | None = None,
    record_key: str | None = None,
) -> GateIssue:
    return GateIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
    )


def _warning(
    code: GateWarningCode,
    message: str,
) -> GateIssue:
    return GateIssue(code=code.value, message=message)


def _deduplicate(
    issues: Sequence[GateIssue],
) -> tuple[GateIssue, ...]:
    unique = {
        json.dumps(
            issue.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
        ): issue
        for issue in issues
    }
    return tuple(unique[key] for key in sorted(unique))


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value.strip()


def _datetime_text(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    try:
        dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an ISO datetime"
        ) from exc
    return text


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _canonical(value.to_dict())
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(
                value.items(),
                key=lambda pair: str(pair[0]),
            )
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return str(value)
        return round(value, 15)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return value


def _hash(domain: str, value: Any) -> str:
    payload = {
        "domain": domain,
        "hash_contract_version": GATE_HASH_CONTRACT_VERSION,
        "value": _canonical(value),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CHECK_SOURCE_TASKS",
    "FinancialP2GateAudit",
    "FinancialP2GateBatch",
    "FinancialP2GateCheck",
    "FinancialP2GateConfig",
    "FinancialP2GateEvidence",
    "FinancialP2GateResearchLogEntry",
    "FinancialP2GateResult",
    "FinancialP2ProductionGate",
    "GATE_ADMISSION_STATUS",
    "GATE_CHECK_IDS",
    "GATE_CONCLUSION_BOUNDARY",
    "GATE_OUTPUT_ANCHORS",
    "GATE_PRODUCTION_STATUS",
    "GATE_RESEARCH_ASSESSMENT",
    "GATE_TASK_IDS",
    "GateErrorCode",
    "GateIssue",
    "GateStatus",
    "IntegrityStatus",
    "PRODUCTION_GATE_IDS",
    "compute_research_log_fingerprint",
    "evaluate_financial_p2_gate",
]
