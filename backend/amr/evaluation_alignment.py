"""P0-4A-STEP1: PRICE_VOLUME evaluation data alignment and gating.

Aligns factor values with forward returns by (date, code), produces
AlignmentReport and GateResult.  Price-volume only in this step.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from .evaluation_input_contract import (
    EvaluationInputBundle,
    FactorType,
    ValueScope,
    ValidationIssue,
    ValidationSeverity,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GateStatus(str, Enum):
    READY = "ready"
    WARNING = "warning"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"
    NOT_RUN = "not_run"


# ---------------------------------------------------------------------------
# GateThresholds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateThresholds:
    min_valid_pair_ratio: float = 0.0
    min_observations: int = 1
    min_dates: int = 1
    min_cross_section_size: int = 1
    max_factor_missing_ratio: float = 1.0
    max_return_missing_ratio: float = 1.0

    def __post_init__(self) -> None:
        ratios = {
            "min_valid_pair_ratio": self.min_valid_pair_ratio,
            "max_factor_missing_ratio": self.max_factor_missing_ratio,
            "max_return_missing_ratio": self.max_return_missing_ratio,
        }
        for name, val in ratios.items():
            if not (0.0 <= val <= 1.0):
                raise ValueError(f"{name} must be in [0, 1], got {val}")
        if self.min_observations < 1:
            raise ValueError(f"min_observations must be >= 1, got {self.min_observations}")
        if self.min_dates < 1:
            raise ValueError(f"min_dates must be >= 1, got {self.min_dates}")
        if self.min_cross_section_size < 1:
            raise ValueError(f"min_cross_section_size must be >= 1, got {self.min_cross_section_size}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_valid_pair_ratio": self.min_valid_pair_ratio,
            "min_observations": self.min_observations,
            "min_dates": self.min_dates,
            "min_cross_section_size": self.min_cross_section_size,
            "max_factor_missing_ratio": self.max_factor_missing_ratio,
            "max_return_missing_ratio": self.max_return_missing_ratio,
        }


# ---------------------------------------------------------------------------
# AlignedEvaluationData
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlignedEvaluationData:
    factor_id: str
    return_set_id: str
    horizon: str
    _valid_frame: pd.DataFrame
    _all_matched_frame: pd.DataFrame

    def __post_init__(self) -> None:
        object.__setattr__(self, "_valid_frame", self._valid_frame.copy())
        object.__setattr__(self, "_all_matched_frame", self._all_matched_frame.copy())

    def get_valid_frame(self) -> pd.DataFrame:
        """Return (date, code, factor_value, forward_return, horizon) with both non-null."""
        return self._valid_frame.copy()

    def get_all_matched_frame(self) -> pd.DataFrame:
        """Return all key-matched rows (may include NaN values)."""
        return self._all_matched_frame.copy()


# ---------------------------------------------------------------------------
# AlignmentReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlignmentReport:
    factor_id: str
    factor_type: str
    value_scope: str
    return_set_id: str | None
    horizon: str | None

    original_factor_rows: int = 0
    selected_return_rows: int = 0
    key_matched_rows: int = 0
    valid_pair_rows: int = 0
    unmatched_factor_rows: int = 0
    unmatched_return_rows: int = 0

    factor_key_match_ratio: float = 0.0
    return_key_match_ratio: float = 0.0
    valid_pair_ratio: float = 0.0

    factor_missing_ratio: float = 0.0
    return_missing_ratio: float = 0.0

    valid_dates: int = 0
    date_start: str | None = None
    date_end: str | None = None
    per_date_valid_sample_summary: dict[str, int] = field(default_factory=dict)
    issue_codes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "per_date_valid_sample_summary", dict(self.per_date_valid_sample_summary))
        object.__setattr__(self, "issue_codes", list(self.issue_codes))

    def _ratio(self, num: int, den: int) -> float:
        if den == 0:
            return 0.0
        return num / den


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateResult:
    factor_id: str
    overall_status: GateStatus
    evaluation_readiness: dict[str, GateStatus] = field(default_factory=dict)
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    infos: list[ValidationIssue] = field(default_factory=list)
    thresholds_used: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    not_run_reasons: dict[str, str] = field(default_factory=dict)
    alignment_report: AlignmentReport | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_readiness", dict(self.evaluation_readiness))
        object.__setattr__(self, "errors", list(self.errors))
        object.__setattr__(self, "warnings", list(self.warnings))
        object.__setattr__(self, "infos", list(self.infos))
        object.__setattr__(self, "thresholds_used", dict(self.thresholds_used))
        object.__setattr__(self, "evidence", dict(self.evidence))
        object.__setattr__(self, "not_run_reasons", dict(self.not_run_reasons))


# ---------------------------------------------------------------------------
# Helper: build issues
# ---------------------------------------------------------------------------


def _err(code: str, msg: str, **kw: Any) -> ValidationIssue:
    return ValidationIssue(code=code, severity=ValidationSeverity.ERROR, message=msg, **kw)


def _warn(code: str, msg: str, **kw: Any) -> ValidationIssue:
    return ValidationIssue(code=code, severity=ValidationSeverity.WARNING, message=msg, **kw)


def _info(code: str, msg: str, **kw: Any) -> ValidationIssue:
    return ValidationIssue(code=code, severity=ValidationSeverity.INFO, message=msg, **kw)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def align_price_volume_bundle(
    bundle: EvaluationInputBundle,
    *,
    horizon: str,
    thresholds: GateThresholds | None = None,
) -> tuple[AlignedEvaluationData | None, AlignmentReport, GateResult]:
    """Align PRICE_VOLUME factor values with forward returns by (date, code).

    Returns (aligned_data_or_None, alignment_report, gate_result).
    """
    if thresholds is None:
        thresholds = GateThresholds()

    rec = bundle.factor_record
    fv = bundle.factor_values
    fr = bundle.forward_returns

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    infos: list[ValidationIssue] = []
    not_run_reasons: dict[str, str] = {}
    evaluation_readiness: dict[str, GateStatus] = {}

    # --- Scope gate ---
    if rec.factor_type is not FactorType.PRICE_VOLUME:
        report = _empty_report(rec.factor_id, rec.factor_type.value, rec.value_scope.value, None, None)
        gate = GateResult(
            factor_id=rec.factor_id,
            overall_status=GateStatus.NOT_APPLICABLE,
            not_run_reasons={"cross_sectional_evaluation": f"factor_type={rec.factor_type.value}"},
            errors=[_err("NOT_APPLICABLE_FACTOR_TYPE", f"Only PRICE_VOLUME supported, got {rec.factor_type.value}")],
            thresholds_used=thresholds.to_dict(),
            alignment_report=report,
        )
        return None, report, gate

    if rec.value_scope is not ValueScope.SECURITY_LEVEL:
        report = _empty_report(rec.factor_id, rec.factor_type.value, rec.value_scope.value, None, None)
        gate = GateResult(
            factor_id=rec.factor_id,
            overall_status=GateStatus.NOT_APPLICABLE,
            not_run_reasons={"cross_sectional_evaluation": f"value_scope={rec.value_scope.value}"},
            errors=[_err("NOT_APPLICABLE_VALUE_SCOPE", f"Only SECURITY_LEVEL supported, got {rec.value_scope.value}")],
            thresholds_used=thresholds.to_dict(),
            alignment_report=report,
        )
        return None, report, gate

    # --- Forward returns gate ---
    if fr is None:
        report = _empty_report(rec.factor_id, rec.factor_type.value, rec.value_scope.value, None, None)
        gate = GateResult(
            factor_id=rec.factor_id,
            overall_status=GateStatus.NOT_RUN,
            not_run_reasons={"cross_sectional_evaluation": "no_forward_returns"},
            thresholds_used=thresholds.to_dict(),
            alignment_report=report,
        )
        return None, report, gate

    # --- Horizon gate ---
    ret_frame = fr.get_frame()
    if "horizon" not in ret_frame.columns:
        report = _empty_report(rec.factor_id, rec.factor_type.value, rec.value_scope.value, fr.return_set_id, None)
        gate = GateResult(
            factor_id=rec.factor_id,
            overall_status=GateStatus.NOT_RUN,
            not_run_reasons={"cross_sectional_evaluation": "no_horizon_column"},
            errors=[_err("MISSING_HORIZON_COLUMN", "ForwardReturnBatch has no horizon column")],
            thresholds_used=thresholds.to_dict(),
            alignment_report=report,
        )
        return None, report, gate

    horizon_int = _parse_horizon_int(horizon)
    if horizon_int is None:
        report = _empty_report(rec.factor_id, rec.factor_type.value, rec.value_scope.value, fr.return_set_id, horizon)
        gate = GateResult(
            factor_id=rec.factor_id,
            overall_status=GateStatus.NOT_RUN,
            not_run_reasons={"cross_sectional_evaluation": f"horizon={horizon} not found"},
            errors=[_err("HORIZON_NOT_FOUND", f"Horizon '{horizon}' not found in forward returns")],
            thresholds_used=thresholds.to_dict(),
            alignment_report=report,
        )
        return None, report, gate

    sub = ret_frame[ret_frame["horizon"].astype(str) == str(horizon_int)].copy()
    if len(sub) == 0:
        report = _empty_report(rec.factor_id, rec.factor_type.value, rec.value_scope.value, fr.return_set_id, horizon)
        gate = GateResult(
            factor_id=rec.factor_id,
            overall_status=GateStatus.NOT_RUN,
            not_run_reasons={"cross_sectional_evaluation": f"horizon={horizon} empty after filter"},
            errors=[_err("HORIZON_NOT_FOUND", f"No rows for horizon '{horizon}'")],
            thresholds_used=thresholds.to_dict(),
            alignment_report=report,
        )
        return None, report, gate

    # --- Alignment ---
    factor_frame = fv.get_frame()
    original_factor_rows = len(factor_frame)
    selected_return_rows = len(sub)

    merged = factor_frame.merge(sub, on=["date", "code"], how="outer", indicator=True, suffixes=("", "_ret"))
    both_mask = merged["_merge"] == "both"
    left_only_mask = merged["_merge"] == "left_only"
    right_only_mask = merged["_merge"] == "right_only"

    key_matched_rows = int(both_mask.sum())
    unmatched_factor_rows = int(left_only_mask.sum())
    unmatched_return_rows = int(right_only_mask.sum())

    factor_key_match_ratio = key_matched_rows / original_factor_rows if original_factor_rows > 0 else 0.0
    return_key_match_ratio = key_matched_rows / selected_return_rows if selected_return_rows > 0 else 0.0

    # Valid pairs: both key-matched AND both values non-null
    both = merged[both_mask].copy()
    valid_mask = both["factor_value"].notna() & both["forward_return"].notna()
    valid_pairs = both[valid_mask]
    valid_pair_rows = len(valid_pairs)
    valid_pair_ratio = valid_pair_rows / original_factor_rows if original_factor_rows > 0 else 0.0

    factor_missing_ratio = 1.0 - (both["factor_value"].notna().sum() / key_matched_rows) if key_matched_rows > 0 else 0.0
    return_missing_ratio = 1.0 - (both["forward_return"].notna().sum() / key_matched_rows) if key_matched_rows > 0 else 0.0

    valid_dates = valid_pairs["date"].nunique() if valid_pair_rows > 0 else 0
    date_start = valid_pairs["date"].min() if valid_pair_rows > 0 else None
    date_end = valid_pairs["date"].max() if valid_pair_rows > 0 else None

    per_date = {}
    if valid_pair_rows > 0:
        per_date = valid_pairs.groupby("date").size().to_dict()
        per_date = {str(k): int(v) for k, v in per_date.items()}

    report = AlignmentReport(
        factor_id=rec.factor_id,
        factor_type=rec.factor_type.value,
        value_scope=rec.value_scope.value,
        return_set_id=fr.return_set_id,
        horizon=horizon,
        original_factor_rows=original_factor_rows,
        selected_return_rows=selected_return_rows,
        key_matched_rows=key_matched_rows,
        valid_pair_rows=valid_pair_rows,
        unmatched_factor_rows=unmatched_factor_rows,
        unmatched_return_rows=unmatched_return_rows,
        factor_key_match_ratio=factor_key_match_ratio,
        return_key_match_ratio=return_key_match_ratio,
        valid_pair_ratio=valid_pair_ratio,
        factor_missing_ratio=factor_missing_ratio,
        return_missing_ratio=return_missing_ratio,
        valid_dates=valid_dates,
        date_start=str(date_start) if date_start is not None else None,
        date_end=str(date_end) if date_end is not None else None,
        per_date_valid_sample_summary=per_date,
    )

    # --- Gating ---
    issue_codes: list[str] = []

    if key_matched_rows == 0:
        errors.append(_err("ALIGNMENT_NO_MATCH", "Zero key-matched rows between factor values and forward returns"))
        issue_codes.append("ALIGNMENT_NO_MATCH")

    if key_matched_rows > 0 and valid_pair_rows == 0:
        errors.append(_err("NO_VALID_PAIRS", "Key-matched but all pairs have NaN factor_value or forward_return"))
        issue_codes.append("NO_VALID_PAIRS")

    if valid_pair_rows > 0:
        # Constant factor check
        if valid_pairs["factor_value"].nunique() == 1:
            errors.append(_err("FACTOR_CONSTANT", "All valid factor values are identical"))
            issue_codes.append("FACTOR_CONSTANT")

        # Daily cross-section constant check
        daily_nunique = valid_pairs.groupby("date")["factor_value"].nunique()
        const_dates = daily_nunique[daily_nunique == 1]
        const_dates = const_dates[valid_pairs.groupby("date").size() >= 2]
        if len(const_dates) > 0:
            warnings.append(_warn("DAILY_CROSS_SECTION_CONSTANT", f"{len(const_dates)} dates have constant factor values"))
            issue_codes.append("DAILY_CROSS_SECTION_CONSTANT")

        # Observations
        if valid_pair_rows < thresholds.min_observations:
            errors.append(_err("INSUFFICIENT_OBSERVATIONS", f"valid_pairs={valid_pair_rows} < min={thresholds.min_observations}", row_count=valid_pair_rows))
            issue_codes.append("INSUFFICIENT_OBSERVATIONS")

        # Valid pair ratio
        if valid_pair_ratio < thresholds.min_valid_pair_ratio:
            warnings.append(_warn("VALID_PAIR_RATIO_LOW", f"valid_pair_ratio={valid_pair_ratio:.4f} < min={thresholds.min_valid_pair_ratio}", details={"valid_pair_ratio": valid_pair_ratio, "threshold": thresholds.min_valid_pair_ratio}))
            issue_codes.append("VALID_PAIR_RATIO_LOW")

        # Dates
        if valid_dates < thresholds.min_dates:
            warnings.append(_warn("INSUFFICIENT_DATES", f"valid_dates={valid_dates} < min={thresholds.min_dates}", details={"valid_dates": valid_dates}))
            issue_codes.append("INSUFFICIENT_DATES")

        # Cross-section size
        min_daily = valid_pairs.groupby("date").size().min()
        if min_daily < thresholds.min_cross_section_size:
            warnings.append(_warn("LOW_CROSS_SECTION", f"min daily codes={min_daily} < min={thresholds.min_cross_section_size}", details={"min_daily_codes": int(min_daily)}))
            issue_codes.append("LOW_CROSS_SECTION")

        # Missing ratios
        if factor_missing_ratio > thresholds.max_factor_missing_ratio:
            warnings.append(_warn("HIGH_FACTOR_MISSING", f"factor_missing_ratio={factor_missing_ratio:.4f} > max={thresholds.max_factor_missing_ratio}"))
            issue_codes.append("HIGH_FACTOR_MISSING")

        if return_missing_ratio > thresholds.max_return_missing_ratio:
            warnings.append(_warn("HIGH_RETURN_MISSING", f"return_missing_ratio={return_missing_ratio:.4f} > max={thresholds.max_return_missing_ratio}"))
            issue_codes.append("HIGH_RETURN_MISSING")

    # Overall status
    if any(e for e in errors if e.code in ("ALIGNMENT_NO_MATCH", "NO_VALID_PAIRS", "INSUFFICIENT_OBSERVATIONS", "FACTOR_CONSTANT")):
        overall = GateStatus.BLOCKED
    elif warnings:
        overall = GateStatus.WARNING
    elif valid_pair_rows > 0:
        overall = GateStatus.READY
        evaluation_readiness["cross_sectional_evaluation"] = GateStatus.READY
    else:
        overall = GateStatus.BLOCKED
        errors.append(_err("NO_VALID_PAIRS", "No valid evaluation pairs"))
        issue_codes.append("NO_VALID_PAIRS")

    report = AlignmentReport(
        factor_id=rec.factor_id,
        factor_type=rec.factor_type.value,
        value_scope=rec.value_scope.value,
        return_set_id=fr.return_set_id,
        horizon=horizon,
        original_factor_rows=original_factor_rows,
        selected_return_rows=selected_return_rows,
        key_matched_rows=key_matched_rows,
        valid_pair_rows=valid_pair_rows,
        unmatched_factor_rows=unmatched_factor_rows,
        unmatched_return_rows=unmatched_return_rows,
        factor_key_match_ratio=factor_key_match_ratio,
        return_key_match_ratio=return_key_match_ratio,
        valid_pair_ratio=valid_pair_ratio,
        factor_missing_ratio=factor_missing_ratio,
        return_missing_ratio=return_missing_ratio,
        valid_dates=valid_dates,
        date_start=str(date_start) if date_start is not None else None,
        date_end=str(date_end) if date_end is not None else None,
        per_date_valid_sample_summary=per_date,
        issue_codes=issue_codes,
    )

    gate = GateResult(
        factor_id=rec.factor_id,
        overall_status=overall,
        evaluation_readiness=evaluation_readiness,
        errors=errors,
        warnings=warnings,
        infos=infos,
        thresholds_used=thresholds.to_dict(),
        evidence={"valid_pair_rows": valid_pair_rows, "valid_dates": valid_dates, "key_matched_rows": key_matched_rows},
        not_run_reasons=not_run_reasons,
        alignment_report=report,
    )

    aligned = None
    if valid_pair_rows > 0 and overall != GateStatus.BLOCKED:
        out = valid_pairs[["date", "code", "factor_value", "forward_return"]].copy()
        out["horizon"] = horizon
        aligned = AlignedEvaluationData(
            factor_id=rec.factor_id,
            return_set_id=fr.return_set_id,
            horizon=horizon,
            _valid_frame=out,
            _all_matched_frame=both[both_mask][["date", "code", "factor_value", "forward_return"]].copy(),
        )

    return aligned, report, gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_report(factor_id: str, factor_type: str, value_scope: str,
                  return_set_id: str | None, horizon: str | None) -> AlignmentReport:
    return AlignmentReport(
        factor_id=factor_id, factor_type=factor_type, value_scope=value_scope,
        return_set_id=return_set_id, horizon=horizon,
    )


def _parse_horizon_int(horizon: str) -> int | None:
    try:
        return int(horizon)
    except (ValueError, TypeError):
        return None
