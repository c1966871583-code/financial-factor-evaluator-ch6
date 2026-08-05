"""FIN-P2-R: deterministic, label-safe financial risk evidence.

The module implements a research-only two-layer protocol:

1. auditable accounting red flags produce a transparent review priority;
2. when enough time-available hard labels exist, a small deterministic
   calibration model is evaluated on company-disjoint test observations.

The result is a manual-review queue.  It is never a fraud, misstatement,
no-risk, admission, or trading determination.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

import numpy as np


R_SCHEMA_VERSION = "FinancialP2REvidence-v1.0"
R_AUDIT_SCHEMA_VERSION = "FinancialP2REvidenceAudit-v1.0"
R_POLICY_VERSION = "FIN-P2-R-POLICY-v1.0"
R_HASH_CONTRACT_VERSION = "FIN-P2-R-HASH-v1.0"
R_VALIDATION_TRACK = "R"
R_EVIDENCE_PRIORITY = "risk"
R_LABEL_STATES = (
    "hard_positive",
    "soft_positive",
    "confirmed_negative",
    "unlabeled",
)
R_REVIEW_BOUNDARY = (
    "Research-only manual-review priority; not a fraud, misstatement, "
    "no-risk, admission, or trading determination."
)
R_SUPERVISED_MINIMUM_HARD_POSITIVES = 10


class RGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class RSupervisedStatus(str, Enum):
    COMPLETED = "completed"
    NOT_RUN = "not_run"


class RErrorCode(str, Enum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_RECORDS = "INVALID_RECORDS"
    INVALID_RECORD = "INVALID_RECORD"
    DUPLICATE_RECORD_KEY = "DUPLICATE_RECORD_KEY"
    FUTURE_FINANCIAL_ANNOUNCEMENT = "FUTURE_FINANCIAL_ANNOUNCEMENT"
    INVALID_LABEL_STATE = "INVALID_LABEL_STATE"
    LABEL_METADATA_MISSING = "LABEL_METADATA_MISSING"
    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"
    NON_SYNTHETIC_INPUT = "NON_SYNTHETIC_INPUT"
    INPUT_MUTATED = "INPUT_MUTATED"


class RWarningCode(str, Enum):
    LABEL_NOT_YET_AVAILABLE = "LABEL_NOT_YET_AVAILABLE"
    SUPERVISED_HARD_POSITIVES_INSUFFICIENT = (
        "SUPERVISED_HARD_POSITIVES_INSUFFICIENT"
    )
    SUPERVISED_SPLIT_NOT_EVALUABLE = "SUPERVISED_SPLIT_NOT_EVALUABLE"
    MISSING_TRANSPARENT_FIELDS = "MISSING_TRANSPARENT_FIELDS"


@dataclass(frozen=True)
class FinancialP2REvidenceConfig:
    as_of: str
    top_k: int = 10
    test_fraction: float = 0.35
    split_salt: str = "FIN-P2-R-company-split-v1"
    minimum_hard_positives: int = R_SUPERVISED_MINIMUM_HARD_POSITIVES
    calibration_bins: int = 5
    validation_track: str = R_VALIDATION_TRACK
    evidence_priority: str = R_EVIDENCE_PRIORITY
    schema_version: str = R_SCHEMA_VERSION
    policy_version: str = R_POLICY_VERSION
    synthetic_test_only: bool = True

    def __post_init__(self) -> None:
        _date_text(self.as_of, "as_of")
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int):
            raise TypeError("top_k must be an integer")
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")
        if isinstance(self.test_fraction, bool) or not isinstance(
            self.test_fraction, (int, float)
        ):
            raise TypeError("test_fraction must be numeric")
        if not 0.0 < float(self.test_fraction) < 1.0:
            raise ValueError("test_fraction must be between 0 and 1")
        _required_text(self.split_salt, "split_salt")
        if (
            isinstance(self.minimum_hard_positives, bool)
            or not isinstance(self.minimum_hard_positives, int)
            or self.minimum_hard_positives
            != R_SUPERVISED_MINIMUM_HARD_POSITIVES
        ):
            raise ValueError(
                "minimum_hard_positives must be frozen at "
                f"{R_SUPERVISED_MINIMUM_HARD_POSITIVES}"
            )
        if (
            isinstance(self.calibration_bins, bool)
            or not isinstance(self.calibration_bins, int)
            or self.calibration_bins < 2
        ):
            raise ValueError("calibration_bins must be an integer >= 2")
        frozen = {
            "validation_track": (self.validation_track, R_VALIDATION_TRACK),
            "evidence_priority": (
                self.evidence_priority,
                R_EVIDENCE_PRIORITY,
            ),
            "schema_version": (self.schema_version, R_SCHEMA_VERSION),
            "policy_version": (self.policy_version, R_POLICY_VERSION),
            "synthetic_test_only": (self.synthetic_test_only, True),
        }
        for name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{name} must be frozen at {expected!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "top_k": self.top_k,
            "test_fraction": float(self.test_fraction),
            "split_salt": self.split_salt,
            "minimum_hard_positives": self.minimum_hard_positives,
            "calibration_bins": self.calibration_bins,
            "validation_track": self.validation_track,
            "evidence_priority": self.evidence_priority,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "synthetic_test_only": self.synthetic_test_only,
        }


@dataclass(frozen=True)
class RIssue:
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
class FinancialRiskScreeningRow:
    symbol: str
    report_period: str
    announced_at: str
    as_of: str
    sector_type: str
    transparent_score: int
    risk_level: str
    evidence: tuple[str, ...]
    missing_fields: tuple[str, ...]
    data_quality: str
    declared_label_state: str
    effective_label_state: str
    label_available_at: str | None
    label_source_url: str | None
    label_source_quality: str | None
    split: str
    model_risk_score: float | None
    conclusion_boundary: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "report_period": self.report_period,
            "announced_at": self.announced_at,
            "as_of": self.as_of,
            "sector_type": self.sector_type,
            "transparent_score": self.transparent_score,
            "risk_level": self.risk_level,
            "evidence": list(self.evidence),
            "missing_fields": list(self.missing_fields),
            "data_quality": self.data_quality,
            "declared_label_state": self.declared_label_state,
            "effective_label_state": self.effective_label_state,
            "label_available_at": self.label_available_at,
            "label_source_url": self.label_source_url,
            "label_source_quality": self.label_source_quality,
            "split": self.split,
            "model_risk_score": self.model_risk_score,
            "conclusion_boundary": self.conclusion_boundary,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialRiskReviewQueueItem:
    rank: int
    symbol: str
    report_period: str
    transparent_score: int
    risk_level: str
    evidence: tuple[str, ...]
    effective_label_state: str
    model_risk_score: float | None
    conclusion_boundary: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "symbol": self.symbol,
            "report_period": self.report_period,
            "transparent_score": self.transparent_score,
            "risk_level": self.risk_level,
            "evidence": list(self.evidence),
            "effective_label_state": self.effective_label_state,
            "model_risk_score": self.model_risk_score,
            "conclusion_boundary": self.conclusion_boundary,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class RCalibrationBin:
    bin_index: int
    lower_bound: float
    upper_bound: float
    observation_count: int
    predicted_mean: float | None
    observed_positive_rate: float | None
    absolute_gap: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bin_index": self.bin_index,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "observation_count": self.observation_count,
            "predicted_mean": self.predicted_mean,
            "observed_positive_rate": self.observed_positive_rate,
            "absolute_gap": self.absolute_gap,
        }


@dataclass(frozen=True)
class FinancialRiskSupervisedEvidence:
    status: str
    reason_code: str | None
    positive_definition: str
    negative_definition: str
    excluded_label_states: tuple[str, ...]
    minimum_hard_positive_companies: int
    hard_positive_company_count: int
    train_company_count: int
    test_company_count: int
    train_observation_count: int
    test_observation_count: int
    train_hard_positive_count: int
    train_confirmed_negative_count: int
    test_hard_positive_count: int
    test_confirmed_negative_count: int
    pr_auc: float | None
    roc_auc: float | None
    brier_score: float | None
    top_k: int
    top_k_hit_rate: float | None
    expected_calibration_error: float | None
    calibration: tuple[RCalibrationBin, ...]
    negative_control_status: str
    negative_control_pr_auc: float | None
    negative_control_roc_auc: float | None
    negative_control_fingerprint: str
    train_company_fingerprint: str
    test_company_fingerprint: str
    model_fingerprint: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "positive_definition": self.positive_definition,
            "negative_definition": self.negative_definition,
            "excluded_label_states": list(self.excluded_label_states),
            "minimum_hard_positive_companies":
                self.minimum_hard_positive_companies,
            "hard_positive_company_count":
                self.hard_positive_company_count,
            "train_company_count": self.train_company_count,
            "test_company_count": self.test_company_count,
            "train_observation_count": self.train_observation_count,
            "test_observation_count": self.test_observation_count,
            "train_hard_positive_count":
                self.train_hard_positive_count,
            "train_confirmed_negative_count":
                self.train_confirmed_negative_count,
            "test_hard_positive_count": self.test_hard_positive_count,
            "test_confirmed_negative_count":
                self.test_confirmed_negative_count,
            "pr_auc": self.pr_auc,
            "roc_auc": self.roc_auc,
            "brier_score": self.brier_score,
            "top_k": self.top_k,
            "top_k_hit_rate": self.top_k_hit_rate,
            "expected_calibration_error":
                self.expected_calibration_error,
            "calibration": [item.to_dict() for item in self.calibration],
            "negative_control_status": self.negative_control_status,
            "negative_control_pr_auc": self.negative_control_pr_auc,
            "negative_control_roc_auc": self.negative_control_roc_auc,
            "negative_control_fingerprint":
                self.negative_control_fingerprint,
            "train_company_fingerprint":
                self.train_company_fingerprint,
            "test_company_fingerprint":
                self.test_company_fingerprint,
            "model_fingerprint": self.model_fingerprint,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2REvidenceAudit:
    gate_status: str
    errors: tuple[RIssue, ...]
    warnings: tuple[RIssue, ...]
    input_record_count: int
    accepted_record_count: int
    label_state_counts: tuple[tuple[str, int], ...]
    effective_label_state_counts: tuple[tuple[str, int], ...]
    configuration_fingerprint: str
    input_fingerprint: str
    financial_input_fingerprint: str
    label_input_fingerprint: str
    split_fingerprint: str
    output_fingerprint: str
    schema_version: str
    audit_schema_version: str
    policy_version: str
    hash_contract_version: str
    conclusion_boundary: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_status": self.gate_status,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
            "input_record_count": self.input_record_count,
            "accepted_record_count": self.accepted_record_count,
            "label_state_counts": dict(self.label_state_counts),
            "effective_label_state_counts": dict(
                self.effective_label_state_counts
            ),
            "configuration_fingerprint":
                self.configuration_fingerprint,
            "input_fingerprint": self.input_fingerprint,
            "financial_input_fingerprint":
                self.financial_input_fingerprint,
            "label_input_fingerprint": self.label_input_fingerprint,
            "split_fingerprint": self.split_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "schema_version": self.schema_version,
            "audit_schema_version": self.audit_schema_version,
            "policy_version": self.policy_version,
            "hash_contract_version": self.hash_contract_version,
            "conclusion_boundary": self.conclusion_boundary,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2REvidenceResult:
    screening_rows: tuple[FinancialRiskScreeningRow, ...]
    review_queue: tuple[FinancialRiskReviewQueueItem, ...]
    supervised_evidence: FinancialRiskSupervisedEvidence
    evidence_audit: FinancialP2REvidenceAudit

    def get_row(
        self, symbol: Any, report_period: Any
    ) -> FinancialRiskScreeningRow:
        normalized_symbol = _required_text(symbol, "symbol")
        normalized_period = _date_text(report_period, "report_period")
        matches = [
            row
            for row in self.screening_rows
            if row.symbol == normalized_symbol
            and row.report_period == normalized_period
        ]
        if len(matches) != 1:
            raise LookupError(
                "expected one screening row for "
                f"{normalized_symbol}/{normalized_period}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "screening_rows": [
                item.to_dict() for item in self.screening_rows
            ],
            "review_queue": [
                item.to_dict() for item in self.review_queue
            ],
            "supervised_evidence": self.supervised_evidence.to_dict(),
            "evidence_audit": self.evidence_audit.to_dict(),
        }


_TRANSPARENT_FIELDS = (
    "total_assets",
    "total_liabilities",
    "net_profit",
    "operating_cash_flow",
    "receivables_growth_anomaly",
    "inventory_growth_anomaly",
    "other_receivables_anomaly",
    "non_recurring_or_asset_anomaly",
    "audit_opinion",
    "restated",
)
_LABEL_FIELDS = (
    "label_state",
    "label_available_at",
    "label_source_url",
    "label_source_quality",
)


def evaluate_financial_p2_r_evidence(
    records: Sequence[Mapping[str, Any]],
    *,
    configuration: FinancialP2REvidenceConfig,
) -> FinancialP2REvidenceResult:
    """Build transparent and optional supervised FIN-P2-R evidence."""

    if not isinstance(configuration, FinancialP2REvidenceConfig):
        return _blocked_result(
            (
                _issue(
                    RErrorCode.INVALID_CONFIGURATION,
                    "configuration must be FinancialP2REvidenceConfig",
                    "configuration",
                ),
            ),
            configuration=None,
            records=records,
        )
    if (
        isinstance(records, (str, bytes, Mapping))
        or not isinstance(records, Sequence)
    ):
        return _blocked_result(
            (
                _issue(
                    RErrorCode.INVALID_RECORDS,
                    "records must be a sequence of mappings",
                    "records",
                ),
            ),
            configuration=configuration,
            records=(),
        )

    original = copy.deepcopy(records)
    mutation_guard = _safe_hash(original)
    normalized, errors, warnings = _normalize_records(
        records, configuration
    )
    if not records:
        errors.append(
            _issue(
                RErrorCode.INVALID_RECORDS,
                "records must not be empty",
                "records",
            )
        )
    if _safe_hash(records) != mutation_guard:
        errors.append(
            _issue(
                RErrorCode.INPUT_MUTATED,
                "input records changed during evaluation",
                "records",
            )
        )
    if errors:
        return _blocked_result(
            tuple(errors),
            configuration=configuration,
            records=records,
            warnings=tuple(warnings),
            input_fingerprint=mutation_guard,
        )

    input_fingerprint = _hash(normalized)
    base_rows = [_screen_record(item, configuration) for item in normalized]
    supervised = _build_supervised(base_rows, configuration)
    if supervised.status == RSupervisedStatus.NOT_RUN.value:
        warning_code = (
            RWarningCode.SUPERVISED_HARD_POSITIVES_INSUFFICIENT
            if supervised.reason_code == "HARD_POSITIVES_INSUFFICIENT"
            else RWarningCode.SUPERVISED_SPLIT_NOT_EVALUABLE
        )
        warnings.append(
            _warning(
                warning_code,
                "supervised metrics are not run; transparent descriptive "
                "evidence remains available",
                "supervised_evidence",
            )
        )
    rows = _attach_model_scores(base_rows, supervised)
    queue = _build_review_queue(rows, configuration.top_k)

    labels = tuple(
        (
            item["symbol"],
            item["report_period"],
            item["declared_label_state"],
            item["effective_label_state"],
            item.get("label_available_at"),
            item.get("label_source_url"),
            item.get("label_source_quality"),
        )
        for item in normalized
    )
    financial = tuple(
        {
            key: item.get(key)
            for key in (
                "symbol",
                "report_period",
                "announced_at",
                "sector_type",
                *_TRANSPARENT_FIELDS,
            )
        }
        for item in normalized
    )
    split_payload = tuple(
        sorted({(row.symbol, row.split) for row in rows})
    )
    output_fingerprint = _hash(
        {
            "screening_rows": [item.to_dict() for item in rows],
            "review_queue": [item.to_dict() for item in queue],
            "supervised_evidence": supervised.to_dict(),
        }
    )
    audit_base = {
        "gate_status": RGateStatus.READY.value,
        "errors": [],
        "warnings": [item.to_dict() for item in warnings],
        "input_record_count": len(records),
        "accepted_record_count": len(rows),
        "label_state_counts": dict(
            _label_counts(
                item["declared_label_state"] for item in normalized
            )
        ),
        "effective_label_state_counts": dict(
            _label_counts(
                item["effective_label_state"] for item in normalized
            )
        ),
        "configuration_fingerprint": _hash(configuration.to_dict()),
        "input_fingerprint": input_fingerprint,
        "financial_input_fingerprint": _hash(financial),
        "label_input_fingerprint": _hash(labels),
        "split_fingerprint": _hash(split_payload),
        "output_fingerprint": output_fingerprint,
        "schema_version": R_SCHEMA_VERSION,
        "audit_schema_version": R_AUDIT_SCHEMA_VERSION,
        "policy_version": R_POLICY_VERSION,
        "hash_contract_version": R_HASH_CONTRACT_VERSION,
        "conclusion_boundary": R_REVIEW_BOUNDARY,
    }
    audit = FinancialP2REvidenceAudit(
        gate_status=audit_base["gate_status"],
        errors=(),
        warnings=tuple(warnings),
        input_record_count=len(records),
        accepted_record_count=len(rows),
        label_state_counts=_label_counts(
            item["declared_label_state"] for item in normalized
        ),
        effective_label_state_counts=_label_counts(
            item["effective_label_state"] for item in normalized
        ),
        configuration_fingerprint=audit_base[
            "configuration_fingerprint"
        ],
        input_fingerprint=input_fingerprint,
        financial_input_fingerprint=audit_base[
            "financial_input_fingerprint"
        ],
        label_input_fingerprint=audit_base[
            "label_input_fingerprint"
        ],
        split_fingerprint=audit_base["split_fingerprint"],
        output_fingerprint=output_fingerprint,
        schema_version=R_SCHEMA_VERSION,
        audit_schema_version=R_AUDIT_SCHEMA_VERSION,
        policy_version=R_POLICY_VERSION,
        hash_contract_version=R_HASH_CONTRACT_VERSION,
        conclusion_boundary=R_REVIEW_BOUNDARY,
        content_hash=_hash(audit_base),
    )
    return FinancialP2REvidenceResult(
        screening_rows=tuple(rows),
        review_queue=tuple(queue),
        supervised_evidence=supervised,
        evidence_audit=audit,
    )


def _normalize_records(
    records: Sequence[Mapping[str, Any]],
    configuration: FinancialP2REvidenceConfig,
) -> tuple[list[dict[str, Any]], list[RIssue], list[RIssue]]:
    normalized: list[dict[str, Any]] = []
    errors: list[RIssue] = []
    warnings: list[RIssue] = []
    seen: set[tuple[str, str]] = set()
    for index, source in enumerate(records):
        location = f"records[{index}]"
        if not isinstance(source, Mapping):
            errors.append(
                _issue(
                    RErrorCode.INVALID_RECORD,
                    "each record must be a mapping",
                    location,
                )
            )
            continue
        try:
            item = copy.deepcopy(dict(source))
            symbol = _required_text(item.get("symbol"), "symbol")
            period = _date_text(
                item.get("report_period"), "report_period"
            )
            announced = _date_text(
                item.get("announced_at"), "announced_at"
            )
            sector = _required_text(
                item.get("sector_type"), "sector_type"
            ).lower()
        except (TypeError, ValueError) as exc:
            errors.append(
                _issue(
                    RErrorCode.INVALID_RECORD,
                    str(exc),
                    location,
                )
            )
            continue
        key = (symbol, period)
        record_key = f"{symbol}/{period}"
        if key in seen:
            errors.append(
                _issue(
                    RErrorCode.DUPLICATE_RECORD_KEY,
                    "symbol/report_period must be unique",
                    "symbol,report_period",
                    record_key,
                )
            )
            continue
        seen.add(key)
        if announced > configuration.as_of:
            errors.append(
                _issue(
                    RErrorCode.FUTURE_FINANCIAL_ANNOUNCEMENT,
                    "announced_at must not be after as_of",
                    "announced_at",
                    record_key,
                )
            )
        label_state = item.get("label_state", "unlabeled")
        if label_state not in R_LABEL_STATES:
            errors.append(
                _issue(
                    RErrorCode.INVALID_LABEL_STATE,
                    f"label_state must be one of {R_LABEL_STATES}",
                    "label_state",
                    record_key,
                )
            )
            label_state = "unlabeled"
        label_available_at = item.get("label_available_at")
        label_url = item.get("label_source_url")
        label_quality = item.get("label_source_quality")
        if label_state != "unlabeled":
            try:
                label_available_at = _date_text(
                    label_available_at, "label_available_at"
                )
                label_url = _required_text(
                    label_url, "label_source_url"
                )
                label_quality = _required_text(
                    label_quality, "label_source_quality"
                )
            except (TypeError, ValueError) as exc:
                errors.append(
                    _issue(
                        RErrorCode.LABEL_METADATA_MISSING,
                        str(exc),
                        "label_metadata",
                        record_key,
                    )
                )
        else:
            label_available_at = None
            label_url = None
            label_quality = None
        effective = label_state
        if (
            label_state != "unlabeled"
            and isinstance(label_available_at, str)
            and label_available_at > configuration.as_of
        ):
            effective = "unlabeled"
            warnings.append(
                _warning(
                    RWarningCode.LABEL_NOT_YET_AVAILABLE,
                    "label is not observable at as_of and is treated as "
                    "unlabeled, never as negative",
                    "label_available_at",
                    record_key,
                )
            )
        provenance = item.get("provenance")
        if (
            not isinstance(provenance, Mapping)
            or provenance.get("synthetic_test_only") is not True
        ):
            errors.append(
                _issue(
                    RErrorCode.NON_SYNTHETIC_INPUT,
                    "every record must declare synthetic_test_only=true",
                    "provenance",
                    record_key,
                )
            )
        for field in (
            "total_assets",
            "total_liabilities",
            "net_profit",
            "operating_cash_flow",
        ):
            value = item.get(field)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float, np.number))
                or not math.isfinite(float(value))
            ):
                errors.append(
                    _issue(
                        RErrorCode.INVALID_NUMERIC_VALUE,
                        f"{field} must be finite numeric or null",
                        field,
                        record_key,
                    )
                )
        for field in (
            "receivables_growth_anomaly",
            "inventory_growth_anomaly",
            "other_receivables_anomaly",
            "non_recurring_or_asset_anomaly",
            "restated",
        ):
            value = item.get(field)
            if value is not None and not isinstance(value, bool):
                errors.append(
                    _issue(
                        RErrorCode.INVALID_RECORD,
                        f"{field} must be boolean or null",
                        field,
                        record_key,
                    )
                )
        normalized.append(
            {
                **item,
                "symbol": symbol,
                "report_period": period,
                "announced_at": announced,
                "sector_type": sector,
                "declared_label_state": label_state,
                "effective_label_state": effective,
                "label_available_at": label_available_at,
                "label_source_url": label_url,
                "label_source_quality": label_quality,
            }
        )
    normalized.sort(
        key=lambda item: (item["symbol"], item["report_period"])
    )
    return normalized, errors, warnings


def _screen_record(
    item: Mapping[str, Any],
    configuration: FinancialP2REvidenceConfig,
) -> dict[str, Any]:
    evidence: list[str] = []
    missing = tuple(
        field
        for field in _TRANSPARENT_FIELDS
        if item.get(field) is None
    )
    assets = item.get("total_assets")
    liabilities = item.get("total_liabilities")
    net_profit = item.get("net_profit")
    cash_flow = item.get("operating_cash_flow")
    sector = str(item["sector_type"])
    regulated_finance = sector in {
        "bank",
        "broker",
        "insurer",
        "banking",
        "securities",
        "insurance",
    }
    score = 0
    if (
        not regulated_finance
        and _positive(assets)
        and liabilities is not None
        and float(liabilities) / float(assets) > 0.85
    ):
        score += 12
        evidence.append("LEVERAGE_GT_85_NON_FINANCIAL:+12")
    if (
        _positive(assets)
        and net_profit is not None
        and cash_flow is not None
        and (float(net_profit) - float(cash_flow)) / float(assets) > 0.08
    ):
        score += 18
        evidence.append("ACCRUAL_DIFFERENCE_TO_ASSETS_GT_8:+18")
    if (
        net_profit is not None
        and cash_flow is not None
        and float(net_profit) < 0.0
        and float(cash_flow) > 0.0
    ):
        score += 18
        evidence.append("NEGATIVE_PROFIT_POSITIVE_OCF:+18")
    boolean_rules = (
        ("receivables_growth_anomaly", 12, "RECEIVABLES_ANOMALY:+12"),
        ("inventory_growth_anomaly", 12, "INVENTORY_ANOMALY:+12"),
        (
            "other_receivables_anomaly",
            12,
            "OTHER_RECEIVABLES_ANOMALY:+12",
        ),
        (
            "non_recurring_or_asset_anomaly",
            12,
            "NON_RECURRING_OR_ASSET_ANOMALY:+12",
        ),
    )
    for field, points, code in boolean_rules:
        if item.get(field) is True:
            score += points
            evidence.append(code)
    opinion = item.get("audit_opinion")
    if opinion is not None and str(opinion).strip().lower() not in {
        "",
        "standard_unqualified",
        "unqualified",
        "standard",
    }:
        score += 25
        evidence.append(
            f"NON_STANDARD_AUDIT_OPINION[{str(opinion).strip()}]:+25"
        )
    if item.get("restated") is True:
        score += 15
        evidence.append("RESTATEMENT_OR_CORRECTION:+15")
    return {
        "symbol": item["symbol"],
        "report_period": item["report_period"],
        "announced_at": item["announced_at"],
        "as_of": configuration.as_of,
        "sector_type": sector,
        "transparent_score": score,
        "risk_level": _risk_level(score),
        "evidence": tuple(evidence),
        "missing_fields": missing,
        "data_quality": "complete" if not missing else "partial",
        "declared_label_state": item["declared_label_state"],
        "effective_label_state": item["effective_label_state"],
        "label_available_at": item.get("label_available_at"),
        "label_source_url": item.get("label_source_url"),
        "label_source_quality": item.get("label_source_quality"),
        "split": _company_split(item["symbol"], configuration),
    }


def _build_supervised(
    rows: Sequence[Mapping[str, Any]],
    configuration: FinancialP2REvidenceConfig,
) -> FinancialRiskSupervisedEvidence:
    hard_companies = {
        row["symbol"]
        for row in rows
        if row["effective_label_state"] == "hard_positive"
    }
    train_companies = sorted(
        {row["symbol"] for row in rows if row["split"] == "train"}
    )
    test_companies = sorted(
        {row["symbol"] for row in rows if row["split"] == "test"}
    )
    train = [
        row
        for row in rows
        if row["split"] == "train"
        and row["effective_label_state"]
        in {"hard_positive", "confirmed_negative"}
    ]
    test = [
        row
        for row in rows
        if row["split"] == "test"
        and row["effective_label_state"]
        in {"hard_positive", "confirmed_negative"}
    ]
    train_y = np.asarray(
        [
            1.0 if row["effective_label_state"] == "hard_positive" else 0.0
            for row in train
        ],
        dtype=float,
    )
    test_y = np.asarray(
        [
            1.0 if row["effective_label_state"] == "hard_positive" else 0.0
            for row in test
        ],
        dtype=float,
    )
    common = {
        "positive_definition": "effective hard_positive only",
        "negative_definition": "effective confirmed_negative only",
        "excluded_label_states": ("soft_positive", "unlabeled"),
        "minimum_hard_positive_companies":
            configuration.minimum_hard_positives,
        "hard_positive_company_count": len(hard_companies),
        "train_company_count": len(train_companies),
        "test_company_count": len(test_companies),
        "train_observation_count": len(train),
        "test_observation_count": len(test),
        "train_hard_positive_count": int(train_y.sum()),
        "train_confirmed_negative_count": int(
            len(train_y) - train_y.sum()
        ),
        "test_hard_positive_count": int(test_y.sum()),
        "test_confirmed_negative_count": int(
            len(test_y) - test_y.sum()
        ),
        "top_k": configuration.top_k,
        "train_company_fingerprint": _hash(train_companies),
        "test_company_fingerprint": _hash(test_companies),
    }
    if len(hard_companies) < configuration.minimum_hard_positives:
        return _not_run_supervised(
            common,
            "HARD_POSITIVES_INSUFFICIENT",
        )
    if (
        len(set(train_y.tolist())) < 2
        or len(set(test_y.tolist())) < 2
    ):
        return _not_run_supervised(
            common,
            "COMPANY_SPLIT_CLASS_COVERAGE_INSUFFICIENT",
        )
    train_x = np.asarray(
        [float(row["transparent_score"]) / 100.0 for row in train]
    )
    beta = _fit_logistic(train_x, train_y)
    test_x = np.asarray(
        [float(row["transparent_score"]) / 100.0 for row in test]
    )
    test_scores = _sigmoid(beta[0] + beta[1] * test_x)
    calibration = _calibration_bins(
        test_y, test_scores, configuration.calibration_bins
    )
    ece = sum(
        item.observation_count / len(test_y) * float(item.absolute_gap)
        for item in calibration
        if item.absolute_gap is not None
    )
    ordered = sorted(
        range(len(test)),
        key=lambda index: (
            -float(test_scores[index]),
            test[index]["symbol"],
            test[index]["report_period"],
        ),
    )
    top_n = min(configuration.top_k, len(ordered))
    top_hit = (
        float(np.mean(test_y[ordered[:top_n]]))
        if top_n
        else None
    )
    model_fingerprint = _hash(
        {
            "model": "one_feature_logistic_calibration",
            "feature": "transparent_score_div_100",
            "intercept": float(beta[0]),
            "coefficient": float(beta[1]),
            "fit_iterations": 60,
            "l2_slope": 0.1,
        }
    )
    permutation = sorted(
        range(len(test)),
        key=lambda index: hashlib.sha256(
            (
                f"{configuration.split_salt}|negative-control|"
                f"{test[index]['symbol']}|"
                f"{test[index]['report_period']}"
            ).encode("utf-8")
        ).hexdigest(),
    )
    negative_control_y = test_y[np.asarray(permutation)]
    negative_control = {
        "protocol": "deterministic_sha256_label_permutation",
        "permutation": permutation,
        "pr_auc": _average_precision(negative_control_y, test_scores),
        "roc_auc": _roc_auc(negative_control_y, test_scores),
    }
    base = {
        **common,
        "status": RSupervisedStatus.COMPLETED.value,
        "reason_code": None,
        "pr_auc": _average_precision(test_y, test_scores),
        "roc_auc": _roc_auc(test_y, test_scores),
        "brier_score": float(np.mean((test_scores - test_y) ** 2)),
        "top_k_hit_rate": top_hit,
        "expected_calibration_error": float(ece),
        "calibration": calibration,
        "negative_control_status": "completed",
        "negative_control_pr_auc": negative_control["pr_auc"],
        "negative_control_roc_auc": negative_control["roc_auc"],
        "negative_control_fingerprint": _hash(negative_control),
        "model_fingerprint": model_fingerprint,
    }
    return FinancialRiskSupervisedEvidence(
        **base,
        content_hash=_hash(
            {
                **base,
                "calibration": [
                    item.to_dict() for item in calibration
                ],
            }
        ),
    )


def _not_run_supervised(
    common: Mapping[str, Any], reason: str
) -> FinancialRiskSupervisedEvidence:
    base = {
        **common,
        "status": RSupervisedStatus.NOT_RUN.value,
        "reason_code": reason,
        "pr_auc": None,
        "roc_auc": None,
        "brier_score": None,
        "top_k_hit_rate": None,
        "expected_calibration_error": None,
        "calibration": (),
        "negative_control_status": "not_run",
        "negative_control_pr_auc": None,
        "negative_control_roc_auc": None,
        "negative_control_fingerprint": _hash(
            {"status": "not_run", "reason_code": reason}
        ),
        "model_fingerprint": _hash(
            {"status": "not_run", "reason_code": reason}
        ),
    }
    return FinancialRiskSupervisedEvidence(
        **base,
        content_hash=_hash({**base, "calibration": []}),
    )


def _attach_model_scores(
    base_rows: Sequence[Mapping[str, Any]],
    supervised: FinancialRiskSupervisedEvidence,
) -> list[FinancialRiskScreeningRow]:
    # Refit on train labels only to reproduce the audited model fingerprint.
    train = [
        row
        for row in base_rows
        if row["split"] == "train"
        and row["effective_label_state"]
        in {"hard_positive", "confirmed_negative"}
    ]
    beta = None
    if supervised.status == RSupervisedStatus.COMPLETED.value:
        train_x = np.asarray(
            [float(row["transparent_score"]) / 100.0 for row in train]
        )
        train_y = np.asarray(
            [
                1.0
                if row["effective_label_state"] == "hard_positive"
                else 0.0
                for row in train
            ]
        )
        beta = _fit_logistic(train_x, train_y)
    output: list[FinancialRiskScreeningRow] = []
    for row in base_rows:
        score = (
            float(
                _sigmoid(
                    np.asarray(
                        [
                            beta[0]
                            + beta[1]
                            * float(row["transparent_score"])
                            / 100.0
                        ]
                    )
                )[0]
            )
            if beta is not None
            else None
        )
        base = {
            **row,
            "model_risk_score": score,
            "conclusion_boundary": R_REVIEW_BOUNDARY,
        }
        output.append(
            FinancialRiskScreeningRow(
                **base,
                content_hash=_hash(base),
            )
        )
    output.sort(key=lambda item: (item.symbol, item.report_period))
    return output


def _build_review_queue(
    rows: Sequence[FinancialRiskScreeningRow], top_k: int
) -> list[FinancialRiskReviewQueueItem]:
    ranked = sorted(
        rows,
        key=lambda item: (
            -item.transparent_score,
            item.symbol,
            item.report_period,
        ),
    )[:top_k]
    queue = []
    for rank, row in enumerate(ranked, start=1):
        base = {
            "rank": rank,
            "symbol": row.symbol,
            "report_period": row.report_period,
            "transparent_score": row.transparent_score,
            "risk_level": row.risk_level,
            "evidence": row.evidence,
            "effective_label_state": row.effective_label_state,
            "model_risk_score": row.model_risk_score,
            "conclusion_boundary": R_REVIEW_BOUNDARY,
        }
        queue.append(
            FinancialRiskReviewQueueItem(
                **base,
                content_hash=_hash(
                    {
                        **base,
                        "evidence": list(row.evidence),
                    }
                ),
            )
        )
    return queue


def _blocked_result(
    errors: tuple[RIssue, ...],
    *,
    configuration: FinancialP2REvidenceConfig | None,
    records: Any,
    warnings: tuple[RIssue, ...] = (),
    input_fingerprint: str | None = None,
) -> FinancialP2REvidenceResult:
    config_payload = (
        configuration.to_dict()
        if isinstance(configuration, FinancialP2REvidenceConfig)
        else {"configuration": "invalid"}
    )
    safe_count = (
        len(records)
        if isinstance(records, Sequence)
        and not isinstance(records, (str, bytes))
        else 0
    )
    supervised = _not_run_supervised(
        {
            "positive_definition": "effective hard_positive only",
            "negative_definition": "effective confirmed_negative only",
            "excluded_label_states": ("soft_positive", "unlabeled"),
            "minimum_hard_positive_companies":
                R_SUPERVISED_MINIMUM_HARD_POSITIVES,
            "hard_positive_company_count": 0,
            "train_company_count": 0,
            "test_company_count": 0,
            "train_observation_count": 0,
            "test_observation_count": 0,
            "train_hard_positive_count": 0,
            "train_confirmed_negative_count": 0,
            "test_hard_positive_count": 0,
            "test_confirmed_negative_count": 0,
            "top_k": configuration.top_k
            if isinstance(configuration, FinancialP2REvidenceConfig)
            else 0,
            "train_company_fingerprint": _hash([]),
            "test_company_fingerprint": _hash([]),
        },
        "GATE_BLOCKED",
    )
    input_hash = input_fingerprint or _safe_hash(records)
    audit_base = {
        "gate_status": RGateStatus.BLOCKED.value,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "input_record_count": safe_count,
        "accepted_record_count": 0,
        "label_state_counts": dict(_label_counts(())),
        "effective_label_state_counts": dict(_label_counts(())),
        "configuration_fingerprint": _hash(config_payload),
        "input_fingerprint": input_hash,
        "financial_input_fingerprint": _hash([]),
        "label_input_fingerprint": _hash([]),
        "split_fingerprint": _hash([]),
        "output_fingerprint": _hash(
            {"screening_rows": [], "review_queue": []}
        ),
        "schema_version": R_SCHEMA_VERSION,
        "audit_schema_version": R_AUDIT_SCHEMA_VERSION,
        "policy_version": R_POLICY_VERSION,
        "hash_contract_version": R_HASH_CONTRACT_VERSION,
        "conclusion_boundary": R_REVIEW_BOUNDARY,
    }
    audit = FinancialP2REvidenceAudit(
        gate_status=audit_base["gate_status"],
        errors=errors,
        warnings=warnings,
        input_record_count=safe_count,
        accepted_record_count=0,
        label_state_counts=_label_counts(()),
        effective_label_state_counts=_label_counts(()),
        configuration_fingerprint=audit_base[
            "configuration_fingerprint"
        ],
        input_fingerprint=input_hash,
        financial_input_fingerprint=audit_base[
            "financial_input_fingerprint"
        ],
        label_input_fingerprint=audit_base[
            "label_input_fingerprint"
        ],
        split_fingerprint=audit_base["split_fingerprint"],
        output_fingerprint=audit_base["output_fingerprint"],
        schema_version=R_SCHEMA_VERSION,
        audit_schema_version=R_AUDIT_SCHEMA_VERSION,
        policy_version=R_POLICY_VERSION,
        hash_contract_version=R_HASH_CONTRACT_VERSION,
        conclusion_boundary=R_REVIEW_BOUNDARY,
        content_hash=_hash(audit_base),
    )
    return FinancialP2REvidenceResult(
        screening_rows=(),
        review_queue=(),
        supervised_evidence=supervised,
        evidence_audit=audit,
    )


def _fit_logistic(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    design = np.column_stack((np.ones(len(x)), x))
    beta = np.zeros(2, dtype=float)
    regularization = np.diag([0.0, 0.1])
    for _ in range(60):
        probabilities = _sigmoid(design @ beta)
        weights = probabilities * (1.0 - probabilities)
        gradient = design.T @ (probabilities - y) + regularization @ beta
        hessian = design.T @ (weights[:, None] * design) + regularization
        beta -= np.linalg.solve(hessian + np.eye(2) * 1e-12, gradient)
    return beta


def _sigmoid(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _average_precision(y: np.ndarray, score: np.ndarray) -> float:
    order = np.argsort(-score, kind="mergesort")
    sorted_y = y[order]
    positive_count = int(sorted_y.sum())
    if positive_count == 0:
        raise ValueError("average precision requires positives")
    precision = np.cumsum(sorted_y) / np.arange(1, len(sorted_y) + 1)
    return float(np.sum(precision * sorted_y) / positive_count)


def _roc_auc(y: np.ndarray, score: np.ndarray) -> float:
    positive = score[y == 1.0]
    negative = score[y == 0.0]
    comparisons = [
        1.0 if pos > neg else 0.5 if pos == neg else 0.0
        for pos in positive
        for neg in negative
    ]
    return float(np.mean(comparisons))


def _calibration_bins(
    y: np.ndarray, score: np.ndarray, bins: int
) -> tuple[RCalibrationBin, ...]:
    output = []
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        mask = (
            (score >= lower) & (score <= upper)
            if index == bins - 1
            else (score >= lower) & (score < upper)
        )
        count = int(mask.sum())
        predicted = float(score[mask].mean()) if count else None
        observed = float(y[mask].mean()) if count else None
        gap = (
            abs(predicted - observed)
            if predicted is not None and observed is not None
            else None
        )
        output.append(
            RCalibrationBin(
                bin_index=index,
                lower_bound=lower,
                upper_bound=upper,
                observation_count=count,
                predicted_mean=predicted,
                observed_positive_rate=observed,
                absolute_gap=gap,
            )
        )
    return tuple(output)


def _company_split(
    symbol: str, configuration: FinancialP2REvidenceConfig
) -> str:
    digest = hashlib.sha256(
        f"{configuration.split_salt}|{symbol}".encode("utf-8")
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(2**64)
    return "test" if bucket < configuration.test_fraction else "train"


def _risk_level(score: int) -> str:
    if score >= 60:
        return "strong_warning"
    if score >= 35:
        return "warning"
    if score >= 15:
        return "review"
    return "low"


def _label_counts(states: Any) -> tuple[tuple[str, int], ...]:
    state_list = list(states)
    return tuple((state, state_list.count(state)) for state in R_LABEL_STATES)


def _positive(value: Any) -> bool:
    return value is not None and float(value) > 0.0


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _date_text(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name)
    try:
        parsed = dt.date.fromisoformat(normalized)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc
    if len(normalized) != 10 or parsed.year < 1900:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    return normalized


def _issue(
    code: RErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> RIssue:
    return RIssue(code.value, message, field_name, record_key)


def _warning(
    code: RWarningCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> RIssue:
    return RIssue(code.value, message, field_name, record_key)


def _hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_hash(value: Any) -> str:
    try:
        return _hash(value)
    except (TypeError, ValueError):
        return _hash({"unhashable_input_type": type(value).__name__})
