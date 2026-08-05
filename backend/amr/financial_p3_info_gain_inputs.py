"""INFO-GAIN-02A: prepare frozen common-sample inputs without evaluation.

The caller supplies explicit accepted common-sample rows.  This module only
validates and packages those rows with frozen member, label, configuration,
and provenance references.  It never intersects samples, constructs a
combination, calls an M/F/R evaluator, or calculates a metric or increment.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from backend.amr.financial_p3_common_sample import (
    COMMON_SAMPLE_HASH_CONTRACT_VERSION,
)
from backend.amr.financial_p3_info_gain_contract import (
    INFO_GAIN_COMBO_ORDER,
    INFO_GAIN_CONTRACT_VERSION,
    INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT,
    INFO_GAIN_PRODUCTION_STATUS,
    InfoGainEvaluationConfig,
)


INFO_GAIN_INPUT_SCHEMA_VERSION = "FinancialP3InfoGainInputPackage-v1.0"
INFO_GAIN_INPUT_AUDIT_SCHEMA_VERSION = (
    "FinancialP3InfoGainInputPreparationAudit-v1.0"
)
INFO_GAIN_INPUT_POLICY_VERSION = "FIN-P3-INFO-GAIN-02A-POLICY-v1.0"
INFO_GAIN_INPUT_HASH_CONTRACT_VERSION = "FIN-P3-INFO-GAIN-02A-HASH-v1.0"
INFO_GAIN_INPUT_CONCLUSION_BOUNDARY = (
    "Frozen common-sample input preparation only. No sample reconstruction, "
    "combination construction, M/F/R evaluation, metric, strongest-member "
    "selection, information-gain, admission, production, empirical-return, "
    "fraud, or trading conclusion."
)

_KEY_COLUMNS = ("evaluation_date", "security_id")
_MANIFEST_COLUMNS = (*_KEY_COLUMNS, "eligible")
_MEMBER_FRAME_COLUMNS = (
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
    "selected_member",
    "best_member",
    "best_member_factor_id",
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
class InfoGainInputIssue:
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
class InfoGainInputPreparationConfig:
    run_id: str
    contract: InfoGainEvaluationConfig
    predecessor_task: str = "FIN-P3-COMBOS"
    predecessor_status: str = "ACCEPTED"
    predecessor_output_fingerprint: str = (
        INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT
    )
    synthetic_test_only: bool = True
    sample_reconstruction_allowed: bool = False
    evaluator_execution_allowed: bool = False
    metric_calculation_allowed: bool = False
    information_gain_decision_allowed: bool = False
    policy_version: str = INFO_GAIN_INPUT_POLICY_VERSION
    schema_version: str = INFO_GAIN_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _required_text(self.run_id, "run_id")
        if not isinstance(self.contract, InfoGainEvaluationConfig):
            raise TypeError("contract must be InfoGainEvaluationConfig")
        if self.contract.contract_version != INFO_GAIN_CONTRACT_VERSION:
            raise ValueError("INFO-GAIN-01 contract version mismatch")
        frozen = {
            "predecessor_task": (self.predecessor_task, "FIN-P3-COMBOS"),
            "predecessor_status": (self.predecessor_status, "ACCEPTED"),
            "predecessor_output_fingerprint": (
                self.predecessor_output_fingerprint,
                INFO_GAIN_PREDECESSOR_OUTPUT_FINGERPRINT,
            ),
            "synthetic_test_only": (self.synthetic_test_only, True),
            "sample_reconstruction_allowed": (
                self.sample_reconstruction_allowed,
                False,
            ),
            "evaluator_execution_allowed": (
                self.evaluator_execution_allowed,
                False,
            ),
            "metric_calculation_allowed": (
                self.metric_calculation_allowed,
                False,
            ),
            "information_gain_decision_allowed": (
                self.information_gain_decision_allowed,
                False,
            ),
            "policy_version": (
                self.policy_version,
                INFO_GAIN_INPUT_POLICY_VERSION,
            ),
            "schema_version": (
                self.schema_version,
                INFO_GAIN_INPUT_SCHEMA_VERSION,
            ),
        }
        for field_name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{field_name} must be frozen at {expected!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "contract_hash": self.contract.content_hash,
            "predecessor_task": self.predecessor_task,
            "predecessor_status": self.predecessor_status,
            "predecessor_output_fingerprint": (
                self.predecessor_output_fingerprint
            ),
            "synthetic_test_only": self.synthetic_test_only,
            "sample_reconstruction_allowed": (
                self.sample_reconstruction_allowed
            ),
            "evaluator_execution_allowed": self.evaluator_execution_allowed,
            "metric_calculation_allowed": self.metric_calculation_allowed,
            "information_gain_decision_allowed": (
                self.information_gain_decision_allowed
            ),
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class InfoGainCommonSampleInputBatch:
    dataset_id: str
    version: str
    combo_id: str
    combo_definition_version: str
    common_sample_reference: str
    declared_common_sample_fingerprint: str
    _common_sample_manifest: pd.DataFrame
    _member_observations: pd.DataFrame
    member_formula_versions: Mapping[str, str]
    source_factor_run_references: Mapping[str, str]
    track_input_references: Mapping[str, Mapping[str, Any]]
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
        if not isinstance(self._member_observations, pd.DataFrame):
            raise TypeError("_member_observations must be a DataFrame")
        object.__setattr__(
            self,
            "_common_sample_manifest",
            self._common_sample_manifest.copy(deep=True),
        )
        object.__setattr__(
            self,
            "_member_observations",
            self._member_observations.copy(deep=True),
        )
        for field_name in (
            "member_formula_versions",
            "source_factor_run_references",
            "track_input_references",
            "provenance",
        ):
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(copy.deepcopy(dict(getattr(self, field_name)))),
            )

    def get_common_sample_manifest(self) -> pd.DataFrame:
        return self._common_sample_manifest.copy(deep=True)

    def get_member_observations(self) -> pd.DataFrame:
        return self._member_observations.copy(deep=True)

    def get_member_formula_versions(self) -> dict[str, str]:
        return copy.deepcopy(dict(self.member_formula_versions))

    def get_source_factor_run_references(self) -> dict[str, str]:
        return copy.deepcopy(dict(self.source_factor_run_references))

    def get_track_input_references(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.track_input_references))

    def get_provenance(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.provenance))


@dataclass(frozen=True)
class PreparedTrackInput:
    track_id: str
    preparation_status: str
    evaluation_contexts: tuple[str, ...]
    label_references: tuple[str, ...]
    evaluation_config_reference: str | None
    reason_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "preparation_status": self.preparation_status,
            "evaluation_contexts": list(self.evaluation_contexts),
            "label_references": list(self.label_references),
            "evaluation_config_reference": self.evaluation_config_reference,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class PreparedInfoGainCommonSampleInput:
    dataset_id: str
    version: str
    combo_id: str
    combo_definition_version: str
    common_sample_reference: str
    common_sample_fingerprint: str
    evaluation_period_count: int
    common_sample_row_count: int
    per_period_row_counts: tuple[tuple[str, int], ...]
    member_directions: tuple[tuple[str, str], ...]
    member_formula_versions: tuple[tuple[str, str], ...]
    source_factor_run_references: tuple[tuple[str, str], ...]
    track_inputs: tuple[PreparedTrackInput, ...]
    _common_sample_manifest: pd.DataFrame
    _member_observations: pd.DataFrame
    provenance: Mapping[str, Any]
    schema_version: str
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_common_sample_manifest",
            self._common_sample_manifest.copy(deep=True),
        )
        object.__setattr__(
            self,
            "_member_observations",
            self._member_observations.copy(deep=True),
        )
        object.__setattr__(
            self,
            "provenance",
            MappingProxyType(copy.deepcopy(dict(self.provenance))),
        )

    def get_common_sample_manifest(self) -> pd.DataFrame:
        return self._common_sample_manifest.copy(deep=True)

    def get_member_observations(self) -> pd.DataFrame:
        return self._member_observations.copy(deep=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "combo_id": self.combo_id,
            "combo_definition_version": self.combo_definition_version,
            "common_sample_reference": self.common_sample_reference,
            "common_sample_fingerprint": self.common_sample_fingerprint,
            "evaluation_period_count": self.evaluation_period_count,
            "common_sample_row_count": self.common_sample_row_count,
            "per_period_row_counts": [
                {"evaluation_date": date, "row_count": count}
                for date, count in self.per_period_row_counts
            ],
            "member_directions": dict(self.member_directions),
            "member_formula_versions": dict(self.member_formula_versions),
            "source_factor_run_references": dict(
                self.source_factor_run_references
            ),
            "track_inputs": [item.to_dict() for item in self.track_inputs],
            "common_sample_manifest": _frame_records(
                self.get_common_sample_manifest()
            ),
            "member_observations": _frame_records(
                self.get_member_observations()
            ),
            "provenance": copy.deepcopy(dict(self.provenance)),
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class InfoGainInputPreparationAudit:
    gate_status: str
    errors: tuple[InfoGainInputIssue, ...]
    warnings: tuple[InfoGainInputIssue, ...]
    combo_count: int
    total_common_sample_rows: int
    exact_frozen_samples_verified: bool
    pit_safe: bool
    common_input_packages_created: bool
    sample_reconstructed: bool
    combination_constructed: bool
    evaluator_calls_performed: bool
    metrics_calculated: bool
    strongest_member_selected: bool
    information_gain_decision_made: bool
    contract_hash: str
    predecessor_output_fingerprint: str
    input_fingerprint: str
    output_fingerprint: str
    production_status: str
    conclusion_boundary: str
    schema_version: str
    audit_schema_version: str
    policy_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }
        values["errors"] = [item.to_dict() for item in self.errors]
        values["warnings"] = [item.to_dict() for item in self.warnings]
        return values


@dataclass(frozen=True)
class InfoGainInputPreparationResult:
    packages: tuple[PreparedInfoGainCommonSampleInput, ...]
    audit: InfoGainInputPreparationAudit

    def to_dict(self) -> dict[str, Any]:
        return {
            "packages": [item.to_dict() for item in self.packages],
            "audit": self.audit.to_dict(),
        }


def prepare_financial_p3_info_gain_inputs(
    batches: Sequence[InfoGainCommonSampleInputBatch],
    *,
    configuration: InfoGainInputPreparationConfig,
) -> InfoGainInputPreparationResult:
    if not isinstance(configuration, InfoGainInputPreparationConfig):
        raise TypeError("configuration must be InfoGainInputPreparationConfig")
    supplied = tuple(batches)
    errors: list[InfoGainInputIssue] = []
    warnings: list[InfoGainInputIssue] = []
    if any(not isinstance(item, InfoGainCommonSampleInputBatch) for item in supplied):
        errors.append(_issue("INVALID_BATCH", "all batches must use the formal input type"))
        return _blocked(configuration, errors)
    combo_ids = [item.combo_id for item in supplied]
    if len(combo_ids) != len(set(combo_ids)):
        errors.append(_issue("DUPLICATE_COMBO", "combo batches must be unique"))
    if set(combo_ids) != set(INFO_GAIN_COMBO_ORDER):
        errors.append(_issue("COMBO_SET_MISMATCH", "batches must be exactly VQ, QG, CASHQ"))
    if errors:
        return _blocked(configuration, errors)
    by_id = {item.combo_id: item for item in supplied}
    ordered = tuple(by_id[item] for item in INFO_GAIN_COMBO_ORDER)
    input_fingerprint = _hash(
        "p3_info_gain_02a_inputs",
        {
            "configuration": configuration.to_dict(),
            "batches": [_batch_payload(item) for item in ordered],
        },
    )
    packages: list[PreparedInfoGainCommonSampleInput] = []
    for batch in ordered:
        package, batch_errors, batch_warnings = _prepare_one(
            batch, configuration
        )
        errors.extend(batch_errors)
        warnings.extend(batch_warnings)
        if package is not None:
            packages.append(package)
    if errors:
        return _blocked(
            configuration,
            errors,
            warnings=warnings,
            packages=tuple(packages),
            input_fingerprint=input_fingerprint,
        )
    output_fingerprint = _hash(
        "p3_info_gain_02a_output",
        [item.to_dict() for item in packages],
    )
    audit = _build_audit(
        configuration=configuration,
        gate_status="ready",
        errors=(),
        warnings=tuple(_deduplicate(warnings)),
        packages=tuple(packages),
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
    )
    return InfoGainInputPreparationResult(tuple(packages), audit)


def serialize_info_gain_input_preparation_result(
    result: InfoGainInputPreparationResult,
) -> str:
    if not isinstance(result, InfoGainInputPreparationResult):
        raise TypeError("result must be InfoGainInputPreparationResult")
    return json.dumps(
        _canonical(result.to_dict()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _prepare_one(batch, configuration):
    errors: list[InfoGainInputIssue] = []
    warnings: list[InfoGainInputIssue] = []
    contract = configuration.contract
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
        errors.append(_issue("DECLARED_SAMPLE_FINGERPRINT_MISMATCH", "declared common sample fingerprint drifted", batch.combo_id))
    if batch.get_provenance().get("synthetic_test_only") is not True:
        errors.append(_issue("PROVENANCE_SCOPE_MISMATCH", "current accepted samples are synthetic-test-only", batch.combo_id))
    manifest = batch.get_common_sample_manifest()
    observations = batch.get_member_observations()
    forbidden = _FORBIDDEN_COLUMNS & {str(item) for item in observations.columns}
    if forbidden:
        errors.append(_issue("FORBIDDEN_DECISION_FIELD", "input contains selection, metric, or decision fields", batch.combo_id, field_name=",".join(sorted(forbidden))))
    missing_manifest = set(_MANIFEST_COLUMNS) - set(manifest.columns)
    if missing_manifest:
        errors.append(_issue("MANIFEST_COLUMNS_MISSING", "common sample manifest columns are missing", batch.combo_id, field_name=",".join(sorted(missing_manifest))))
    else:
        manifest = manifest.loc[:, _MANIFEST_COLUMNS].copy(deep=True)
        _normalize_keys(manifest, errors, batch.combo_id)
        invalid_eligible = ~manifest["eligible"].map(
            lambda value: type(value) in (bool, np.bool_)
        )
        if bool(invalid_eligible.any()):
            errors.append(_issue("INVALID_ELIGIBLE", "eligible must contain booleans", batch.combo_id, field_name="eligible"))
        elif not manifest["eligible"].map(bool).all():
            errors.append(_issue("INELIGIBLE_COMMON_ROW", "all explicit common rows must be eligible", batch.combo_id, field_name="eligible"))
        if bool(manifest.duplicated(list(_KEY_COLUMNS)).any()):
            errors.append(_issue("DUPLICATE_SAMPLE_KEY", "common sample keys must be unique", batch.combo_id))
        manifest = manifest.sort_values(list(_KEY_COLUMNS), kind="stable").reset_index(drop=True)
        if len(manifest) != sample_ref.common_sample_row_count:
            errors.append(_issue("SAMPLE_ROW_COUNT_MISMATCH", "common sample row count drifted", batch.combo_id))
        if manifest["evaluation_date"].nunique() != sample_ref.evaluation_period_count:
            errors.append(_issue("SAMPLE_PERIOD_COUNT_MISMATCH", "common sample period count drifted", batch.combo_id))
        actual_fingerprint = _common_sample_fingerprint(manifest)
        if actual_fingerprint != sample_ref.common_sample_fingerprint:
            errors.append(_issue("ACTUAL_SAMPLE_FINGERPRINT_MISMATCH", "explicit common sample keys drifted", batch.combo_id))
    missing_observations = set(_MEMBER_FRAME_COLUMNS) - set(observations.columns)
    if missing_observations:
        errors.append(_issue("MEMBER_COLUMNS_MISSING", "member observation columns are missing", batch.combo_id, field_name=",".join(sorted(missing_observations))))
    else:
        observations = observations.loc[:, _MEMBER_FRAME_COLUMNS].copy(deep=True)
        _normalize_keys(observations, errors, batch.combo_id)
        observations["member_factor_id"] = observations["member_factor_id"].map(
            lambda value: "" if pd.isna(value) else str(value).strip()
        )
        if bool(observations.duplicated([*_KEY_COLUMNS, "member_factor_id"]).any()):
            errors.append(_issue("DUPLICATE_MEMBER_KEY", "member security-date-factor keys must be unique", batch.combo_id))
        _validate_observation_values(observations, errors, batch.combo_id)
        observations = observations.sort_values(
            [*_KEY_COLUMNS, "member_factor_id"], kind="stable"
        ).reset_index(drop=True)
    expected_members = tuple(item[0] for item in combo_ref.member_directions)
    if not missing_observations:
        if set(observations["member_factor_id"]) != set(expected_members):
            errors.append(_issue("MEMBER_SET_MISMATCH", "member set does not match the frozen combo", batch.combo_id))
    if not missing_manifest and not missing_observations:
        manifest_keys = _key_set(manifest)
        for member_id in expected_members:
            member = observations[observations["member_factor_id"] == member_id]
            if _key_set(member) != manifest_keys:
                errors.append(_issue("MEMBER_SAMPLE_KEYS_MISMATCH", "member keys must equal the frozen common sample", batch.combo_id, member_id))
        for _, group in observations.groupby(list(_KEY_COLUMNS), sort=False):
            for column in _LABEL_CONTROL_COLUMNS:
                if group[column].nunique(dropna=False) > 1:
                    errors.append(_issue("LABEL_OR_CONTROL_MISMATCH", "members must share labels and controls", batch.combo_id, field_name=column))
                    break
            if errors:
                break
    formula_versions = batch.get_member_formula_versions()
    run_references = batch.get_source_factor_run_references()
    if set(formula_versions) != set(expected_members):
        errors.append(_issue("FORMULA_VERSION_SET_MISMATCH", "formula versions must cover all frozen members", batch.combo_id))
    if set(run_references) != set(expected_members):
        errors.append(_issue("SOURCE_RUN_SET_MISMATCH", "source runs must cover all frozen members", batch.combo_id))
    track_inputs = _validate_track_references(
        batch.get_track_input_references(), batch.combo_id, errors
    )
    if errors:
        return None, errors, warnings
    per_period = tuple(
        (str(date), int(count))
        for date, count in manifest.groupby("evaluation_date", sort=True).size().items()
    )
    payload = {
        "dataset_id": batch.dataset_id,
        "version": batch.version,
        "combo_id": batch.combo_id,
        "combo_definition_version": batch.combo_definition_version,
        "common_sample_reference": batch.common_sample_reference,
        "common_sample_fingerprint": sample_ref.common_sample_fingerprint,
        "evaluation_period_count": len(per_period),
        "common_sample_row_count": len(manifest),
        "per_period_row_counts": [
            {"evaluation_date": date, "row_count": count}
            for date, count in per_period
        ],
        "member_directions": dict(combo_ref.member_directions),
        "member_formula_versions": {
            item: formula_versions[item] for item in expected_members
        },
        "source_factor_run_references": {
            item: run_references[item] for item in expected_members
        },
        "track_inputs": [item.to_dict() for item in track_inputs],
        "common_sample_manifest": _frame_records(manifest),
        "member_observations": _frame_records(observations),
        "provenance": batch.get_provenance(),
        "schema_version": INFO_GAIN_INPUT_SCHEMA_VERSION,
    }
    package = PreparedInfoGainCommonSampleInput(
        dataset_id=batch.dataset_id,
        version=batch.version,
        combo_id=batch.combo_id,
        combo_definition_version=batch.combo_definition_version,
        common_sample_reference=batch.common_sample_reference,
        common_sample_fingerprint=sample_ref.common_sample_fingerprint,
        evaluation_period_count=len(per_period),
        common_sample_row_count=len(manifest),
        per_period_row_counts=per_period,
        member_directions=combo_ref.member_directions,
        member_formula_versions=tuple(
            (item, formula_versions[item]) for item in expected_members
        ),
        source_factor_run_references=tuple(
            (item, run_references[item]) for item in expected_members
        ),
        track_inputs=track_inputs,
        _common_sample_manifest=manifest,
        _member_observations=observations,
        provenance=batch.get_provenance(),
        schema_version=INFO_GAIN_INPUT_SCHEMA_VERSION,
        content_hash=_hash("p3_info_gain_02a_package", payload),
    )
    warnings.extend(
        (
            _issue("F_CONTEXT_NOT_FROZEN", "F input remains not_run", batch.combo_id),
            _issue("R_CONTEXT_NOT_FROZEN", "R input remains not_run", batch.combo_id),
        )
    )
    return package, errors, warnings


def _validate_observation_values(frame, errors, combo_id):
    for column in ("factor_value", "forward_return", "size_control"):
        converted = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(converted).all():
            errors.append(_issue("NONFINITE_REQUIRED_VALUE", "accepted common rows require finite values", combo_id, field_name=column))
        frame[column] = converted.astype(float)
    evaluation = pd.to_datetime(frame["evaluation_date"], errors="coerce", format="mixed")
    factor_effective = pd.to_datetime(frame["factor_effective_date"], errors="coerce", format="mixed")
    control_effective = pd.to_datetime(frame["control_effective_date"], errors="coerce", format="mixed")
    return_start = pd.to_datetime(frame["return_start_date"], errors="coerce", format="mixed")
    for column, values in (
        ("factor_effective_date", factor_effective),
        ("control_effective_date", control_effective),
        ("return_start_date", return_start),
    ):
        if bool(values.isna().any()):
            errors.append(_issue("INVALID_DATE", "date value is invalid", combo_id, field_name=column))
        frame[column] = values.dt.date.astype(str)
    if bool((factor_effective > evaluation).any()) or bool((control_effective > evaluation).any()):
        errors.append(_issue("FUTURE_FACTOR_OR_CONTROL", "factor/control effective dates must not exceed evaluation date", combo_id))
    if bool((return_start <= evaluation).any()):
        errors.append(_issue("INVALID_RETURN_ALIGNMENT", "return start must follow evaluation date", combo_id))
    frame["industry_code"] = frame["industry_code"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    if bool((frame["industry_code"] == "").any()):
        errors.append(_issue("MISSING_INDUSTRY_CONTROL", "industry control must be present", combo_id, field_name="industry_code"))


def _validate_track_references(references, combo_id, errors):
    if set(references) != {"M", "F", "R"}:
        errors.append(_issue("TRACK_REFERENCE_SET_MISMATCH", "track references must be exactly M, F, R", combo_id))
        return ()
    expected = {
        "M": ("ready", ("M:20D",), None),
        "F": ("not_run", (), "CONTEXT_NOT_FROZEN"),
        "R": ("not_run", (), "CONTEXT_NOT_FROZEN"),
    }
    output = []
    for track_id in ("M", "F", "R"):
        value = references[track_id]
        if not isinstance(value, Mapping):
            errors.append(_issue("INVALID_TRACK_REFERENCE", "track reference must be a mapping", combo_id, field_name=track_id))
            continue
        status = value.get("preparation_status")
        contexts = tuple(value.get("evaluation_contexts", ()))
        labels = tuple(value.get("label_references", ()))
        config_reference = value.get("evaluation_config_reference")
        reason = value.get("reason_code")
        expected_status, expected_contexts, expected_reason = expected[track_id]
        if (status, contexts, reason) != (
            expected_status,
            expected_contexts,
            expected_reason,
        ):
            errors.append(_issue("TRACK_STATUS_OR_CONTEXT_DRIFT", "track readiness or context drifted", combo_id, field_name=track_id))
        if track_id == "M":
            if not labels or not isinstance(config_reference, str) or not config_reference.strip():
                errors.append(_issue("M_REFERENCE_INCOMPLETE", "M:20D label and configuration references are required", combo_id))
        elif labels or config_reference is not None:
            errors.append(_issue("UNFROZEN_TRACK_REFERENCE_PRESENT", "F/R references must remain absent until separately frozen", combo_id, field_name=track_id))
        output.append(
            PreparedTrackInput(
                track_id=track_id,
                preparation_status=str(status),
                evaluation_contexts=contexts,
                label_references=tuple(str(item) for item in labels),
                evaluation_config_reference=(
                    None if config_reference is None else str(config_reference)
                ),
                reason_code=None if reason is None else str(reason),
            )
        )
    return tuple(output)


def _blocked(configuration, errors, *, warnings=(), packages=(), input_fingerprint=None):
    input_fp = input_fingerprint or _hash("p3_info_gain_02a_inputs", [])
    output_fp = _hash("p3_info_gain_02a_output", [item.to_dict() for item in packages])
    audit = _build_audit(
        configuration=configuration,
        gate_status="blocked",
        errors=tuple(_deduplicate(errors)),
        warnings=tuple(_deduplicate(warnings)),
        packages=tuple(packages),
        input_fingerprint=input_fp,
        output_fingerprint=output_fp,
    )
    return InfoGainInputPreparationResult(tuple(packages), audit)


def _build_audit(*, configuration, gate_status, errors, warnings, packages, input_fingerprint, output_fingerprint):
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "combo_count": len(packages),
        "total_common_sample_rows": sum(item.common_sample_row_count for item in packages),
        "exact_frozen_samples_verified": gate_status == "ready",
        "pit_safe": gate_status == "ready",
        "common_input_packages_created": gate_status == "ready",
        "sample_reconstructed": False,
        "combination_constructed": False,
        "evaluator_calls_performed": False,
        "metrics_calculated": False,
        "strongest_member_selected": False,
        "information_gain_decision_made": False,
        "contract_hash": configuration.contract.content_hash,
        "predecessor_output_fingerprint": configuration.predecessor_output_fingerprint,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": output_fingerprint,
        "production_status": INFO_GAIN_PRODUCTION_STATUS,
        "conclusion_boundary": INFO_GAIN_INPUT_CONCLUSION_BOUNDARY,
        "schema_version": INFO_GAIN_INPUT_SCHEMA_VERSION,
        "audit_schema_version": INFO_GAIN_INPUT_AUDIT_SCHEMA_VERSION,
        "policy_version": INFO_GAIN_INPUT_POLICY_VERSION,
        "hash_contract_version": INFO_GAIN_INPUT_HASH_CONTRACT_VERSION,
    }
    return InfoGainInputPreparationAudit(
        gate_status=gate_status,
        errors=errors,
        warnings=warnings,
        combo_count=len(packages),
        total_common_sample_rows=sum(item.common_sample_row_count for item in packages),
        exact_frozen_samples_verified=gate_status == "ready",
        pit_safe=gate_status == "ready",
        common_input_packages_created=gate_status == "ready",
        sample_reconstructed=False,
        combination_constructed=False,
        evaluator_calls_performed=False,
        metrics_calculated=False,
        strongest_member_selected=False,
        information_gain_decision_made=False,
        contract_hash=configuration.contract.content_hash,
        predecessor_output_fingerprint=configuration.predecessor_output_fingerprint,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
        production_status=INFO_GAIN_PRODUCTION_STATUS,
        conclusion_boundary=INFO_GAIN_INPUT_CONCLUSION_BOUNDARY,
        schema_version=INFO_GAIN_INPUT_SCHEMA_VERSION,
        audit_schema_version=INFO_GAIN_INPUT_AUDIT_SCHEMA_VERSION,
        policy_version=INFO_GAIN_INPUT_POLICY_VERSION,
        hash_contract_version=INFO_GAIN_INPUT_HASH_CONTRACT_VERSION,
        content_hash=_hash("p3_info_gain_02a_audit", payload),
    )


def _batch_payload(batch):
    return {
        "dataset_id": batch.dataset_id,
        "version": batch.version,
        "combo_id": batch.combo_id,
        "combo_definition_version": batch.combo_definition_version,
        "common_sample_reference": batch.common_sample_reference,
        "declared_common_sample_fingerprint": batch.declared_common_sample_fingerprint,
        "common_sample_manifest": _frame_records(batch.get_common_sample_manifest()),
        "member_observations": _frame_records(batch.get_member_observations()),
        "member_formula_versions": batch.get_member_formula_versions(),
        "source_factor_run_references": batch.get_source_factor_run_references(),
        "track_input_references": batch.get_track_input_references(),
        "provenance": batch.get_provenance(),
    }


def _common_sample_fingerprint(manifest):
    payload = {
        "domain": "p3_common_sample_rows",
        "hash_contract_version": COMMON_SAMPLE_HASH_CONTRACT_VERSION,
        "value": _canonical(
            _frame_records(manifest.loc[:, _KEY_COLUMNS])
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_keys(frame, errors, combo_id):
    parsed = pd.to_datetime(frame["evaluation_date"], errors="coerce", format="mixed")
    if bool(parsed.isna().any()):
        errors.append(_issue("INVALID_KEY", "evaluation_date is invalid", combo_id, field_name="evaluation_date"))
    frame["evaluation_date"] = parsed.dt.date.astype(str)
    frame["security_id"] = frame["security_id"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    if bool((frame["security_id"] == "").any()):
        errors.append(_issue("INVALID_KEY", "security_id must be non-empty", combo_id, field_name="security_id"))


def _key_set(frame):
    return set(
        map(
            tuple,
            frame.loc[:, _KEY_COLUMNS].itertuples(index=False, name=None),
        )
    )


def _frame_records(frame):
    normalized = frame.copy(deep=True).reindex(sorted(frame.columns), axis=1)
    sort_columns = [
        item for item in (*_KEY_COLUMNS, "member_factor_id")
        if item in normalized.columns
    ]
    if sort_columns:
        normalized = normalized.sort_values(sort_columns, kind="stable")
    records = []
    for record in normalized.to_dict(orient="records"):
        clean = {}
        for key, value in record.items():
            if pd.isna(value):
                clean[key] = None
            elif isinstance(value, np.bool_):
                clean[key] = bool(value)
            elif isinstance(value, np.integer):
                clean[key] = int(value)
            elif isinstance(value, np.floating):
                clean[key] = float(value)
            else:
                clean[key] = value
        records.append(clean)
    return records


def _issue(code, message, combo_id=None, member_factor_id=None, field_name=None):
    return InfoGainInputIssue(
        code, message, combo_id, member_factor_id, field_name
    )


def _deduplicate(items):
    output = []
    seen = set()
    for item in items:
        key = (
            item.code,
            item.message,
            item.combo_id,
            item.member_factor_id,
            item.field_name,
        )
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _required_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _is_sha256(value):
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _canonical(value):
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
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
