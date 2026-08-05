"""INFO-GAIN-02B: M-track member baselines on accepted common samples.

This adapter validates the accepted INFO-GAIN-02A packages, applies each
member's frozen direction, and delegates every calculation to the accepted
FIN-MVP-M-EVAL single-factor evaluator.  It does not compare a combination
with a member, select a strongest member, or calculate information gain.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from backend.amr.evaluation_core import (
    EvaluationStatus,
    SecurityLevelEvaluationResult,
)
from backend.amr.financial_mvp_m_evaluation import (
    FinancialMVPMEvaluationConfig,
    _evaluate_one_factor,
)
from backend.amr.financial_p3_info_gain_contract import INFO_GAIN_COMBO_ORDER
from backend.amr.financial_p3_info_gain_inputs import (
    InfoGainInputPreparationResult,
    PreparedInfoGainCommonSampleInput,
    serialize_info_gain_input_preparation_result,
)


INFO_GAIN_02B_SCHEMA_VERSION = "FinancialP3InfoGainMMemberBaselines-v1.0"
INFO_GAIN_02B_AUDIT_SCHEMA_VERSION = (
    "FinancialP3InfoGainMMemberBaselineAudit-v1.0"
)
INFO_GAIN_02B_POLICY_VERSION = "FIN-P3-INFO-GAIN-02B-POLICY-v1.0"
INFO_GAIN_02B_HASH_CONTRACT_VERSION = "FIN-P3-INFO-GAIN-02B-HASH-v1.0"
INFO_GAIN_02B_PRODUCTION_STATUS = "not production ready"
INFO_GAIN_02B_CONCLUSION_BOUNDARY = (
    "M-track common-sample member baselines only. No F/R evaluation, "
    "combination evaluation, strongest-member selection, information-gain, "
    "admission, production, empirical-return, fraud, or trading conclusion."
)

ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT = (
    "b9e395416742f79edfd992d176582432ce644251f46cbfadb7d5a9ab661a43ef"
)
ACCEPTED_INFO_GAIN_CONTRACT_HASH = (
    "e6d51313ae0fb326d4b239dbb3aefe542c8d5d623237b05e7678959436766747"
)
ACCEPTED_M_EVALUATOR_SOURCE_SHA256 = (
    "94e5c4a7808273fd4d6f5158b5cabc9dc07cdd0bd94dcbca91802a4d0bd74cea"
)
M_EVALUATOR_REFERENCE = (
    "backend.amr.financial_mvp_m_evaluation:_evaluate_one_factor"
)
M_EVALUATION_CONTEXT = "M:20D"
M_RETURN_HORIZON = "20"
M_HAC_MAX_LAG = 1
M_METRIC_SET = (
    "rank_ic_mean",
    "rank_ic_ir",
    "rank_ic_t_stat",
    "rank_ic_positive_ratio",
    "pearson_ic_mean",
    "pearson_ic_ir",
    "pearson_ic_t_stat",
    "pearson_ic_positive_ratio",
    "quantile_returns",
    "long_short_mean",
    "monotonicity_spearman",
    "daily_results",
    "daily_group_returns",
)
EXPECTED_COMMON_SAMPLE_FINGERPRINTS = {
    "VQ": "ab58b5b1cf5e975563838f9e5aecd367f9c70a25d10d2678c69c6fa4a2f037d1",
    "QG": "3e470edf7b8b8e065ec6f373e2e5872e1cabf42e360212928ecc7276834839ae",
    "CASHQ": "c3d21f755aae395d179e23b361948bcb232f4e52625d12e5dd98bf013ebcd4f7",
}
EXPECTED_MEMBER_DIRECTIONS = {
    "VQ": (("BP", "positive"), ("EBIT_EV", "positive"), ("ROE", "positive"), ("OCF_NP", "positive")),
    "QG": (("SALES_GROWTH", "positive"), ("PROFIT_GROWTH", "positive"), ("ROE", "positive"), ("OCF_NP", "positive")),
    "CASHQ": (("ROA", "positive"), ("OCF_SALES", "positive"), ("ACCRUALS", "negative")),
}


@dataclass(frozen=True)
class MMemberBaselineConfig:
    run_id: str
    evaluation_calendar_reference: str = "synthetic-calendar://month-end-2024"
    evaluation_calendar_version: str = "synthetic-month-end-v1"
    hac_max_lag: int = M_HAC_MAX_LAG
    accepted_02a_output_fingerprint: str = ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT
    accepted_contract_hash: str = ACCEPTED_INFO_GAIN_CONTRACT_HASH
    expected_evaluator_source_sha256: str = ACCEPTED_M_EVALUATOR_SOURCE_SHA256
    synthetic_test_only: bool = True

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "evaluation_calendar_reference",
            "evaluation_calendar_version",
        ):
            _required_text(getattr(self, name), name)
        if self.hac_max_lag != M_HAC_MAX_LAG:
            raise ValueError("hac_max_lag must be frozen at 1")
        if self.accepted_02a_output_fingerprint != ACCEPTED_INFO_GAIN_02A_OUTPUT_FINGERPRINT:
            raise ValueError("accepted INFO-GAIN-02A output fingerprint drifted")
        if self.accepted_contract_hash != ACCEPTED_INFO_GAIN_CONTRACT_HASH:
            raise ValueError("INFO-GAIN-01 contract hash drifted")
        if self.expected_evaluator_source_sha256 != ACCEPTED_M_EVALUATOR_SOURCE_SHA256:
            raise ValueError("accepted M evaluator source hash drifted")
        if self.synthetic_test_only is not True:
            raise ValueError("INFO-GAIN-02B is authorized for synthetic input only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "evaluation_calendar_reference": self.evaluation_calendar_reference,
            "evaluation_calendar_version": self.evaluation_calendar_version,
            "hac_max_lag": self.hac_max_lag,
            "accepted_02a_output_fingerprint": self.accepted_02a_output_fingerprint,
            "accepted_contract_hash": self.accepted_contract_hash,
            "expected_evaluator_source_sha256": self.expected_evaluator_source_sha256,
            "synthetic_test_only": self.synthetic_test_only,
        }


@dataclass(frozen=True)
class MMemberBaselineIssue:
    code: str
    message: str
    combo_id: str | None = None
    member_factor_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "combo_id": self.combo_id,
            "member_factor_id": self.member_factor_id,
        }


@dataclass(frozen=True)
class MMemberBaselineRun:
    combo_id: str
    member_factor_id: str
    frozen_direction: str
    direction_multiplier: int
    common_sample_reference: str
    common_sample_fingerprint: str
    evaluation_context: str
    label_reference: str
    return_set_id: str
    evaluator_reference: str
    evaluator_source_sha256: str
    metric_set: tuple[str, ...]
    calculation_status: str
    evaluation_result: SecurityLevelEvaluationResult | None
    issue_codes: tuple[str, ...]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "combo_id": self.combo_id,
            "member_factor_id": self.member_factor_id,
            "frozen_direction": self.frozen_direction,
            "direction_multiplier": self.direction_multiplier,
            "common_sample_reference": self.common_sample_reference,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "evaluation_context": self.evaluation_context,
            "label_reference": self.label_reference,
            "return_set_id": self.return_set_id,
            "evaluator_reference": self.evaluator_reference,
            "evaluator_source_sha256": self.evaluator_source_sha256,
            "metric_set": list(self.metric_set),
            "calculation_status": self.calculation_status,
            "evaluation_result": (
                self.evaluation_result.to_dict()
                if self.evaluation_result is not None
                else None
            ),
            "issue_codes": list(self.issue_codes),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class MMemberBaselineBundle:
    combo_id: str
    common_sample_reference: str
    common_sample_fingerprint: str
    evaluation_period_count: int
    common_sample_row_count: int
    member_runs: tuple[MMemberBaselineRun, ...]
    calculation_status: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "combo_id": self.combo_id,
            "common_sample_reference": self.common_sample_reference,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "evaluation_period_count": self.evaluation_period_count,
            "common_sample_row_count": self.common_sample_row_count,
            "member_runs": [item.to_dict() for item in self.member_runs],
            "calculation_status": self.calculation_status,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class MMemberBaselineAudit:
    gate_status: str
    errors: tuple[MMemberBaselineIssue, ...]
    warnings: tuple[MMemberBaselineIssue, ...]
    combo_count: int
    member_run_count: int
    completed_run_count: int
    partial_run_count: int
    not_run_count: int
    m_evaluator_call_count: int
    f_evaluator_call_count: int
    r_evaluator_call_count: int
    exact_common_samples_verified: bool
    accepted_input_verified: bool
    existing_m_evaluator_reused: bool
    frozen_directions_applied: bool
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
class MMemberBaselineResult:
    bundles: tuple[MMemberBaselineBundle, ...]
    audit: MMemberBaselineAudit

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundles": [item.to_dict() for item in self.bundles],
            "audit": self.audit.to_dict(),
        }


def evaluate_financial_p3_info_gain_m_member_baselines(
    prepared: InfoGainInputPreparationResult,
    *,
    configuration: MMemberBaselineConfig,
) -> MMemberBaselineResult:
    """Evaluate every combo-member pair on its accepted 02A common sample."""

    if not isinstance(configuration, MMemberBaselineConfig):
        raise TypeError("configuration must be MMemberBaselineConfig")
    if not isinstance(prepared, InfoGainInputPreparationResult):
        raise TypeError("prepared must be InfoGainInputPreparationResult")
    before = serialize_info_gain_input_preparation_result(prepared)
    evaluator_hash = _evaluator_source_sha256()
    errors = _validate_prepared(prepared, configuration, evaluator_hash)
    if errors:
        return _blocked(configuration, prepared, tuple(errors), evaluator_hash)

    bundles: list[MMemberBaselineBundle] = []
    evaluation_errors: list[MMemberBaselineIssue] = []
    calls = 0
    for package in prepared.packages:
        runs: list[MMemberBaselineRun] = []
        track = next(item for item in package.track_inputs if item.track_id == "M")
        label_reference = track.label_references[0]
        for member_factor_id, direction in package.member_directions:
            calls += 1
            try:
                run = _evaluate_member(
                    package,
                    member_factor_id=member_factor_id,
                    direction=direction,
                    label_reference=label_reference,
                    configuration=configuration,
                    evaluator_hash=evaluator_hash,
                )
            except Exception as exc:  # retain auditable failure instead of hiding it
                evaluation_errors.append(
                    MMemberBaselineIssue(
                        code="M_EVALUATOR_CALL_FAILED",
                        message=f"{type(exc).__name__}: {exc}",
                        combo_id=package.combo_id,
                        member_factor_id=member_factor_id,
                    )
                )
                continue
            runs.append(run)
        bundle_payload = {
            "combo_id": package.combo_id,
            "common_sample_reference": package.common_sample_reference,
            "common_sample_fingerprint": package.common_sample_fingerprint,
            "evaluation_period_count": package.evaluation_period_count,
            "common_sample_row_count": package.common_sample_row_count,
            "member_runs": [item.to_dict() for item in runs],
            "calculation_status": _bundle_status(runs, len(package.member_directions)),
        }
        bundles.append(
            MMemberBaselineBundle(
                combo_id=package.combo_id,
                common_sample_reference=package.common_sample_reference,
                common_sample_fingerprint=package.common_sample_fingerprint,
                evaluation_period_count=package.evaluation_period_count,
                common_sample_row_count=package.common_sample_row_count,
                member_runs=tuple(runs),
                calculation_status=bundle_payload["calculation_status"],
                content_hash=_hash("p3_info_gain_02b_bundle", bundle_payload),
            )
        )

    after = serialize_info_gain_input_preparation_result(prepared)
    if before != after:
        raise RuntimeError("INFO-GAIN-02A input was mutated during evaluation")
    return _build_result(
        configuration,
        prepared,
        tuple(bundles),
        tuple(evaluation_errors),
        evaluator_hash,
        calls,
    )


def serialize_m_member_baseline_result(result: MMemberBaselineResult) -> str:
    if not isinstance(result, MMemberBaselineResult):
        raise TypeError("result must be MMemberBaselineResult")
    return json.dumps(
        _canonical(result.to_dict()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validate_prepared(prepared, configuration, evaluator_hash):
    errors: list[MMemberBaselineIssue] = []
    audit = prepared.audit
    if audit.gate_status != "ready" or audit.errors:
        errors.append(_issue("INFO_GAIN_02A_NOT_READY", "02A input gate must be ready"))
    if audit.output_fingerprint != configuration.accepted_02a_output_fingerprint:
        errors.append(_issue("INFO_GAIN_02A_FINGERPRINT_MISMATCH", "02A output fingerprint drifted"))
    recomputed = _hash("p3_info_gain_02a_output", [item.to_dict() for item in prepared.packages])
    if recomputed != audit.output_fingerprint:
        errors.append(_issue("INFO_GAIN_02A_CONTENT_MISMATCH", "02A packages do not match the accepted output fingerprint"))
    if audit.contract_hash != configuration.accepted_contract_hash:
        errors.append(_issue("CONTRACT_HASH_MISMATCH", "INFO-GAIN-01 contract hash drifted"))
    if evaluator_hash != configuration.expected_evaluator_source_sha256:
        errors.append(_issue("M_EVALUATOR_HASH_MISMATCH", "accepted M evaluator source drifted"))
    if tuple(item.combo_id for item in prepared.packages) != INFO_GAIN_COMBO_ORDER:
        errors.append(_issue("COMBO_ORDER_MISMATCH", "packages must be ordered VQ, QG, CASHQ"))
        return errors
    for package in prepared.packages:
        errors.extend(_validate_package(package))
    return errors


def _validate_package(package: PreparedInfoGainCommonSampleInput):
    errors: list[MMemberBaselineIssue] = []
    combo_id = package.combo_id
    if package.common_sample_fingerprint != EXPECTED_COMMON_SAMPLE_FINGERPRINTS[combo_id]:
        errors.append(_issue("COMMON_SAMPLE_FINGERPRINT_MISMATCH", "common sample fingerprint drifted", combo_id))
    if package.evaluation_period_count != 18 or package.common_sample_row_count != 900:
        errors.append(_issue("COMMON_SAMPLE_SHAPE_MISMATCH", "common sample must remain 18 periods and 900 rows", combo_id))
    if package.member_directions != EXPECTED_MEMBER_DIRECTIONS[combo_id]:
        errors.append(_issue("MEMBER_DIRECTION_MISMATCH", "member set, order, or direction drifted", combo_id))
    m_tracks = tuple(item for item in package.track_inputs if item.track_id == "M")
    if len(m_tracks) != 1:
        errors.append(_issue("M_TRACK_INPUT_MISSING", "exactly one M track input is required", combo_id))
        return errors
    track = m_tracks[0]
    if track.preparation_status != "ready" or track.evaluation_contexts != (M_EVALUATION_CONTEXT,):
        errors.append(_issue("M_TRACK_INPUT_NOT_READY", "M track must be ready only for M:20D", combo_id))
    if len(track.label_references) != 1 or not track.evaluation_config_reference:
        errors.append(_issue("M_TRACK_REFERENCE_INVALID", "M label and evaluation configuration references are required", combo_id))
    observations = package.get_member_observations()
    required = {"evaluation_date", "security_id", "member_factor_id", "factor_value", "forward_return"}
    if not required.issubset(observations.columns):
        errors.append(_issue("MEMBER_OBSERVATION_COLUMNS_MISSING", "member observations lack M evaluator inputs", combo_id))
        return errors
    expected_members = tuple(item[0] for item in package.member_directions)
    if set(observations["member_factor_id"].astype(str)) != set(expected_members):
        errors.append(_issue("MEMBER_OBSERVATION_SET_MISMATCH", "member observations do not match the frozen set", combo_id))
    for member_id in expected_members:
        member = observations[observations["member_factor_id"] == member_id]
        if len(member) != 900 or member[["evaluation_date", "security_id"]].duplicated().any():
            errors.append(_issue("MEMBER_SAMPLE_SHAPE_MISMATCH", "each member must have exactly 900 unique common-sample rows", combo_id, member_id))
        numeric = member[["factor_value", "forward_return"]].apply(pd.to_numeric, errors="coerce")
        if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
            errors.append(_issue("NONFINITE_M_INPUT", "factor values and M labels must be finite", combo_id, member_id))
    return errors


def _evaluate_member(package, *, member_factor_id, direction, label_reference, configuration, evaluator_hash):
    observations = package.get_member_observations()
    member = observations[observations["member_factor_id"] == member_factor_id].copy()
    multiplier = 1 if direction == "positive" else -1
    frame = pd.DataFrame(
        {
            "date": member["evaluation_date"].astype(str),
            "factor_value": pd.to_numeric(member["factor_value"], errors="raise") * multiplier,
            "forward_return": pd.to_numeric(member["forward_return"], errors="raise"),
        }
    ).sort_values(["date"], kind="mergesort").reset_index(drop=True)
    evaluation_dates = tuple(sorted(frame["date"].unique()))
    evaluator_config = FinancialMVPMEvaluationConfig(
        evaluation_dates=evaluation_dates,
        evaluation_calendar_reference=configuration.evaluation_calendar_reference,
        evaluation_calendar_version=configuration.evaluation_calendar_version,
        hac_max_lag=configuration.hac_max_lag,
    )
    return_set_id = f"{label_reference}|{package.common_sample_reference}"
    evaluated = _evaluate_one_factor(
        factor_id=member_factor_id,
        factor_frame=frame,
        return_set_id=return_set_id,
        configuration=evaluator_config,
    )
    status = evaluated.overall_status.value
    payload = {
        "combo_id": package.combo_id,
        "member_factor_id": member_factor_id,
        "frozen_direction": direction,
        "direction_multiplier": multiplier,
        "common_sample_reference": package.common_sample_reference,
        "common_sample_fingerprint": package.common_sample_fingerprint,
        "evaluation_context": M_EVALUATION_CONTEXT,
        "label_reference": label_reference,
        "return_set_id": return_set_id,
        "evaluator_reference": M_EVALUATOR_REFERENCE,
        "evaluator_source_sha256": evaluator_hash,
        "metric_set": list(M_METRIC_SET),
        "calculation_status": status,
        "evaluation_result": evaluated.to_dict(),
        "issue_codes": list(evaluated.issue_codes),
    }
    return MMemberBaselineRun(
        combo_id=package.combo_id,
        member_factor_id=member_factor_id,
        frozen_direction=direction,
        direction_multiplier=multiplier,
        common_sample_reference=package.common_sample_reference,
        common_sample_fingerprint=package.common_sample_fingerprint,
        evaluation_context=M_EVALUATION_CONTEXT,
        label_reference=label_reference,
        return_set_id=return_set_id,
        evaluator_reference=M_EVALUATOR_REFERENCE,
        evaluator_source_sha256=evaluator_hash,
        metric_set=M_METRIC_SET,
        calculation_status=status,
        evaluation_result=evaluated,
        issue_codes=tuple(evaluated.issue_codes),
        content_hash=_hash("p3_info_gain_02b_member_run", payload),
    )


def _bundle_status(runs: Sequence[MMemberBaselineRun], expected_count: int) -> str:
    if len(runs) != expected_count or any(item.calculation_status == EvaluationStatus.NOT_RUN.value for item in runs):
        return "not_run"
    if any(item.calculation_status == EvaluationStatus.PARTIAL.value for item in runs):
        return "partial"
    return "completed"


def _build_result(configuration, prepared, bundles, errors, evaluator_hash, calls):
    runs = tuple(run for bundle in bundles for run in bundle.member_runs)
    completed = sum(item.calculation_status == "completed" for item in runs)
    partial = sum(item.calculation_status == "partial" for item in runs)
    not_run = 11 - completed - partial
    gate_status = "ready" if not errors and completed == 11 else "blocked"
    output_fingerprint = _hash("p3_info_gain_02b_output", [item.to_dict() for item in bundles])
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [],
        "combo_count": len(bundles),
        "member_run_count": len(runs),
        "completed_run_count": completed,
        "partial_run_count": partial,
        "not_run_count": not_run,
        "m_evaluator_call_count": calls,
        "f_evaluator_call_count": 0,
        "r_evaluator_call_count": 0,
        "exact_common_samples_verified": gate_status == "ready",
        "accepted_input_verified": gate_status == "ready",
        "existing_m_evaluator_reused": True,
        "frozen_directions_applied": bool(runs),
        "metrics_calculated": bool(runs),
        "combination_evaluated": False,
        "strongest_member_selected": False,
        "information_gain_calculated": False,
        "input_fingerprint": prepared.audit.output_fingerprint,
        "output_fingerprint": output_fingerprint,
        "evaluator_source_sha256": evaluator_hash,
        "production_status": INFO_GAIN_02B_PRODUCTION_STATUS,
        "conclusion_boundary": INFO_GAIN_02B_CONCLUSION_BOUNDARY,
        "schema_version": INFO_GAIN_02B_SCHEMA_VERSION,
        "audit_schema_version": INFO_GAIN_02B_AUDIT_SCHEMA_VERSION,
        "policy_version": INFO_GAIN_02B_POLICY_VERSION,
        "hash_contract_version": INFO_GAIN_02B_HASH_CONTRACT_VERSION,
    }
    audit_values = dict(payload)
    audit_values["errors"] = tuple(errors)
    audit_values["warnings"] = ()
    audit = MMemberBaselineAudit(
        **audit_values,
        content_hash=_hash("p3_info_gain_02b_audit", payload),
    )
    return MMemberBaselineResult(bundles=bundles, audit=audit)


def _blocked(configuration, prepared, errors, evaluator_hash):
    return _build_result(configuration, prepared, (), errors, evaluator_hash, 0)


def _evaluator_source_sha256() -> str:
    source = inspect.getsourcefile(_evaluate_one_factor)
    if source is None:
        return "unavailable"
    return hashlib.sha256(Path(source).read_bytes()).hexdigest()


def _issue(code, message, combo_id=None, member_factor_id=None):
    return MMemberBaselineIssue(code, message, combo_id, member_factor_id)


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
    payload = json.dumps(
        {"domain": domain, "value": _canonical(value)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
