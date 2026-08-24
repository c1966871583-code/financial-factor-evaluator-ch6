"""INFO-GAIN-02C: formal F-track member-baseline status on frozen samples.

The accepted INFO-GAIN-02A packages explicitly do not freeze an F-track
forecast context.  This module records one auditable ``not_run`` baseline per
combo-member pair and fails closed on any input-state drift.  It never
constructs forecast data or calls the existing F evaluator.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.amr.financial_p2_f_evidence import evaluate_financial_p2_f_evidence
from backend.amr.financial_p3_info_gain_contract import INFO_GAIN_COMBO_ORDER
from backend.amr.financial_p3_info_gain_inputs import (
    InfoGainInputPreparationResult,
    compute_info_gain_input_output_fingerprint,
    serialize_info_gain_input_preparation_result,
)

INFO_GAIN_02C_SCHEMA_VERSION = "FinancialP3InfoGainFMemberBaselines-v1.0"
INFO_GAIN_02C_AUDIT_SCHEMA_VERSION = "FinancialP3InfoGainFMemberBaselineAudit-v1.0"
INFO_GAIN_02C_POLICY_VERSION = "FIN-P3-INFO-GAIN-02C-POLICY-v1.0"
INFO_GAIN_02C_HASH_CONTRACT_VERSION = "FIN-P3-INFO-GAIN-02C-HASH-v1.0"
INFO_GAIN_02C_PRODUCTION_STATUS = "not production ready"
INFO_GAIN_02C_CONCLUSION_BOUNDARY = (
    "Formal F-track not_run member-baseline status only. No F forecast input "
    "construction, evaluator call, M/R evaluation, combination evaluation, "
    "strongest-member selection, information-gain, admission, production, "
    "empirical-return, fraud, or trading conclusion."
)

ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT = (
    "1599c601f11da9d67adf7d538f80fe75488ac2481c0794678d6660589ea1c48e"
)
ACCEPTED_INFO_GAIN_CONTRACT_HASH = (
    "e6d51313ae0fb326d4b239dbb3aefe542c8d5d623237b05e7678959436766747"
)
ACCEPTED_F_EVALUATOR_SOURCE_SHA256 = (
    "f44dee7df677a8e4921f14c953d2ba25df1bbdb8d782db7528ddf8359c0d443b"
)
F_EVALUATOR_REFERENCE = (
    "backend.amr.financial_p2_f_evidence.evaluate_financial_p2_f_evidence"
)
F_METRICS = (
    "oos_mae",
    "relative_mae_improvement",
    "residual_rank_ic",
    "interval_coverage",
    "interval_calibration_error",
)
NOT_RUN_REASON = "F_CONTEXT_NOT_FROZEN"
INPUT_NOT_RUN_REASON = "CONTEXT_NOT_FROZEN"
EXPECTED_MEMBER_DIRECTIONS = {
    "VQ": (("BP", "positive"), ("EBIT_EV", "positive"), ("ROE", "positive"), ("OCF_NP", "positive")),
    "QG": (("SALES_GROWTH", "positive"), ("PROFIT_GROWTH", "positive"), ("ROE", "positive"), ("OCF_NP", "positive")),
    "CASHQ": (("ROA", "positive"), ("OCF_SALES", "positive"), ("ACCRUALS", "negative")),
}


@dataclass(frozen=True)
class FMemberBaselineConfig:
    run_id: str
    accepted_02a_output_fingerprint: str = ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT
    accepted_contract_hash: str = ACCEPTED_INFO_GAIN_CONTRACT_HASH
    expected_evaluator_source_sha256: str = ACCEPTED_F_EVALUATOR_SOURCE_SHA256
    synthetic_test_only: bool = True

    def __post_init__(self) -> None:
        _required_text(self.run_id, "run_id")
        if self.accepted_02a_output_fingerprint != ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT:
            raise ValueError("accepted INFO-GAIN-02A output fingerprint drifted")
        if self.accepted_contract_hash != ACCEPTED_INFO_GAIN_CONTRACT_HASH:
            raise ValueError("INFO-GAIN-01 contract hash drifted")
        if self.expected_evaluator_source_sha256 != ACCEPTED_F_EVALUATOR_SOURCE_SHA256:
            raise ValueError("accepted F evaluator source hash drifted")
        if self.synthetic_test_only is not True:
            raise ValueError("INFO-GAIN-02C is authorized for synthetic input only")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class FMemberBaselineIssue:
    code: str
    message: str
    combo_id: str | None = None
    member_factor_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class FMemberBaselineRun:
    combo_id: str
    member_factor_id: str
    frozen_direction: str
    common_sample_reference: str
    common_sample_fingerprint: str
    calculation_status: str
    not_run_reason: str
    evaluator_reference: str
    evaluator_source_sha256: str
    metric_statuses: tuple[tuple[str, str], ...]
    metric_values: tuple[tuple[str, None], ...]
    issue_codes: tuple[str, ...]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "combo_id": self.combo_id,
            "member_factor_id": self.member_factor_id,
            "frozen_direction": self.frozen_direction,
            "common_sample_reference": self.common_sample_reference,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "calculation_status": self.calculation_status,
            "not_run_reason": self.not_run_reason,
            "evaluator_reference": self.evaluator_reference,
            "evaluator_source_sha256": self.evaluator_source_sha256,
            "metric_statuses": dict(self.metric_statuses),
            "metric_values": dict(self.metric_values),
            "issue_codes": list(self.issue_codes),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FMemberBaselineBundle:
    combo_id: str
    common_sample_reference: str
    common_sample_fingerprint: str
    member_runs: tuple[FMemberBaselineRun, ...]
    calculation_status: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "combo_id": self.combo_id,
            "common_sample_reference": self.common_sample_reference,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "member_runs": [item.to_dict() for item in self.member_runs],
            "calculation_status": self.calculation_status,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FMemberBaselineAudit:
    gate_status: str
    errors: tuple[FMemberBaselineIssue, ...]
    warnings: tuple[FMemberBaselineIssue, ...]
    combo_count: int
    member_run_count: int
    completed_run_count: int
    not_run_count: int
    f_evaluator_call_count: int
    m_evaluator_call_count: int
    r_evaluator_call_count: int
    accepted_input_verified: bool
    exact_common_samples_verified: bool
    F_context_status: str
    existing_F_evaluator_identified: bool
    forecast_input_constructed: bool
    metrics_calculated: bool
    combination_evaluated: bool
    strongest_member_selected: bool
    information_gain_calculated: bool
    input_fingerprint: str
    output_fingerprint: str
    evaluator_source_sha256: str
    production_status: str
    conclusion_boundary: str
    schema_version: str
    audit_schema_version: str
    policy_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {name: getattr(self, name) for name in self.__dataclass_fields__}
        values["errors"] = [item.to_dict() for item in self.errors]
        values["warnings"] = [item.to_dict() for item in self.warnings]
        return values


@dataclass(frozen=True)
class FMemberBaselineResult:
    bundles: tuple[FMemberBaselineBundle, ...]
    audit: FMemberBaselineAudit

    def to_dict(self) -> dict[str, Any]:
        return {"bundles": [item.to_dict() for item in self.bundles], "audit": self.audit.to_dict()}


def evaluate_financial_p3_info_gain_f_member_baselines(
    prepared: InfoGainInputPreparationResult,
    *,
    configuration: FMemberBaselineConfig,
) -> FMemberBaselineResult:
    """Return formal F ``not_run`` baselines for every frozen member."""

    if not isinstance(configuration, FMemberBaselineConfig):
        raise TypeError("configuration must be FMemberBaselineConfig")
    if not isinstance(prepared, InfoGainInputPreparationResult):
        raise TypeError("prepared must be InfoGainInputPreparationResult")
    before = serialize_info_gain_input_preparation_result(prepared)
    evaluator_hash = _evaluator_source_sha256()
    errors = _validate(prepared, configuration, evaluator_hash)
    if errors:
        return _build_result(prepared, (), tuple(errors), evaluator_hash)

    bundles = []
    for package in prepared.packages:
        runs = tuple(
            _not_run_member(package, member_id, direction, evaluator_hash)
            for member_id, direction in package.member_directions
        )
        payload = {
            "combo_id": package.combo_id,
            "common_sample_reference": package.common_sample_reference,
            "common_sample_fingerprint": package.common_sample_fingerprint,
            "member_runs": [item.to_dict() for item in runs],
            "calculation_status": "not_run",
        }
        bundles.append(FMemberBaselineBundle(
            combo_id=package.combo_id,
            common_sample_reference=package.common_sample_reference,
            common_sample_fingerprint=package.common_sample_fingerprint,
            member_runs=runs,
            calculation_status="not_run",
            content_hash=_hash("p3_info_gain_02c_bundle", payload),
        ))
    if serialize_info_gain_input_preparation_result(prepared) != before:
        raise RuntimeError("INFO-GAIN-02A input was mutated during F baseline status preparation")
    return _build_result(prepared, tuple(bundles), (), evaluator_hash)


def serialize_f_member_baseline_result(result: FMemberBaselineResult) -> str:
    if not isinstance(result, FMemberBaselineResult):
        raise TypeError("result must be FMemberBaselineResult")
    return json.dumps(_canonical(result.to_dict()), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate(prepared, configuration, evaluator_hash):
    errors: list[FMemberBaselineIssue] = []
    audit = prepared.audit
    if audit.gate_status != "ready" or audit.errors:
        errors.append(_issue("INFO_GAIN_02A_NOT_READY", "02A input gate must be ready"))
    if audit.output_fingerprint != configuration.accepted_02a_output_fingerprint:
        errors.append(_issue("INFO_GAIN_02A_FINGERPRINT_MISMATCH", f"02A output fingerprint drifted: expected={configuration.accepted_02a_output_fingerprint} actual={audit.output_fingerprint}"))
    if compute_info_gain_input_output_fingerprint(prepared.packages) != audit.output_fingerprint:
        errors.append(_issue("INFO_GAIN_02A_CONTENT_MISMATCH", "02A packages do not match accepted output"))
    if audit.contract_hash != configuration.accepted_contract_hash:
        errors.append(_issue("CONTRACT_HASH_MISMATCH", "INFO-GAIN-01 contract hash drifted"))
    if evaluator_hash != configuration.expected_evaluator_source_sha256:
        errors.append(_issue("F_EVALUATOR_HASH_MISMATCH", "accepted F evaluator source drifted"))
    if tuple(item.combo_id for item in prepared.packages) != INFO_GAIN_COMBO_ORDER:
        errors.append(_issue("COMBO_ORDER_MISMATCH", "packages must be ordered VQ, QG, CASHQ"))
        return errors
    for package in prepared.packages:
        if package.member_directions != EXPECTED_MEMBER_DIRECTIONS[package.combo_id]:
            errors.append(_issue("MEMBER_DIRECTION_MISMATCH", "member set, order, or direction drifted", package.combo_id))
        tracks = tuple(item for item in package.track_inputs if item.track_id == "F")
        if len(tracks) != 1:
            errors.append(_issue("F_TRACK_INPUT_MISSING", "exactly one F track input is required", package.combo_id))
            continue
        track = tracks[0]
        if track.preparation_status != "not_run" or track.reason_code != INPUT_NOT_RUN_REASON:
            errors.append(_issue("F_CONTEXT_STATE_DRIFT", "F context must remain formal not_run", package.combo_id))
        if track.evaluation_contexts or track.label_references or track.evaluation_config_reference is not None:
            errors.append(_issue("F_CONTEXT_REFERENCE_DRIFT", "F context must not contain unfrozen evaluation references", package.combo_id))
    return errors


def _not_run_member(package, member_id, direction, evaluator_hash):
    metric_statuses = tuple((metric, "not_run") for metric in F_METRICS)
    metric_values = tuple((metric, None) for metric in F_METRICS)
    payload = {
        "combo_id": package.combo_id,
        "member_factor_id": member_id,
        "frozen_direction": direction,
        "common_sample_reference": package.common_sample_reference,
        "common_sample_fingerprint": package.common_sample_fingerprint,
        "calculation_status": "not_run",
        "not_run_reason": NOT_RUN_REASON,
        "evaluator_reference": F_EVALUATOR_REFERENCE,
        "evaluator_source_sha256": evaluator_hash,
        "metric_statuses": dict(metric_statuses),
        "metric_values": dict(metric_values),
        "issue_codes": [NOT_RUN_REASON],
    }
    return FMemberBaselineRun(
        combo_id=package.combo_id,
        member_factor_id=member_id,
        frozen_direction=direction,
        common_sample_reference=package.common_sample_reference,
        common_sample_fingerprint=package.common_sample_fingerprint,
        calculation_status="not_run",
        not_run_reason=NOT_RUN_REASON,
        evaluator_reference=F_EVALUATOR_REFERENCE,
        evaluator_source_sha256=evaluator_hash,
        metric_statuses=metric_statuses,
        metric_values=metric_values,
        issue_codes=(NOT_RUN_REASON,),
        content_hash=_hash("p3_info_gain_02c_member_run", payload),
    )


def _build_result(prepared, bundles, errors, evaluator_hash):
    runs = tuple(run for bundle in bundles for run in bundle.member_runs)
    output_fingerprint = _hash("p3_info_gain_02c_output", [item.to_dict() for item in bundles])
    gate_status = "ready" if not errors and len(runs) == 11 else "blocked"
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [],
        "combo_count": len(bundles),
        "member_run_count": len(runs),
        "completed_run_count": 0,
        "not_run_count": len(runs) if not errors else 11,
        "f_evaluator_call_count": 0,
        "m_evaluator_call_count": 0,
        "r_evaluator_call_count": 0,
        "accepted_input_verified": gate_status == "ready",
        "exact_common_samples_verified": gate_status == "ready",
        "F_context_status": "not_run",
        "existing_F_evaluator_identified": True,
        "forecast_input_constructed": False,
        "metrics_calculated": False,
        "combination_evaluated": False,
        "strongest_member_selected": False,
        "information_gain_calculated": False,
        "input_fingerprint": prepared.audit.output_fingerprint,
        "output_fingerprint": output_fingerprint,
        "evaluator_source_sha256": evaluator_hash,
        "production_status": INFO_GAIN_02C_PRODUCTION_STATUS,
        "conclusion_boundary": INFO_GAIN_02C_CONCLUSION_BOUNDARY,
        "schema_version": INFO_GAIN_02C_SCHEMA_VERSION,
        "audit_schema_version": INFO_GAIN_02C_AUDIT_SCHEMA_VERSION,
        "policy_version": INFO_GAIN_02C_POLICY_VERSION,
        "hash_contract_version": INFO_GAIN_02C_HASH_CONTRACT_VERSION,
    }
    values = dict(payload)
    values["errors"] = tuple(errors)
    values["warnings"] = ()
    audit = FMemberBaselineAudit(**values, content_hash=_hash("p3_info_gain_02c_audit", payload))
    return FMemberBaselineResult(tuple(bundles), audit)


def _evaluator_source_sha256() -> str:
    source = inspect.getsourcefile(evaluate_financial_p2_f_evidence)
    return hashlib.sha256(Path(source).read_bytes()).hexdigest() if source else "unavailable"


def _issue(code, message, combo_id=None, member_factor_id=None):
    return FMemberBaselineIssue(code, message, combo_id, member_factor_id)


def _required_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _canonical(value):
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer):
        return int(value)
    raise TypeError(f"unsupported canonical type: {type(value).__name__}")


def _hash(domain, value):
    encoded = json.dumps({"domain": domain, "value": _canonical(value)}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
