"""FIN-MVP-DATA: three-factor controlled ``FinancialBatch`` integration.

The module reuses the public ``FinancialBatch`` contract.  Evaluation-date,
sample, lineage, path, snapshot, and formula evidence is kept in a separate
immutable integration sidecar.  No label data is read, no dynamic formula is
executed, and no R1A/R1B/R1C semantic is recomputed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

import pandas as pd

from .evaluation_input_contract import (
    EvaluationInputContractError,
    FactorType,
    FinancialBatch,
    ValueScope,
)
from .financial_lineage import (
    NOT_APPLICABLE,
    FinancialObservationLineage,
    ObservationLineageReference,
    PathType,
    compute_factor_value_hash,
    recompute_lineage_content_hash,
)
from .financial_sample import (
    SampleFormationReference,
    compute_sample_fingerprint,
    recompute_sample_content_hash,
)

MVP_BATCH_SCHEMA_VERSION = "FinancialMVPBatch-v1.0"
MVP_AUDIT_SCHEMA_VERSION = "FinancialBatchAudit-v1.0"
MVP_OBSERVATION_SCHEMA_VERSION = "FinancialBatchObservation-v1.0"
HASH_CONTRACT_VERSION = "FIN-MVP-DATA-HASH-v1.0"
FORMULA_REGISTRY_VERSION = "FIN-MVP-FORMULA-REGISTRY-v2.0"
SUPPORTED_FACTOR_IDS = ("ROE", "BP", "OCF_NP")
INTEGRATION_KEY_FIELDS = ("evaluation_date", "code", "factor_id")
PUBLIC_BATCH_SORT_FIELDS = (
    "code",
    "report_period",
    "effective_date",
)


class MVPFactorId(str, Enum):
    ROE = "ROE"
    BP = "BP"
    OCF_NP = "OCF_NP"


class FinancialSectorType(str, Enum):
    NON_FINANCIAL = "NON_FINANCIAL"
    BANK = "BANK"
    INSURANCE = "INSURANCE"
    SECURITIES = "SECURITIES"
    DIVERSIFIED_FINANCIAL = "DIVERSIFIED_FINANCIAL"


class FormulaCalculationStatus(str, Enum):
    VALID = "VALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID_DENOMINATOR = "INVALID_DENOMINATOR"
    MISSING_REQUIRED_INPUT = "MISSING_REQUIRED_INPUT"
    SECTOR_CLASSIFICATION_MISSING = "SECTOR_CLASSIFICATION_MISSING"
    SECTOR_FORMULA_MISMATCH = "SECTOR_FORMULA_MISMATCH"
    NONFINITE_INPUT = "NONFINITE_INPUT"


class MVPBatchGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class MVPBatchErrorCode(str, Enum):
    UNSUPPORTED_MVP_FACTOR = "UNSUPPORTED_MVP_FACTOR"
    MVP_FACTOR_COVERAGE_INCOMPLETE = "MVP_FACTOR_COVERAGE_INCOMPLETE"
    FINANCIAL_BATCH_REQUIRED_FIELD_MISSING = "FINANCIAL_BATCH_REQUIRED_FIELD_MISSING"
    EFFECTIVE_DATE_AFTER_EVALUATION_DATE = "EFFECTIVE_DATE_AFTER_EVALUATION_DATE"
    LINEAGE_REFERENCE_MISSING = "LINEAGE_REFERENCE_MISSING"
    SAMPLE_MASK_REFERENCE_MISSING = "SAMPLE_MASK_REFERENCE_MISSING"
    INVALID_FACTOR_VALUE = "INVALID_FACTOR_VALUE"
    NONFINITE_FACTOR_VALUE = "NONFINITE_FACTOR_VALUE"
    DUPLICATE_FINANCIAL_OBSERVATION = "DUPLICATE_FINANCIAL_OBSERVATION"
    FINANCIAL_OBSERVATION_CONFLICT = "FINANCIAL_OBSERVATION_CONFLICT"
    CROSS_SECURITY_FACTOR_VALUE_DETECTED = "CROSS_SECURITY_FACTOR_VALUE_DETECTED"
    INPUT_MUTATION_DETECTED = "INPUT_MUTATION_DETECTED"
    NONDETERMINISTIC_BATCH_OUTPUT = "NONDETERMINISTIC_BATCH_OUTPUT"
    FUTURE_LABEL_DEPENDENCY_DETECTED = "FUTURE_LABEL_DEPENDENCY_DETECTED"
    PATH_A_UPSTREAM_PROOF_MISSING = "PATH_A_UPSTREAM_PROOF_MISSING"
    PATH_B_FORMULA_REFERENCE_MISSING = "PATH_B_FORMULA_REFERENCE_MISSING"
    DYNAMIC_FORMULA_NOT_ALLOWED = "DYNAMIC_FORMULA_NOT_ALLOWED"
    FORMULA_INPUT_REFERENCE_MISSING = "FORMULA_INPUT_REFERENCE_MISSING"
    SECTOR_CLASSIFICATION_MISSING = "SECTOR_CLASSIFICATION_MISSING"
    SECTOR_FORMULA_MISMATCH = "SECTOR_FORMULA_MISMATCH"
    FORMULA_NOT_APPLICABLE = "FORMULA_NOT_APPLICABLE"
    FORMULA_INPUT_REQUIRES_FIN_R2_PREP = "FORMULA_INPUT_REQUIRES_FIN_R2_PREP"
    LINEAGE_CONTENT_HASH_MISMATCH = "LINEAGE_CONTENT_HASH_MISMATCH"
    SAMPLE_CONTENT_HASH_MISMATCH = "SAMPLE_CONTENT_HASH_MISMATCH"
    SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH = "SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH"
    FACTOR_VALUE_HASH_MISMATCH = "FACTOR_VALUE_HASH_MISMATCH"
    BATCH_CONSTRUCTION_FAILED = "BATCH_CONSTRUCTION_FAILED"
    INVALID_MVP_BATCH_INPUT = "INVALID_MVP_BATCH_INPUT"


class MVPBatchLookupError(LookupError):
    def __init__(
        self,
        code: MVPBatchErrorCode,
        message: str,
        *,
        lookup_key: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.code = code.value
        self.lookup_key = lookup_key


@dataclass(frozen=True)
class MVPFormulaDefinition:
    factor_id: str
    formula_id: str
    formula_version: str
    numerator_field: str
    denominator_field: str
    required_input_fields: tuple[str, ...]
    applicable_sector_types: tuple[str, ...]
    excluded_sector_types: tuple[str, ...]
    industry_standard: str
    industry_level: int
    sector_mapping_version: str
    formula_variant: str
    denominator_policy: str
    fallback_policy: str
    not_applicable_reason: str | None
    effective_from: str
    registry_version: str = FORMULA_REGISTRY_VERSION

    @property
    def formula_reference(self) -> str:
        return f"registered-formula://{self.formula_id}/{self.formula_version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "numerator_field": self.numerator_field,
            "denominator_field": self.denominator_field,
            "required_input_fields": list(self.required_input_fields),
            "applicable_sector_types": list(self.applicable_sector_types),
            "excluded_sector_types": list(self.excluded_sector_types),
            "industry_standard": self.industry_standard,
            "industry_level": self.industry_level,
            "sector_mapping_version": self.sector_mapping_version,
            "formula_variant": self.formula_variant,
            "denominator_policy": self.denominator_policy,
            "fallback_policy": self.fallback_policy,
            "not_applicable_reason": self.not_applicable_reason,
            "effective_from": self.effective_from,
            "registry_version": self.registry_version,
            "formula_reference": self.formula_reference,
        }


FORMULA_REGISTRY = (
    MVPFormulaDefinition(
        factor_id=MVPFactorId.ROE.value,
        formula_id="FIN-MVP-ROE",
        formula_version="FIN-MVP-ROE-v1.0",
        numerator_field="parent_net_profit_ttm",
        denominator_field="average_parent_equity",
        required_input_fields=(
            "parent_net_profit_ttm",
            "average_parent_equity",
        ),
        applicable_sector_types=tuple(item.value for item in FinancialSectorType),
        excluded_sector_types=(),
        industry_standard="ExposureBatch-v1",
        industry_level=1,
        sector_mapping_version="FIN-SECTOR-MAP-v1.0",
        formula_variant="parent_net_profit_ttm/average_parent_equity",
        denominator_policy="REQUIRE_POSITIVE; ZERO_OR_NEGATIVE_INVALID; NO_EPSILON_SUBSTITUTION",
        fallback_policy="NO_FALLBACK",
        not_applicable_reason=None,
        effective_from="2026-08-20",
    ),
    MVPFormulaDefinition(
        factor_id=MVPFactorId.BP.value,
        formula_id="FIN-MVP-BP",
        formula_version="FIN-MVP-BP-v1.0",
        numerator_field="parent_equity",
        denominator_field="market_cap",
        required_input_fields=("parent_equity", "market_cap"),
        applicable_sector_types=tuple(item.value for item in FinancialSectorType),
        excluded_sector_types=(),
        industry_standard="ExposureBatch-v1",
        industry_level=1,
        sector_mapping_version="FIN-SECTOR-MAP-v1.0",
        formula_variant="parent_equity/evaluation_date_total_market_cap",
        denominator_policy="MARKET_CAP_POSITIVE_AND_SAME_AS_OF; NON_POSITIVE_EQUITY_INVALID; NO_EPSILON_SUBSTITUTION",
        fallback_policy="NO_FALLBACK",
        not_applicable_reason=None,
        effective_from="2026-08-20",
    ),
    MVPFormulaDefinition(
        factor_id=MVPFactorId.OCF_NP.value,
        formula_id="FIN-MVP-OCFNP",
        formula_version="FIN-MVP-OCFNP-v1.0",
        numerator_field="operating_cash_flow_ttm",
        denominator_field="parent_net_profit_ttm",
        required_input_fields=(
            "operating_cash_flow_ttm",
            "parent_net_profit_ttm",
        ),
        applicable_sector_types=(FinancialSectorType.NON_FINANCIAL.value,),
        excluded_sector_types=tuple(
            item.value
            for item in FinancialSectorType
            if item is not FinancialSectorType.NON_FINANCIAL
        ),
        industry_standard="ExposureBatch-v1",
        industry_level=1,
        sector_mapping_version="FIN-SECTOR-MAP-v1.0",
        formula_variant="operating_cash_flow_ttm/parent_net_profit_ttm",
        denominator_policy="ABS_DENOMINATOR_GT_MATERIALITY_FLOOR; NO_EPSILON_SUBSTITUTION",
        fallback_policy="NO_FALLBACK",
        not_applicable_reason="Operating cash flow is not comparable for financial-sector business models.",
        effective_from="2026-08-20",
    ),
)


def formula_definition_for(factor_id: Any) -> MVPFormulaDefinition:
    normalized = _required_text(factor_id, "factor_id")
    for definition in FORMULA_REGISTRY:
        if definition.factor_id == normalized:
            return definition
    raise ValueError(f"unsupported MVP factor_id: {normalized}")


@dataclass(frozen=True)
class FormulaCalculationResult:
    factor_id: str
    sector_type: str | None
    status: str
    value: float | None
    issue_code: str | None
    formula_variant: str | None
    formula_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "sector_type": self.sector_type,
            "status": self.status,
            "value": self.value,
            "issue_code": self.issue_code,
            "formula_variant": self.formula_variant,
            "formula_version": self.formula_version,
        }


def evaluate_registered_mvp_formula(
    factor_id: Any,
    formula_inputs: Mapping[str, Any],
    *,
    sector_type: Any,
    declared_sector_type: Any | None = None,
    denominator_materiality_floor: float = 1e-12,
    market_cap_as_of: Any | None = None,
    evaluation_date: Any | None = None,
) -> FormulaCalculationResult:
    """Evaluate a registered formula with PIT sector routing, fail closed."""
    definition = formula_definition_for(factor_id)
    if sector_type is None or not str(sector_type).strip():
        return _formula_result(
            definition, None, FormulaCalculationStatus.SECTOR_CLASSIFICATION_MISSING
        )
    normalized_sector = str(getattr(sector_type, "value", sector_type)).strip().upper()
    if normalized_sector not in {item.value for item in FinancialSectorType}:
        return _formula_result(
            definition,
            normalized_sector,
            FormulaCalculationStatus.SECTOR_CLASSIFICATION_MISSING,
        )
    if declared_sector_type is not None:
        declared = (
            str(getattr(declared_sector_type, "value", declared_sector_type))
            .strip()
            .upper()
        )
        if declared != normalized_sector:
            return _formula_result(
                definition,
                normalized_sector,
                FormulaCalculationStatus.SECTOR_FORMULA_MISMATCH,
            )
    if normalized_sector not in definition.applicable_sector_types:
        return _formula_result(
            definition, normalized_sector, FormulaCalculationStatus.NOT_APPLICABLE
        )
    if not isinstance(formula_inputs, Mapping):
        return _formula_result(
            definition,
            normalized_sector,
            FormulaCalculationStatus.MISSING_REQUIRED_INPUT,
        )
    if set(map(str, formula_inputs)) != set(definition.required_input_fields):
        return _formula_result(
            definition,
            normalized_sector,
            FormulaCalculationStatus.MISSING_REQUIRED_INPUT,
        )
    try:
        values = {
            name: float(formula_inputs[name])
            for name in definition.required_input_fields
        }
    except (KeyError, TypeError, ValueError):
        return _formula_result(
            definition, normalized_sector, FormulaCalculationStatus.NONFINITE_INPUT
        )
    if not all(math.isfinite(value) for value in values.values()):
        return _formula_result(
            definition, normalized_sector, FormulaCalculationStatus.NONFINITE_INPUT
        )
    denominator = values[definition.denominator_field]
    numerator = values[definition.numerator_field]
    invalid = (
        denominator <= 0
        if definition.factor_id in ("ROE", "BP")
        else abs(denominator) <= denominator_materiality_floor
    )
    if definition.factor_id == "BP":
        invalid = invalid or numerator <= 0
        if market_cap_as_of is None or evaluation_date is None:
            return _formula_result(
                definition,
                normalized_sector,
                FormulaCalculationStatus.MISSING_REQUIRED_INPUT,
            )
        invalid = invalid or str(market_cap_as_of) != str(evaluation_date)
    if invalid:
        return _formula_result(
            definition, normalized_sector, FormulaCalculationStatus.INVALID_DENOMINATOR
        )
    value = numerator / denominator
    if not math.isfinite(value):
        return _formula_result(
            definition, normalized_sector, FormulaCalculationStatus.NONFINITE_INPUT
        )
    return FormulaCalculationResult(
        definition.factor_id,
        normalized_sector,
        FormulaCalculationStatus.VALID.value,
        value,
        None,
        definition.formula_variant,
        definition.formula_version,
    )


def _formula_result(
    definition: MVPFormulaDefinition,
    sector: str | None,
    status: FormulaCalculationStatus,
) -> FormulaCalculationResult:
    return FormulaCalculationResult(
        definition.factor_id,
        sector,
        status.value,
        None,
        status.value,
        definition.formula_variant
        if status is not FormulaCalculationStatus.NOT_APPLICABLE
        else None,
        definition.formula_version,
    )


@dataclass(frozen=True)
class MVPBatchConfig:
    batch_version: str = "FIN-MVP-DATA-v1.0"
    batch_source: str = "fin-mvp-data-controlled-adapter"
    frequency: str = "quarterly"
    universe: str = "PIT_NON_FIN_A_SHARE_V1"
    schema_version: str = MVP_BATCH_SCHEMA_VERSION
    formula_registry_version: str = FORMULA_REGISTRY_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "batch_version",
            "batch_source",
            "frequency",
            "universe",
            "schema_version",
            "formula_registry_version",
        ):
            _required_text(getattr(self, field_name), field_name)
        if self.schema_version != MVP_BATCH_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {MVP_BATCH_SCHEMA_VERSION}")
        if self.formula_registry_version != FORMULA_REGISTRY_VERSION:
            raise ValueError("unsupported formula_registry_version")

    def to_dict(self) -> dict[str, str]:
        return {
            "batch_version": self.batch_version,
            "batch_source": self.batch_source,
            "frequency": self.frequency,
            "universe": self.universe,
            "schema_version": self.schema_version,
            "formula_registry_version": self.formula_registry_version,
        }


@dataclass(frozen=True)
class MVPBatchIssue:
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
class MVPBatchObservation:
    schema_version: str
    observation_id: str
    evaluation_date: str
    code: str
    factor_id: str
    report_period: str
    publish_date: str
    effective_date: str
    factor_value: float
    factor_value_hash: str
    path_type: str
    upstream_calculation_reference: str
    upstream_calculation_version: str
    upstream_calculation_hash: str
    formula_id: str
    formula_version: str
    formula_reference: str
    formula_input_hash: str
    formula_input_references: tuple[str, ...]
    source_snapshot_fingerprint: str
    financial_lineage_id: str
    financial_lineage_content_hash: str
    financial_lineage_reference: str
    sample_id: str
    sample_content_hash: str
    sample_reference: str
    factor_sample_mask: bool
    content_hash: str

    def to_dict(self, *, include_content_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "evaluation_date": self.evaluation_date,
            "code": self.code,
            "factor_id": self.factor_id,
            "report_period": self.report_period,
            "publish_date": self.publish_date,
            "effective_date": self.effective_date,
            "factor_value": self.factor_value,
            "factor_value_hash": self.factor_value_hash,
            "path_type": self.path_type,
            "upstream_calculation_reference": self.upstream_calculation_reference,
            "upstream_calculation_version": self.upstream_calculation_version,
            "upstream_calculation_hash": self.upstream_calculation_hash,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "formula_reference": self.formula_reference,
            "formula_input_hash": self.formula_input_hash,
            "formula_input_references": list(self.formula_input_references),
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "financial_lineage_id": self.financial_lineage_id,
            "financial_lineage_content_hash": self.financial_lineage_content_hash,
            "financial_lineage_reference": self.financial_lineage_reference,
            "sample_id": self.sample_id,
            "sample_content_hash": self.sample_content_hash,
            "sample_reference": self.sample_reference,
            "factor_sample_mask": self.factor_sample_mask,
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class MVPBatchObservationReference:
    location: str
    schema_version: str
    row_count: int
    index_fields: tuple[str, ...]
    content_hash: str
    records: tuple[MVPBatchObservation, ...]

    def lookup(
        self,
        evaluation_date: Any,
        code: Any,
        factor_id: Any,
    ) -> MVPBatchObservation:
        key = (
            _date_iso(evaluation_date),
            _required_text(code, "code"),
            _required_text(factor_id, "factor_id"),
        )
        matches = [
            item
            for item in self.records
            if (item.evaluation_date, item.code, item.factor_id) == key
        ]
        if len(matches) != 1:
            raise MVPBatchLookupError(
                MVPBatchErrorCode.LINEAGE_REFERENCE_MISSING,
                f"expected one integrated observation for {key}, found {len(matches)}",
                lookup_key=key,
            )
        return matches[0]

    def to_dict(self, *, include_records: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "location": self.location,
            "schema_version": self.schema_version,
            "row_count": self.row_count,
            "index_fields": list(self.index_fields),
            "content_hash": self.content_hash,
        }
        if include_records:
            payload["records"] = [item.to_dict() for item in self.records]
        return payload


@dataclass(frozen=True)
class FinancialBatchAudit:
    schema_version: str
    run_id: str
    supported_factor_ids: tuple[str, ...]
    path_a_count: int
    path_b_count: int
    total_input_count: int
    accepted_count: int
    rejected_count: int
    conflict_count: int
    timing_references: tuple[str, ...]
    provenance_references: tuple[str, ...]
    sample_references: tuple[str, ...]
    batch_fingerprints: tuple[tuple[str, str], ...]
    gate_status: str
    errors: tuple[MVPBatchIssue, ...]
    warnings: tuple[MVPBatchIssue, ...]
    content_hash: str

    def to_dict(self, *, include_content_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "supported_factor_ids": list(self.supported_factor_ids),
            "path_a_count": self.path_a_count,
            "path_b_count": self.path_b_count,
            "total_input_count": self.total_input_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "conflict_count": self.conflict_count,
            "timing_references": list(self.timing_references),
            "provenance_references": list(self.provenance_references),
            "sample_references": list(self.sample_references),
            "batch_fingerprints": dict(self.batch_fingerprints),
            "gate_status": self.gate_status,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class MVPFinancialBatchResult:
    batches: tuple[FinancialBatch, ...]
    observation_reference: MVPBatchObservationReference | None
    financial_batch_audit: FinancialBatchAudit

    def get_batch(self, factor_id: Any) -> FinancialBatch:
        normalized = _required_text(factor_id, "factor_id")
        matches = [item for item in self.batches if item.factor_id == normalized]
        if len(matches) != 1:
            raise MVPBatchLookupError(
                MVPBatchErrorCode.UNSUPPORTED_MVP_FACTOR,
                f"expected one batch for {normalized}, found {len(matches)}",
                lookup_key=(normalized,),
            )
        return matches[0]

    def to_dict(self, *, include_rows: bool = False) -> dict[str, Any]:
        batches: list[dict[str, Any]] = []
        for item in self.batches:
            payload: dict[str, Any] = {
                "factor_id": item.factor_id,
                "factor_type": item.factor_type.value,
                "value_scope": item.value_scope.value,
                "version": item.version,
                "source": item.source,
                "frequency": item.frequency,
                "universe": item.universe,
                "schema_version": item.schema_version,
                "provenance": copy.deepcopy(item.provenance),
                "row_count": len(item.get_frame()),
            }
            if include_rows:
                payload["rows"] = _frame_records(item)
            batches.append(payload)
        return {
            "batches": batches,
            "observation_reference": (
                self.observation_reference.to_dict()
                if self.observation_reference is not None
                else None
            ),
            "financial_batch_audit": self.financial_batch_audit.to_dict(),
        }


def recompute_observation_content_hash(
    record: MVPBatchObservation,
) -> str:
    return _versioned_hash(
        "mvp_batch_observation",
        record.to_dict(include_content_hash=False),
    )


def compute_formula_input_hash(
    factor_id: Any,
    formula_inputs: Mapping[str, Any],
    formula_input_references: Iterable[Any],
) -> str:
    definition = formula_definition_for(factor_id)
    values = _validate_formula_inputs(definition, formula_inputs)
    references = _reference_tuple(formula_input_references)
    return _versioned_hash(
        "formula_input",
        {
            "formula": definition.to_dict(),
            "values": values,
            "input_record_references": references,
        },
    )


def calculate_registered_mvp_formula(
    factor_id: Any,
    formula_inputs: Mapping[str, Any],
    *,
    sector_type: Any,
    declared_sector_type: Any | None = None,
    market_cap_as_of: Any | None = None,
    evaluation_date: Any | None = None,
) -> float:
    """Calculate one frozen formula over already prepared controlled inputs.

    Denominator anomaly policy is intentionally not inferred here.  A zero or
    negative denominator requires FIN-R2-PREP and raises ``ValueError``.
    """

    result = evaluate_registered_mvp_formula(
        factor_id,
        formula_inputs,
        sector_type=sector_type,
        declared_sector_type=declared_sector_type,
        market_cap_as_of=market_cap_as_of,
        evaluation_date=evaluation_date,
    )
    if result.status != FormulaCalculationStatus.VALID.value:
        raise ValueError(result.status)
    assert result.value is not None
    return result.value


def build_mvp_financial_batches(
    records: Iterable[Mapping[str, Any]],
    *,
    lineage_references: Mapping[str, ObservationLineageReference],
    sample_references: Mapping[str, SampleFormationReference],
    configuration: MVPBatchConfig,
    future_labels: Any = None,
) -> MVPFinancialBatchResult:
    """Return three public batches only when the entire integration passes.

    ``future_labels`` is a deliberate isolation probe.  It is never iterated,
    copied, hashed, validated, or serialized.
    """

    del future_labels
    if not isinstance(configuration, MVPBatchConfig):
        return _blocked_empty(
            _issue(
                MVPBatchErrorCode.INVALID_MVP_BATCH_INPUT,
                "configuration must be an MVPBatchConfig",
                "configuration",
            )
        )
    if not isinstance(lineage_references, Mapping):
        return _blocked_empty(
            _issue(
                MVPBatchErrorCode.LINEAGE_REFERENCE_MISSING,
                "lineage_references must be a mapping",
                "lineage_references",
            ),
            configuration=configuration,
        )
    if not isinstance(sample_references, Mapping):
        return _blocked_empty(
            _issue(
                MVPBatchErrorCode.SAMPLE_MASK_REFERENCE_MISSING,
                "sample_references must be a mapping",
                "sample_references",
            ),
            configuration=configuration,
        )
    try:
        raw_records = list(records)
        controlled_records = copy.deepcopy(raw_records)
        input_before = _versioned_hash(
            "input_mutation_guard",
            _mutation_guard_value(
                {
                    "records": raw_records,
                    "lineage_references": lineage_references,
                    "sample_references": sample_references,
                    "configuration": configuration.to_dict(),
                }
            ),
        )
    except Exception as exc:  # noqa: BLE001 - untrusted input boundary
        return _blocked_empty(
            _issue(
                MVPBatchErrorCode.INVALID_MVP_BATCH_INPUT,
                f"inputs are not canonicalizable: {type(exc).__name__}",
                "records,lineage_references,sample_references",
            ),
            configuration=configuration,
        )

    errors: list[MVPBatchIssue] = []
    warnings: list[MVPBatchIssue] = []
    _validate_reference_maps(lineage_references, sample_references, errors)

    observations: list[MVPBatchObservation] = []
    for index, raw_record in enumerate(controlled_records):
        record_key = f"records[{index}]"
        if not isinstance(raw_record, Mapping):
            errors.append(
                _issue(
                    MVPBatchErrorCode.INVALID_MVP_BATCH_INPUT,
                    "each integration record must be a mapping",
                    "records",
                    record_key,
                )
            )
            continue
        observation = _normalize_observation(
            dict(raw_record),
            record_key=record_key,
            lineage_references=lineage_references,
            sample_references=sample_references,
            errors=errors,
        )
        if observation is not None:
            observations.append(observation)

    observations.sort(key=_observation_sort_key)
    _validate_observation_conflicts(observations, errors)
    _validate_cross_security_isolation(observations, errors)
    present_factors = {item.factor_id for item in observations}
    if present_factors != set(SUPPORTED_FACTOR_IDS):
        errors.append(
            _issue(
                MVPBatchErrorCode.MVP_FACTOR_COVERAGE_INCOMPLETE,
                "accepted candidates must cover exactly ROE, BP, and OCF_NP",
                "factor_id",
            )
        )

    try:
        input_after = _versioned_hash(
            "input_mutation_guard",
            _mutation_guard_value(
                {
                    "records": raw_records,
                    "lineage_references": lineage_references,
                    "sample_references": sample_references,
                    "configuration": configuration.to_dict(),
                }
            ),
        )
        if input_before != input_after:
            errors.append(
                _issue(
                    MVPBatchErrorCode.INPUT_MUTATION_DETECTED,
                    "upstream inputs changed during Batch integration",
                )
            )
    except Exception:  # noqa: BLE001 - mutation guard must fail closed
        errors.append(
            _issue(
                MVPBatchErrorCode.INPUT_MUTATION_DETECTED,
                "upstream inputs became non-canonical during integration",
            )
        )

    errors = _deduplicate_issues(errors)
    warnings = _deduplicate_issues(warnings)
    ready = not errors
    observation_reference = (
        _build_observation_reference(tuple(observations)) if ready else None
    )
    batches: tuple[FinancialBatch, ...] = ()
    batch_fingerprints: tuple[tuple[str, str], ...] = ()
    if ready and observation_reference is not None:
        batches, batch_fingerprints, construction_errors = _build_batches(
            observations,
            observation_reference=observation_reference,
            configuration=configuration,
        )
        if construction_errors:
            errors = _deduplicate_issues([*errors, *construction_errors])
            ready = False
            observation_reference = None
            batches = ()
            batch_fingerprints = ()

    audit = _build_audit(
        observations=observations,
        total_input_count=len(raw_records),
        errors=tuple(errors),
        warnings=tuple(warnings),
        batch_fingerprints=batch_fingerprints,
        configuration=configuration,
        ready=ready,
    )
    return MVPFinancialBatchResult(
        batches=batches if ready else (),
        observation_reference=observation_reference if ready else None,
        financial_batch_audit=audit,
    )


def _validate_reference_maps(
    lineage_references: Mapping[str, ObservationLineageReference],
    sample_references: Mapping[str, SampleFormationReference],
    errors: list[MVPBatchIssue],
) -> None:
    for mapping_name, mapping, code in (
        (
            "lineage_references",
            lineage_references,
            MVPBatchErrorCode.LINEAGE_REFERENCE_MISSING,
        ),
        (
            "sample_references",
            sample_references,
            MVPBatchErrorCode.SAMPLE_MASK_REFERENCE_MISSING,
        ),
    ):
        keys = {str(key) for key in mapping}
        if keys != set(SUPPORTED_FACTOR_IDS):
            errors.append(
                _issue(
                    code,
                    f"{mapping_name} keys must be exactly {SUPPORTED_FACTOR_IDS}",
                    mapping_name,
                )
            )

    for factor_id in SUPPORTED_FACTOR_IDS:
        lineage_reference = lineage_references.get(factor_id)
        if not isinstance(lineage_reference, ObservationLineageReference):
            errors.append(
                _issue(
                    MVPBatchErrorCode.LINEAGE_REFERENCE_MISSING,
                    f"{factor_id} has no FIN-R1B reference",
                    "lineage_references",
                    factor_id,
                )
            )
        else:
            if lineage_reference.row_count != len(lineage_reference.records):
                errors.append(
                    _issue(
                        MVPBatchErrorCode.LINEAGE_REFERENCE_MISSING,
                        f"{factor_id} lineage row_count mismatch",
                        "lineage_reference.row_count",
                        factor_id,
                    )
                )
            for lineage in lineage_reference.records:
                if (
                    lineage.factor_id != factor_id
                    or lineage.content_hash != recompute_lineage_content_hash(lineage)
                ):
                    errors.append(
                        _issue(
                            MVPBatchErrorCode.LINEAGE_CONTENT_HASH_MISMATCH,
                            f"{factor_id} lineage is mismatched or tampered",
                            "lineage_reference",
                            lineage.lineage_id,
                        )
                    )

        sample_reference = sample_references.get(factor_id)
        if not isinstance(sample_reference, SampleFormationReference):
            errors.append(
                _issue(
                    MVPBatchErrorCode.SAMPLE_MASK_REFERENCE_MISSING,
                    f"{factor_id} has no FIN-R1C sample reference",
                    "sample_references",
                    factor_id,
                )
            )
        else:
            if sample_reference.row_count != len(
                sample_reference.records
            ) or sample_reference.sample_fingerprint != compute_sample_fingerprint(
                sample_reference.records
            ):
                errors.append(
                    _issue(
                        MVPBatchErrorCode.SAMPLE_CONTENT_HASH_MISMATCH,
                        f"{factor_id} sample reference fingerprint mismatch",
                        "sample_reference",
                        factor_id,
                    )
                )
            for sample in sample_reference.records:
                if (
                    sample.factor_id != factor_id
                    or sample.content_hash != recompute_sample_content_hash(sample)
                ):
                    errors.append(
                        _issue(
                            MVPBatchErrorCode.SAMPLE_CONTENT_HASH_MISMATCH,
                            f"{factor_id} sample row is mismatched or tampered",
                            "sample_reference",
                            sample.sample_id,
                        )
                    )


def _normalize_observation(
    record: dict[str, Any],
    *,
    record_key: str,
    lineage_references: Mapping[str, ObservationLineageReference],
    sample_references: Mapping[str, SampleFormationReference],
    errors: list[MVPBatchIssue],
) -> MVPBatchObservation | None:
    dynamic_fields = sorted(
        field_name
        for field_name in (
            "formula",
            "expression",
            "code_text",
            "executable_code",
            "factor_formula",
        )
        if field_name in record and record[field_name] not in (None, "", NOT_APPLICABLE)
    )
    if dynamic_fields:
        errors.append(
            _issue(
                MVPBatchErrorCode.DYNAMIC_FORMULA_NOT_ALLOWED,
                "dynamic formula or executable text is not accepted",
                ",".join(dynamic_fields),
                record_key,
            )
        )
        return None
    try:
        evaluation_date = _date_iso(record.get("evaluation_date"))
        code = _required_text(record.get("code"), "code")
        factor_id = _required_text(record.get("factor_id"), "factor_id")
        report_period = _date_iso(record.get("report_period"))
        publish_date = _date_iso(record.get("publish_date"))
        effective_date = _date_iso(record.get("effective_date"))
        path_type = _required_text(record.get("path_type"), "path_type")
        snapshot_fingerprint = _required_text(
            record.get("source_snapshot_fingerprint"),
            "source_snapshot_fingerprint",
        )
    except (TypeError, ValueError) as exc:
        errors.append(
            _issue(
                MVPBatchErrorCode.FINANCIAL_BATCH_REQUIRED_FIELD_MISSING,
                str(exc),
                "evaluation_date,code,factor_id,report_period,"
                "publish_date,effective_date,path_type,"
                "source_snapshot_fingerprint",
                record_key,
            )
        )
        return None
    if record.get("synthetic_test_only") is not True:
        errors.append(
            _issue(
                MVPBatchErrorCode.INVALID_MVP_BATCH_INPUT,
                "FIN-MVP-DATA accepts only synthetic_test_only=true input",
                "synthetic_test_only",
                record_key,
            )
        )
        return None
    if factor_id not in SUPPORTED_FACTOR_IDS:
        errors.append(
            _issue(
                MVPBatchErrorCode.UNSUPPORTED_MVP_FACTOR,
                f"factor_id {factor_id} is outside the approved MVP scope",
                "factor_id",
                record_key,
            )
        )
        return None
    if not report_period <= publish_date <= effective_date:
        errors.append(
            _issue(
                MVPBatchErrorCode.INVALID_MVP_BATCH_INPUT,
                "dates must satisfy report_period <= publish <= effective",
                "report_period,publish_date,effective_date",
                record_key,
            )
        )
        return None
    if effective_date > evaluation_date:
        errors.append(
            _issue(
                MVPBatchErrorCode.EFFECTIVE_DATE_AFTER_EVALUATION_DATE,
                "effective_date must not be after evaluation_date",
                "effective_date,evaluation_date",
                record_key,
            )
        )
        return None
    if path_type not in {item.value for item in PathType}:
        errors.append(
            _issue(
                MVPBatchErrorCode.INVALID_MVP_BATCH_INPUT,
                "path_type must be A or B",
                "path_type",
                record_key,
            )
        )
        return None

    sample_reference = sample_references.get(factor_id)
    lineage_reference = lineage_references.get(factor_id)
    if not isinstance(sample_reference, SampleFormationReference):
        errors.append(
            _issue(
                MVPBatchErrorCode.SAMPLE_MASK_REFERENCE_MISSING,
                "factor has no valid FIN-R1C sample reference",
                "sample_references",
                record_key,
            )
        )
        return None
    sample_matches = [
        item
        for item in sample_reference.records
        if (
            item.evaluation_date,
            item.code,
            item.factor_id,
        )
        == (evaluation_date, code, factor_id)
    ]
    if len(sample_matches) != 1:
        errors.append(
            _issue(
                MVPBatchErrorCode.SAMPLE_MASK_REFERENCE_MISSING,
                "integration key does not resolve to one FIN-R1C sample",
                ",".join(INTEGRATION_KEY_FIELDS),
                record_key,
            )
        )
        return None
    sample = sample_matches[0]
    if not sample.factor_sample_mask:
        errors.append(
            _issue(
                MVPBatchErrorCode.SAMPLE_MASK_REFERENCE_MISSING,
                "factor_sample_mask=false records cannot enter FinancialBatch",
                "factor_sample_mask",
                record_key,
            )
        )
        return None
    if (
        sample.report_period != report_period
        or sample.publish_date != publish_date
        or sample.effective_date != effective_date
    ):
        errors.append(
            _issue(
                MVPBatchErrorCode.SAMPLE_MASK_REFERENCE_MISSING,
                "input dates differ from the selected FIN-R1C sample",
                "report_period,publish_date,effective_date",
                record_key,
            )
        )
        return None

    if not isinstance(lineage_reference, ObservationLineageReference):
        errors.append(
            _issue(
                MVPBatchErrorCode.LINEAGE_REFERENCE_MISSING,
                "factor has no valid FIN-R1B lineage reference",
                "lineage_references",
                record_key,
            )
        )
        return None
    lineage_matches = [
        item
        for item in lineage_reference.records
        if item.lineage_id == sample.financial_lineage_id
    ]
    if len(lineage_matches) != 1:
        errors.append(
            _issue(
                MVPBatchErrorCode.LINEAGE_REFERENCE_MISSING,
                "sample lineage_id does not resolve to one FIN-R1B record",
                "financial_lineage_id",
                record_key,
            )
        )
        return None
    lineage = lineage_matches[0]
    if (
        lineage.code != code
        or lineage.factor_id != factor_id
        or lineage.report_period != report_period
        or lineage.publish_date != publish_date
        or lineage.effective_date != effective_date
        or lineage.content_hash != sample.financial_lineage_content_hash
    ):
        errors.append(
            _issue(
                MVPBatchErrorCode.LINEAGE_REFERENCE_MISSING,
                "FIN-R1B lineage differs from the FIN-R1C sample",
                "lineage_reference",
                record_key,
            )
        )
        return None
    if snapshot_fingerprint != lineage.source_snapshot_fingerprint:
        errors.append(
            _issue(
                MVPBatchErrorCode.SOURCE_SNAPSHOT_FINGERPRINT_MISMATCH,
                "source snapshot fingerprint differs from FIN-R1B",
                "source_snapshot_fingerprint",
                record_key,
            )
        )
        return None
    if lineage.path_type != path_type:
        errors.append(
            _issue(
                MVPBatchErrorCode.LINEAGE_REFERENCE_MISSING,
                "path_type differs from FIN-R1B lineage",
                "path_type",
                record_key,
            )
        )
        return None

    path_evidence = _resolve_factor_value(
        record,
        factor_id=factor_id,
        path_type=path_type,
        lineage=lineage,
        record_key=record_key,
        errors=errors,
    )
    if path_evidence is None:
        return None
    factor_value, evidence = path_evidence
    if (
        sample.raw_pit_factor_value is None
        or factor_value != sample.raw_pit_factor_value
        or compute_factor_value_hash(factor_value) != sample.factor_value_hash
        or compute_factor_value_hash(factor_value) != lineage.factor_value_hash
    ):
        errors.append(
            _issue(
                MVPBatchErrorCode.FACTOR_VALUE_HASH_MISMATCH,
                "integrated factor_value differs from R1B/R1C",
                "factor_value",
                record_key,
            )
        )
        return None

    observation_id = _versioned_hash(
        "observation_id",
        {
            "evaluation_date": evaluation_date,
            "code": code,
            "factor_id": factor_id,
            "sample_id": sample.sample_id,
            "lineage_id": lineage.lineage_id,
            "path_type": path_type,
        },
    )
    fields = {
        "schema_version": MVP_OBSERVATION_SCHEMA_VERSION,
        "observation_id": observation_id,
        "evaluation_date": evaluation_date,
        "code": code,
        "factor_id": factor_id,
        "report_period": report_period,
        "publish_date": publish_date,
        "effective_date": effective_date,
        "factor_value": factor_value,
        "factor_value_hash": compute_factor_value_hash(factor_value),
        "path_type": path_type,
        **evidence,
        "source_snapshot_fingerprint": snapshot_fingerprint,
        "financial_lineage_id": lineage.lineage_id,
        "financial_lineage_content_hash": lineage.content_hash,
        "financial_lineage_reference": lineage_reference.location,
        "sample_id": sample.sample_id,
        "sample_content_hash": sample.content_hash,
        "sample_reference": sample_reference.location,
        "factor_sample_mask": sample.factor_sample_mask,
    }
    content_hash = _versioned_hash("mvp_batch_observation", fields)
    return MVPBatchObservation(**fields, content_hash=content_hash)


def _resolve_factor_value(
    record: dict[str, Any],
    *,
    factor_id: str,
    path_type: str,
    lineage: FinancialObservationLineage,
    record_key: str,
    errors: list[MVPBatchIssue],
) -> tuple[float, dict[str, Any]] | None:
    if path_type == PathType.UPSTREAM_COMPUTED.value:
        try:
            factor_value = _finite_factor_value(record.get("factor_value"))
        except TypeError as exc:
            errors.append(
                _issue(
                    MVPBatchErrorCode.INVALID_FACTOR_VALUE,
                    str(exc),
                    "factor_value",
                    record_key,
                )
            )
            return None
        except ValueError as exc:
            errors.append(
                _issue(
                    MVPBatchErrorCode.NONFINITE_FACTOR_VALUE,
                    str(exc),
                    "factor_value",
                    record_key,
                )
            )
            return None
        try:
            upstream_reference = _required_text(
                record.get("upstream_calculation_reference"),
                "upstream_calculation_reference",
            )
            upstream_version = _required_text(
                record.get("upstream_calculation_version"),
                "upstream_calculation_version",
            )
            upstream_hash = _sha256_text(
                record.get("upstream_calculation_hash"),
                "upstream_calculation_hash",
            )
        except (TypeError, ValueError) as exc:
            errors.append(
                _issue(
                    MVPBatchErrorCode.PATH_A_UPSTREAM_PROOF_MISSING,
                    str(exc),
                    "upstream_calculation_reference,"
                    "upstream_calculation_version,"
                    "upstream_calculation_hash",
                    record_key,
                )
            )
            return None
        if upstream_reference != lineage.upstream_calculation_reference:
            errors.append(
                _issue(
                    MVPBatchErrorCode.PATH_A_UPSTREAM_PROOF_MISSING,
                    "upstream reference differs from FIN-R1B lineage",
                    "upstream_calculation_reference",
                    record_key,
                )
            )
            return None
        return factor_value, {
            "upstream_calculation_reference": upstream_reference,
            "upstream_calculation_version": upstream_version,
            "upstream_calculation_hash": upstream_hash,
            "formula_id": NOT_APPLICABLE,
            "formula_version": NOT_APPLICABLE,
            "formula_reference": NOT_APPLICABLE,
            "formula_input_hash": NOT_APPLICABLE,
            "formula_input_references": (),
        }

    definition = formula_definition_for(factor_id)
    try:
        formula_id = _required_text(record.get("formula_id"), "formula_id")
        formula_version = _required_text(
            record.get("formula_version"), "formula_version"
        )
        formula_inputs = record.get("formula_inputs")
        if not isinstance(formula_inputs, Mapping):
            raise TypeError("formula_inputs must be a mapping")
        references = _reference_tuple(record.get("formula_input_references"))
    except (TypeError, ValueError) as exc:
        errors.append(
            _issue(
                MVPBatchErrorCode.PATH_B_FORMULA_REFERENCE_MISSING,
                str(exc),
                "formula_id,formula_version,formula_inputs,formula_input_references",
                record_key,
            )
        )
        return None
    if (
        formula_id != definition.formula_id
        or formula_version != definition.formula_version
        or lineage.formula_reference != definition.formula_reference
    ):
        errors.append(
            _issue(
                MVPBatchErrorCode.PATH_B_FORMULA_REFERENCE_MISSING,
                "formula identity differs from the frozen registry or lineage",
                "formula_id,formula_version",
                record_key,
            )
        )
        return None
    try:
        factor_value = calculate_registered_mvp_formula(
            factor_id,
            formula_inputs,
            sector_type=record.get("sector_type"),
            declared_sector_type=record.get("declared_sector_type"),
            market_cap_as_of=record.get("market_cap_as_of"),
            evaluation_date=record.get("evaluation_date"),
        )
        formula_input_hash = compute_formula_input_hash(
            factor_id, formula_inputs, references
        )
    except (TypeError, ValueError) as exc:
        status_to_code = {
            FormulaCalculationStatus.SECTOR_CLASSIFICATION_MISSING.value: MVPBatchErrorCode.SECTOR_CLASSIFICATION_MISSING,
            FormulaCalculationStatus.SECTOR_FORMULA_MISMATCH.value: MVPBatchErrorCode.SECTOR_FORMULA_MISMATCH,
            FormulaCalculationStatus.NOT_APPLICABLE.value: MVPBatchErrorCode.FORMULA_NOT_APPLICABLE,
            FormulaCalculationStatus.INVALID_DENOMINATOR.value: MVPBatchErrorCode.FORMULA_INPUT_REQUIRES_FIN_R2_PREP,
            FormulaCalculationStatus.NONFINITE_INPUT.value: MVPBatchErrorCode.FORMULA_INPUT_REQUIRES_FIN_R2_PREP,
        }
        code = status_to_code.get(
            str(exc), MVPBatchErrorCode.FORMULA_INPUT_REFERENCE_MISSING
        )
        errors.append(
            _issue(
                code,
                str(exc),
                "formula_inputs,formula_input_references",
                record_key,
            )
        )
        return None
    if "factor_value" in record and record["factor_value"] is not None:
        try:
            provided = _finite_factor_value(record["factor_value"])
        except (TypeError, ValueError):
            provided = math.nan
        if provided != factor_value:
            errors.append(
                _issue(
                    MVPBatchErrorCode.FACTOR_VALUE_HASH_MISMATCH,
                    "provided factor_value differs from fixed formula result",
                    "factor_value",
                    record_key,
                )
            )
            return None
    return factor_value, {
        "upstream_calculation_reference": NOT_APPLICABLE,
        "upstream_calculation_version": NOT_APPLICABLE,
        "upstream_calculation_hash": NOT_APPLICABLE,
        "formula_id": definition.formula_id,
        "formula_version": definition.formula_version,
        "formula_reference": definition.formula_reference,
        "formula_input_hash": formula_input_hash,
        "formula_input_references": references,
    }


def _validate_formula_inputs(
    definition: MVPFormulaDefinition,
    formula_inputs: Mapping[str, Any],
) -> dict[str, float]:
    if not isinstance(formula_inputs, Mapping):
        raise TypeError("formula_inputs must be a mapping")
    actual_fields = {str(key) for key in formula_inputs}
    expected_fields = set(definition.required_input_fields)
    if actual_fields != expected_fields:
        raise ValueError(
            f"formula_inputs fields must be exactly {definition.required_input_fields}"
        )
    values: dict[str, float] = {}
    for field_name in definition.required_input_fields:
        try:
            values[field_name] = _finite_factor_value(formula_inputs[field_name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a finite prepared input") from exc
    return values


def _reference_tuple(values: Any) -> tuple[str, ...]:
    if isinstance(values, str) or values is None:
        raise TypeError("formula_input_references must be a non-empty iterable of ids")
    try:
        references = tuple(
            sorted(
                {_required_text(value, "formula_input_reference") for value in values}
            )
        )
    except TypeError as exc:
        raise TypeError("formula_input_references must be iterable") from exc
    if not references:
        raise ValueError("formula_input_references must be non-empty")
    return references


def _validate_observation_conflicts(
    observations: list[MVPBatchObservation],
    errors: list[MVPBatchIssue],
) -> None:
    groups: dict[tuple[str, str, str], list[MVPBatchObservation]] = {}
    for item in observations:
        key = (item.evaluation_date, item.code, item.factor_id)
        groups.setdefault(key, []).append(item)
    for key, group in sorted(groups.items()):
        if len(group) <= 1:
            continue
        signatures = {
            _versioned_hash(
                "duplicate_signature",
                {
                    field_name: value
                    for field_name, value in item.to_dict().items()
                    if field_name
                    not in {
                        "observation_id",
                        "content_hash",
                    }
                },
            )
            for item in group
        }
        code = (
            MVPBatchErrorCode.DUPLICATE_FINANCIAL_OBSERVATION
            if len(signatures) == 1
            else MVPBatchErrorCode.FINANCIAL_OBSERVATION_CONFLICT
        )
        errors.append(
            _issue(
                code,
                f"integration key occurs {len(group)} times",
                ",".join(INTEGRATION_KEY_FIELDS),
                "|".join(key),
            )
        )

    public_groups: dict[tuple[str, str, str, str], list[MVPBatchObservation]] = {}
    for item in observations:
        key = (
            item.factor_id,
            item.code,
            item.report_period,
            item.effective_date,
        )
        public_groups.setdefault(key, []).append(item)
    for key, group in sorted(public_groups.items()):
        values = {(item.factor_value_hash, item.financial_lineage_id) for item in group}
        if len(values) > 1:
            errors.append(
                _issue(
                    MVPBatchErrorCode.FINANCIAL_OBSERVATION_CONFLICT,
                    "public FinancialBatch key has conflicting values or lineage",
                    "factor_id,code,report_period,effective_date",
                    "|".join(key),
                )
            )


def _validate_cross_security_isolation(
    observations: list[MVPBatchObservation],
    errors: list[MVPBatchIssue],
) -> None:
    owners: dict[tuple[str, str], set[str]] = {}
    for item in observations:
        references = [
            ("lineage", item.financial_lineage_id),
            ("sample", item.sample_id),
        ]
        if item.path_type == PathType.UPSTREAM_COMPUTED.value:
            references.append(("upstream", item.upstream_calculation_reference))
        else:
            references.extend(
                ("formula_input", reference)
                for reference in item.formula_input_references
            )
        for reference_type, reference in references:
            owners.setdefault((reference_type, reference), set()).add(item.code)
    for reference, codes in sorted(owners.items()):
        if len(codes) > 1:
            errors.append(
                _issue(
                    MVPBatchErrorCode.CROSS_SECURITY_FACTOR_VALUE_DETECTED,
                    "one factor-side reference is attached to multiple "
                    f"securities: {sorted(codes)}",
                    reference[0],
                    reference[1],
                )
            )


def _build_observation_reference(
    records: tuple[MVPBatchObservation, ...],
) -> MVPBatchObservationReference:
    content_hash = _versioned_hash(
        "mvp_observation_reference",
        [item.to_dict() for item in records],
    )
    return MVPBatchObservationReference(
        location=f"immutable://financial-mvp-batch/{content_hash}.json",
        schema_version=MVP_OBSERVATION_SCHEMA_VERSION,
        row_count=len(records),
        index_fields=INTEGRATION_KEY_FIELDS,
        content_hash=content_hash,
        records=records,
    )


def _build_batches(
    observations: list[MVPBatchObservation],
    *,
    observation_reference: MVPBatchObservationReference,
    configuration: MVPBatchConfig,
) -> tuple[
    tuple[FinancialBatch, ...],
    tuple[tuple[str, str], ...],
    list[MVPBatchIssue],
]:
    batches: list[FinancialBatch] = []
    fingerprints: list[tuple[str, str]] = []
    errors: list[MVPBatchIssue] = []
    for factor_id in SUPPORTED_FACTOR_IDS:
        factor_observations = [
            item for item in observations if item.factor_id == factor_id
        ]
        public_rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in factor_observations:
            key = (item.code, item.report_period, item.effective_date)
            public_rows_by_key.setdefault(
                key,
                {
                    "code": item.code,
                    "report_period": item.report_period,
                    "publish_date": item.publish_date,
                    "effective_date": item.effective_date,
                    "factor_value": item.factor_value,
                },
            )
        public_rows = [public_rows_by_key[key] for key in sorted(public_rows_by_key)]
        fingerprint = _versioned_hash(
            "public_financial_batch",
            {
                "factor_id": factor_id,
                "configuration": configuration.to_dict(),
                "rows": public_rows,
                "integration_records": [item.to_dict() for item in factor_observations],
            },
        )
        frame = pd.DataFrame(
            public_rows,
            columns=[
                "code",
                "report_period",
                "publish_date",
                "effective_date",
                "factor_value",
            ],
        )
        try:
            batch = FinancialBatch(
                factor_id=factor_id,
                factor_type=FactorType.FINANCIAL,
                value_scope=ValueScope.SECURITY_LEVEL,
                version=configuration.batch_version,
                source=configuration.batch_source,
                frequency=configuration.frequency,
                universe=configuration.universe,
                _frame=frame,
                provenance={
                    "mvp_batch_schema_version": MVP_BATCH_SCHEMA_VERSION,
                    "formula_registry_version": FORMULA_REGISTRY_VERSION,
                    "batch_fingerprint": fingerprint,
                    "observation_reference": observation_reference.location,
                    "observation_reference_content_hash": observation_reference.content_hash,
                    "integration_row_count": len(factor_observations),
                    "public_row_count": len(public_rows),
                    "future_labels_consumed": False,
                    "synthetic_test_only": True,
                },
            )
        except EvaluationInputContractError as exc:
            errors.append(
                _issue(
                    MVPBatchErrorCode.BATCH_CONSTRUCTION_FAILED,
                    f"{factor_id} public FinancialBatch rejected: {exc}",
                    exc.field_name,
                    factor_id,
                )
            )
            continue
        batches.append(batch)
        fingerprints.append((factor_id, fingerprint))
    return tuple(batches), tuple(fingerprints), errors


def _build_audit(
    *,
    observations: list[MVPBatchObservation],
    total_input_count: int,
    errors: tuple[MVPBatchIssue, ...],
    warnings: tuple[MVPBatchIssue, ...],
    batch_fingerprints: tuple[tuple[str, str], ...],
    configuration: MVPBatchConfig,
    ready: bool,
) -> FinancialBatchAudit:
    status = (
        MVPBatchGateStatus.READY.value
        if ready and not errors
        else MVPBatchGateStatus.BLOCKED.value
    )
    conflict_codes = {
        MVPBatchErrorCode.DUPLICATE_FINANCIAL_OBSERVATION.value,
        MVPBatchErrorCode.FINANCIAL_OBSERVATION_CONFLICT.value,
        MVPBatchErrorCode.CROSS_SECURITY_FACTOR_VALUE_DETECTED.value,
    }
    timing_references = tuple(
        sorted({f"{item.factor_id}:{item.effective_date}" for item in observations})
    )
    provenance_references = tuple(
        sorted(
            {
                f"{item.factor_id}:{item.financial_lineage_reference}"
                for item in observations
            }
        )
    )
    sample_references = tuple(
        sorted({f"{item.factor_id}:{item.sample_reference}" for item in observations})
    )
    accepted_count = len(observations) if status == "ready" else 0
    fields = {
        "schema_version": MVP_AUDIT_SCHEMA_VERSION,
        "supported_factor_ids": SUPPORTED_FACTOR_IDS,
        "path_a_count": sum(
            item.path_type == PathType.UPSTREAM_COMPUTED.value for item in observations
        ),
        "path_b_count": sum(
            item.path_type == PathType.REGISTERED_FORMULA.value for item in observations
        ),
        "total_input_count": total_input_count,
        "accepted_count": accepted_count,
        "rejected_count": total_input_count - accepted_count,
        "conflict_count": sum(item.code in conflict_codes for item in errors),
        "timing_references": timing_references,
        "provenance_references": provenance_references,
        "sample_references": sample_references,
        "batch_fingerprints": batch_fingerprints,
        "gate_status": status,
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
        "configuration": configuration.to_dict(),
    }
    run_id = _versioned_hash("financial_batch_run", fields)
    content_hash = _versioned_hash(
        "financial_batch_audit", {**fields, "run_id": run_id}
    )
    return FinancialBatchAudit(
        schema_version=MVP_AUDIT_SCHEMA_VERSION,
        run_id=run_id,
        supported_factor_ids=SUPPORTED_FACTOR_IDS,
        path_a_count=fields["path_a_count"],
        path_b_count=fields["path_b_count"],
        total_input_count=total_input_count,
        accepted_count=accepted_count,
        rejected_count=total_input_count - accepted_count,
        conflict_count=fields["conflict_count"],
        timing_references=timing_references,
        provenance_references=provenance_references,
        sample_references=sample_references,
        batch_fingerprints=batch_fingerprints,
        gate_status=status,
        errors=errors,
        warnings=warnings,
        content_hash=content_hash,
    )


def _blocked_empty(
    issue: MVPBatchIssue,
    *,
    configuration: MVPBatchConfig | None = None,
) -> MVPFinancialBatchResult:
    config = configuration or MVPBatchConfig()
    audit = _build_audit(
        observations=[],
        total_input_count=0,
        errors=(issue,),
        warnings=(),
        batch_fingerprints=(),
        configuration=config,
        ready=False,
    )
    return MVPFinancialBatchResult(
        batches=(),
        observation_reference=None,
        financial_batch_audit=audit,
    )


def _issue(
    code: MVPBatchErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> MVPBatchIssue:
    return MVPBatchIssue(
        code=code.value,
        message=message,
        field_name=field_name,
        record_key=record_key,
    )


def _deduplicate_issues(
    issues: Iterable[MVPBatchIssue],
) -> list[MVPBatchIssue]:
    unique = {
        (item.code, item.message, item.field_name, item.record_key): item
        for item in issues
    }
    return [
        unique[key]
        for key in sorted(
            unique,
            key=lambda item: tuple("" if part is None else part for part in item),
        )
    ]


def _observation_sort_key(
    item: MVPBatchObservation,
) -> tuple[int, str, str, str, str]:
    return (
        SUPPORTED_FACTOR_IDS.index(item.factor_id),
        item.evaluation_date,
        item.code,
        item.report_period,
        item.effective_date,
    )


def _frame_records(batch: FinancialBatch) -> list[dict[str, Any]]:
    frame = batch.get_frame().sort_values(
        list(PUBLIC_BATCH_SORT_FIELDS), kind="mergesort"
    )
    output: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        output.append(
            {
                "code": str(row["code"]),
                "report_period": _date_iso(row["report_period"]),
                "publish_date": _date_iso(row["publish_date"]),
                "effective_date": _date_iso(row["effective_date"]),
                "factor_value": float(row["factor_value"]),
            }
        )
    return output


def _sha256_text(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{field_name} must be a 64-character SHA-256")
    return text


def _finite_factor_value(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("factor value must be numeric, not boolean")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("factor value must be numeric") from exc
    if not math.isfinite(converted):
        raise ValueError("factor value must be finite")
    return converted


def _date_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        raise TypeError("date must be non-empty")
    return date.fromisoformat(value.strip()).isoformat()


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _versioned_hash(domain: str, value: Any) -> str:
    payload = {
        "hash_contract_version": HASH_CONTRACT_VERSION,
        "domain": domain,
        "payload": _canonical_json_value(value),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mutation_guard_value(value: Any) -> Any:
    """Canonicalize hostile inputs only for before/after mutation checks."""

    if isinstance(value, Mapping):
        return {
            str(key): _mutation_guard_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_mutation_guard_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return {"__nonfinite_input__": "nan"}
        return {
            "__nonfinite_input__": (
                "positive_infinity" if value > 0 else "negative_infinity"
            )
        }
    if isinstance(value, Enum):
        return _mutation_guard_value(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _mutation_guard_value(value.to_dict())
    return {"__input_type__": type(value).__name__}


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, Enum):
        return _canonical_json_value(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not canonical JSON")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _canonical_json_value(value.to_dict())
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")
