"""FIN-P3-COMBOS: deterministic FIN-24 preset combination experiments.

The module constructs exactly three equal-weight combinations on PIT-safe,
independently eligible cross-sections.  Each predeclared reference/composite
pair is evaluated through the accepted FIN-23 common-sample comparator.  It
does not select a best factor or make a FIN-25 information-gain decision.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd

from backend.amr.financial_fingerprint import canonicalize_financial_fingerprint
from backend.amr.financial_p3_common_sample import (
    COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT,
    FinancialP3CommonSampleAudit,
    FinancialP3CommonSampleBatch,
    FinancialP3CommonSampleComparison,
    FinancialP3CommonSampleConfig,
    compute_common_sample_manifest_fingerprint,
    evaluate_financial_p3_common_sample,
)

COMBINATIONS_SCHEMA_VERSION = "FinancialP3Combinations-v1.0"
COMBINATIONS_AUDIT_SCHEMA_VERSION = "FinancialP3CombinationsAudit-v1.0"
COMBINATIONS_POLICY_VERSION = "FIN-P3-COMBOS-POLICY-v1.0"
COMBINATIONS_HASH_CONTRACT_VERSION = "FIN-P3-COMBOS-HASH-v2.2"
COMBINATIONS_FINGERPRINT_FLOAT_DECIMALS = 8
COMBINATIONS_PREDECESSOR_OUTPUT_FINGERPRINT = (
    "a15859003aadf685aeea6bc9941aa62133bba0cf8e5913a1289735d33d94ce6e"
)
COMBINATIONS_RESEARCH_ASSESSMENT = "exploratory"
COMBINATIONS_PRODUCTION_STATUS = "not production ready"
COMBINATIONS_ADMISSION_STATUS = "not_assessed"
COMBINATIONS_MIN_CROSS_SECTION = 30
COMBINATIONS_MIN_PERIODS = 12
COMBINATIONS_CONCLUSION_BOUNDARY = (
    "Synthetic FIN-24 preset equal-weight construction and FIN-23 common-"
    "sample evaluation only; metrics and deltas are not a FIN-25 information-"
    "gain determination, best-factor selection, admission or rejection, "
    "production approval, empirical return claim, or trading instruction."
)

_MANIFEST_COLUMNS = ("evaluation_date", "security_id", "eligible")
_KEY_COLUMNS = ("evaluation_date", "security_id")
_VALUE_COLUMNS = {
    "BP": "bp",
    "EBIT_EV": "ebit_ev",
    "ROE": "roe",
    "OCF_NP": "ocf_np",
    "SALES_GROWTH": "sales_growth",
    "PROFIT_GROWTH": "profit_growth",
    "ROA": "roa",
    "OCF_SALES": "ocf_sales",
    "ACCRUALS": "accruals",
}
_EFFECTIVE_DATE_COLUMNS = {
    factor_id: f"{column}_effective_date"
    for factor_id, column in _VALUE_COLUMNS.items()
}
_FRAME_COLUMNS = (
    *_KEY_COLUMNS,
    *_VALUE_COLUMNS.values(),
    *_EFFECTIVE_DATE_COLUMNS.values(),
    "control_effective_date",
    "return_start_date",
    "forward_return",
    "size_control",
    "industry_code",
)
_FORBIDDEN_FIELDS = {
    "selected_combination",
    "selected_reference_factor",
    "best_single_factor",
    "best_combination",
    "dynamic_weight",
    "optimized_weight",
    "information_gain_decision",
    "admission_decision",
}
_REFERENCE_FORMULA_VERSIONS = {
    "BP": "FIN-MVP-BP-v1.0",
    "ROE": "FIN-MVP-ROE-v1.0",
    "OCF_NP": "FIN-MVP-OCFNP-v1.0",
}
_FIN_P2_GATE_ANCHOR = {
    "task_id": "FIN-P2-GATE",
    "status": "ACCEPTED",
    "output_fingerprint": COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT,
    "research_integrity_status": "complete",
    "production_status": "not production ready",
}


class CombinationGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class CombinationErrorCode(str, Enum):
    INVALID_PREDECESSOR_ANCHOR = "INVALID_PREDECESSOR_ANCHOR"
    NON_SYNTHETIC_INPUT = "NON_SYNTHETIC_INPUT"
    MISSING_COLUMN = "MISSING_COLUMN"
    INVALID_KEY = "INVALID_KEY"
    DUPLICATE_MANIFEST_KEY = "DUPLICATE_MANIFEST_KEY"
    DUPLICATE_OBSERVATION_KEY = "DUPLICATE_OBSERVATION_KEY"
    OBSERVATION_OUTSIDE_MANIFEST = "OBSERVATION_OUTSIDE_MANIFEST"
    MANIFEST_FINGERPRINT_MISMATCH = "MANIFEST_FINGERPRINT_MISMATCH"
    INVALID_NUMERIC = "INVALID_NUMERIC"
    INVALID_DATE = "INVALID_DATE"
    FUTURE_FACTOR_OR_CONTROL = "FUTURE_FACTOR_OR_CONTROL"
    INVALID_RETURN_ALIGNMENT = "INVALID_RETURN_ALIGNMENT"
    FORBIDDEN_SELECTION_FIELD = "FORBIDDEN_SELECTION_FIELD"
    COMPARATOR_BLOCKED = "COMPARATOR_BLOCKED"
    INPUT_MUTATED = "INPUT_MUTATED"


class CombinationWarningCode(str, Enum):
    SYNTHETIC_COMBINATIONS_ONLY = "SYNTHETIC_COMBINATIONS_ONLY"
    EXACT_FIN24_FORMULAS = "EXACT_FIN24_FORMULAS"
    PREDECLARED_REFERENCES_NOT_BEST = "PREDECLARED_REFERENCES_NOT_BEST"
    INFORMATION_GAIN_NOT_DECIDED = "INFORMATION_GAIN_NOT_DECIDED"
    PRODUCTION_GATES_NOT_EVALUATED = "PRODUCTION_GATES_NOT_EVALUATED"


@dataclass(frozen=True)
class CombinationIssue:
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
class CombinationTerm:
    factor_id: str
    weight: float

    def to_dict(self) -> dict[str, Any]:
        return {"factor_id": self.factor_id, "weight": self.weight}


@dataclass(frozen=True)
class FinancialP3CombinationDefinition:
    combination_id: str
    display_name: str
    formula_version: str
    formula_expression: str
    reference_factor_id: str
    reference_formula_version: str
    terms: tuple[CombinationTerm, ...]
    weighting: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "combination_id": self.combination_id,
            "display_name": self.display_name,
            "formula_version": self.formula_version,
            "formula_expression": self.formula_expression,
            "reference_factor_id": self.reference_factor_id,
            "reference_formula_version": self.reference_formula_version,
            "terms": [term.to_dict() for term in self.terms],
            "weighting": self.weighting,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP3CombinationsConfig:
    run_id: str
    expected_manifest_fingerprint: str
    execution_timestamp: str
    minimum_cross_section: int = COMBINATIONS_MIN_CROSS_SECTION
    minimum_periods: int = COMBINATIONS_MIN_PERIODS
    standardization_method: str = "population_zscore_ddof0"
    standardization_scope: str = "eligible_manifest_before_labels"
    combination_policy: str = "exact_fin24_three"
    weighting: str = "equal_weight"
    missing_value_policy: str = "preserve_no_imputation"
    automatic_reference_selection: bool = False
    dynamic_weighting_allowed: bool = False
    information_gain_decision_allowed: bool = False
    synthetic_test_only: bool = True
    predecessor_output_fingerprint: str = (
        COMBINATIONS_PREDECESSOR_OUTPUT_FINGERPRINT
    )
    policy_version: str = COMBINATIONS_POLICY_VERSION
    schema_version: str = COMBINATIONS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _required_text(self.run_id, "run_id"))
        if not _is_sha256(self.expected_manifest_fingerprint):
            raise ValueError("expected_manifest_fingerprint must be SHA-256")
        _datetime_text(self.execution_timestamp, "execution_timestamp")
        frozen = {
            "minimum_cross_section": (self.minimum_cross_section, 30),
            "minimum_periods": (self.minimum_periods, 12),
            "standardization_method": (
                self.standardization_method,
                "population_zscore_ddof0",
            ),
            "standardization_scope": (
                self.standardization_scope,
                "eligible_manifest_before_labels",
            ),
            "combination_policy": (
                self.combination_policy,
                "exact_fin24_three",
            ),
            "weighting": (self.weighting, "equal_weight"),
            "missing_value_policy": (
                self.missing_value_policy,
                "preserve_no_imputation",
            ),
            "automatic_reference_selection": (
                self.automatic_reference_selection,
                False,
            ),
            "dynamic_weighting_allowed": (
                self.dynamic_weighting_allowed,
                False,
            ),
            "information_gain_decision_allowed": (
                self.information_gain_decision_allowed,
                False,
            ),
            "synthetic_test_only": (self.synthetic_test_only, True),
            "predecessor_output_fingerprint": (
                self.predecessor_output_fingerprint,
                COMBINATIONS_PREDECESSOR_OUTPUT_FINGERPRINT,
            ),
            "policy_version": (
                self.policy_version,
                COMBINATIONS_POLICY_VERSION,
            ),
            "schema_version": (
                self.schema_version,
                COMBINATIONS_SCHEMA_VERSION,
            ),
        }
        for name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{name} must be frozen at {expected!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class FinancialP3CombinationsBatch:
    dataset_id: str
    version: str
    _manifest: pd.DataFrame
    _frame: pd.DataFrame
    declared_manifest_fingerprint: str
    predecessor_anchor: Mapping[str, Any]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        _required_text(self.dataset_id, "dataset_id")
        _required_text(self.version, "version")
        if not isinstance(self._manifest, pd.DataFrame):
            raise TypeError("_manifest must be a pandas DataFrame")
        if not isinstance(self._frame, pd.DataFrame):
            raise TypeError("_frame must be a pandas DataFrame")
        if not _is_sha256(self.declared_manifest_fingerprint):
            raise ValueError("declared_manifest_fingerprint must be SHA-256")
        object.__setattr__(self, "_manifest", self._manifest.copy(deep=True))
        object.__setattr__(self, "_frame", self._frame.copy(deep=True))
        object.__setattr__(
            self,
            "predecessor_anchor",
            MappingProxyType(copy.deepcopy(dict(self.predecessor_anchor))),
        )
        object.__setattr__(
            self,
            "provenance",
            MappingProxyType(copy.deepcopy(dict(self.provenance))),
        )

    def get_manifest(self) -> pd.DataFrame:
        return self._manifest.copy(deep=True)

    def get_frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)

    def get_predecessor_anchor(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.predecessor_anchor))

    def get_provenance(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.provenance))


@dataclass(frozen=True)
class ConstituentCoverage:
    factor_id: str
    available_observation_count: int
    standardized_period_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "available_observation_count": self.available_observation_count,
            "standardized_period_count": self.standardized_period_count,
        }


@dataclass(frozen=True)
class CombinationConstructionAudit:
    combination_id: str
    reference_factor_id: str
    eligible_sample_size: int
    reference_available_size: int
    combination_available_size: int
    constructed_period_count: int
    constituent_coverage: tuple[ConstituentCoverage, ...]
    construction_fingerprint: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "combination_id": self.combination_id,
            "reference_factor_id": self.reference_factor_id,
            "eligible_sample_size": self.eligible_sample_size,
            "reference_available_size": self.reference_available_size,
            "combination_available_size": self.combination_available_size,
            "constructed_period_count": self.constructed_period_count,
            "constituent_coverage": [
                item.to_dict() for item in self.constituent_coverage
            ],
            "construction_fingerprint": self.construction_fingerprint,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP3CombinationExperiment:
    definition: FinancialP3CombinationDefinition
    construction_audit: CombinationConstructionAudit
    comparison: FinancialP3CommonSampleComparison
    common_sample_audit: FinancialP3CommonSampleAudit
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition": self.definition.to_dict(),
            "construction_audit": self.construction_audit.to_dict(),
            "comparison": self.comparison.to_dict(),
            "common_sample_audit": self.common_sample_audit.to_dict(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class FinancialP3CombinationsAudit:
    gate_status: str
    errors: tuple[CombinationIssue, ...]
    warnings: tuple[CombinationIssue, ...]
    experiment_count: int
    exact_formulas_frozen: bool
    equal_weight_only: bool
    pit_safe: bool
    return_label_independent_construction: bool
    common_sample_comparator_used: bool
    fin24_combinations_constructed: bool
    automatic_reference_selection_performed: bool
    dynamic_weighting_performed: bool
    information_gain_decision_made: bool
    synthetic_test_only: bool
    research_assessment: str
    production_status: str
    admission_status: str
    manifest_fingerprint: str
    input_fingerprint: str
    output_fingerprint: str
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
class FinancialP3CombinationsResult:
    definitions: tuple[FinancialP3CombinationDefinition, ...]
    experiments: tuple[FinancialP3CombinationExperiment, ...]
    combinations_audit: FinancialP3CombinationsAudit

    def to_dict(self) -> dict[str, Any]:
        return {
            "definitions": [item.to_dict() for item in self.definitions],
            "experiments": [item.to_dict() for item in self.experiments],
            "combinations_audit": self.combinations_audit.to_dict(),
        }


_DEFINITION_SPECS = (
    {
        "combination_id": "VQ",
        "display_name": "Value Quality",
        "formula_version": "FIN-24-VQ-v1.0",
        "formula_expression": (
            "(z(BP)+z(EBIT_EV)+z(ROE)+z(OCF_NP))/4"
        ),
        "reference_factor_id": "BP",
        "terms": (("BP", 0.25), ("EBIT_EV", 0.25), ("ROE", 0.25), ("OCF_NP", 0.25)),
    },
    {
        "combination_id": "QG",
        "display_name": "Quality Growth",
        "formula_version": "FIN-24-QG-v1.0",
        "formula_expression": (
            "(z(SALES_GROWTH)+z(PROFIT_GROWTH)+z(ROE)+z(OCF_NP))/4"
        ),
        "reference_factor_id": "ROE",
        "terms": (
            ("SALES_GROWTH", 0.25),
            ("PROFIT_GROWTH", 0.25),
            ("ROE", 0.25),
            ("OCF_NP", 0.25),
        ),
    },
    {
        "combination_id": "CASHQ",
        "display_name": "Cash Earnings Quality",
        "formula_version": "FIN-24-CASHQ-v1.0",
        "formula_expression": "(z(ROA)+z(OCF_SALES)-z(ACCRUALS))/3",
        "reference_factor_id": "OCF_NP",
        "terms": (
            ("ROA", 1.0 / 3.0),
            ("OCF_SALES", 1.0 / 3.0),
            ("ACCRUALS", -1.0 / 3.0),
        ),
    },
)


def get_fin24_combination_definitions(
) -> tuple[FinancialP3CombinationDefinition, ...]:
    definitions = []
    for spec in _DEFINITION_SPECS:
        terms = tuple(
            CombinationTerm(factor_id=factor_id, weight=weight)
            for factor_id, weight in spec["terms"]
        )
        payload = {
            **{key: value for key, value in spec.items() if key != "terms"},
            "reference_formula_version": _REFERENCE_FORMULA_VERSIONS[
                spec["reference_factor_id"]
            ],
            "terms": [term.to_dict() for term in terms],
            "weighting": "equal_weight",
        }
        definitions.append(
            FinancialP3CombinationDefinition(
                combination_id=spec["combination_id"],
                display_name=spec["display_name"],
                formula_version=spec["formula_version"],
                formula_expression=spec["formula_expression"],
                reference_factor_id=spec["reference_factor_id"],
                reference_formula_version=payload[
                    "reference_formula_version"
                ],
                terms=terms,
                weighting="equal_weight",
                content_hash=_hash("fin24_definition", payload),
            )
        )
    return tuple(definitions)


def evaluate_financial_p3_combinations(
    batch: FinancialP3CombinationsBatch,
    *,
    configuration: FinancialP3CombinationsConfig,
) -> FinancialP3CombinationsResult:
    if not isinstance(batch, FinancialP3CombinationsBatch):
        raise TypeError("batch must be FinancialP3CombinationsBatch")
    if not isinstance(configuration, FinancialP3CombinationsConfig):
        raise TypeError("configuration must be FinancialP3CombinationsConfig")
    definitions = get_fin24_combination_definitions()
    manifest = batch.get_manifest()
    frame = batch.get_frame()
    anchor = batch.get_predecessor_anchor()
    provenance = batch.get_provenance()
    guard = _batch_guard(batch)
    errors: list[CombinationIssue] = []
    warnings = _default_warnings()
    _validate_anchor(anchor, errors)
    if not bool(provenance.get("synthetic_test_only")):
        errors.append(
            _error(
                CombinationErrorCode.NON_SYNTHETIC_INPUT,
                "provenance.synthetic_test_only must be true",
            )
        )
    forbidden_provenance = _FORBIDDEN_FIELDS & {
        str(key) for key in provenance
    }
    if forbidden_provenance:
        errors.append(
            _error(
                CombinationErrorCode.FORBIDDEN_SELECTION_FIELD,
                "selection, optimization, or decision fields are forbidden",
                field_name=",".join(sorted(forbidden_provenance)),
            )
        )
    normalized_manifest = _normalize_manifest(manifest, errors)
    normalized_frame = _normalize_frame(frame, errors)
    manifest_fingerprint = (
        compute_common_sample_manifest_fingerprint(normalized_manifest)
        if not normalized_manifest.empty
        else _hash("p3_common_sample_manifest", [])
    )
    if manifest_fingerprint != batch.declared_manifest_fingerprint:
        errors.append(
            _error(
                CombinationErrorCode.MANIFEST_FINGERPRINT_MISMATCH,
                "declared manifest fingerprint does not match",
            )
        )
    if manifest_fingerprint != configuration.expected_manifest_fingerprint:
        errors.append(
            _error(
                CombinationErrorCode.MANIFEST_FINGERPRINT_MISMATCH,
                "configuration does not bind the supplied manifest",
            )
        )
    _validate_relationships(normalized_manifest, normalized_frame, errors)
    input_fingerprint = _hash(
        "p3_combinations_input",
        {
            "manifest": _frame_records(normalized_manifest),
            "frame": _frame_records(normalized_frame),
            "anchor": anchor,
            "provenance": provenance,
            "configuration": configuration.to_dict(),
            "definitions": [item.to_dict() for item in definitions],
        },
    )
    if errors:
        return _blocked_result(
            definitions=definitions,
            errors=errors,
            warnings=warnings,
            manifest_fingerprint=manifest_fingerprint,
            input_fingerprint=input_fingerprint,
        )

    joined = _join_manifest(normalized_manifest, normalized_frame)
    experiments: list[FinancialP3CombinationExperiment] = []
    runtime_errors: list[CombinationIssue] = []
    for definition in definitions:
        experiment = _run_experiment(
            joined=joined,
            manifest=normalized_manifest,
            definition=definition,
            configuration=configuration,
            provenance=provenance,
        )
        if experiment is None:
            runtime_errors.append(
                _error(
                    CombinationErrorCode.COMPARATOR_BLOCKED,
                    f"FIN-23 comparator blocked {definition.combination_id}",
                    record_key=definition.combination_id,
                )
            )
        else:
            experiments.append(experiment)
    if runtime_errors:
        return _blocked_result(
            definitions=definitions,
            errors=runtime_errors,
            warnings=warnings,
            manifest_fingerprint=manifest_fingerprint,
            input_fingerprint=input_fingerprint,
        )
    if _batch_guard(batch) != guard:
        return _blocked_result(
            definitions=definitions,
            errors=[
                _error(
                    CombinationErrorCode.INPUT_MUTATED,
                    "input batch changed during evaluation",
                )
            ],
            warnings=warnings,
            manifest_fingerprint=manifest_fingerprint,
            input_fingerprint=input_fingerprint,
        )
    output_fingerprint = _hash(
        "p3_combinations_output",
        [experiment.to_dict() for experiment in experiments],
    )
    audit = _build_audit(
        gate_status=CombinationGateStatus.READY.value,
        errors=(),
        warnings=warnings,
        experiment_count=len(experiments),
        manifest_fingerprint=manifest_fingerprint,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
    )
    return FinancialP3CombinationsResult(
        definitions=definitions,
        experiments=tuple(experiments),
        combinations_audit=audit,
    )


def _run_experiment(
    *,
    joined: pd.DataFrame,
    manifest: pd.DataFrame,
    definition: FinancialP3CombinationDefinition,
    configuration: FinancialP3CombinationsConfig,
    provenance: Mapping[str, Any],
) -> FinancialP3CombinationExperiment | None:
    standardized: dict[str, pd.Series] = {}
    factor_ids = tuple(
        dict.fromkeys(
            [term.factor_id for term in definition.terms]
            + [definition.reference_factor_id]
        )
    )
    coverages = []
    for factor_id in factor_ids:
        z_values, available_count, period_count = _standardize_factor(
            joined,
            factor_id=factor_id,
            minimum_cross_section=configuration.minimum_cross_section,
        )
        standardized[factor_id] = z_values
        coverages.append(
            ConstituentCoverage(
                factor_id=factor_id,
                available_observation_count=available_count,
                standardized_period_count=period_count,
            )
        )
    combined = pd.Series(0.0, index=joined.index, dtype=float)
    combined_available = pd.Series(True, index=joined.index, dtype=bool)
    for term in definition.terms:
        values = standardized[term.factor_id]
        combined = combined + term.weight * values
        combined_available &= np.isfinite(values)
    combined = combined.where(combined_available, np.nan)
    reference = standardized[definition.reference_factor_id]
    eligible = joined["eligible"].fillna(False).astype(bool)
    combination_available_size = int((eligible & np.isfinite(combined)).sum())
    reference_available_size = int((eligible & np.isfinite(reference)).sum())
    constructed_counts = (
        joined.loc[eligible & np.isfinite(combined)]
        .groupby("evaluation_date")
        .size()
    )
    constructed_period_count = int(
        (constructed_counts >= configuration.minimum_cross_section).sum()
    )
    construction_rows = joined.loc[
        joined["_observation_present"], list(_KEY_COLUMNS)
    ].copy()
    for factor_id in factor_ids:
        construction_rows[f"z_{factor_id}"] = standardized[factor_id].loc[
            construction_rows.index
        ]
    construction_rows["reference_factor_value"] = reference.loc[
        construction_rows.index
    ]
    construction_rows["combined_factor_value"] = combined.loc[
        construction_rows.index
    ]
    construction_fingerprint = _hash(
        "p3_combination_construction",
        {
            "definition": definition.to_dict(),
            "rows": _frame_records(construction_rows),
        },
    )
    construction_payload = {
        "combination_id": definition.combination_id,
        "reference_factor_id": definition.reference_factor_id,
        "eligible_sample_size": int(eligible.sum()),
        "reference_available_size": reference_available_size,
        "combination_available_size": combination_available_size,
        "constructed_period_count": constructed_period_count,
        "constituent_coverage": [item.to_dict() for item in coverages],
        "construction_fingerprint": construction_fingerprint,
    }
    construction_audit = CombinationConstructionAudit(
        combination_id=definition.combination_id,
        reference_factor_id=definition.reference_factor_id,
        eligible_sample_size=int(eligible.sum()),
        reference_available_size=reference_available_size,
        combination_available_size=combination_available_size,
        constructed_period_count=constructed_period_count,
        constituent_coverage=tuple(coverages),
        construction_fingerprint=construction_fingerprint,
        content_hash=_hash(
            "p3_combination_construction_audit", construction_payload
        ),
    )
    observed = joined["_observation_present"].astype(bool)
    comparator_frame = joined.loc[observed, list(_KEY_COLUMNS)].copy()
    effective_columns = [
        _EFFECTIVE_DATE_COLUMNS[factor_id] for factor_id in factor_ids
    ]
    comparator_frame["factor_effective_date"] = (
        joined.loc[observed, effective_columns]
        .max(axis=1)
        .astype(str)
    )
    comparator_frame["control_effective_date"] = joined.loc[
        observed, "control_effective_date"
    ]
    comparator_frame["return_start_date"] = joined.loc[
        observed, "return_start_date"
    ]
    comparator_frame["single_factor_value"] = reference.loc[observed]
    comparator_frame["combined_factor_value"] = combined.loc[observed]
    for column in ("forward_return", "size_control", "industry_code"):
        comparator_frame[column] = joined.loc[observed, column]
    comparator_batch = FinancialP3CommonSampleBatch(
        dataset_id=f"{definition.combination_id}-common-sample",
        version="FIN-P3-COMBOS-v1.0",
        _manifest=manifest,
        _frame=comparator_frame,
        declared_manifest_fingerprint=(
            compute_common_sample_manifest_fingerprint(manifest)
        ),
        gate_anchor=_FIN_P2_GATE_ANCHOR,
        provenance={
            "synthetic_test_only": True,
            "provider": provenance.get("provider", "deterministic_fixture"),
            "universe_policy": "independent_frozen_manifest",
        },
    )
    comparator_config = FinancialP3CommonSampleConfig(
        comparison_id=(
            f"{configuration.run_id}-{definition.combination_id}"
        ),
        single_factor_id=definition.reference_factor_id,
        combined_factor_id=definition.combination_id,
        single_formula_version=definition.reference_formula_version,
        combined_formula_version=definition.formula_version,
        expected_manifest_fingerprint=(
            configuration.expected_manifest_fingerprint
        ),
        execution_timestamp=configuration.execution_timestamp,
    )
    result = evaluate_financial_p3_common_sample(
        comparator_batch,
        configuration=comparator_config,
    )
    if (
        result.comparison is None
        or result.common_sample_audit.gate_status != "ready"
    ):
        return None
    experiment_payload = {
        "definition": definition.to_dict(),
        "construction_audit": construction_audit.to_dict(),
        "comparison": result.comparison.to_dict(),
        "common_sample_audit": result.common_sample_audit.to_dict(),
    }
    return FinancialP3CombinationExperiment(
        definition=definition,
        construction_audit=construction_audit,
        comparison=result.comparison,
        common_sample_audit=result.common_sample_audit,
        content_hash=_hash("p3_combination_experiment", experiment_payload),
    )


def _standardize_factor(
    frame: pd.DataFrame,
    *,
    factor_id: str,
    minimum_cross_section: int,
) -> tuple[pd.Series, int, int]:
    column = _VALUE_COLUMNS[factor_id]
    eligible = frame["eligible"].fillna(False).astype(bool)
    finite = np.isfinite(frame[column])
    available = eligible & finite
    output = pd.Series(np.nan, index=frame.index, dtype=float)
    period_count = 0
    for indices in frame.loc[available].groupby("evaluation_date").groups.values():
        values = frame.loc[indices, column].astype(float)
        if len(values) < minimum_cross_section:
            continue
        scale = float(values.std(ddof=0))
        if not math.isfinite(scale) or scale <= 0.0:
            continue
        output.loc[indices] = (values - float(values.mean())) / scale
        period_count += 1
    return output, int(available.sum()), period_count


def _validate_anchor(
    anchor: Mapping[str, Any], errors: list[CombinationIssue]
) -> None:
    if (
        anchor.get("task_id") != "FIN-P3-COMMON-SAMPLE"
        or str(anchor.get("status", "")).upper() != "ACCEPTED"
        or anchor.get("output_fingerprint")
        != COMBINATIONS_PREDECESSOR_OUTPUT_FINGERPRINT
        or anchor.get("same_sample_enforced") is not True
        or anchor.get("research_assessment") != "exploratory"
        or anchor.get("production_status") != "not production ready"
    ):
        errors.append(
            _error(
                CombinationErrorCode.INVALID_PREDECESSOR_ANCHOR,
                "FIN-P3-COMMON-SAMPLE accepted anchor does not match",
            )
        )


def _normalize_manifest(
    manifest: pd.DataFrame, errors: list[CombinationIssue]
) -> pd.DataFrame:
    missing = [column for column in _MANIFEST_COLUMNS if column not in manifest]
    if missing:
        for column in missing:
            errors.append(
                _error(
                    CombinationErrorCode.MISSING_COLUMN,
                    "manifest is missing a required column",
                    field_name=column,
                )
            )
        return pd.DataFrame(columns=_MANIFEST_COLUMNS)
    output = manifest.loc[:, _MANIFEST_COLUMNS].copy(deep=True)
    _normalize_keys(output, errors)
    invalid_eligible = ~output["eligible"].map(
        lambda value: type(value) in (bool, np.bool_)
    )
    if bool(invalid_eligible.any()):
        errors.append(
            _error(
                CombinationErrorCode.INVALID_KEY,
                "eligible must contain only booleans",
                field_name="eligible",
            )
        )
    output["eligible"] = output["eligible"].map(lambda value: bool(value))
    if bool(output.duplicated(list(_KEY_COLUMNS)).any()):
        errors.append(
            _error(
                CombinationErrorCode.DUPLICATE_MANIFEST_KEY,
                "manifest security-date keys must be unique",
            )
        )
    return output.sort_values(list(_KEY_COLUMNS), kind="stable").reset_index(
        drop=True
    )


def _normalize_frame(
    frame: pd.DataFrame, errors: list[CombinationIssue]
) -> pd.DataFrame:
    forbidden = _FORBIDDEN_FIELDS & {str(column) for column in frame.columns}
    if forbidden:
        errors.append(
            _error(
                CombinationErrorCode.FORBIDDEN_SELECTION_FIELD,
                "selection, optimization, or decision columns are forbidden",
                field_name=",".join(sorted(forbidden)),
            )
        )
    missing = [column for column in _FRAME_COLUMNS if column not in frame]
    if missing:
        for column in missing:
            errors.append(
                _error(
                    CombinationErrorCode.MISSING_COLUMN,
                    "observation frame is missing a required column",
                    field_name=column,
                )
            )
        return pd.DataFrame(columns=_FRAME_COLUMNS)
    output = frame.loc[:, _FRAME_COLUMNS].copy(deep=True)
    _normalize_keys(output, errors)
    if bool(output.duplicated(list(_KEY_COLUMNS)).any()):
        errors.append(
            _error(
                CombinationErrorCode.DUPLICATE_OBSERVATION_KEY,
                "observation security-date keys must be unique",
            )
        )
    for column in (*_VALUE_COLUMNS.values(), "forward_return", "size_control"):
        original = output[column]
        converted = pd.to_numeric(original, errors="coerce")
        invalid = original.notna() & converted.isna()
        if bool(invalid.any()):
            errors.append(
                _error(
                    CombinationErrorCode.INVALID_NUMERIC,
                    f"{column} contains a non-numeric value",
                    field_name=column,
                )
            )
        output[column] = converted.astype(float)
    date_columns = (
        *_EFFECTIVE_DATE_COLUMNS.values(),
        "control_effective_date",
        "return_start_date",
    )
    for column in date_columns:
        parsed = pd.to_datetime(output[column], errors="coerce", format="mixed")
        if bool(parsed.isna().any()):
            errors.append(
                _error(
                    CombinationErrorCode.INVALID_DATE,
                    f"{column} contains an invalid date",
                    field_name=column,
                )
            )
        output[column] = parsed.dt.date.astype(str)
    output["industry_code"] = output["industry_code"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    return output.sort_values(list(_KEY_COLUMNS), kind="stable").reset_index(
        drop=True
    )


def _normalize_keys(
    frame: pd.DataFrame, errors: list[CombinationIssue]
) -> None:
    dates = pd.to_datetime(
        frame["evaluation_date"], errors="coerce", format="mixed"
    )
    if bool(dates.isna().any()):
        errors.append(
            _error(
                CombinationErrorCode.INVALID_KEY,
                "evaluation_date contains an invalid date",
                field_name="evaluation_date",
            )
        )
    frame["evaluation_date"] = dates.dt.date.astype(str)
    security = frame["security_id"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    if bool((security == "").any()):
        errors.append(
            _error(
                CombinationErrorCode.INVALID_KEY,
                "security_id must be non-empty",
                field_name="security_id",
            )
        )
    frame["security_id"] = security


def _validate_relationships(
    manifest: pd.DataFrame,
    frame: pd.DataFrame,
    errors: list[CombinationIssue],
) -> None:
    if manifest.empty or frame.empty:
        return
    manifest_keys = set(
        zip(manifest["evaluation_date"], manifest["security_id"], strict=True)
    )
    frame_keys = set(
        zip(frame["evaluation_date"], frame["security_id"], strict=True)
    )
    outside = sorted(frame_keys - manifest_keys)
    if outside:
        errors.append(
            _error(
                CombinationErrorCode.OBSERVATION_OUTSIDE_MANIFEST,
                "observation keys must belong to the independent manifest",
                record_key=f"{outside[0][0]}|{outside[0][1]}",
            )
        )
    evaluation = pd.to_datetime(
        frame["evaluation_date"], errors="coerce", format="mixed"
    )
    for factor_id, column in _EFFECTIVE_DATE_COLUMNS.items():
        effective = pd.to_datetime(frame[column], errors="coerce", format="mixed")
        if bool((effective > evaluation).any()):
            errors.append(
                _error(
                    CombinationErrorCode.FUTURE_FACTOR_OR_CONTROL,
                    f"{factor_id} effective date must not exceed evaluation date",
                    field_name=column,
                )
            )
    control = pd.to_datetime(
        frame["control_effective_date"], errors="coerce", format="mixed"
    )
    if bool((control > evaluation).any()):
        errors.append(
            _error(
                CombinationErrorCode.FUTURE_FACTOR_OR_CONTROL,
                "control effective date must not exceed evaluation date",
                field_name="control_effective_date",
            )
        )
    return_start = pd.to_datetime(
        frame["return_start_date"], errors="coerce", format="mixed"
    )
    if bool((return_start <= evaluation).any()):
        errors.append(
            _error(
                CombinationErrorCode.INVALID_RETURN_ALIGNMENT,
                "return_start_date must be after evaluation_date",
                field_name="return_start_date",
            )
        )


def _join_manifest(manifest: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    observed = frame.copy(deep=True)
    observed["_observation_present"] = True
    joined = manifest.merge(observed, on=list(_KEY_COLUMNS), how="left", sort=True)
    joined["_observation_present"] = joined["_observation_present"].fillna(False)
    return joined.sort_values(list(_KEY_COLUMNS), kind="stable").reset_index(
        drop=True
    )


def _blocked_result(
    *,
    definitions: tuple[FinancialP3CombinationDefinition, ...],
    errors: Sequence[CombinationIssue],
    warnings: Sequence[CombinationIssue],
    manifest_fingerprint: str,
    input_fingerprint: str,
) -> FinancialP3CombinationsResult:
    output_fingerprint = _hash(
        "p3_combinations_blocked_output",
        [item.to_dict() for item in _deduplicate(errors)],
    )
    audit = _build_audit(
        gate_status=CombinationGateStatus.BLOCKED.value,
        errors=_deduplicate(errors),
        warnings=warnings,
        experiment_count=0,
        manifest_fingerprint=manifest_fingerprint,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
    )
    return FinancialP3CombinationsResult(
        definitions=definitions,
        experiments=(),
        combinations_audit=audit,
    )


def _build_audit(
    *,
    gate_status: str,
    errors: Sequence[CombinationIssue],
    warnings: Sequence[CombinationIssue],
    experiment_count: int,
    manifest_fingerprint: str,
    input_fingerprint: str,
    output_fingerprint: str,
) -> FinancialP3CombinationsAudit:
    payload = {
        "gate_status": gate_status,
        "errors": [item.to_dict() for item in _deduplicate(errors)],
        "warnings": [item.to_dict() for item in _deduplicate(warnings)],
        "experiment_count": experiment_count,
        "exact_formulas_frozen": gate_status == "ready",
        "equal_weight_only": gate_status == "ready",
        "pit_safe": gate_status == "ready",
        "return_label_independent_construction": gate_status == "ready",
        "common_sample_comparator_used": gate_status == "ready",
        "fin24_combinations_constructed": (
            gate_status == "ready" and experiment_count == 3
        ),
        "automatic_reference_selection_performed": False,
        "dynamic_weighting_performed": False,
        "information_gain_decision_made": False,
        "synthetic_test_only": True,
        "research_assessment": COMBINATIONS_RESEARCH_ASSESSMENT,
        "production_status": COMBINATIONS_PRODUCTION_STATUS,
        "admission_status": COMBINATIONS_ADMISSION_STATUS,
        "manifest_fingerprint": manifest_fingerprint,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": output_fingerprint,
        "conclusion_boundary": COMBINATIONS_CONCLUSION_BOUNDARY,
        "schema_version": COMBINATIONS_SCHEMA_VERSION,
        "audit_schema_version": COMBINATIONS_AUDIT_SCHEMA_VERSION,
        "policy_version": COMBINATIONS_POLICY_VERSION,
        "hash_contract_version": COMBINATIONS_HASH_CONTRACT_VERSION,
    }
    constructor = {
        **payload,
        "errors": tuple(_deduplicate(errors)),
        "warnings": tuple(_deduplicate(warnings)),
        "content_hash": _hash("p3_combinations_audit", payload),
    }
    return FinancialP3CombinationsAudit(**constructor)


def _default_warnings() -> tuple[CombinationIssue, ...]:
    return (
        _warning(
            CombinationWarningCode.SYNTHETIC_COMBINATIONS_ONLY,
            "Only deterministic synthetic FIN-24 evidence is authorized.",
        ),
        _warning(
            CombinationWarningCode.EXACT_FIN24_FORMULAS,
            "Exactly three preset equal-weight FIN-24 formulas are constructed.",
        ),
        _warning(
            CombinationWarningCode.PREDECLARED_REFERENCES_NOT_BEST,
            "Reference factors are frozen inputs, not best-factor selections.",
        ),
        _warning(
            CombinationWarningCode.INFORMATION_GAIN_NOT_DECIDED,
            "FIN-23 deltas do not create a FIN-25 information-gain decision.",
        ),
        _warning(
            CombinationWarningCode.PRODUCTION_GATES_NOT_EVALUATED,
            "Costs, trading states, real data, and production gates are out of scope.",
        ),
    )


def _batch_guard(batch: FinancialP3CombinationsBatch) -> str:
    return _hash(
        "p3_combinations_batch_guard",
        {
            "dataset_id": batch.dataset_id,
            "version": batch.version,
            "manifest": _frame_records(batch.get_manifest()),
            "frame": _frame_records(batch.get_frame()),
            "declared_manifest_fingerprint": batch.declared_manifest_fingerprint,
            "predecessor_anchor": batch.get_predecessor_anchor(),
            "provenance": batch.get_provenance(),
        },
    )


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    ordered = frame.copy(deep=True)
    if all(column in ordered for column in _KEY_COLUMNS):
        ordered = ordered.sort_values(list(_KEY_COLUMNS), kind="stable")
    return [
        {str(column): _canonical(value) for column, value in row.items()}
        for row in ordered.to_dict(orient="records")
    ]


def _error(
    code: CombinationErrorCode,
    message: str,
    *,
    field_name: str | None = None,
    record_key: str | None = None,
) -> CombinationIssue:
    return CombinationIssue(code.value, message, field_name, record_key)


def _warning(code: CombinationWarningCode, message: str) -> CombinationIssue:
    return CombinationIssue(code.value, message)


def _deduplicate(items: Sequence[CombinationIssue]) -> tuple[CombinationIssue, ...]:
    seen: set[tuple[Any, ...]] = set()
    output = []
    for item in items:
        key = (item.code, item.message, item.field_name, item.record_key)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return tuple(output)


def _required_text(value: Any, field_name: str) -> str:
    normalized = "" if value is None else str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _datetime_text(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name)
    try:
        dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    return normalized


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _canonical(value: Any) -> Any:
    return canonicalize_financial_fingerprint(
        value,
        float_decimals=COMBINATIONS_FINGERPRINT_FLOAT_DECIMALS,
    )


def _hash(domain: str, value: Any) -> str:
    payload = json.dumps(
        {
            "domain": domain,
            "hash_contract_version": COMBINATIONS_HASH_CONTRACT_VERSION,
            "value": _canonical(value),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "COMBINATIONS_ADMISSION_STATUS",
    "COMBINATIONS_CONCLUSION_BOUNDARY",
    "COMBINATIONS_PREDECESSOR_OUTPUT_FINGERPRINT",
    "COMBINATIONS_PRODUCTION_STATUS",
    "COMBINATIONS_RESEARCH_ASSESSMENT",
    "CombinationConstructionAudit",
    "CombinationErrorCode",
    "CombinationGateStatus",
    "CombinationIssue",
    "CombinationTerm",
    "ConstituentCoverage",
    "FinancialP3CombinationDefinition",
    "FinancialP3CombinationExperiment",
    "FinancialP3CombinationsAudit",
    "FinancialP3CombinationsBatch",
    "FinancialP3CombinationsConfig",
    "FinancialP3CombinationsResult",
    "evaluate_financial_p3_combinations",
    "get_fin24_combination_definitions",
]
