"""FIN-P3-INFO-GAIN-02: member baselines on accepted common samples.

The caller supplies the explicit accepted common-sample rows for each FIN-24
combination.  This module never constructs a sample intersection or a
combination value.  For each frozen member it routes the already-restricted
rows through the accepted FIN-23 common-sample evaluator and retains only the
member metric object.  No combo/member delta or information-gain decision is
produced here.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from backend.amr.evaluation_core import EvaluationStatus
from backend.amr.financial_p3_common_sample import (
    COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT,
    CommonSampleGateStatus,
    CommonSampleMetrics,
    FinancialP3CommonSampleBatch,
    FinancialP3CommonSampleConfig,
    compute_common_sample_manifest_fingerprint,
    evaluate_financial_p3_common_sample,
)
from backend.amr.financial_p3_info_gain_contract import (
    INFO_GAIN_COMBO_ORDER,
    INFO_GAIN_CONTRACT_VERSION,
    INFO_GAIN_PRODUCTION_STATUS,
    InfoGainEvaluationConfig,
)


MEMBER_BASELINE_SCHEMA_VERSION = "CommonSampleMemberBaselineRun-v1.0"
MEMBER_BASELINE_BUNDLE_SCHEMA_VERSION = "ComboMemberBaselineBundle-v1.0"
MEMBER_BASELINE_AUDIT_SCHEMA_VERSION = (
    "CommonSampleMemberBaselineAudit-v1.0"
)
MEMBER_BASELINE_POLICY_VERSION = "FIN-P3-INFO-GAIN-02-POLICY-v1.0"
MEMBER_BASELINE_HASH_CONTRACT_VERSION = (
    "FIN-P3-INFO-GAIN-02-HASH-v1.0"
)
MEMBER_BASELINE_CONCLUSION_BOUNDARY = (
    "Common-sample member baseline calculation only. No combination metric "
    "delta, strongest-member selection, information-gain assessment, "
    "admission, production, empirical-return, fraud, or trading conclusion."
)

_MANIFEST_COLUMNS = ("evaluation_date", "security_id", "eligible")
_KEY_COLUMNS = ("evaluation_date", "security_id")
_FRAME_COLUMNS = (
    "evaluation_date",
    "security_id",
    "member_factor_id",
    "factor_effective_date",
    "factor_value",
    "control_effective_date",
    "return_start_date",
    "forward_return",
    "size_control",
    "industry_code",
)
_LABEL_CONTROL_COLUMNS = (
    "control_effective_date",
    "return_start_date",
    "forward_return",
    "size_control",
    "industry_code",
)
_FORBIDDEN_COLUMNS = {
    "best_member",
    "best_member_factor_id",
    "selected_member",
    "selected_metric",
    "combination_value",
    "delta_ic",
    "delta_icir",
    "delta_monotonicity",
    "delta_fm_r2",
    "information_gain_decision",
    "admission_decision",
}


@dataclass(frozen=True)
class MemberBaselineIssue:
    code: str
    message: str
    combo_id: str | None = None
    member_factor_id: str | None = None
    field_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "combo_id": self.combo_id,
            "member_factor_id": self.member_factor_id,
            "field_name": self.field_name,
        }


@dataclass(frozen=True)
class CommonSampleMemberBaselineConfig:
    run_id: str
    execution_timestamp: str
    evaluation_config_reference: str
    info_gain_contract: InfoGainEvaluationConfig
    hac_context_status: str = "M:20D_only"
    m_5d_status: str = EvaluationStatus.NOT_RUN.value
    m_60d_status: str = EvaluationStatus.NOT_RUN.value
    f_track_status: str = EvaluationStatus.NOT_RUN.value
    r_track_status: str = EvaluationStatus.NOT_RUN.value
    information_gain_decision_allowed: bool = False
    best_member_selection_allowed: bool = False
    synthetic_test_only: bool = True
    policy_version: str = MEMBER_BASELINE_POLICY_VERSION
    schema_version: str = MEMBER_BASELINE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "execution_timestamp",
            "evaluation_config_reference",
        ):
            _required_text(getattr(self, field_name), field_name)
        if not isinstance(self.info_gain_contract, InfoGainEvaluationConfig):
            raise TypeError("info_gain_contract must be InfoGainEvaluationConfig")
        if self.info_gain_contract.contract_version != INFO_GAIN_CONTRACT_VERSION:
            raise ValueError("INFO-GAIN-01 contract version mismatch")
        frozen = {
            "hac_context_status": (self.hac_context_status, "M:20D_only"),
            "m_5d_status": (self.m_5d_status, "not_run"),
            "m_60d_status": (self.m_60d_status, "not_run"),
            "f_track_status": (self.f_track_status, "not_run"),
            "r_track_status": (self.r_track_status, "not_run"),
            "information_gain_decision_allowed": (
                self.information_gain_decision_allowed,
                False,
            ),
            "best_member_selection_allowed": (
                self.best_member_selection_allowed,
                False,
            ),
            "synthetic_test_only": (self.synthetic_test_only, True),
            "policy_version": (
                self.policy_version,
                MEMBER_BASELINE_POLICY_VERSION,
            ),
            "schema_version": (
                self.schema_version,
                MEMBER_BASELINE_SCHEMA_VERSION,
            ),
        }
        for field_name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{field_name} must be frozen at {expected!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "execution_timestamp": self.execution_timestamp,
            "evaluation_config_reference": self.evaluation_config_reference,
            "info_gain_contract_hash": self.info_gain_contract.content_hash,
            "hac_context_status": self.hac_context_status,
            "m_5d_status": self.m_5d_status,
            "m_60d_status": self.m_60d_status,
            "f_track_status": self.f_track_status,
            "r_track_status": self.r_track_status,
            "information_gain_decision_allowed": (
                self.information_gain_decision_allowed
            ),
            "best_member_selection_allowed": (
                self.best_member_selection_allowed
            ),
            "synthetic_test_only": self.synthetic_test_only,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CommonSampleMemberBaselineBatch:
    dataset_id: str
    version: str
    combo_id: str
    combo_definition_version: str
    common_sample_reference: str
    declared_common_sample_fingerprint: str
    _common_sample_manifest: pd.DataFrame
    _member_frame: pd.DataFrame
    member_formula_versions: Mapping[str, str]
    source_factor_run_references: Mapping[str, str]
    source_label_references: tuple[str, ...]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in (
            "dataset_id",
            "version",
            "combo_id",
            "combo_definition_version",
            "common_sample_reference",
        ):
            _required_text(getattr(self, field_name), field_name)
        if not _is_sha256(self.declared_common_sample_fingerprint):
            raise ValueError("declared_common_sample_fingerprint must be SHA-256")
        if not isinstance(self._common_sample_manifest, pd.DataFrame):
            raise TypeError("_common_sample_manifest must be a DataFrame")
        if not isinstance(self._member_frame, pd.DataFrame):
            raise TypeError("_member_frame must be a DataFrame")
        object.__setattr__(
            self,
            "_common_sample_manifest",
            self._common_sample_manifest.copy(deep=True),
        )
        object.__setattr__(
            self, "_member_frame", self._member_frame.copy(deep=True)
        )
        object.__setattr__(
            self,
            "member_formula_versions",
            MappingProxyType(copy.deepcopy(dict(self.member_formula_versions))),
        )
        object.__setattr__(
            self,
            "source_factor_run_references",
            MappingProxyType(
                copy.deepcopy(dict(self.source_factor_run_references))
            ),
        )
        object.__setattr__(
            self,
            "source_label_references",
            tuple(str(item) for item in self.source_label_references),
        )
        object.__setattr__(
            self,
            "provenance",
            MappingProxyType(copy.deepcopy(dict(self.provenance))),
        )

    def get_common_sample_manifest(self) -> pd.DataFrame:
        return self._common_sample_manifest.copy(deep=True)

    def get_member_frame(self) -> pd.DataFrame:
        return self._member_frame.copy(deep=True)

    def get_member_formula_versions(self) -> dict[str, str]:
        return copy.deepcopy(dict(self.member_formula_versions))

    def get_source_factor_run_references(self) -> dict[str, str]:
        return copy.deepcopy(dict(self.source_factor_run_references))

    def get_provenance(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.provenance))


@dataclass(frozen=True)
class MemberTrackBaselineResult:
    track_id: str
    evaluation_context: str
    calculation_status: str
    evaluator_reference: str
    reason_code: str | None
    metrics: CommonSampleMetrics | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "evaluation_context": self.evaluation_context,
            "calculation_status": self.calculation_status,
            "evaluator_reference": self.evaluator_reference,
            "reason_code": self.reason_code,
            "metrics": None if self.metrics is None else self.metrics.to_dict(),
        }


@dataclass(frozen=True)
class CommonSampleMemberBaselineRun:
    schema_version: str
    run_id: str
    contract_version: str
    combo_id: str
    combo_definition_version: str
    member_factor_id: str
    member_direction: str
    common_sample_reference: str
    common_sample_fingerprint: str
    evaluation_config_reference: str
    source_factor_run_reference: str
    source_label_references: tuple[str, ...]
    evaluation_period_count: int
    common_sample_row_count: int
    m_track_results: tuple[MemberTrackBaselineResult, ...]
    f_track_result: MemberTrackBaselineResult
    r_track_result: MemberTrackBaselineResult
    calculation_status: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "contract_version": self.contract_version,
            "combo_id": self.combo_id,
            "combo_definition_version": self.combo_definition_version,
            "member_factor_id": self.member_factor_id,
            "member_direction": self.member_direction,
            "common_sample_reference": self.common_sample_reference,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "evaluation_config_reference": self.evaluation_config_reference,
            "source_factor_run_reference": self.source_factor_run_reference,
            "source_label_references": list(self.source_label_references),
            "evaluation_period_count": self.evaluation_period_count,
            "common_sample_row_count": self.common_sample_row_count,
            "m_track_results": [item.to_dict() for item in self.m_track_results],
            "f_track_result": self.f_track_result.to_dict(),
            "r_track_result": self.r_track_result.to_dict(),
            "calculation_status": self.calculation_status,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class ComboMemberBaselineBundle:
    combo_id: str
    common_sample_fingerprint: str
    per_period_common_sample_counts: tuple[tuple[str, int], ...]
    member_baselines: tuple[CommonSampleMemberBaselineRun, ...]
    expected_member_count: int
    completed_member_count: int
    failed_member_count: int
    not_evaluable_member_count: int
    bundle_status: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "combo_id": self.combo_id,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "per_period_common_sample_counts": [
                {"evaluation_date": date, "count": count}
                for date, count in self.per_period_common_sample_counts
            ],
            "member_baselines": [item.to_dict() for item in self.member_baselines],
            "expected_member_count": self.expected_member_count,
            "completed_member_count": self.completed_member_count,
            "failed_member_count": self.failed_member_count,
            "not_evaluable_member_count": self.not_evaluable_member_count,
            "bundle_status": self.bundle_status,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class CommonSampleMemberBaselineAudit:
    gate_status: str
    errors: tuple[MemberBaselineIssue, ...]
    warnings: tuple[MemberBaselineIssue, ...]
    combo_count: int
    expected_member_count: int
    completed_member_count: int
    failed_member_count: int
    same_sample_enforced: bool
    member_full_sample_reused: bool
    existing_evaluator_reused: bool
    combination_reconstructed: bool
    information_gain_delta_calculated: bool
    information_gain_decision_made: bool
    production_status: str
    info_gain_contract_hash: str
    input_fingerprint: str
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
            "combo_count": self.combo_count,
            "expected_member_count": self.expected_member_count,
            "completed_member_count": self.completed_member_count,
            "failed_member_count": self.failed_member_count,
            "same_sample_enforced": self.same_sample_enforced,
            "member_full_sample_reused": self.member_full_sample_reused,
            "existing_evaluator_reused": self.existing_evaluator_reused,
            "combination_reconstructed": self.combination_reconstructed,
            "information_gain_delta_calculated": (
                self.information_gain_delta_calculated
            ),
            "information_gain_decision_made": (
                self.information_gain_decision_made
            ),
            "production_status": self.production_status,
            "info_gain_contract_hash": self.info_gain_contract_hash,
            "input_fingerprint": self.input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "schema_version": self.schema_version,
            "audit_schema_version": self.audit_schema_version,
            "policy_version": self.policy_version,
            "hash_contract_version": self.hash_contract_version,
            "conclusion_boundary": self.conclusion_boundary,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class CommonSampleMemberBaselineResult:
    bundles: tuple[ComboMemberBaselineBundle, ...]
    audit: CommonSampleMemberBaselineAudit

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundles": [item.to_dict() for item in self.bundles],
            "audit": self.audit.to_dict(),
        }


def evaluate_common_sample_member_baselines(
    batches: Sequence[CommonSampleMemberBaselineBatch],
    *,
    configuration: CommonSampleMemberBaselineConfig,
) -> CommonSampleMemberBaselineResult:
    if not isinstance(configuration, CommonSampleMemberBaselineConfig):
        raise TypeError("configuration must be CommonSampleMemberBaselineConfig")
    supplied = tuple(batches)
    errors: list[MemberBaselineIssue] = []
    warnings: list[MemberBaselineIssue] = []
    if any(not isinstance(item, CommonSampleMemberBaselineBatch) for item in supplied):
        errors.append(_issue("INVALID_BATCH", "all batches must use the formal batch type"))
        return _blocked_result(configuration, errors)
    ids = [item.combo_id for item in supplied]
    if len(ids) != len(set(ids)):
        errors.append(_issue("DUPLICATE_COMBO", "combo batches must be unique"))
    if set(ids) != set(INFO_GAIN_COMBO_ORDER):
        errors.append(_issue("COMBO_SET_MISMATCH", "batches must be exactly VQ, QG, CASHQ"))
    if errors:
        return _blocked_result(configuration, errors)
    by_id = {item.combo_id: item for item in supplied}
    ordered = tuple(by_id[item] for item in INFO_GAIN_COMBO_ORDER)
    input_fingerprint = _hash(
        "member_baseline_inputs", [_batch_payload(item) for item in ordered]
    )
    bundles: list[ComboMemberBaselineBundle] = []
    for batch in ordered:
        bundle, batch_errors, batch_warnings = _evaluate_combo(
            batch, configuration
        )
        errors.extend(batch_errors)
        warnings.extend(batch_warnings)
        if bundle is not None:
            bundles.append(bundle)
    if errors:
        return _blocked_result(
            configuration,
            errors,
            warnings=warnings,
            input_fingerprint=input_fingerprint,
            bundles=tuple(bundles),
        )
    completed = sum(item.completed_member_count for item in bundles)
    failed = sum(item.failed_member_count for item in bundles)
    output_payload = [item.to_dict() for item in bundles]
    output_fingerprint = _hash("member_baseline_output", output_payload)
    audit = _build_audit(
        gate_status=CommonSampleGateStatus.READY.value,
        errors=(),
        warnings=tuple(_deduplicate(warnings)),
        bundles=tuple(bundles),
        completed=completed,
        failed=failed,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
        info_gain_contract_hash=configuration.info_gain_contract.content_hash,
    )
    return CommonSampleMemberBaselineResult(tuple(bundles), audit)


def serialize_common_sample_member_baseline_result(
    result: CommonSampleMemberBaselineResult,
) -> str:
    if not isinstance(result, CommonSampleMemberBaselineResult):
        raise TypeError("result must be CommonSampleMemberBaselineResult")
    return json.dumps(
        _canonical(result.to_dict()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _evaluate_combo(
    batch: CommonSampleMemberBaselineBatch,
    configuration: CommonSampleMemberBaselineConfig,
) -> tuple[
    ComboMemberBaselineBundle | None,
    list[MemberBaselineIssue],
    list[MemberBaselineIssue],
]:
    errors: list[MemberBaselineIssue] = []
    warnings: list[MemberBaselineIssue] = []
    contract = configuration.info_gain_contract
    combo_ref = next(
        item for item in contract.combination_references
        if item.combo_id == batch.combo_id
    )
    sample_ref = next(
        item for item in contract.common_sample_references
        if item.combo_id == batch.combo_id
    )
    if batch.combo_definition_version != combo_ref.combo_definition_version:
        errors.append(_issue("COMBO_VERSION_MISMATCH", "combo definition version drifted", batch.combo_id))
    if batch.common_sample_reference != sample_ref.common_sample_reference:
        errors.append(_issue("SAMPLE_REFERENCE_MISMATCH", "common sample reference drifted", batch.combo_id))
    if batch.declared_common_sample_fingerprint != sample_ref.common_sample_fingerprint:
        errors.append(_issue("SAMPLE_FINGERPRINT_MISMATCH", "common sample fingerprint drifted", batch.combo_id))
    if batch.get_provenance().get("synthetic_test_only") is not True:
        errors.append(_issue("NON_SYNTHETIC_INPUT", "current accepted evaluator is synthetic-only", batch.combo_id))
    manifest = batch.get_common_sample_manifest()
    frame = batch.get_member_frame()
    forbidden = _FORBIDDEN_COLUMNS & {str(column) for column in frame.columns}
    if forbidden:
        errors.append(
            _issue(
                "FORBIDDEN_DECISION_FIELD",
                "member baseline input must not carry selection, delta, or decision fields",
                batch.combo_id,
                field_name=",".join(sorted(forbidden)),
            )
        )
    if set(_MANIFEST_COLUMNS) - set(manifest.columns):
        errors.append(_issue("MANIFEST_COLUMNS_MISSING", "common sample manifest columns are missing", batch.combo_id))
    else:
        manifest = manifest.loc[:, _MANIFEST_COLUMNS].copy()
        manifest["evaluation_date"] = manifest["evaluation_date"].astype(str)
        manifest["security_id"] = manifest["security_id"].astype(str)
        if len(manifest) != sample_ref.common_sample_row_count:
            errors.append(_issue("SAMPLE_ROW_COUNT_MISMATCH", "common sample must contain 900 rows", batch.combo_id))
        if manifest["evaluation_date"].nunique() != sample_ref.evaluation_period_count:
            errors.append(_issue("SAMPLE_PERIOD_COUNT_MISMATCH", "common sample must contain 18 periods", batch.combo_id))
        if bool(manifest.duplicated(list(_KEY_COLUMNS)).any()):
            errors.append(_issue("DUPLICATE_SAMPLE_KEY", "common sample keys must be unique", batch.combo_id))
        if not manifest["eligible"].map(lambda value: type(value) in (bool, np.bool_)).all():
            errors.append(_issue("INVALID_ELIGIBLE", "eligible must be boolean", batch.combo_id))
        elif not manifest["eligible"].map(bool).all():
            errors.append(_issue("INELIGIBLE_COMMON_ROW", "explicit common sample rows must all be eligible", batch.combo_id))
        manifest = manifest.sort_values(list(_KEY_COLUMNS), kind="stable").reset_index(drop=True)
    if set(_FRAME_COLUMNS) - set(frame.columns):
        errors.append(_issue("MEMBER_FRAME_COLUMNS_MISSING", "member frame columns are missing", batch.combo_id))
    else:
        frame = frame.loc[:, _FRAME_COLUMNS].copy()
        for column in (*_KEY_COLUMNS, "member_factor_id"):
            frame[column] = frame[column].astype(str)
        if bool(frame.duplicated([*_KEY_COLUMNS, "member_factor_id"]).any()):
            errors.append(_issue("DUPLICATE_MEMBER_KEY", "member frame keys must be unique", batch.combo_id))
    expected_members = tuple(item[0] for item in combo_ref.member_directions)
    if not errors:
        actual_members = set(frame["member_factor_id"])
        if actual_members != set(expected_members):
            errors.append(_issue("MEMBER_SET_MISMATCH", "member set does not match frozen combo", batch.combo_id))
        manifest_keys = set(map(tuple, manifest.loc[:, _KEY_COLUMNS].itertuples(index=False, name=None)))
        for member_id in expected_members:
            member = frame[frame["member_factor_id"] == member_id]
            member_keys = set(map(tuple, member.loc[:, _KEY_COLUMNS].itertuples(index=False, name=None)))
            if member_keys != manifest_keys:
                errors.append(_issue("MEMBER_SAMPLE_KEYS_MISMATCH", "member rows must equal the explicit common sample", batch.combo_id, member_id))
        for _, group in frame.groupby(list(_KEY_COLUMNS), sort=False):
            for column in _LABEL_CONTROL_COLUMNS:
                if group[column].nunique(dropna=False) > 1:
                    errors.append(_issue("LABEL_OR_CONTROL_MISMATCH", "members must share labels and controls", batch.combo_id, field_name=column))
                    break
            if errors:
                break
    formula_versions = batch.get_member_formula_versions()
    run_references = batch.get_source_factor_run_references()
    if set(formula_versions) != set(expected_members):
        errors.append(_issue("FORMULA_VERSION_SET_MISMATCH", "formula versions must cover every frozen member", batch.combo_id))
    if set(run_references) != set(expected_members):
        errors.append(_issue("SOURCE_RUN_SET_MISMATCH", "source run references must cover every frozen member", batch.combo_id))
    if errors:
        return None, errors, warnings
    runs: list[CommonSampleMemberBaselineRun] = []
    direction_by_member = dict(combo_ref.member_directions)
    for member_id in expected_members:
        run, issue = _evaluate_member(
            batch=batch,
            configuration=configuration,
            manifest=manifest,
            frame=frame[frame["member_factor_id"] == member_id].copy(),
            member_id=member_id,
            member_direction=direction_by_member[member_id],
            formula_version=formula_versions[member_id],
            source_run_reference=run_references[member_id],
            expected_fingerprint=sample_ref.common_sample_fingerprint,
        )
        runs.append(run)
        if issue is not None:
            warnings.append(issue)
    completed = sum(item.calculation_status == "completed" for item in runs)
    failed = sum(item.calculation_status == "blocked" for item in runs)
    not_evaluable = sum(
        item.calculation_status in {"not_applicable", "insufficient"}
        for item in runs
    )
    bundle_status = (
        EvaluationStatus.COMPLETED.value
        if completed == len(expected_members)
        else EvaluationStatus.PARTIAL.value
    )
    payload = {
        "combo_id": batch.combo_id,
        "common_sample_fingerprint": sample_ref.common_sample_fingerprint,
        "per_period_common_sample_counts": [
            {"evaluation_date": date, "count": int(count)}
            for date, count in manifest.groupby("evaluation_date", sort=True).size().items()
        ],
        "member_baselines": [item.to_dict() for item in runs],
        "expected_member_count": len(expected_members),
        "completed_member_count": completed,
        "failed_member_count": failed,
        "not_evaluable_member_count": not_evaluable,
        "bundle_status": bundle_status,
        "schema_version": MEMBER_BASELINE_BUNDLE_SCHEMA_VERSION,
    }
    bundle = ComboMemberBaselineBundle(
        combo_id=batch.combo_id,
        common_sample_fingerprint=sample_ref.common_sample_fingerprint,
        per_period_common_sample_counts=tuple(
            (str(date), int(count))
            for date, count in manifest.groupby("evaluation_date", sort=True).size().items()
        ),
        member_baselines=tuple(runs),
        expected_member_count=len(expected_members),
        completed_member_count=completed,
        failed_member_count=failed,
        not_evaluable_member_count=not_evaluable,
        bundle_status=bundle_status,
        schema_version=MEMBER_BASELINE_BUNDLE_SCHEMA_VERSION,
        content_hash=_hash("member_baseline_bundle", payload),
    )
    return bundle, errors, warnings


def _evaluate_member(
    *,
    batch: CommonSampleMemberBaselineBatch,
    configuration: CommonSampleMemberBaselineConfig,
    manifest: pd.DataFrame,
    frame: pd.DataFrame,
    member_id: str,
    member_direction: str,
    formula_version: str,
    source_run_reference: str,
    expected_fingerprint: str,
) -> tuple[CommonSampleMemberBaselineRun, MemberBaselineIssue | None]:
    directed = pd.to_numeric(frame["factor_value"], errors="coerce")
    if member_direction == "negative":
        directed = -directed
    evaluator_frame = pd.DataFrame(
        {
            "evaluation_date": frame["evaluation_date"],
            "security_id": frame["security_id"],
            "factor_effective_date": frame["factor_effective_date"],
            "control_effective_date": frame["control_effective_date"],
            "return_start_date": frame["return_start_date"],
            "single_factor_value": directed,
            "combined_factor_value": directed,
            "forward_return": frame["forward_return"],
            "size_control": frame["size_control"],
            "industry_code": frame["industry_code"],
        }
    )
    evaluator_manifest = manifest.copy(deep=True)
    manifest_fingerprint = compute_common_sample_manifest_fingerprint(
        evaluator_manifest
    )
    evaluator_batch = FinancialP3CommonSampleBatch(
        dataset_id=f"{batch.dataset_id}:{member_id}",
        version=batch.version,
        _manifest=evaluator_manifest,
        _frame=evaluator_frame,
        declared_manifest_fingerprint=manifest_fingerprint,
        gate_anchor={
            "task_id": "FIN-P2-GATE",
            "status": "ACCEPTED",
            "output_fingerprint": COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT,
            "research_integrity_status": "complete",
            "production_status": INFO_GAIN_PRODUCTION_STATUS,
        },
        provenance={
            "synthetic_test_only": True,
            "purpose": "common_sample_member_baseline",
            "combo_id": batch.combo_id,
            "member_factor_id": member_id,
        },
    )
    evaluator_config = FinancialP3CommonSampleConfig(
        comparison_id=f"{configuration.run_id}:{batch.combo_id}:{member_id}",
        single_factor_id=member_id,
        combined_factor_id=f"MEMBER_BASELINE_PLACEHOLDER_{batch.combo_id}_{member_id}",
        single_formula_version=formula_version,
        combined_formula_version="MEMBER-BASELINE-IDENTITY-v1.0",
        expected_manifest_fingerprint=manifest_fingerprint,
        execution_timestamp=configuration.execution_timestamp,
    )
    result = evaluate_financial_p3_common_sample(
        evaluator_batch, configuration=evaluator_config
    )
    metrics = None
    status = "blocked"
    warnings: list[str] = []
    issue: MemberBaselineIssue | None = None
    if (
        result.common_sample_audit.gate_status == "ready"
        and result.comparison is not None
        and result.comparison.single_factor_metrics is not None
        and result.common_sample_audit.common_sample_fingerprint
        == expected_fingerprint
    ):
        metrics = result.comparison.single_factor_metrics
        status = "completed"
    else:
        code = (
            "COMMON_SAMPLE_FINGERPRINT_MISMATCH"
            if result.common_sample_audit.common_sample_fingerprint
            != expected_fingerprint
            else "MEMBER_EVALUATOR_FAILED"
        )
        warnings.extend(item.code for item in result.common_sample_audit.errors)
        warnings.append(code)
        issue = _issue(
            code,
            "member baseline was retained as failed",
            batch.combo_id,
            member_id,
        )
    m_results = (
        MemberTrackBaselineResult(
            "M", "5D", "not_run", "not_called", "CONTEXT_NOT_FROZEN", None
        ),
        MemberTrackBaselineResult(
            "M",
            "20D",
            status,
            "backend.amr.financial_p3_common_sample.evaluate_financial_p3_common_sample",
            None if status == "completed" else "MEMBER_EVALUATOR_FAILED",
            metrics,
        ),
        MemberTrackBaselineResult(
            "M", "60D", "not_run", "not_called", "CONTEXT_NOT_FROZEN", None
        ),
    )
    f_result = MemberTrackBaselineResult(
        "F", "F", "not_run", "not_called", "CONTEXT_NOT_FROZEN", None
    )
    r_result = MemberTrackBaselineResult(
        "R", "R", "not_run", "not_called", "CONTEXT_NOT_FROZEN", None
    )
    payload = {
        "schema_version": MEMBER_BASELINE_SCHEMA_VERSION,
        "run_id": configuration.run_id,
        "contract_version": configuration.info_gain_contract.contract_version,
        "combo_id": batch.combo_id,
        "combo_definition_version": batch.combo_definition_version,
        "member_factor_id": member_id,
        "member_direction": member_direction,
        "common_sample_reference": batch.common_sample_reference,
        "common_sample_fingerprint": expected_fingerprint,
        "evaluation_config_reference": configuration.evaluation_config_reference,
        "source_factor_run_reference": source_run_reference,
        "source_label_references": list(batch.source_label_references),
        "evaluation_period_count": manifest["evaluation_date"].nunique(),
        "common_sample_row_count": len(manifest),
        "m_track_results": [item.to_dict() for item in m_results],
        "f_track_result": f_result.to_dict(),
        "r_track_result": r_result.to_dict(),
        "calculation_status": status,
        "warnings": warnings,
        "limitations": [
            "M 5D/60D and F/R contexts are not frozen and remain not_run",
            "synthetic common-sample research only; not production evidence",
        ],
    }
    run = CommonSampleMemberBaselineRun(
        schema_version=MEMBER_BASELINE_SCHEMA_VERSION,
        run_id=configuration.run_id,
        contract_version=configuration.info_gain_contract.contract_version,
        combo_id=batch.combo_id,
        combo_definition_version=batch.combo_definition_version,
        member_factor_id=member_id,
        member_direction=member_direction,
        common_sample_reference=batch.common_sample_reference,
        common_sample_fingerprint=expected_fingerprint,
        evaluation_config_reference=configuration.evaluation_config_reference,
        source_factor_run_reference=source_run_reference,
        source_label_references=batch.source_label_references,
        evaluation_period_count=int(manifest["evaluation_date"].nunique()),
        common_sample_row_count=len(manifest),
        m_track_results=m_results,
        f_track_result=f_result,
        r_track_result=r_result,
        calculation_status=status,
        warnings=tuple(warnings),
        limitations=tuple(payload["limitations"]),
        content_hash=_hash("member_baseline_run", payload),
    )
    return run, issue


def _blocked_result(
    configuration: CommonSampleMemberBaselineConfig,
    errors: Sequence[MemberBaselineIssue],
    *,
    warnings: Sequence[MemberBaselineIssue] = (),
    input_fingerprint: str | None = None,
    bundles: tuple[ComboMemberBaselineBundle, ...] = (),
) -> CommonSampleMemberBaselineResult:
    input_fp = input_fingerprint or _hash("member_baseline_inputs", [])
    output_fp = _hash("member_baseline_output", [item.to_dict() for item in bundles])
    audit = _build_audit(
        gate_status=CommonSampleGateStatus.BLOCKED.value,
        errors=tuple(_deduplicate(errors)),
        warnings=tuple(_deduplicate(warnings)),
        bundles=bundles,
        completed=sum(item.completed_member_count for item in bundles),
        failed=sum(item.failed_member_count for item in bundles),
        input_fingerprint=input_fp,
        output_fingerprint=output_fp,
        info_gain_contract_hash=configuration.info_gain_contract.content_hash,
    )
    return CommonSampleMemberBaselineResult(bundles, audit)


def _build_audit(
    *,
    gate_status: str,
    errors: tuple[MemberBaselineIssue, ...],
    warnings: tuple[MemberBaselineIssue, ...],
    bundles: tuple[ComboMemberBaselineBundle, ...],
    completed: int,
    failed: int,
    input_fingerprint: str,
    output_fingerprint: str,
    info_gain_contract_hash: str,
) -> CommonSampleMemberBaselineAudit:
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "combo_count": len(bundles),
        "expected_member_count": sum(item.expected_member_count for item in bundles),
        "completed_member_count": completed,
        "failed_member_count": failed,
        "same_sample_enforced": True,
        "member_full_sample_reused": False,
        "existing_evaluator_reused": True,
        "combination_reconstructed": False,
        "information_gain_delta_calculated": False,
        "information_gain_decision_made": False,
        "production_status": INFO_GAIN_PRODUCTION_STATUS,
        "info_gain_contract_hash": info_gain_contract_hash,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": output_fingerprint,
        "schema_version": MEMBER_BASELINE_SCHEMA_VERSION,
        "audit_schema_version": MEMBER_BASELINE_AUDIT_SCHEMA_VERSION,
        "policy_version": MEMBER_BASELINE_POLICY_VERSION,
        "hash_contract_version": MEMBER_BASELINE_HASH_CONTRACT_VERSION,
        "conclusion_boundary": MEMBER_BASELINE_CONCLUSION_BOUNDARY,
    }
    return CommonSampleMemberBaselineAudit(
        gate_status=gate_status,
        errors=errors,
        warnings=warnings,
        combo_count=len(bundles),
        expected_member_count=sum(item.expected_member_count for item in bundles),
        completed_member_count=completed,
        failed_member_count=failed,
        same_sample_enforced=True,
        member_full_sample_reused=False,
        existing_evaluator_reused=True,
        combination_reconstructed=False,
        information_gain_delta_calculated=False,
        information_gain_decision_made=False,
        production_status=INFO_GAIN_PRODUCTION_STATUS,
        info_gain_contract_hash=info_gain_contract_hash,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
        schema_version=MEMBER_BASELINE_SCHEMA_VERSION,
        audit_schema_version=MEMBER_BASELINE_AUDIT_SCHEMA_VERSION,
        policy_version=MEMBER_BASELINE_POLICY_VERSION,
        hash_contract_version=MEMBER_BASELINE_HASH_CONTRACT_VERSION,
        conclusion_boundary=MEMBER_BASELINE_CONCLUSION_BOUNDARY,
        content_hash=_hash("member_baseline_audit", payload),
    )


def _batch_payload(batch: CommonSampleMemberBaselineBatch) -> dict[str, Any]:
    return {
        "dataset_id": batch.dataset_id,
        "version": batch.version,
        "combo_id": batch.combo_id,
        "combo_definition_version": batch.combo_definition_version,
        "common_sample_reference": batch.common_sample_reference,
        "declared_common_sample_fingerprint": batch.declared_common_sample_fingerprint,
        "common_sample_manifest": _frame_records(batch.get_common_sample_manifest()),
        "member_frame": _frame_records(batch.get_member_frame()),
        "member_formula_versions": batch.get_member_formula_versions(),
        "source_factor_run_references": batch.get_source_factor_run_references(),
        "source_label_references": list(batch.source_label_references),
        "provenance": batch.get_provenance(),
    }


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    normalized = frame.copy(deep=True)
    normalized = normalized.reindex(sorted(normalized.columns), axis=1)
    if set(_KEY_COLUMNS).issubset(normalized.columns):
        sort_columns = [column for column in (*_KEY_COLUMNS, "member_factor_id") if column in normalized.columns]
        normalized = normalized.sort_values(sort_columns, kind="stable")
    records: list[dict[str, Any]] = []
    for record in normalized.to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for key, value in record.items():
            if pd.isna(value):
                clean[key] = None
            elif isinstance(value, (np.integer,)):
                clean[key] = int(value)
            elif isinstance(value, (np.floating,)):
                clean[key] = float(value)
            elif isinstance(value, (np.bool_,)):
                clean[key] = bool(value)
            else:
                clean[key] = value
        records.append(clean)
    return records


def _issue(
    code: str,
    message: str,
    combo_id: str | None = None,
    member_factor_id: str | None = None,
    field_name: str | None = None,
) -> MemberBaselineIssue:
    return MemberBaselineIssue(code, message, combo_id, member_factor_id, field_name)


def _deduplicate(items: Sequence[MemberBaselineIssue]) -> list[MemberBaselineIssue]:
    output: list[MemberBaselineIssue] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        key = (item.code, item.message, item.combo_id, item.member_factor_id, item.field_name)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        return float(value)
    raise TypeError(f"unsupported canonical type: {type(value).__name__}")


def _hash(domain: str, value: Any) -> str:
    payload = json.dumps(
        {"domain": domain, "value": _canonical(value)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
