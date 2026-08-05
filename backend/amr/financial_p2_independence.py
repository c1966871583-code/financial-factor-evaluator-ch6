"""FIN-P2-INDEP: PIT-safe M/F/R independence and incremental evidence.

The module is additive and research-only.  It consumes a common factor-side
sample plus three independently timed labels, requires point-in-time industry
and size controls, and reports:

* same-type peer correlation and neutralized factor fingerprints;
* Track-M 20D Fama-MacBeth incremental evidence with public HAC t-statistics;
* Track-F next-quarter baseline-residual conditional increment; and
* Track-R hard-label versus confirmed-negative ranking increment.

Ordinary t-statistics are deliberately not part of the public result.  The
newest frozen OOS test and multiple-testing/FDR belong to FIN-P2-OOS-FDR.
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
import pandas as pd
from scipy.stats import spearmanr


INDEP_SCHEMA_VERSION = "FinancialP2Independence-v1.0"
INDEP_AUDIT_SCHEMA_VERSION = "FinancialP2IndependenceAudit-v1.0"
INDEP_FACTOR_SCHEMA_VERSION = "FinancialP2IndependenceFactor-v1.0"
INDEP_CONTINUOUS_SCHEMA_VERSION = (
    "FinancialP2ContinuousIncrement-v1.0"
)
INDEP_RISK_SCHEMA_VERSION = "FinancialP2RiskIncrement-v1.0"
INDEP_POLICY_VERSION = "FIN-P2-INDEP-POLICY-v1.0"
INDEP_HASH_CONTRACT_VERSION = "FIN-P2-INDEP-HASH-v1.0"
INDEP_TRACKS = ("M", "F", "R")
INDEP_PRIORITIES = {
    "M": "primary",
    "F": "supporting",
    "R": "risk",
}
INDEP_PREDECESSOR_TASKS = {
    "M": "FIN-P2-M-ENH",
    "F": "FIN-P2-F",
    "R": "FIN-P2-R",
}
INDEP_PREDECESSOR_OUTPUT_FINGERPRINTS = {
    "M": (
        "7496da71a9a4b6e429201c3173d903efd28e422acf07786a0c7"
        "d4d532be5b4d1"
    ),
    "F": (
        "01f82894b9b327ed661b9fe3d9fe96fcc605a3df9502cee61d6c"
        "9c0becf11282"
    ),
    "R": (
        "dd376c087244dc57098828ee5a14b840ebe7404ddc48693ebb70a"
        "609035f0327"
    ),
}
INDEP_SUPPORTED_FACTOR_IDS = ("ROE", "BP", "OCF_NP")
INDEP_MIN_CROSS_SECTION = 30
INDEP_MIN_PERIODS = 12
INDEP_MIN_R_HARD_POSITIVES = 30
INDEP_M_HORIZON = 20
INDEP_HAC_MAX_LAG = 3
INDEP_R_LABEL_STATES = (
    "hard_positive",
    "soft_positive",
    "confirmed_negative",
    "unlabeled",
)
INDEP_CONCLUSION_BOUNDARY = (
    "Synthetic research-only independence evidence; not an admission, "
    "return promise, fraud or misstatement determination, no-risk "
    "determination, or trading instruction."
)

_REQUIRED_COLUMNS = (
    "evaluation_date",
    "code",
    "factor_id",
    "factor_value",
    "peer_factor_value",
    "industry_code",
    "log_market_cap",
    "control_effective_date",
    "m_forward_return",
    "m_label_available_at",
    "f_residual",
    "f_label_available_at",
    "r_label_state",
    "r_label_available_at",
)
_FACTOR_COLUMNS = (
    "factor_value",
    "peer_factor_value",
    "log_market_cap",
)


class IndependenceGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class IndependenceEvidenceStatus(str, Enum):
    COMPLETED = "completed"
    NOT_RUN = "not_run"


class IndependenceErrorCode(str, Enum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_BATCH = "INVALID_BATCH"
    INVALID_PREDECESSOR_ANCHOR = "INVALID_PREDECESSOR_ANCHOR"
    PREDECESSOR_NOT_ACCEPTED = "PREDECESSOR_NOT_ACCEPTED"
    NON_SYNTHETIC_INPUT = "NON_SYNTHETIC_INPUT"
    MISSING_COLUMN = "MISSING_COLUMN"
    INVALID_RECORD = "INVALID_RECORD"
    DUPLICATE_FACTOR_KEY = "DUPLICATE_FACTOR_KEY"
    UNSUPPORTED_FACTOR_ID = "UNSUPPORTED_FACTOR_ID"
    CONTROL_PIT_VIOLATION = "CONTROL_PIT_VIOLATION"
    LABEL_TIMING_VIOLATION = "LABEL_TIMING_VIOLATION"
    LABEL_METADATA_MISSING = "LABEL_METADATA_MISSING"
    INVALID_R_LABEL_STATE = "INVALID_R_LABEL_STATE"
    INPUT_MUTATED = "INPUT_MUTATED"


class IndependenceWarningCode(str, Enum):
    SYNTHETIC_RESEARCH_ONLY = "SYNTHETIC_RESEARCH_ONLY"
    IN_SAMPLE_DESCRIPTIVE_ONLY = "IN_SAMPLE_DESCRIPTIVE_ONLY"
    LABEL_NOT_AVAILABLE_BY_AS_OF = "LABEL_NOT_AVAILABLE_BY_AS_OF"
    TRACK_INSUFFICIENT_SAMPLE = "TRACK_INSUFFICIENT_SAMPLE"
    R_EXCLUDED_LABEL_STATES = "R_EXCLUDED_LABEL_STATES"


@dataclass(frozen=True)
class FinancialP2IndependenceConfig:
    analysis_as_of: str
    evaluation_dates: tuple[str, ...]
    factor_ids: tuple[str, ...] = INDEP_SUPPORTED_FACTOR_IDS
    minimum_cross_section: int = INDEP_MIN_CROSS_SECTION
    minimum_periods: int = INDEP_MIN_PERIODS
    minimum_r_hard_positives: int = INDEP_MIN_R_HARD_POSITIVES
    m_horizon: int = INDEP_M_HORIZON
    hac_max_lag: int = INDEP_HAC_MAX_LAG
    controls: tuple[str, ...] = (
        "point_in_time_industry",
        "point_in_time_log_market_cap",
    )
    peer_method: str = "spearman"
    ordinary_t_stat_public: bool = False
    oos_status: str = "not_run"
    multiple_testing_status: str = "not_run"
    automatic_best_specification_selection: bool = False
    track_replacement_allowed: bool = False
    synthetic_test_only: bool = True
    schema_version: str = INDEP_SCHEMA_VERSION
    policy_version: str = INDEP_POLICY_VERSION

    def __post_init__(self) -> None:
        normalized_as_of = _date_text(
            self.analysis_as_of,
            "analysis_as_of",
        )
        normalized_dates = tuple(
            _date_text(value, "evaluation_dates")
            for value in self.evaluation_dates
        )
        if normalized_dates != tuple(sorted(set(normalized_dates))):
            raise ValueError(
                "evaluation_dates must be sorted and unique"
            )
        if len(normalized_dates) < INDEP_MIN_PERIODS:
            raise ValueError(
                f"evaluation_dates must contain at least {INDEP_MIN_PERIODS}"
            )
        if any(
            _parse_date(value) >= _parse_date(normalized_as_of)
            for value in normalized_dates
        ):
            raise ValueError(
                "evaluation_dates must precede analysis_as_of"
            )
        frozen = {
            "factor_ids": (
                tuple(self.factor_ids),
                INDEP_SUPPORTED_FACTOR_IDS,
            ),
            "minimum_cross_section": (
                self.minimum_cross_section,
                INDEP_MIN_CROSS_SECTION,
            ),
            "minimum_periods": (
                self.minimum_periods,
                INDEP_MIN_PERIODS,
            ),
            "minimum_r_hard_positives": (
                self.minimum_r_hard_positives,
                INDEP_MIN_R_HARD_POSITIVES,
            ),
            "m_horizon": (self.m_horizon, INDEP_M_HORIZON),
            "hac_max_lag": (
                self.hac_max_lag,
                INDEP_HAC_MAX_LAG,
            ),
            "controls": (
                tuple(self.controls),
                (
                    "point_in_time_industry",
                    "point_in_time_log_market_cap",
                ),
            ),
            "peer_method": (self.peer_method, "spearman"),
            "ordinary_t_stat_public": (
                self.ordinary_t_stat_public,
                False,
            ),
            "oos_status": (self.oos_status, "not_run"),
            "multiple_testing_status": (
                self.multiple_testing_status,
                "not_run",
            ),
            "automatic_best_specification_selection": (
                self.automatic_best_specification_selection,
                False,
            ),
            "track_replacement_allowed": (
                self.track_replacement_allowed,
                False,
            ),
            "synthetic_test_only": (
                self.synthetic_test_only,
                True,
            ),
            "schema_version": (
                self.schema_version,
                INDEP_SCHEMA_VERSION,
            ),
            "policy_version": (
                self.policy_version,
                INDEP_POLICY_VERSION,
            ),
        }
        for name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(
                    f"{name} must be frozen at {expected!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_as_of": self.analysis_as_of,
            "evaluation_dates": list(self.evaluation_dates),
            "factor_ids": list(self.factor_ids),
            "minimum_cross_section": self.minimum_cross_section,
            "minimum_periods": self.minimum_periods,
            "minimum_r_hard_positives":
                self.minimum_r_hard_positives,
            "m_horizon": self.m_horizon,
            "hac_max_lag": self.hac_max_lag,
            "controls": list(self.controls),
            "peer_method": self.peer_method,
            "ordinary_t_stat_public":
                self.ordinary_t_stat_public,
            "oos_status": self.oos_status,
            "multiple_testing_status":
                self.multiple_testing_status,
            "automatic_best_specification_selection":
                self.automatic_best_specification_selection,
            "track_replacement_allowed":
                self.track_replacement_allowed,
            "synthetic_test_only": self.synthetic_test_only,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True)
class FinancialP2IndependenceBatch:
    dataset_id: str
    version: str
    source: str
    _frame: pd.DataFrame
    track_anchors: Mapping[str, Mapping[str, Any]]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        _required_text(self.dataset_id, "dataset_id")
        _required_text(self.version, "version")
        _required_text(self.source, "source")
        if not isinstance(self._frame, pd.DataFrame):
            raise TypeError("_frame must be a pandas DataFrame")
        if not isinstance(self.track_anchors, Mapping):
            raise TypeError("track_anchors must be a mapping")
        if not isinstance(self.provenance, Mapping):
            raise TypeError("provenance must be a mapping")
        object.__setattr__(self, "_frame", self._frame.copy(deep=True))
        object.__setattr__(
            self,
            "track_anchors",
            copy.deepcopy(dict(self.track_anchors)),
        )
        object.__setattr__(
            self,
            "provenance",
            copy.deepcopy(dict(self.provenance)),
        )

    def get_frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)

    def get_track_anchors(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(dict(self.track_anchors))

    def get_provenance(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.provenance))


@dataclass(frozen=True)
class IndependenceIssue:
    code: str
    message: str
    field_name: str | None = None
    record_key: str | None = None
    track: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_name": self.field_name,
            "record_key": self.record_key,
            "track": self.track,
        }


@dataclass(frozen=True)
class FinancialP2ContinuousIncrement:
    factor_id: str
    validation_track: str
    evidence_priority: str
    method: str
    status: str
    reason_code: str | None
    paired_count: int
    effective_periods: int
    minimum_cross_section: int
    minimum_periods: int
    incremental_beta_mean: float | None
    incremental_beta_hac_t_stat: float | None
    incremental_r2_mean: float | None
    conditional_rank_ic_mean: float | None
    conditional_rank_ic_positive_ratio: float | None
    ordinary_t_stat_public: bool
    label_fingerprint: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "validation_track": self.validation_track,
            "evidence_priority": self.evidence_priority,
            "method": self.method,
            "status": self.status,
            "reason_code": self.reason_code,
            "paired_count": self.paired_count,
            "effective_periods": self.effective_periods,
            "minimum_cross_section": self.minimum_cross_section,
            "minimum_periods": self.minimum_periods,
            "incremental_beta_mean": self.incremental_beta_mean,
            "incremental_beta_hac_t_stat":
                self.incremental_beta_hac_t_stat,
            "incremental_r2_mean": self.incremental_r2_mean,
            "conditional_rank_ic_mean":
                self.conditional_rank_ic_mean,
            "conditional_rank_ic_positive_ratio":
                self.conditional_rank_ic_positive_ratio,
            "ordinary_t_stat_public":
                self.ordinary_t_stat_public,
            "label_fingerprint": self.label_fingerprint,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2RiskIncrement:
    factor_id: str
    validation_track: str
    evidence_priority: str
    method: str
    status: str
    reason_code: str | None
    labeled_count: int
    hard_positive_count: int
    confirmed_negative_count: int
    soft_positive_excluded_count: int
    unlabeled_excluded_count: int
    minimum_hard_positives: int
    baseline_pr_auc: float | None
    augmented_pr_auc: float | None
    incremental_pr_auc: float | None
    baseline_roc_auc: float | None
    augmented_roc_auc: float | None
    incremental_roc_auc: float | None
    negative_control_pr_auc_increment: float | None
    evaluation_scope: str
    label_fingerprint: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "validation_track": self.validation_track,
            "evidence_priority": self.evidence_priority,
            "method": self.method,
            "status": self.status,
            "reason_code": self.reason_code,
            "labeled_count": self.labeled_count,
            "hard_positive_count": self.hard_positive_count,
            "confirmed_negative_count":
                self.confirmed_negative_count,
            "soft_positive_excluded_count":
                self.soft_positive_excluded_count,
            "unlabeled_excluded_count":
                self.unlabeled_excluded_count,
            "minimum_hard_positives":
                self.minimum_hard_positives,
            "baseline_pr_auc": self.baseline_pr_auc,
            "augmented_pr_auc": self.augmented_pr_auc,
            "incremental_pr_auc": self.incremental_pr_auc,
            "baseline_roc_auc": self.baseline_roc_auc,
            "augmented_roc_auc": self.augmented_roc_auc,
            "incremental_roc_auc": self.incremental_roc_auc,
            "negative_control_pr_auc_increment":
                self.negative_control_pr_auc_increment,
            "evaluation_scope": self.evaluation_scope,
            "label_fingerprint": self.label_fingerprint,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2IndependenceFactor:
    factor_id: str
    factor_sample_count: int
    evaluation_periods: int
    peer_correlation_method: str
    same_type_peer_rank_correlation_mean: float | None
    neutralization_status: str
    controls: tuple[str, ...]
    neutralized_factor_fingerprint: str
    conditional_factor_fingerprint: str
    m_evidence: FinancialP2ContinuousIncrement
    f_evidence: FinancialP2ContinuousIncrement
    r_evidence: FinancialP2RiskIncrement
    track_replacement_allowed: bool
    automatic_best_specification_selection: bool
    oos_status: str
    multiple_testing_status: str
    conclusion: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "factor_sample_count": self.factor_sample_count,
            "evaluation_periods": self.evaluation_periods,
            "peer_correlation_method":
                self.peer_correlation_method,
            "same_type_peer_rank_correlation_mean":
                self.same_type_peer_rank_correlation_mean,
            "neutralization_status": self.neutralization_status,
            "controls": list(self.controls),
            "neutralized_factor_fingerprint":
                self.neutralized_factor_fingerprint,
            "conditional_factor_fingerprint":
                self.conditional_factor_fingerprint,
            "m_evidence": self.m_evidence.to_dict(),
            "f_evidence": self.f_evidence.to_dict(),
            "r_evidence": self.r_evidence.to_dict(),
            "track_replacement_allowed":
                self.track_replacement_allowed,
            "automatic_best_specification_selection":
                self.automatic_best_specification_selection,
            "oos_status": self.oos_status,
            "multiple_testing_status":
                self.multiple_testing_status,
            "conclusion": self.conclusion,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2IndependenceAudit:
    gate_status: str
    errors: tuple[IndependenceIssue, ...]
    warnings: tuple[IndependenceIssue, ...]
    input_row_count: int
    accepted_row_count: int
    supported_factor_ids: tuple[str, ...]
    validation_tracks: tuple[str, ...]
    predecessor_anchor_fingerprints: tuple[
        tuple[str, str], ...
    ]
    configuration_fingerprint: str
    input_fingerprint: str
    factor_sample_fingerprint: str
    control_input_fingerprint: str
    m_label_fingerprint: str
    f_label_fingerprint: str
    r_label_fingerprint: str
    output_fingerprint: str
    ordinary_t_stat_public: bool
    oos_status: str
    multiple_testing_status: str
    synthetic_test_only: bool
    conclusion_boundary: str
    schema_version: str
    audit_schema_version: str
    policy_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_status": self.gate_status,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [
                item.to_dict() for item in self.warnings
            ],
            "input_row_count": self.input_row_count,
            "accepted_row_count": self.accepted_row_count,
            "supported_factor_ids": list(self.supported_factor_ids),
            "validation_tracks": list(self.validation_tracks),
            "predecessor_anchor_fingerprints": dict(
                self.predecessor_anchor_fingerprints
            ),
            "configuration_fingerprint":
                self.configuration_fingerprint,
            "input_fingerprint": self.input_fingerprint,
            "factor_sample_fingerprint":
                self.factor_sample_fingerprint,
            "control_input_fingerprint":
                self.control_input_fingerprint,
            "m_label_fingerprint": self.m_label_fingerprint,
            "f_label_fingerprint": self.f_label_fingerprint,
            "r_label_fingerprint": self.r_label_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "ordinary_t_stat_public":
                self.ordinary_t_stat_public,
            "oos_status": self.oos_status,
            "multiple_testing_status":
                self.multiple_testing_status,
            "synthetic_test_only": self.synthetic_test_only,
            "conclusion_boundary": self.conclusion_boundary,
            "schema_version": self.schema_version,
            "audit_schema_version": self.audit_schema_version,
            "policy_version": self.policy_version,
            "hash_contract_version": self.hash_contract_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP2IndependenceResult:
    factor_evidence: tuple[FinancialP2IndependenceFactor, ...]
    independence_audit: FinancialP2IndependenceAudit

    def get_factor(
        self,
        factor_id: Any,
    ) -> FinancialP2IndependenceFactor:
        normalized = _required_text(factor_id, "factor_id")
        matches = [
            item
            for item in self.factor_evidence
            if item.factor_id == normalized
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one factor evidence for {normalized}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_evidence": [
                item.to_dict() for item in self.factor_evidence
            ],
            "independence_audit":
                self.independence_audit.to_dict(),
        }


def evaluate_financial_p2_independence(
    batch: FinancialP2IndependenceBatch,
    *,
    configuration: FinancialP2IndependenceConfig,
) -> FinancialP2IndependenceResult:
    """Evaluate deterministic, PIT-safe M/F/R incremental evidence."""

    if not isinstance(batch, FinancialP2IndependenceBatch):
        raise TypeError(
            "batch must be FinancialP2IndependenceBatch"
        )
    if not isinstance(configuration, FinancialP2IndependenceConfig):
        raise TypeError(
            "configuration must be FinancialP2IndependenceConfig"
        )

    raw_frame = batch.get_frame()
    anchors = batch.get_track_anchors()
    provenance = batch.get_provenance()
    mutation_guard = _hash(
        "independence_batch_guard",
        {
            "frame": _frame_records(raw_frame),
            "anchors": anchors,
            "provenance": provenance,
        },
    )

    errors: list[IndependenceIssue] = []
    warnings: list[IndependenceIssue] = [
        _warning(
            IndependenceWarningCode.SYNTHETIC_RESEARCH_ONLY,
            "Only deterministic synthetic research evidence is "
            "authorized.",
        ),
        _warning(
            IndependenceWarningCode.IN_SAMPLE_DESCRIPTIVE_ONLY,
            "OOS final testing and multiple-testing/FDR remain not_run.",
        ),
        _warning(
            IndependenceWarningCode.R_EXCLUDED_LABEL_STATES,
            "Track R excludes soft_positive and unlabeled from "
            "binary incremental evidence.",
            track="R",
        ),
    ]

    anchor_fingerprints = _validate_anchors(anchors, errors)
    if not bool(provenance.get("synthetic_test_only")):
        errors.append(
            _error(
                IndependenceErrorCode.NON_SYNTHETIC_INPUT,
                "provenance.synthetic_test_only must be true",
                field_name="provenance.synthetic_test_only",
            )
        )

    normalized = _normalize_frame(
        raw_frame,
        configuration=configuration,
        errors=errors,
        warnings=warnings,
    )
    input_fingerprint = _hash(
        "independence_raw_input",
        _frame_records(raw_frame),
    )
    factor_sample_fingerprint = _factor_sample_hash(normalized)
    control_input_fingerprint = _control_hash(normalized)
    label_hashes = {
        track: _label_hash(normalized, track)
        for track in INDEP_TRACKS
    }

    if errors:
        return _blocked_result(
            batch=batch,
            configuration=configuration,
            raw_frame=raw_frame,
            normalized=normalized,
            errors=errors,
            warnings=warnings,
            anchor_fingerprints=anchor_fingerprints,
            input_fingerprint=input_fingerprint,
            factor_sample_fingerprint=factor_sample_fingerprint,
            control_input_fingerprint=control_input_fingerprint,
            label_hashes=label_hashes,
            mutation_guard=mutation_guard,
        )

    factor_results: list[FinancialP2IndependenceFactor] = []
    for factor_id in configuration.factor_ids:
        factor_frame = normalized[
            normalized["factor_id"] == factor_id
        ].copy()
        prepared = _prepare_factor_controls(factor_frame)
        factor_result, factor_warnings = _build_factor_evidence(
            factor_id,
            prepared,
            configuration=configuration,
        )
        factor_results.append(factor_result)
        warnings.extend(factor_warnings)

    output_fingerprint = _hash(
        "independence_output",
        [item.to_dict() for item in factor_results],
    )

    current_guard = _hash(
        "independence_batch_guard",
        {
            "frame": _frame_records(batch.get_frame()),
            "anchors": batch.get_track_anchors(),
            "provenance": batch.get_provenance(),
        },
    )
    if current_guard != mutation_guard:
        errors.append(
            _error(
                IndependenceErrorCode.INPUT_MUTATED,
                "input batch changed during evaluation",
            )
        )
        return _blocked_result(
            batch=batch,
            configuration=configuration,
            raw_frame=raw_frame,
            normalized=normalized,
            errors=errors,
            warnings=warnings,
            anchor_fingerprints=anchor_fingerprints,
            input_fingerprint=input_fingerprint,
            factor_sample_fingerprint=factor_sample_fingerprint,
            control_input_fingerprint=control_input_fingerprint,
            label_hashes=label_hashes,
            mutation_guard=current_guard,
        )

    audit = _build_audit(
        gate_status=IndependenceGateStatus.READY.value,
        configuration=configuration,
        input_row_count=len(raw_frame),
        accepted_row_count=len(normalized),
        errors=(),
        warnings=_deduplicate_issues(warnings),
        anchor_fingerprints=anchor_fingerprints,
        input_fingerprint=input_fingerprint,
        factor_sample_fingerprint=factor_sample_fingerprint,
        control_input_fingerprint=control_input_fingerprint,
        label_hashes=label_hashes,
        output_fingerprint=output_fingerprint,
    )
    return FinancialP2IndependenceResult(
        factor_evidence=tuple(factor_results),
        independence_audit=audit,
    )


def _validate_anchors(
    anchors: Mapping[str, Mapping[str, Any]],
    errors: list[IndependenceIssue],
) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    if set(anchors) != set(INDEP_TRACKS):
        errors.append(
            _error(
                IndependenceErrorCode.INVALID_PREDECESSOR_ANCHOR,
                "track_anchors must contain exactly M, F, and R",
                field_name="track_anchors",
            )
        )
    for track in INDEP_TRACKS:
        anchor = anchors.get(track)
        if not isinstance(anchor, Mapping):
            errors.append(
                _error(
                    IndependenceErrorCode.INVALID_PREDECESSOR_ANCHOR,
                    f"missing mapping anchor for Track {track}",
                    field_name=f"track_anchors.{track}",
                    track=track,
                )
            )
            continue
        task_id = anchor.get("task_id")
        status = str(anchor.get("status", "")).upper()
        priority = anchor.get("evidence_priority")
        fingerprint = anchor.get("output_fingerprint")
        if task_id != INDEP_PREDECESSOR_TASKS[track]:
            errors.append(
                _error(
                    IndependenceErrorCode.INVALID_PREDECESSOR_ANCHOR,
                    f"Track {track} task_id does not match the "
                    "frozen predecessor",
                    field_name=f"track_anchors.{track}.task_id",
                    track=track,
                )
            )
        if status != "ACCEPTED":
            errors.append(
                _error(
                    IndependenceErrorCode.PREDECESSOR_NOT_ACCEPTED,
                    f"Track {track} predecessor must be ACCEPTED",
                    field_name=f"track_anchors.{track}.status",
                    track=track,
                )
            )
        if priority != INDEP_PRIORITIES[track]:
            errors.append(
                _error(
                    IndependenceErrorCode.INVALID_PREDECESSOR_ANCHOR,
                    f"Track {track} evidence priority must remain "
                    f"{INDEP_PRIORITIES[track]}",
                    field_name=(
                        f"track_anchors.{track}.evidence_priority"
                    ),
                    track=track,
                )
            )
        if not _is_sha256(fingerprint):
            errors.append(
                _error(
                    IndependenceErrorCode.INVALID_PREDECESSOR_ANCHOR,
                    f"Track {track} output_fingerprint must be SHA-256",
                    field_name=(
                        f"track_anchors.{track}.output_fingerprint"
                    ),
                    track=track,
                )
            )
        elif fingerprint != INDEP_PREDECESSOR_OUTPUT_FINGERPRINTS[
            track
        ]:
            errors.append(
                _error(
                    IndependenceErrorCode.INVALID_PREDECESSOR_ANCHOR,
                    f"Track {track} output_fingerprint does not match "
                    "the frozen accepted predecessor",
                    field_name=(
                        f"track_anchors.{track}.output_fingerprint"
                    ),
                    track=track,
                )
            )
        else:
            fingerprints[track] = str(fingerprint)
    return fingerprints


def _normalize_frame(
    frame: pd.DataFrame,
    *,
    configuration: FinancialP2IndependenceConfig,
    errors: list[IndependenceIssue],
    warnings: list[IndependenceIssue],
) -> pd.DataFrame:
    missing = [
        column
        for column in _REQUIRED_COLUMNS
        if column not in frame.columns
    ]
    for column in missing:
        errors.append(
            _error(
                IndependenceErrorCode.MISSING_COLUMN,
                f"required column {column!r} is missing",
                field_name=column,
            )
        )
    if missing:
        return pd.DataFrame(columns=_REQUIRED_COLUMNS)

    records: list[dict[str, Any]] = []
    analysis_as_of = _parse_date(configuration.analysis_as_of)
    configured_dates = set(configuration.evaluation_dates)
    for index, raw in enumerate(
        frame.loc[:, _REQUIRED_COLUMNS].to_dict(orient="records")
    ):
        record_key = f"row={index}"
        try:
            evaluation_date = _date_text(
                raw["evaluation_date"],
                "evaluation_date",
            )
            code = _required_text(raw["code"], "code")
            factor_id = _required_text(
                raw["factor_id"],
                "factor_id",
            )
            if factor_id not in INDEP_SUPPORTED_FACTOR_IDS:
                errors.append(
                    _error(
                        IndependenceErrorCode.UNSUPPORTED_FACTOR_ID,
                        f"unsupported factor_id {factor_id!r}",
                        field_name="factor_id",
                        record_key=record_key,
                    )
                )
                continue
            if evaluation_date not in configured_dates:
                continue
            control_effective = _date_text(
                raw["control_effective_date"],
                "control_effective_date",
            )
            if _parse_date(control_effective) > _parse_date(
                evaluation_date
            ):
                errors.append(
                    _error(
                        IndependenceErrorCode.CONTROL_PIT_VIOLATION,
                        "industry/size controls are not effective by "
                        "evaluation_date",
                        field_name="control_effective_date",
                        record_key=(
                            f"{evaluation_date}/{code}/{factor_id}"
                        ),
                    )
                )
                continue
            values = {
                column: _finite_float(raw[column], column)
                for column in _FACTOR_COLUMNS
            }
            industry_code = _required_text(
                raw["industry_code"],
                "industry_code",
            )
            m_value, m_available = _normalize_continuous_label(
                raw["m_forward_return"],
                raw["m_label_available_at"],
                evaluation_date=evaluation_date,
                analysis_as_of=analysis_as_of,
                track="M",
                record_key=record_key,
                errors=errors,
                warnings=warnings,
            )
            f_value, f_available = _normalize_continuous_label(
                raw["f_residual"],
                raw["f_label_available_at"],
                evaluation_date=evaluation_date,
                analysis_as_of=analysis_as_of,
                track="F",
                record_key=record_key,
                errors=errors,
                warnings=warnings,
            )
            r_state, r_available = _normalize_r_label(
                raw["r_label_state"],
                raw["r_label_available_at"],
                evaluation_date=evaluation_date,
                analysis_as_of=analysis_as_of,
                record_key=record_key,
                errors=errors,
                warnings=warnings,
            )
            records.append(
                {
                    "evaluation_date": evaluation_date,
                    "code": code,
                    "factor_id": factor_id,
                    **values,
                    "industry_code": industry_code,
                    "control_effective_date": control_effective,
                    "m_forward_return": m_value,
                    "m_label_available_at": m_available,
                    "f_residual": f_value,
                    "f_label_available_at": f_available,
                    "r_label_state": r_state,
                    "r_label_available_at": r_available,
                }
            )
        except (TypeError, ValueError) as exc:
            errors.append(
                _error(
                    IndependenceErrorCode.INVALID_RECORD,
                    str(exc),
                    record_key=record_key,
                )
            )

    normalized = pd.DataFrame.from_records(
        records,
        columns=_REQUIRED_COLUMNS,
    )
    if normalized.empty:
        return normalized
    duplicated = normalized.duplicated(
        subset=["evaluation_date", "code", "factor_id"],
        keep=False,
    )
    if bool(duplicated.any()):
        for row in normalized.loc[
            duplicated,
            ["evaluation_date", "code", "factor_id"],
        ].drop_duplicates().to_dict(orient="records"):
            errors.append(
                _error(
                    IndependenceErrorCode.DUPLICATE_FACTOR_KEY,
                    "duplicate factor-side key",
                    record_key=(
                        f"{row['evaluation_date']}/"
                        f"{row['code']}/{row['factor_id']}"
                    ),
                )
            )
    return normalized.sort_values(
        ["factor_id", "evaluation_date", "code"],
        kind="stable",
    ).reset_index(drop=True)


def _normalize_continuous_label(
    value: Any,
    available_at: Any,
    *,
    evaluation_date: str,
    analysis_as_of: dt.date,
    track: str,
    record_key: str,
    errors: list[IndependenceIssue],
    warnings: list[IndependenceIssue],
) -> tuple[float | None, str | None]:
    value_missing = _missing(value)
    date_missing = _missing(available_at)
    if value_missing and date_missing:
        return None, None
    if value_missing != date_missing:
        errors.append(
            _error(
                IndependenceErrorCode.LABEL_METADATA_MISSING,
                f"Track {track} label and availability must be "
                "present or absent together",
                field_name=f"{track.lower()}_label_available_at",
                record_key=record_key,
                track=track,
            )
        )
        return None, None
    normalized_date = _date_text(
        available_at,
        f"{track.lower()}_label_available_at",
    )
    available_date = _parse_date(normalized_date)
    if available_date <= _parse_date(evaluation_date):
        errors.append(
            _error(
                IndependenceErrorCode.LABEL_TIMING_VIOLATION,
                f"Track {track} outcome must occur after "
                "evaluation_date",
                field_name=f"{track.lower()}_label_available_at",
                record_key=record_key,
                track=track,
            )
        )
        return None, None
    if available_date > analysis_as_of:
        warnings.append(
            _warning(
                IndependenceWarningCode.LABEL_NOT_AVAILABLE_BY_AS_OF,
                f"Track {track} label is not available by analysis_as_of",
                record_key=record_key,
                track=track,
            )
        )
        return None, None
    return _finite_float(value, f"{track.lower()}_label"), normalized_date


def _normalize_r_label(
    state: Any,
    available_at: Any,
    *,
    evaluation_date: str,
    analysis_as_of: dt.date,
    record_key: str,
    errors: list[IndependenceIssue],
    warnings: list[IndependenceIssue],
) -> tuple[str, str | None]:
    normalized_state = _required_text(state, "r_label_state")
    if normalized_state not in INDEP_R_LABEL_STATES:
        errors.append(
            _error(
                IndependenceErrorCode.INVALID_R_LABEL_STATE,
                f"invalid R label state {normalized_state!r}",
                field_name="r_label_state",
                record_key=record_key,
                track="R",
            )
        )
        return "unlabeled", None
    if normalized_state == "unlabeled":
        if not _missing(available_at):
            errors.append(
                _error(
                    IndependenceErrorCode.LABEL_TIMING_VIOLATION,
                    "unlabeled R rows cannot have label availability",
                    field_name="r_label_available_at",
                    record_key=record_key,
                    track="R",
                )
            )
        return "unlabeled", None
    if _missing(available_at):
        errors.append(
            _error(
                IndependenceErrorCode.LABEL_METADATA_MISSING,
                "labeled R rows require label availability metadata",
                field_name="r_label_available_at",
                record_key=record_key,
                track="R",
            )
        )
        return "unlabeled", None
    normalized_date = _date_text(
        available_at,
        "r_label_available_at",
    )
    available_date = _parse_date(normalized_date)
    if available_date <= _parse_date(evaluation_date):
        errors.append(
            _error(
                IndependenceErrorCode.LABEL_TIMING_VIOLATION,
                "R outcome must occur after evaluation_date",
                field_name="r_label_available_at",
                record_key=record_key,
                track="R",
            )
        )
        return "unlabeled", None
    if available_date > analysis_as_of:
        warnings.append(
            _warning(
                IndependenceWarningCode.LABEL_NOT_AVAILABLE_BY_AS_OF,
                "R label is not available by analysis_as_of",
                record_key=record_key,
                track="R",
            )
        )
        return "unlabeled", None
    return normalized_state, normalized_date


def _prepare_factor_controls(frame: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for _, group in frame.groupby("evaluation_date", sort=True):
        prepared = group.copy()
        industry = _industry_matrix(prepared["industry_code"])
        size = _zscore(prepared["log_market_cap"].to_numpy(float))
        controls = np.column_stack(
            [np.ones(len(prepared)), size, industry]
        )
        factor = _zscore(prepared["factor_value"].to_numpy(float))
        peer = _zscore(
            prepared["peer_factor_value"].to_numpy(float)
        )
        factor_neutral = _residualize(factor, controls)
        peer_neutral = _residualize(peer, controls)
        conditional = _residualize(
            factor_neutral,
            np.column_stack(
                [np.ones(len(prepared)), peer_neutral]
            ),
        )
        prepared["_size_z"] = size
        prepared["_factor_z"] = factor
        prepared["_peer_z"] = peer
        prepared["_factor_neutral"] = _zscore(factor_neutral)
        prepared["_peer_neutral"] = _zscore(peer_neutral)
        prepared["_factor_conditional"] = _zscore(conditional)
        pieces.append(prepared)
    if not pieces:
        return frame.copy()
    return pd.concat(pieces, ignore_index=True).sort_values(
        ["evaluation_date", "code"],
        kind="stable",
    ).reset_index(drop=True)


def _build_factor_evidence(
    factor_id: str,
    frame: pd.DataFrame,
    *,
    configuration: FinancialP2IndependenceConfig,
) -> tuple[
    FinancialP2IndependenceFactor,
    list[IndependenceIssue],
]:
    warnings: list[IndependenceIssue] = []
    peer_correlations: list[float] = []
    for _, group in frame.groupby("evaluation_date", sort=True):
        correlation = _spearman(
            group["factor_value"].to_numpy(float),
            group["peer_factor_value"].to_numpy(float),
        )
        if correlation is not None:
            peer_correlations.append(correlation)

    m_evidence = _continuous_increment(
        factor_id,
        frame,
        track="M",
        label_column="m_forward_return",
        label_available_column="m_label_available_at",
        method="fama_macbeth_20d_conditional_increment",
        configuration=configuration,
    )
    f_evidence = _continuous_increment(
        factor_id,
        frame,
        track="F",
        label_column="f_residual",
        label_available_column="f_label_available_at",
        method="next_quarter_residual_conditional_increment",
        configuration=configuration,
    )
    r_evidence = _risk_increment(
        factor_id,
        frame,
        configuration=configuration,
    )
    for track, evidence in (
        ("M", m_evidence),
        ("F", f_evidence),
        ("R", r_evidence),
    ):
        if evidence.status != IndependenceEvidenceStatus.COMPLETED.value:
            warnings.append(
                _warning(
                    IndependenceWarningCode.TRACK_INSUFFICIENT_SAMPLE,
                    f"Track {track} evidence is not_run: "
                    f"{evidence.reason_code}",
                    track=track,
                )
            )

    neutralized_fingerprint = _hash(
        "neutralized_factor",
        _records_for_hash(
            frame,
            ["evaluation_date", "code", "_factor_neutral"],
        ),
    )
    conditional_fingerprint = _hash(
        "conditional_factor",
        _records_for_hash(
            frame,
            [
                "evaluation_date",
                "code",
                "_factor_conditional",
            ],
        ),
    )
    payload = {
        "factor_id": factor_id,
        "factor_sample_count": len(frame),
        "evaluation_periods": int(
            frame["evaluation_date"].nunique()
        ),
        "peer_correlation_method": "spearman",
        "same_type_peer_rank_correlation_mean":
            _mean_or_none(peer_correlations),
        "neutralization_status": "completed",
        "controls": [
            "point_in_time_industry",
            "point_in_time_log_market_cap",
        ],
        "neutralized_factor_fingerprint":
            neutralized_fingerprint,
        "conditional_factor_fingerprint":
            conditional_fingerprint,
        "m_evidence": m_evidence.to_dict(),
        "f_evidence": f_evidence.to_dict(),
        "r_evidence": r_evidence.to_dict(),
        "track_replacement_allowed": False,
        "automatic_best_specification_selection": False,
        "oos_status": "not_run",
        "multiple_testing_status": "not_run",
        "conclusion": "exploratory",
        "schema_version": INDEP_FACTOR_SCHEMA_VERSION,
    }
    content_hash = _hash("independence_factor", payload)
    return (
        FinancialP2IndependenceFactor(
            factor_id=factor_id,
            factor_sample_count=len(frame),
            evaluation_periods=int(
                frame["evaluation_date"].nunique()
            ),
            peer_correlation_method="spearman",
            same_type_peer_rank_correlation_mean=
                _mean_or_none(peer_correlations),
            neutralization_status="completed",
            controls=(
                "point_in_time_industry",
                "point_in_time_log_market_cap",
            ),
            neutralized_factor_fingerprint=
                neutralized_fingerprint,
            conditional_factor_fingerprint=
                conditional_fingerprint,
            m_evidence=m_evidence,
            f_evidence=f_evidence,
            r_evidence=r_evidence,
            track_replacement_allowed=False,
            automatic_best_specification_selection=False,
            oos_status="not_run",
            multiple_testing_status="not_run",
            conclusion="exploratory",
            schema_version=INDEP_FACTOR_SCHEMA_VERSION,
            content_hash=content_hash,
        ),
        warnings,
    )


def _continuous_increment(
    factor_id: str,
    frame: pd.DataFrame,
    *,
    track: str,
    label_column: str,
    label_available_column: str,
    method: str,
    configuration: FinancialP2IndependenceConfig,
) -> FinancialP2ContinuousIncrement:
    paired = frame[
        frame[label_column].notna()
        & frame[label_available_column].notna()
    ].copy()
    label_fingerprint = _hash(
        f"{track}_continuous_labels",
        _records_for_hash(
            paired,
            [
                "evaluation_date",
                "code",
                label_column,
                label_available_column,
            ],
        ),
    )
    betas: list[float] = []
    increments: list[float] = []
    rank_ics: list[float] = []
    paired_count = 0
    for _, group in paired.groupby("evaluation_date", sort=True):
        if len(group) < configuration.minimum_cross_section:
            continue
        y = group[label_column].to_numpy(float)
        if _is_constant(y):
            continue
        baseline = _period_design(group, include_factor=False)
        augmented = _period_design(group, include_factor=True)
        baseline_beta = _ols(baseline, y)
        augmented_beta = _ols(augmented, y)
        baseline_prediction = baseline @ baseline_beta
        augmented_prediction = augmented @ augmented_beta
        residual = y - baseline_prediction
        rank_ic = _spearman(
            group["_factor_conditional"].to_numpy(float),
            residual,
        )
        betas.append(float(augmented_beta[-1]))
        increments.append(
            max(
                -1.0,
                min(
                    1.0,
                    _r_squared(y, augmented_prediction)
                    - _r_squared(y, baseline_prediction),
                ),
            )
        )
        if rank_ic is not None:
            rank_ics.append(rank_ic)
        paired_count += len(group)

    if len(betas) < configuration.minimum_periods:
        return _not_run_continuous(
            factor_id,
            track=track,
            method=method,
            reason_code="INSUFFICIENT_EFFECTIVE_PERIODS",
            paired_count=paired_count,
            effective_periods=len(betas),
            label_fingerprint=label_fingerprint,
            configuration=configuration,
        )
    payload = {
        "factor_id": factor_id,
        "validation_track": track,
        "evidence_priority": INDEP_PRIORITIES[track],
        "method": method,
        "status": IndependenceEvidenceStatus.COMPLETED.value,
        "reason_code": None,
        "paired_count": paired_count,
        "effective_periods": len(betas),
        "minimum_cross_section":
            configuration.minimum_cross_section,
        "minimum_periods": configuration.minimum_periods,
        "incremental_beta_mean": _mean_or_none(betas),
        "incremental_beta_hac_t_stat":
            _hac_t_stat(betas, configuration.hac_max_lag),
        "incremental_r2_mean": _mean_or_none(increments),
        "conditional_rank_ic_mean":
            _mean_or_none(rank_ics),
        "conditional_rank_ic_positive_ratio":
            _positive_ratio(rank_ics),
        "ordinary_t_stat_public": False,
        "label_fingerprint": label_fingerprint,
        "schema_version": INDEP_CONTINUOUS_SCHEMA_VERSION,
    }
    return FinancialP2ContinuousIncrement(
        **payload,
        content_hash=_hash("continuous_increment", payload),
    )


def _not_run_continuous(
    factor_id: str,
    *,
    track: str,
    method: str,
    reason_code: str,
    paired_count: int,
    effective_periods: int,
    label_fingerprint: str,
    configuration: FinancialP2IndependenceConfig,
) -> FinancialP2ContinuousIncrement:
    payload = {
        "factor_id": factor_id,
        "validation_track": track,
        "evidence_priority": INDEP_PRIORITIES[track],
        "method": method,
        "status": IndependenceEvidenceStatus.NOT_RUN.value,
        "reason_code": reason_code,
        "paired_count": paired_count,
        "effective_periods": effective_periods,
        "minimum_cross_section":
            configuration.minimum_cross_section,
        "minimum_periods": configuration.minimum_periods,
        "incremental_beta_mean": None,
        "incremental_beta_hac_t_stat": None,
        "incremental_r2_mean": None,
        "conditional_rank_ic_mean": None,
        "conditional_rank_ic_positive_ratio": None,
        "ordinary_t_stat_public": False,
        "label_fingerprint": label_fingerprint,
        "schema_version": INDEP_CONTINUOUS_SCHEMA_VERSION,
    }
    return FinancialP2ContinuousIncrement(
        **payload,
        content_hash=_hash("continuous_increment", payload),
    )


def _risk_increment(
    factor_id: str,
    frame: pd.DataFrame,
    *,
    configuration: FinancialP2IndependenceConfig,
) -> FinancialP2RiskIncrement:
    counts = frame["r_label_state"].value_counts().to_dict()
    hard_count = int(counts.get("hard_positive", 0))
    negative_count = int(counts.get("confirmed_negative", 0))
    soft_count = int(counts.get("soft_positive", 0))
    unlabeled_count = int(counts.get("unlabeled", 0))
    labeled = frame[
        frame["r_label_state"].isin(
            ["hard_positive", "confirmed_negative"]
        )
        & frame["r_label_available_at"].notna()
    ].copy()
    label_fingerprint = _hash(
        "R_labels",
        _records_for_hash(
            frame,
            [
                "evaluation_date",
                "code",
                "r_label_state",
                "r_label_available_at",
            ],
        ),
    )
    if (
        hard_count < configuration.minimum_r_hard_positives
        or negative_count < 1
    ):
        return _not_run_risk(
            factor_id,
            reason_code="INSUFFICIENT_HARD_LABELS",
            labeled_count=len(labeled),
            hard_count=hard_count,
            negative_count=negative_count,
            soft_count=soft_count,
            unlabeled_count=unlabeled_count,
            label_fingerprint=label_fingerprint,
            configuration=configuration,
        )

    y = (
        labeled["r_label_state"] == "hard_positive"
    ).astype(float).to_numpy()
    baseline = _pooled_risk_design(labeled, include_factor=False)
    augmented = _pooled_risk_design(labeled, include_factor=True)
    baseline_score = _sigmoid(
        baseline @ _fit_logistic(baseline, y)
    )
    augmented_score = _sigmoid(
        augmented @ _fit_logistic(augmented, y)
    )
    baseline_pr = _average_precision(y, baseline_score)
    augmented_pr = _average_precision(y, augmented_score)
    baseline_roc = _roc_auc(y, baseline_score)
    augmented_roc = _roc_auc(y, augmented_score)

    negative_control = labeled.copy()
    negative_control["_negative_control_factor"] = (
        negative_control.groupby(
            "evaluation_date",
            sort=True,
        )["_factor_conditional"].transform(
            _deterministic_permutation
        )
    )
    negative_design = _pooled_risk_design(
        negative_control,
        include_factor=True,
        factor_column="_negative_control_factor",
    )
    negative_score = _sigmoid(
        negative_design @ _fit_logistic(negative_design, y)
    )
    negative_pr = _average_precision(y, negative_score)

    payload = {
        "factor_id": factor_id,
        "validation_track": "R",
        "evidence_priority": INDEP_PRIORITIES["R"],
        "method": "hard_label_conditional_ranking_increment",
        "status": IndependenceEvidenceStatus.COMPLETED.value,
        "reason_code": None,
        "labeled_count": len(labeled),
        "hard_positive_count": hard_count,
        "confirmed_negative_count": negative_count,
        "soft_positive_excluded_count": soft_count,
        "unlabeled_excluded_count": unlabeled_count,
        "minimum_hard_positives":
            configuration.minimum_r_hard_positives,
        "baseline_pr_auc": baseline_pr,
        "augmented_pr_auc": augmented_pr,
        "incremental_pr_auc": augmented_pr - baseline_pr,
        "baseline_roc_auc": baseline_roc,
        "augmented_roc_auc": augmented_roc,
        "incremental_roc_auc": augmented_roc - baseline_roc,
        "negative_control_pr_auc_increment":
            negative_pr - baseline_pr,
        "evaluation_scope": "descriptive_in_sample_only",
        "label_fingerprint": label_fingerprint,
        "schema_version": INDEP_RISK_SCHEMA_VERSION,
    }
    return FinancialP2RiskIncrement(
        **payload,
        content_hash=_hash("risk_increment", payload),
    )


def _not_run_risk(
    factor_id: str,
    *,
    reason_code: str,
    labeled_count: int,
    hard_count: int,
    negative_count: int,
    soft_count: int,
    unlabeled_count: int,
    label_fingerprint: str,
    configuration: FinancialP2IndependenceConfig,
) -> FinancialP2RiskIncrement:
    payload = {
        "factor_id": factor_id,
        "validation_track": "R",
        "evidence_priority": INDEP_PRIORITIES["R"],
        "method": "hard_label_conditional_ranking_increment",
        "status": IndependenceEvidenceStatus.NOT_RUN.value,
        "reason_code": reason_code,
        "labeled_count": labeled_count,
        "hard_positive_count": hard_count,
        "confirmed_negative_count": negative_count,
        "soft_positive_excluded_count": soft_count,
        "unlabeled_excluded_count": unlabeled_count,
        "minimum_hard_positives":
            configuration.minimum_r_hard_positives,
        "baseline_pr_auc": None,
        "augmented_pr_auc": None,
        "incremental_pr_auc": None,
        "baseline_roc_auc": None,
        "augmented_roc_auc": None,
        "incremental_roc_auc": None,
        "negative_control_pr_auc_increment": None,
        "evaluation_scope": "descriptive_in_sample_only",
        "label_fingerprint": label_fingerprint,
        "schema_version": INDEP_RISK_SCHEMA_VERSION,
    }
    return FinancialP2RiskIncrement(
        **payload,
        content_hash=_hash("risk_increment", payload),
    )


def _period_design(
    group: pd.DataFrame,
    *,
    include_factor: bool,
) -> np.ndarray:
    industry = _industry_matrix(group["industry_code"])
    columns = [
        np.ones(len(group)),
        group["_size_z"].to_numpy(float),
        group["_peer_neutral"].to_numpy(float),
    ]
    if industry.shape[1]:
        columns.extend(
            industry[:, index]
            for index in range(industry.shape[1])
        )
    if include_factor:
        columns.append(
            group["_factor_conditional"].to_numpy(float)
        )
    return np.column_stack(columns)


def _pooled_risk_design(
    frame: pd.DataFrame,
    *,
    include_factor: bool,
    factor_column: str = "_factor_conditional",
) -> np.ndarray:
    industries = _category_matrix(frame["industry_code"])
    dates = _category_matrix(frame["evaluation_date"])
    columns = [
        np.ones(len(frame)),
        frame["_size_z"].to_numpy(float),
        frame["_peer_neutral"].to_numpy(float),
    ]
    for matrix in (industries, dates):
        if matrix.shape[1]:
            columns.extend(
                matrix[:, index]
                for index in range(matrix.shape[1])
            )
    if include_factor:
        columns.append(frame[factor_column].to_numpy(float))
    return np.column_stack(columns)


def _industry_matrix(values: pd.Series) -> np.ndarray:
    return _category_matrix(values)


def _category_matrix(values: pd.Series) -> np.ndarray:
    categories = sorted(str(value) for value in values.unique())
    if len(categories) <= 1:
        return np.empty((len(values), 0), dtype=float)
    return np.column_stack(
        [
            (values.astype(str).to_numpy() == category).astype(float)
            for category in categories[1:]
        ]
    )


def _ols(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(x, y, rcond=None)[0]


def _residualize(values: np.ndarray, controls: np.ndarray) -> np.ndarray:
    return values - controls @ _ols(controls, values)


def _r_squared(actual: np.ndarray, predicted: np.ndarray) -> float:
    denominator = float(np.sum((actual - np.mean(actual)) ** 2))
    if denominator <= 1e-15:
        return 0.0
    numerator = float(np.sum((actual - predicted) ** 2))
    return 1.0 - numerator / denominator


def _hac_t_stat(values: Sequence[float], max_lag: int) -> float | None:
    array = np.asarray(values, dtype=float)
    if len(array) < 2 or _is_constant(array):
        return None
    centered = array - float(np.mean(array))
    long_run = float(np.dot(centered, centered) / len(array))
    lag_limit = min(max_lag, len(array) - 1)
    for lag in range(1, lag_limit + 1):
        weight = 1.0 - lag / (lag_limit + 1.0)
        covariance = float(
            np.dot(centered[lag:], centered[:-lag]) / len(array)
        )
        long_run += 2.0 * weight * covariance
    variance = max(long_run / len(array), 0.0)
    if variance <= 1e-15:
        return None
    return float(np.mean(array) / math.sqrt(variance))


def _fit_logistic(
    x: np.ndarray,
    y: np.ndarray,
    *,
    ridge: float = 1e-4,
    iterations: int = 80,
) -> np.ndarray:
    beta = np.zeros(x.shape[1], dtype=float)
    penalty = np.eye(x.shape[1], dtype=float) * ridge
    penalty[0, 0] = 0.0
    for _ in range(iterations):
        probability = _sigmoid(x @ beta)
        weight = np.clip(
            probability * (1.0 - probability),
            1e-6,
            None,
        )
        working = (
            x @ beta + (y - probability) / weight
        )
        weighted_x = x * np.sqrt(weight)[:, None]
        weighted_y = working * np.sqrt(weight)
        next_beta = np.linalg.solve(
            weighted_x.T @ weighted_x + penalty,
            weighted_x.T @ weighted_y,
        )
        if np.max(np.abs(next_beta - beta)) < 1e-10:
            beta = next_beta
            break
        beta = next_beta
    return beta


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _average_precision(actual: np.ndarray, score: np.ndarray) -> float:
    order = np.argsort(-score, kind="stable")
    ordered = actual[order]
    positives = int(np.sum(ordered))
    if positives == 0:
        return 0.0
    cumulative = np.cumsum(ordered)
    precision = cumulative / np.arange(1, len(ordered) + 1)
    return float(np.sum(precision * ordered) / positives)


def _roc_auc(actual: np.ndarray, score: np.ndarray) -> float:
    positives = score[actual == 1.0]
    negatives = score[actual == 0.0]
    if len(positives) == 0 or len(negatives) == 0:
        return 0.5
    comparisons = (
        positives[:, None] > negatives[None, :]
    ).astype(float)
    ties = (
        positives[:, None] == negatives[None, :]
    ).astype(float)
    return float(np.mean(comparisons + 0.5 * ties))


def _spearman(
    left: np.ndarray,
    right: np.ndarray,
) -> float | None:
    if len(left) < 2 or _is_constant(left) or _is_constant(right):
        return None
    result = spearmanr(left, right, nan_policy="omit")
    value = float(result.statistic)
    if not math.isfinite(value):
        return None
    return value


def _zscore(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    mean = float(np.mean(array))
    std = float(np.std(array, ddof=0))
    if std <= 1e-12:
        return np.zeros_like(array, dtype=float)
    return (array - mean) / std


def _deterministic_permutation(values: pd.Series) -> np.ndarray:
    array = values.to_numpy(float)
    if len(array) < 2:
        return array.copy()
    multiplier = 17
    while math.gcd(multiplier, len(array)) != 1:
        multiplier += 2
    indices = (
        np.arange(len(array), dtype=int) * multiplier + 7
    ) % len(array)
    return array[indices]


def _is_constant(values: np.ndarray) -> bool:
    array = np.asarray(values, dtype=float)
    return len(array) == 0 or float(np.ptp(array)) <= 1e-12


def _factor_sample_hash(frame: pd.DataFrame) -> str:
    return _hash(
        "independence_factor_sample",
        _records_for_hash(
            frame,
            [
                "evaluation_date",
                "code",
                "factor_id",
                "factor_value",
                "peer_factor_value",
            ],
        ),
    )


def _control_hash(frame: pd.DataFrame) -> str:
    return _hash(
        "independence_controls",
        _records_for_hash(
            frame,
            [
                "evaluation_date",
                "code",
                "factor_id",
                "industry_code",
                "log_market_cap",
                "control_effective_date",
            ],
        ),
    )


def _label_hash(frame: pd.DataFrame, track: str) -> str:
    columns = {
        "M": ["m_forward_return", "m_label_available_at"],
        "F": ["f_residual", "f_label_available_at"],
        "R": ["r_label_state", "r_label_available_at"],
    }[track]
    return _hash(
        f"independence_{track}_labels",
        _records_for_hash(
            frame,
            ["evaluation_date", "code", "factor_id", *columns],
        ),
    )


def _blocked_result(
    *,
    batch: FinancialP2IndependenceBatch,
    configuration: FinancialP2IndependenceConfig,
    raw_frame: pd.DataFrame,
    normalized: pd.DataFrame,
    errors: Sequence[IndependenceIssue],
    warnings: Sequence[IndependenceIssue],
    anchor_fingerprints: Mapping[str, str],
    input_fingerprint: str,
    factor_sample_fingerprint: str,
    control_input_fingerprint: str,
    label_hashes: Mapping[str, str],
    mutation_guard: str,
) -> FinancialP2IndependenceResult:
    del batch, mutation_guard
    audit = _build_audit(
        gate_status=IndependenceGateStatus.BLOCKED.value,
        configuration=configuration,
        input_row_count=len(raw_frame),
        accepted_row_count=len(normalized),
        errors=_deduplicate_issues(errors),
        warnings=_deduplicate_issues(warnings),
        anchor_fingerprints=anchor_fingerprints,
        input_fingerprint=input_fingerprint,
        factor_sample_fingerprint=factor_sample_fingerprint,
        control_input_fingerprint=control_input_fingerprint,
        label_hashes=label_hashes,
        output_fingerprint=_hash(
            "independence_blocked_output",
            [item.to_dict() for item in errors],
        ),
    )
    return FinancialP2IndependenceResult(
        factor_evidence=(),
        independence_audit=audit,
    )


def _build_audit(
    *,
    gate_status: str,
    configuration: FinancialP2IndependenceConfig,
    input_row_count: int,
    accepted_row_count: int,
    errors: Sequence[IndependenceIssue],
    warnings: Sequence[IndependenceIssue],
    anchor_fingerprints: Mapping[str, str],
    input_fingerprint: str,
    factor_sample_fingerprint: str,
    control_input_fingerprint: str,
    label_hashes: Mapping[str, str],
    output_fingerprint: str,
) -> FinancialP2IndependenceAudit:
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "input_row_count": input_row_count,
        "accepted_row_count": accepted_row_count,
        "supported_factor_ids":
            list(INDEP_SUPPORTED_FACTOR_IDS),
        "validation_tracks": list(INDEP_TRACKS),
        "predecessor_anchor_fingerprints": {
            track: anchor_fingerprints.get(track, "")
            for track in INDEP_TRACKS
        },
        "configuration_fingerprint": _hash(
            "independence_configuration",
            configuration.to_dict(),
        ),
        "input_fingerprint": input_fingerprint,
        "factor_sample_fingerprint":
            factor_sample_fingerprint,
        "control_input_fingerprint":
            control_input_fingerprint,
        "m_label_fingerprint": label_hashes.get(
            "M",
            _hash("empty", []),
        ),
        "f_label_fingerprint": label_hashes.get(
            "F",
            _hash("empty", []),
        ),
        "r_label_fingerprint": label_hashes.get(
            "R",
            _hash("empty", []),
        ),
        "output_fingerprint": output_fingerprint,
        "ordinary_t_stat_public": False,
        "oos_status": "not_run",
        "multiple_testing_status": "not_run",
        "synthetic_test_only": True,
        "conclusion_boundary": INDEP_CONCLUSION_BOUNDARY,
        "schema_version": INDEP_SCHEMA_VERSION,
        "audit_schema_version": INDEP_AUDIT_SCHEMA_VERSION,
        "policy_version": INDEP_POLICY_VERSION,
        "hash_contract_version":
            INDEP_HASH_CONTRACT_VERSION,
    }
    return FinancialP2IndependenceAudit(
        gate_status=gate_status,
        errors=tuple(errors),
        warnings=tuple(warnings),
        input_row_count=input_row_count,
        accepted_row_count=accepted_row_count,
        supported_factor_ids=INDEP_SUPPORTED_FACTOR_IDS,
        validation_tracks=INDEP_TRACKS,
        predecessor_anchor_fingerprints=tuple(
            (
                track,
                anchor_fingerprints.get(track, ""),
            )
            for track in INDEP_TRACKS
        ),
        configuration_fingerprint=payload[
            "configuration_fingerprint"
        ],
        input_fingerprint=input_fingerprint,
        factor_sample_fingerprint=factor_sample_fingerprint,
        control_input_fingerprint=control_input_fingerprint,
        m_label_fingerprint=payload["m_label_fingerprint"],
        f_label_fingerprint=payload["f_label_fingerprint"],
        r_label_fingerprint=payload["r_label_fingerprint"],
        output_fingerprint=output_fingerprint,
        ordinary_t_stat_public=False,
        oos_status="not_run",
        multiple_testing_status="not_run",
        synthetic_test_only=True,
        conclusion_boundary=INDEP_CONCLUSION_BOUNDARY,
        schema_version=INDEP_SCHEMA_VERSION,
        audit_schema_version=INDEP_AUDIT_SCHEMA_VERSION,
        policy_version=INDEP_POLICY_VERSION,
        hash_contract_version=INDEP_HASH_CONTRACT_VERSION,
        content_hash=_hash("independence_audit", payload),
    )


def _records_for_hash(
    frame: pd.DataFrame,
    columns: Sequence[str],
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [
        _canonical(row)
        for row in frame.loc[:, list(columns)].to_dict(
            orient="records"
        )
    ]


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    ordered_columns = sorted(str(column) for column in frame.columns)
    ordered = frame.loc[:, ordered_columns].copy()
    sort_columns = [
        column
        for column in (
            "factor_id",
            "evaluation_date",
            "code",
        )
        if column in ordered.columns
    ]
    if sort_columns:
        ordered = ordered.sort_values(
            sort_columns,
            kind="stable",
        )
    return [
        _canonical(row)
        for row in ordered.to_dict(orient="records")
    ]


def _error(
    code: IndependenceErrorCode,
    message: str,
    *,
    field_name: str | None = None,
    record_key: str | None = None,
    track: str | None = None,
) -> IndependenceIssue:
    return IndependenceIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
        track=track,
    )


def _warning(
    code: IndependenceWarningCode,
    message: str,
    *,
    field_name: str | None = None,
    record_key: str | None = None,
    track: str | None = None,
) -> IndependenceIssue:
    return IndependenceIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
        track=track,
    )


def _deduplicate_issues(
    issues: Sequence[IndependenceIssue],
) -> tuple[IndependenceIssue, ...]:
    unique: dict[str, IndependenceIssue] = {}
    for issue in issues:
        key = json.dumps(
            issue.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
        )
        unique[key] = issue
    return tuple(unique[key] for key in sorted(unique))


def _positive_ratio(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(np.mean(np.asarray(values, dtype=float) > 0.0))


def _mean_or_none(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(np.mean(np.asarray(values, dtype=float)))


def _finite_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be numeric") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value.strip()


def _date_text(value: Any, field_name: str) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = _required_text(value, field_name)
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an ISO date"
        ) from exc


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)


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
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        if math.isnan(numeric):
            return None
        if math.isinf(numeric):
            return str(numeric)
        return round(numeric, 15)
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    if _missing(value):
        return None
    return value


def _hash(domain: str, value: Any) -> str:
    payload = {
        "domain": domain,
        "hash_contract_version": INDEP_HASH_CONTRACT_VERSION,
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
    "FinancialP2ContinuousIncrement",
    "FinancialP2IndependenceAudit",
    "FinancialP2IndependenceBatch",
    "FinancialP2IndependenceConfig",
    "FinancialP2IndependenceFactor",
    "FinancialP2IndependenceResult",
    "FinancialP2RiskIncrement",
    "IndependenceErrorCode",
    "IndependenceEvidenceStatus",
    "IndependenceGateStatus",
    "IndependenceIssue",
    "IndependenceWarningCode",
    "INDEP_AUDIT_SCHEMA_VERSION",
    "INDEP_CONCLUSION_BOUNDARY",
    "INDEP_HASH_CONTRACT_VERSION",
    "INDEP_PREDECESSOR_OUTPUT_FINGERPRINTS",
    "INDEP_POLICY_VERSION",
    "INDEP_SCHEMA_VERSION",
    "evaluate_financial_p2_independence",
]
