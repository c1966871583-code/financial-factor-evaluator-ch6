"""P0-3A-STEP1A: Unified evaluation input contract (corrected).

FactorRecord / FactorValueBatch / ForwardReturnBatch / EvaluationInputBundle.
All types immutable, fail-closed, stable error codes.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FactorType(str, Enum):
    PRICE_VOLUME = "price_volume"
    FINANCIAL = "financial"
    MACRO = "macro"


class ValueScope(str, Enum):
    SECURITY_LEVEL = "security_level"
    MARKET_LEVEL = "market_level"


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ReadinessStage(str, Enum):
    QUALITY_READY = "quality_ready"
    DEFINITION_DEDUP_READY = "definition_dedup_ready"
    NUMERIC_DEDUP_READY = "numeric_dedup_ready"
    EFFECTIVENESS_READY = "effectiveness_ready"
    REVIEW_READY = "review_ready"


# ---------------------------------------------------------------------------
# Stable error codes
# ---------------------------------------------------------------------------


class EvaluationInputContractError(ValueError):
    """Structured error with stable code for all contract violations."""

    def __init__(self, code: str, message: str, *, field_name: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field_name = field_name
        self.details = details or {}

    def to_issue(self, severity: ValidationSeverity = ValidationSeverity.ERROR,
                 row_count: int | None = None) -> "ValidationIssue":
        return ValidationIssue(
            code=self.code, severity=severity, message=str(self),
            field_name=self.field_name, row_count=row_count,
            details=dict(self.details),
        )


# ---------------------------------------------------------------------------
# FactorRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorRecord:
    factor_id: str
    factor_name: str
    factor_type: FactorType
    value_scope: ValueScope
    frequency: str
    version: str
    source: str
    factor_family: str | None = None
    library: str | None = None
    category: str | None = None
    definition: str | None = None
    universe: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.factor_id.strip():
            raise EvaluationInputContractError("MISSING_FACTOR_ID", "factor_id must be non-empty", field_name="factor_id")
        if not self.factor_name.strip():
            raise EvaluationInputContractError("MISSING_FACTOR_NAME", "factor_name must be non-empty", field_name="factor_name")
        if not self.version.strip():
            raise EvaluationInputContractError("MISSING_VERSION", "version must be non-empty", field_name="version")
        if not self.source.strip():
            raise EvaluationInputContractError("MISSING_SOURCE", "source must be non-empty", field_name="source")
        if not self.frequency.strip():
            raise EvaluationInputContractError("MISSING_FREQUENCY", "frequency must be non-empty", field_name="frequency")
        if self.factor_type is FactorType.PRICE_VOLUME and self.value_scope is not ValueScope.SECURITY_LEVEL:
            raise EvaluationInputContractError("SCOPE_MISMATCH", "PRICE_VOLUME factor must have value_scope=SECURITY_LEVEL", field_name="value_scope")
        if self.factor_type is FactorType.FINANCIAL and self.value_scope is not ValueScope.SECURITY_LEVEL:
            raise EvaluationInputContractError("SCOPE_MISMATCH", "FINANCIAL factor must have value_scope=SECURITY_LEVEL", field_name="value_scope")
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_non_empty(value: str, field_name: str, code: str) -> None:
    if not value.strip():
        raise EvaluationInputContractError(code, f"{field_name} must be non-empty", field_name=field_name)


def _validate_dates(series: pd.Series, field_name: str) -> None:
    """Validate all values are parseable dates.  Fails on null or non-date strings."""
    if series.isnull().any():
        raise EvaluationInputContractError("NULL_KEY", f"Null values in {field_name}", field_name=field_name)
    try:
        pd.to_datetime(series, format="%Y-%m-%d", errors="raise")
    except Exception as exc:
        raise EvaluationInputContractError("INVALID_DATE", f"Unparseable date in {field_name}: {exc}", field_name=field_name) from exc


def _validate_numeric_strict(series: pd.Series, field_name: str) -> None:
    """Validate every non-null value is a number.  Strings like 'abc' or '1.2x' fail."""
    try:
        converted = pd.to_numeric(series, errors="raise")
    except Exception as exc:
        raise EvaluationInputContractError("NON_NUMERIC_VALUE", f"Non-numeric value in {field_name}: {exc}", field_name=field_name) from exc
    if (converted == float("inf")).any() or (converted == float("-inf")).any():
        raise EvaluationInputContractError("INFINITE_VALUE", f"Infinite value in {field_name}", field_name=field_name)


def _validate_key_not_null(df: pd.DataFrame, key_cols: list[str]) -> None:
    null_mask = df[key_cols].isnull().any()
    if null_mask.any():
        bad = [c for c in key_cols if null_mask[c]]
        raise EvaluationInputContractError("NULL_KEY", f"Null values in key columns: {bad}", field_name=",".join(bad))


def _validate_no_duplicates(df: pd.DataFrame, key_cols: list[str]) -> None:
    if df.duplicated(subset=key_cols).any():
        raise EvaluationInputContractError("DUPLICATE_KEY", f"Duplicate key in columns: {key_cols}", field_name=",".join(key_cols), details={"key_columns": key_cols})


def _validate_date_order(series_a: pd.Series, series_b: pd.Series, a_label: str, b_label: str) -> None:
    if (series_a > series_b).any():
        raise EvaluationInputContractError("INVALID_DATE_ORDER", f"{a_label} must be <= {b_label}", field_name=f"{a_label},{b_label}")


def _validate_strict_date_order(series_a: pd.Series, series_b: pd.Series, a_label: str, b_label: str) -> None:
    if (series_a >= series_b).any():
        raise EvaluationInputContractError("INVALID_DATE_ORDER", f"{a_label} must be < {b_label}", field_name=f"{a_label},{b_label}")


# ---------------------------------------------------------------------------
# PriceVolumeBatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceVolumeBatch:
    factor_id: str
    factor_type: FactorType
    value_scope: ValueScope
    version: str
    source: str
    _frame: pd.DataFrame
    frequency: str = "day"
    universe: str | None = None
    schema_version: str = "1.0"
    provenance: dict[str, Any] = field(default_factory=dict)

    _REQUIRED_COLS = ("date", "code", "factor_value")
    _KEY_COLS = ("date", "code")

    def __post_init__(self) -> None:
        _validate_non_empty(self.factor_id, "factor_id", "MISSING_FACTOR_ID")
        _validate_non_empty(self.version, "version", "MISSING_VERSION")
        _validate_non_empty(self.source, "source", "MISSING_SOURCE")
        _validate_non_empty(self.frequency, "frequency", "MISSING_FREQUENCY")
        if self.factor_type is not FactorType.PRICE_VOLUME:
            raise EvaluationInputContractError("FACTOR_TYPE_MISMATCH", "PriceVolumeBatch requires factor_type=PRICE_VOLUME")
        if self.value_scope is not ValueScope.SECURITY_LEVEL:
            raise EvaluationInputContractError("SCOPE_MISMATCH", "PriceVolumeBatch requires value_scope=SECURITY_LEVEL")

        frame = self._frame.copy()
        missing = [c for c in self._REQUIRED_COLS if c not in frame.columns]
        if missing:
            raise EvaluationInputContractError("MISSING_REQUIRED_COLUMN", f"Missing columns: {missing}", field_name=",".join(missing))

        _validate_dates(frame["date"], "date")
        _validate_key_not_null(frame, ["code"])
        _validate_numeric_strict(frame["factor_value"], "factor_value")
        _validate_no_duplicates(frame, list(self._KEY_COLS))

        object.__setattr__(self, "_frame", frame)
        object.__setattr__(self, "provenance", copy.deepcopy(self.provenance))

    def get_frame(self) -> pd.DataFrame:
        return self._frame.copy()


# ---------------------------------------------------------------------------
# FinancialBatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinancialBatch:
    factor_id: str
    factor_type: FactorType
    value_scope: ValueScope
    version: str
    source: str
    _frame: pd.DataFrame
    frequency: str = "quarterly"
    universe: str | None = None
    schema_version: str = "1.0"
    provenance: dict[str, Any] = field(default_factory=dict)

    _REQUIRED_COLS = ("code", "report_period", "publish_date", "effective_date", "factor_value")
    _KEY_COLS = ("code", "report_period", "effective_date")

    def __post_init__(self) -> None:
        _validate_non_empty(self.factor_id, "factor_id", "MISSING_FACTOR_ID")
        _validate_non_empty(self.version, "version", "MISSING_VERSION")
        _validate_non_empty(self.source, "source", "MISSING_SOURCE")
        _validate_non_empty(self.frequency, "frequency", "MISSING_FREQUENCY")
        if self.factor_type is not FactorType.FINANCIAL:
            raise EvaluationInputContractError("FACTOR_TYPE_MISMATCH", "FinancialBatch requires factor_type=FINANCIAL")
        if self.value_scope is not ValueScope.SECURITY_LEVEL:
            raise EvaluationInputContractError("SCOPE_MISMATCH", "FinancialBatch requires value_scope=SECURITY_LEVEL")

        frame = self._frame.copy()
        missing = [c for c in self._REQUIRED_COLS if c not in frame.columns]
        if missing:
            raise EvaluationInputContractError("MISSING_REQUIRED_COLUMN", f"Missing columns: {missing}", field_name=",".join(missing))

        _validate_key_not_null(frame, ["code", "report_period", "publish_date", "effective_date"])
        _validate_numeric_strict(frame["factor_value"], "factor_value")

        rp = pd.to_datetime(frame["report_period"], errors="raise")
        pd_date = pd.to_datetime(frame["publish_date"], errors="raise")
        ed = pd.to_datetime(frame["effective_date"], errors="raise")
        _validate_date_order(rp, pd_date, "report_period", "publish_date")
        _validate_strict_date_order(pd_date, ed, "publish_date", "effective_date")
        _validate_no_duplicates(frame, list(self._KEY_COLS))

        object.__setattr__(self, "_frame", frame)
        object.__setattr__(self, "provenance", copy.deepcopy(self.provenance))

    def get_frame(self) -> pd.DataFrame:
        return self._frame.copy()


# ---------------------------------------------------------------------------
# MacroBatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MacroBatch:
    factor_id: str
    factor_type: FactorType
    value_scope: ValueScope
    version: str
    source: str
    _frame: pd.DataFrame
    frequency: str = "monthly"
    universe: str | None = None
    schema_version: str = "1.0"
    provenance: dict[str, Any] = field(default_factory=dict)

    _COMMON_COLS = ("observation_period", "release_date", "effective_date", "factor_value", "region_or_market")
    _MARKET_KEY = ("region_or_market", "observation_period", "release_date", "effective_date")

    def __post_init__(self) -> None:
        _validate_non_empty(self.factor_id, "factor_id", "MISSING_FACTOR_ID")
        _validate_non_empty(self.version, "version", "MISSING_VERSION")
        _validate_non_empty(self.source, "source", "MISSING_SOURCE")
        _validate_non_empty(self.frequency, "frequency", "MISSING_FREQUENCY")
        if self.factor_type is not FactorType.MACRO:
            raise EvaluationInputContractError("FACTOR_TYPE_MISMATCH", "MacroBatch requires factor_type=MACRO")

        frame = self._frame.copy()
        missing = [c for c in self._COMMON_COLS if c not in frame.columns]
        if missing:
            raise EvaluationInputContractError("MISSING_REQUIRED_COLUMN", f"Missing columns: {missing}", field_name=",".join(missing))

        if self.value_scope is ValueScope.SECURITY_LEVEL and "code" not in frame.columns:
            raise EvaluationInputContractError("MISSING_REQUIRED_COLUMN", "MacroBatch with SECURITY_LEVEL requires 'code' column", field_name="code")
        if self.value_scope is ValueScope.MARKET_LEVEL and "code" in frame.columns:
            raise EvaluationInputContractError("SCOPE_MISMATCH", "MacroBatch with MARKET_LEVEL must not have 'code' column", field_name="code")

        if self.value_scope is ValueScope.SECURITY_LEVEL:
            key_cols = list(self._MARKET_KEY) + ["code"]
        else:
            key_cols = list(self._MARKET_KEY)
        _validate_key_not_null(frame, key_cols)
        _validate_numeric_strict(frame["factor_value"], "factor_value")

        op = pd.to_datetime(frame["observation_period"], errors="raise")
        rd = pd.to_datetime(frame["release_date"], errors="raise")
        ed = pd.to_datetime(frame["effective_date"], errors="raise")
        _validate_date_order(op, rd, "observation_period", "release_date")
        _validate_date_order(rd, ed, "release_date", "effective_date")
        _validate_no_duplicates(frame, key_cols)

        object.__setattr__(self, "_frame", frame)
        object.__setattr__(self, "provenance", copy.deepcopy(self.provenance))

    def get_frame(self) -> pd.DataFrame:
        return self._frame.copy()


# ---------------------------------------------------------------------------
# ForwardReturnBatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForwardReturnBatch:
    return_set_id: str
    value_scope: ValueScope
    version: str
    source: str
    return_definition: str
    _frame: pd.DataFrame
    frequency: str = "day"
    universe: str | None = None
    schema_version: str = "1.0"
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty(self.return_set_id, "return_set_id", "MISSING_RETURN_SET_ID")
        _validate_non_empty(self.version, "version", "MISSING_VERSION")
        _validate_non_empty(self.source, "source", "MISSING_SOURCE")
        _validate_non_empty(self.return_definition, "return_definition", "MISSING_RETURN_DEFINITION")

        frame = self._frame.copy()
        if self.value_scope is ValueScope.SECURITY_LEVEL:
            required = ["date", "code", "horizon", "forward_return"]
            key_cols = ["date", "code", "horizon"]
        else:
            required = ["date", "region_or_market", "horizon", "forward_return"]
            key_cols = ["date", "region_or_market", "horizon"]

        missing = [c for c in required if c not in frame.columns]
        if missing:
            raise EvaluationInputContractError("MISSING_REQUIRED_COLUMN", f"Missing columns: {missing}", field_name=",".join(missing))

        _validate_dates(frame["date"], "date")
        _validate_key_not_null(frame, key_cols)
        _validate_numeric_strict(frame["forward_return"], "forward_return")
        horizon_values = pd.to_numeric(frame["horizon"], errors="raise")
        if horizon_values.isna().any() or (horizon_values < 1).any() or (horizon_values % 1 != 0).any():
            raise EvaluationInputContractError("INVALID_HORIZON", "horizon must be a positive integer", field_name="horizon")
        _validate_no_duplicates(frame, key_cols)

        object.__setattr__(self, "_frame", frame)
        object.__setattr__(self, "provenance", copy.deepcopy(self.provenance))

    def get_frame(self) -> pd.DataFrame:
        return self._frame.copy()


# ---------------------------------------------------------------------------
# ValidationIssue / ValidationReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    message: str
    field_name: str | None = None
    row_count: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", copy.deepcopy(self.details))


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    infos: list[ValidationIssue] = field(default_factory=list)
    readiness_stages: set[ReadinessStage] = field(default_factory=set)
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.valid and len(self.errors) == 0:
            raise ValueError("valid=False requires at least one ERROR")
        if self.valid and len(self.errors) > 0:
            raise ValueError("valid=True but errors list is non-empty")


# ---------------------------------------------------------------------------
# EvaluationInputBundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationInputBundle:
    factor_record: FactorRecord
    factor_values: PriceVolumeBatch | FinancialBatch | MacroBatch
    forward_returns: ForwardReturnBatch | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    validation_report: ValidationReport | None = None

    def __post_init__(self) -> None:
        f = self.factor_record
        fv = self.factor_values

        if f.factor_id != fv.factor_id:
            raise EvaluationInputContractError("FACTOR_ID_MISMATCH", f"factor_id mismatch: {f.factor_id} vs {fv.factor_id}", field_name="factor_id")
        if f.factor_type != fv.factor_type:
            raise EvaluationInputContractError("FACTOR_TYPE_MISMATCH", f"factor_type mismatch: {f.factor_type} vs {fv.factor_type}", field_name="factor_type")
        if f.value_scope != fv.value_scope:
            raise EvaluationInputContractError("SCOPE_MISMATCH", f"value_scope mismatch: {f.value_scope} vs {fv.value_scope}", field_name="value_scope")
        if f.version != fv.version:
            raise EvaluationInputContractError("FACTOR_VERSION_MISMATCH", f"version mismatch: FactorRecord={f.version}, FactorValues={fv.version}", field_name="version")

        # Forward returns compatibility checks
        if self.forward_returns is not None:
            fr = self.forward_returns
            if f.value_scope != fr.value_scope:
                raise EvaluationInputContractError("SCOPE_MISMATCH", f"factor value_scope={f.value_scope} != forward_returns value_scope={fr.value_scope}", field_name="value_scope")
            if f.universe is not None and fr.universe is not None and f.universe != fr.universe:
                raise EvaluationInputContractError("UNIVERSE_MISMATCH", f"universe mismatch: {f.universe} vs {fr.universe}", field_name="universe")

        object.__setattr__(self, "provenance", copy.deepcopy(self.provenance))

    def compute_readiness(self) -> set[ReadinessStage]:
        stages: set[ReadinessStage] = {ReadinessStage.QUALITY_READY}

        # NUMERIC_DEDUP_READY: factor values exist and are valid (guaranteed by construction)
        stages.add(ReadinessStage.NUMERIC_DEDUP_READY)

        # DEFINITION_DEDUP_READY: only if definition is non-empty
        definition = (self.factor_record.definition or "").strip()
        if definition:
            stages.add(ReadinessStage.DEFINITION_DEDUP_READY)

        # EFFECTIVENESS_READY: only for SECURITY_LEVEL with compatible forward returns
        if (self.factor_record.value_scope is ValueScope.SECURITY_LEVEL
                and self.forward_returns is not None
                and self.forward_returns.value_scope is ValueScope.SECURITY_LEVEL):
            stages.add(ReadinessStage.EFFECTIVENESS_READY)

        # REVIEW_READY: never auto
        return stages
