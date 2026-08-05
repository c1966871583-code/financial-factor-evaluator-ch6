"""FIN-P2-F: PIT-safe next-quarter financial supporting evidence.

The module deliberately stays independent from the accepted Track-M path.  It
uses deterministic synthetic inputs to evaluate whether a small robust linear
increment improves on the same-quarter-last-year baseline for four operating
targets.  The newest test partition is consumed once and is never used for
model, feature, threshold, direction, or interval selection.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


P2_F_SCHEMA_VERSION = "FinancialP2FEvidence-v1.0"
P2_F_AUDIT_SCHEMA_VERSION = "FinancialP2FEvidenceAudit-v1.0"
P2_F_TARGET_SCHEMA_VERSION = "FinancialP2FTargetEvidence-v1.0"
P2_F_PREDICTION_SCHEMA_VERSION = "FinancialP2FPrediction-v1.0"
P2_F_HASH_CONTRACT_VERSION = "FIN-P2-F-HASH-v1.0"
P2_F_POLICY_VERSION = "FIN-P2-F-POLICY-v1.0"
P2_F_VALIDATION_TRACK = "F"
P2_F_EVIDENCE_PRIORITY = "supporting"
P2_F_MODEL = "robust_linear_incremental"
P2_F_BASELINE = "same_quarter_last_year"
P2_F_SPLIT = (0.60, 0.20, 0.20)
P2_F_INTERVAL_LEVEL = 0.80
P2_F_MIN_CALIBRATION_RESIDUALS = 20
P2_F_TARGETS = (
    "next_quarter_revenue",
    "next_quarter_parent_net_profit",
    "next_quarter_operating_cash_flow",
    "next_quarter_gross_margin",
)

_TARGET_COLUMNS = {
    "next_quarter_revenue": "revenue",
    "next_quarter_parent_net_profit": "parent_net_profit",
    "next_quarter_operating_cash_flow": "operating_cash_flow",
    "next_quarter_gross_margin": "gross_margin",
}
_AMOUNT_TARGETS = frozenset(P2_F_TARGETS[:3])
_REQUIRED_COLUMNS = (
    "symbol",
    "report_period",
    "announced_at",
    "version_at",
    "revenue",
    "parent_net_profit",
    "operating_cash_flow",
    "operating_cost",
    "total_assets",
    "total_liabilities",
    "equity",
)
_NUMERIC_COLUMNS = (
    "revenue",
    "parent_net_profit",
    "operating_cash_flow",
    "operating_cost",
    "total_assets",
    "total_liabilities",
    "equity",
)
_FEATURE_NAMES = (
    "current_target_scaled",
    "current_target_yoy_delta_scaled",
    "revenue_yoy_delta_scaled",
    "profit_margin",
    "cash_margin",
    "gross_margin",
    "leverage",
    "quarter_q2",
    "quarter_q3",
    "quarter_q4",
)


class P2FGateStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class P2FTargetStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"


class P2FErrorCode(str, Enum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_FORECAST_BATCH = "INVALID_FORECAST_BATCH"
    NON_SYNTHETIC_INPUT = "NON_SYNTHETIC_INPUT"
    MISSING_COLUMN = "MISSING_COLUMN"
    INVALID_TEXT = "INVALID_TEXT"
    INVALID_DATE = "INVALID_DATE"
    INVALID_NUMERIC = "INVALID_NUMERIC"
    NON_POSITIVE_SCALE = "NON_POSITIVE_SCALE"
    VERSION_BEFORE_ANNOUNCEMENT = "VERSION_BEFORE_ANNOUNCEMENT"
    DUPLICATE_VERSION_KEY = "DUPLICATE_VERSION_KEY"
    INSUFFICIENT_PERIODS = "INSUFFICIENT_PERIODS"
    INSUFFICIENT_TRAINING = "INSUFFICIENT_TRAINING"
    INPUT_MUTATED = "INPUT_MUTATED"


@dataclass(frozen=True)
class FinancialP2FForecastBatch:
    dataset_id: str
    version: str
    source: str
    _frame: pd.DataFrame
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        _required_text(self.dataset_id, "dataset_id")
        _required_text(self.version, "version")
        _required_text(self.source, "source")
        if not isinstance(self._frame, pd.DataFrame):
            raise TypeError("_frame must be a pandas DataFrame")
        if not isinstance(self.provenance, Mapping):
            raise TypeError("provenance must be a mapping")
        object.__setattr__(self, "_frame", self._frame.copy(deep=True))
        object.__setattr__(self, "provenance", dict(self.provenance))

    def get_frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)


@dataclass(frozen=True)
class FinancialP2FEvidenceConfig:
    as_of: str
    minimum_training_rows: int = 40
    minimum_training_periods: int = 5
    train_fraction: float = P2_F_SPLIT[0]
    calibration_fraction: float = P2_F_SPLIT[1]
    test_fraction: float = P2_F_SPLIT[2]
    interval_level: float = P2_F_INTERVAL_LEVEL
    minimum_calibration_residuals: int = P2_F_MIN_CALIBRATION_RESIDUALS
    validation_track: str = P2_F_VALIDATION_TRACK
    evidence_priority: str = P2_F_EVIDENCE_PRIORITY
    baseline: str = P2_F_BASELINE
    model: str = P2_F_MODEL
    test_selection_policy: str = "one_shot_no_test_tuning"
    m_replacement_allowed: bool = False
    stock_price_forecast_allowed: bool = False
    investment_advice_allowed: bool = False
    synthetic_test_only: bool = True
    schema_version: str = P2_F_SCHEMA_VERSION
    policy_version: str = P2_F_POLICY_VERSION

    def __post_init__(self) -> None:
        as_of = _parse_timestamp(self.as_of, "as_of")
        object.__setattr__(self, "as_of", as_of.isoformat())
        if isinstance(self.minimum_training_rows, bool) or (
            not isinstance(self.minimum_training_rows, int)
            or self.minimum_training_rows < 1
        ):
            raise ValueError("minimum_training_rows must be a positive integer")
        if isinstance(self.minimum_training_periods, bool) or (
            not isinstance(self.minimum_training_periods, int)
            or self.minimum_training_periods < 2
        ):
            raise ValueError(
                "minimum_training_periods must be an integer >= 2"
            )
        frozen = {
            "train_fraction": (self.train_fraction, P2_F_SPLIT[0]),
            "calibration_fraction": (
                self.calibration_fraction,
                P2_F_SPLIT[1],
            ),
            "test_fraction": (self.test_fraction, P2_F_SPLIT[2]),
            "interval_level": (
                self.interval_level,
                P2_F_INTERVAL_LEVEL,
            ),
            "minimum_calibration_residuals": (
                self.minimum_calibration_residuals,
                P2_F_MIN_CALIBRATION_RESIDUALS,
            ),
            "validation_track": (
                self.validation_track,
                P2_F_VALIDATION_TRACK,
            ),
            "evidence_priority": (
                self.evidence_priority,
                P2_F_EVIDENCE_PRIORITY,
            ),
            "baseline": (self.baseline, P2_F_BASELINE),
            "model": (self.model, P2_F_MODEL),
            "test_selection_policy": (
                self.test_selection_policy,
                "one_shot_no_test_tuning",
            ),
            "m_replacement_allowed": (
                self.m_replacement_allowed,
                False,
            ),
            "stock_price_forecast_allowed": (
                self.stock_price_forecast_allowed,
                False,
            ),
            "investment_advice_allowed": (
                self.investment_advice_allowed,
                False,
            ),
            "synthetic_test_only": (self.synthetic_test_only, True),
            "schema_version": (
                self.schema_version,
                P2_F_SCHEMA_VERSION,
            ),
            "policy_version": (
                self.policy_version,
                P2_F_POLICY_VERSION,
            ),
        }
        for field_name, (actual, expected) in frozen.items():
            if actual != expected:
                raise ValueError(f"{field_name} must be frozen at {expected}")

    def to_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class P2FIssue:
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
class FinancialP2FPrediction:
    symbol: str
    feature_report_period: str
    target_report_period: str
    target: str
    actual: float
    prediction: float
    baseline_current: float
    interval_low_80: float | None
    interval_high_80: float | None
    model: str
    reliability: str
    as_of: str
    feature_visible_at: str
    label_available_at: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class FinancialP2FTargetEvidence:
    target: str
    validation_track: str
    evidence_priority: str
    baseline: str
    model: str
    status: str
    train_periods: tuple[str, ...]
    calibration_periods: tuple[str, ...]
    test_periods: tuple[str, ...]
    train_count: int
    calibration_count: int
    test_count: int
    oos_mae: float
    baseline_mae: float
    relative_mae_improvement: float | None
    residual_rank_ic: float | None
    evaluated_rank_ic_periods: int
    improvement_positive_period_ratio: float | None
    direction_stability: str
    calibration_residual_count: int
    interval_level: float
    interval_status: str
    interval_half_width: float | None
    interval_coverage: float | None
    reliability: str
    test_selection_policy: str
    predictions: tuple[FinancialP2FPrediction, ...]
    feature_names: tuple[str, ...]
    model_fingerprint: str
    split_fingerprint: str
    schema_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["train_periods"] = list(self.train_periods)
        values["calibration_periods"] = list(
            self.calibration_periods
        )
        values["test_periods"] = list(self.test_periods)
        values["predictions"] = [
            item.to_dict() for item in self.predictions
        ]
        values["feature_names"] = list(self.feature_names)
        return values


@dataclass(frozen=True)
class FinancialP2FEvidenceAudit:
    gate_status: str
    errors: tuple[P2FIssue, ...]
    warnings: tuple[P2FIssue, ...]
    target_ids: tuple[str, ...]
    raw_row_count: int
    globally_visible_row_count: int
    selected_sample_count: int
    excluded_after_as_of_count: int
    version_selection_policy: str
    next_quarter_policy: str
    input_fingerprint: str
    selected_input_fingerprint: str
    configuration_fingerprint: str
    output_fingerprint: str
    validation_track: str
    evidence_priority: str
    m_replacement_allowed: bool
    synthetic_test_only: bool
    schema_version: str
    audit_schema_version: str
    hash_contract_version: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        values["errors"] = [item.to_dict() for item in self.errors]
        values["warnings"] = [item.to_dict() for item in self.warnings]
        values["target_ids"] = list(self.target_ids)
        return values


@dataclass(frozen=True)
class FinancialP2FEvidenceResult:
    target_evidence: tuple[FinancialP2FTargetEvidence, ...]
    evidence_audit: FinancialP2FEvidenceAudit

    def get_target(self, target: Any) -> FinancialP2FTargetEvidence:
        normalized = _required_text(target, "target")
        matches = [
            item for item in self.target_evidence
            if item.target == normalized
        ]
        if len(matches) != 1:
            raise LookupError(f"expected one evidence result for {normalized}")
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_evidence": [
                item.to_dict() for item in self.target_evidence
            ],
            "evidence_audit": self.evidence_audit.to_dict(),
        }


@dataclass(frozen=True)
class _RobustModel:
    location: np.ndarray
    scale: np.ndarray
    coefficients: np.ndarray


def evaluate_financial_p2_f_evidence(
    batch: FinancialP2FForecastBatch,
    *,
    configuration: FinancialP2FEvidenceConfig,
) -> FinancialP2FEvidenceResult:
    """Evaluate four next-quarter targets as Track-F supporting evidence."""

    validation_errors = _validate_top_level(batch, configuration)
    if validation_errors:
        return _blocked_result(validation_errors, batch, configuration)

    raw = batch.get_frame()
    before = _hash(
        "financial_p2_f_input_guard",
        {
            "frame": _frame_records(raw),
            "provenance": batch.provenance,
            "configuration": configuration.to_dict(),
        },
    )
    normalized, excluded, errors = _normalize_frame(
        raw, pd.Timestamp(configuration.as_of)
    )
    if errors:
        return _blocked_result(
            errors,
            batch,
            configuration,
            raw_count=len(raw),
            visible_count=len(normalized),
            excluded_count=excluded,
        )

    sample_frames: dict[str, pd.DataFrame] = {}
    for target in P2_F_TARGETS:
        sample_frames[target] = _build_target_samples(
            normalized, target, pd.Timestamp(configuration.as_of)
        )
    periods = sorted(
        {
            str(period)
            for frame in sample_frames.values()
            for period in frame["target_report_period"].unique()
        }
    )
    if len(periods) < 5:
        return _blocked_result(
            [
                _issue(
                    P2FErrorCode.INSUFFICIENT_PERIODS,
                    "at least five target quarters are required for 60/20/20",
                    "target_report_period",
                )
            ],
            batch,
            configuration,
            raw_count=len(raw),
            visible_count=len(normalized),
            excluded_count=excluded,
        )
    train_periods, calibration_periods, test_periods = _split_periods(
        periods
    )
    if len(train_periods) < configuration.minimum_training_periods:
        return _blocked_result(
            [
                _issue(
                    P2FErrorCode.INSUFFICIENT_PERIODS,
                    "training partition has too few distinct quarters",
                    "target_report_period",
                )
            ],
            batch,
            configuration,
            raw_count=len(raw),
            visible_count=len(normalized),
            excluded_count=excluded,
        )

    evidence: list[FinancialP2FTargetEvidence] = []
    warnings: list[P2FIssue] = []
    for target in P2_F_TARGETS:
        target_result, target_warning = _evaluate_target(
            sample_frames[target],
            target,
            train_periods,
            calibration_periods,
            test_periods,
            configuration,
        )
        if target_result is None:
            return _blocked_result(
                [
                    _issue(
                        P2FErrorCode.INSUFFICIENT_TRAINING,
                        f"{target} does not satisfy frozen sample minima",
                        target,
                    )
                ],
                batch,
                configuration,
                raw_count=len(raw),
                visible_count=len(normalized),
                excluded_count=excluded,
            )
        evidence.append(target_result)
        if target_warning is not None:
            warnings.append(target_warning)

    after = _hash(
        "financial_p2_f_input_guard",
        {
            "frame": _frame_records(batch.get_frame()),
            "provenance": batch.provenance,
            "configuration": configuration.to_dict(),
        },
    )
    if before != after:
        return _blocked_result(
            [
                _issue(
                    P2FErrorCode.INPUT_MUTATED,
                    "forecast input changed during evidence construction",
                    "batch",
                )
            ],
            batch,
            configuration,
            raw_count=len(raw),
            visible_count=len(normalized),
            excluded_count=excluded,
        )

    selected_fingerprint = _hash(
        "financial_p2_f_selected_inputs",
        {
            target: _frame_records(sample_frames[target])
            for target in P2_F_TARGETS
        },
    )
    output_fingerprint = _hash(
        "financial_p2_f_outputs",
        [item.to_dict() for item in evidence],
    )
    audit = _build_audit(
        status=P2FGateStatus.READY,
        errors=(),
        warnings=tuple(warnings),
        batch=batch,
        configuration=configuration,
        raw_count=len(raw),
        visible_count=len(normalized),
        sample_count=sum(len(frame) for frame in sample_frames.values()),
        excluded_count=excluded,
        selected_fingerprint=selected_fingerprint,
        output_fingerprint=output_fingerprint,
    )
    return FinancialP2FEvidenceResult(tuple(evidence), audit)


def _evaluate_target(
    samples: pd.DataFrame,
    target: str,
    train_periods: tuple[str, ...],
    calibration_periods: tuple[str, ...],
    test_periods: tuple[str, ...],
    configuration: FinancialP2FEvidenceConfig,
) -> tuple[FinancialP2FTargetEvidence | None, P2FIssue | None]:
    partitions = {
        "train": samples[
            samples["target_report_period"].isin(train_periods)
        ].copy(),
        "calibration": samples[
            samples["target_report_period"].isin(calibration_periods)
        ].copy(),
        "test": samples[
            samples["target_report_period"].isin(test_periods)
        ].copy(),
    }
    if (
        len(partitions["train"]) < configuration.minimum_training_rows
        or any(frame.empty for frame in partitions.values())
    ):
        return None, None

    train = partitions["train"]
    model = _fit_robust_linear(
        train.loc[:, _FEATURE_NAMES].to_numpy(dtype=float),
        train["target_increment_scaled"].to_numpy(dtype=float),
    )
    calibration_prediction = _restore_prediction(
        partitions["calibration"],
        _predict_robust(
            model,
            partitions["calibration"]
            .loc[:, _FEATURE_NAMES]
            .to_numpy(dtype=float),
        ),
        target,
    )
    test_prediction = _restore_prediction(
        partitions["test"],
        _predict_robust(
            model,
            partitions["test"]
            .loc[:, _FEATURE_NAMES]
            .to_numpy(dtype=float),
        ),
        target,
    )
    calibration_residuals = (
        partitions["calibration"]["actual"].to_numpy(dtype=float)
        - calibration_prediction
    )
    interval_available = (
        len(calibration_residuals)
        >= configuration.minimum_calibration_residuals
    )
    half_width = (
        float(
            np.quantile(
                np.abs(calibration_residuals),
                configuration.interval_level,
                method="higher",
            )
        )
        if interval_available
        else None
    )
    actual = partitions["test"]["actual"].to_numpy(dtype=float)
    baseline = partitions["test"]["baseline"].to_numpy(dtype=float)
    model_abs_error = np.abs(actual - test_prediction)
    baseline_abs_error = np.abs(actual - baseline)
    oos_mae = float(model_abs_error.mean())
    baseline_mae = float(baseline_abs_error.mean())
    improvement = (
        float((baseline_mae - oos_mae) / baseline_mae)
        if baseline_mae > 0
        else None
    )
    rank_values = []
    period_improvements = []
    test_with_prediction = partitions["test"].copy()
    test_with_prediction["prediction"] = test_prediction
    for _, period_frame in test_with_prediction.groupby(
        "target_report_period", sort=True
    ):
        actual_increment = (
            period_frame["actual"] - period_frame["baseline"]
        )
        predicted_increment = (
            period_frame["prediction"] - period_frame["baseline"]
        )
        if (
            actual_increment.nunique() > 1
            and predicted_increment.nunique() > 1
        ):
            correlation = spearmanr(
                predicted_increment.to_numpy(dtype=float),
                actual_increment.to_numpy(dtype=float),
            ).statistic
            if math.isfinite(float(correlation)):
                rank_values.append(float(correlation))
        model_period_mae = float(
            np.abs(
                period_frame["actual"] - period_frame["prediction"]
            ).mean()
        )
        baseline_period_mae = float(
            np.abs(
                period_frame["actual"] - period_frame["baseline"]
            ).mean()
        )
        period_improvements.append(baseline_period_mae - model_period_mae)
    positive_ratio = (
        float(sum(item > 0 for item in period_improvements))
        / len(period_improvements)
        if period_improvements
        else None
    )
    direction = _direction_stability(period_improvements)
    residual_rank_ic = (
        float(np.mean(rank_values)) if rank_values else None
    )
    reliability = _reliability(
        target, len(calibration_residuals), improvement
    )
    prediction_rows = []
    ordered = test_with_prediction.sort_values(
        ["target_report_period", "symbol"], kind="mergesort"
    )
    for row in ordered.to_dict(orient="records"):
        low = (
            float(row["prediction"] - half_width)
            if half_width is not None
            else None
        )
        high = (
            float(row["prediction"] + half_width)
            if half_width is not None
            else None
        )
        fields = {
            "symbol": row["symbol"],
            "feature_report_period": row["feature_report_period"],
            "target_report_period": row["target_report_period"],
            "target": target,
            "actual": float(row["actual"]),
            "prediction": float(row["prediction"]),
            "baseline_current": float(row["baseline"]),
            "interval_low_80": low,
            "interval_high_80": high,
            "model": P2_F_MODEL,
            "reliability": reliability,
            "as_of": configuration.as_of,
            "feature_visible_at": row["feature_visible_at"],
            "label_available_at": row["label_available_at"],
            "schema_version": P2_F_PREDICTION_SCHEMA_VERSION,
        }
        prediction_rows.append(
            FinancialP2FPrediction(
                **fields,
                content_hash=_hash("financial_p2_f_prediction", fields),
            )
        )
    coverage = (
        float(
            np.mean(
                (actual >= test_prediction - half_width)
                & (actual <= test_prediction + half_width)
            )
        )
        if half_width is not None
        else None
    )
    model_fingerprint = _hash(
        "financial_p2_f_model",
        {
            "target": target,
            "feature_names": _FEATURE_NAMES,
            "location": model.location.tolist(),
            "scale": model.scale.tolist(),
            "coefficients": model.coefficients.tolist(),
            "training_rows": _frame_records(train),
        },
    )
    split_fingerprint = _hash(
        "financial_p2_f_split",
        {
            "train": train_periods,
            "calibration": calibration_periods,
            "test": test_periods,
        },
    )
    fields = {
        "target": target,
        "validation_track": P2_F_VALIDATION_TRACK,
        "evidence_priority": P2_F_EVIDENCE_PRIORITY,
        "baseline": P2_F_BASELINE,
        "model": P2_F_MODEL,
        "status": (
            P2FTargetStatus.COMPLETED.value
            if interval_available
            else P2FTargetStatus.PARTIAL.value
        ),
        "train_periods": train_periods,
        "calibration_periods": calibration_periods,
        "test_periods": test_periods,
        "train_count": len(partitions["train"]),
        "calibration_count": len(partitions["calibration"]),
        "test_count": len(partitions["test"]),
        "oos_mae": oos_mae,
        "baseline_mae": baseline_mae,
        "relative_mae_improvement": improvement,
        "residual_rank_ic": residual_rank_ic,
        "evaluated_rank_ic_periods": len(rank_values),
        "improvement_positive_period_ratio": positive_ratio,
        "direction_stability": direction,
        "calibration_residual_count": len(calibration_residuals),
        "interval_level": configuration.interval_level,
        "interval_status": (
            "calibrated"
            if interval_available
            else "not_run_insufficient_calibration_residuals"
        ),
        "interval_half_width": half_width,
        "interval_coverage": coverage,
        "reliability": reliability,
        "test_selection_policy": configuration.test_selection_policy,
        "predictions": tuple(prediction_rows),
        "feature_names": _FEATURE_NAMES,
        "model_fingerprint": model_fingerprint,
        "split_fingerprint": split_fingerprint,
        "schema_version": P2_F_TARGET_SCHEMA_VERSION,
    }
    result = FinancialP2FTargetEvidence(
        **fields,
        content_hash=_hash("financial_p2_f_target_evidence", fields),
    )
    warning = (
        None
        if interval_available
        else P2FIssue(
            code="INTERVAL_NOT_RUN_INSUFFICIENT_CALIBRATION",
            message=(
                f"{target} has fewer than "
                f"{configuration.minimum_calibration_residuals} "
                "calibration residuals"
            ),
            field_name=target,
        )
    )
    return result, warning


def _normalize_frame(
    raw: pd.DataFrame,
    as_of: pd.Timestamp,
) -> tuple[pd.DataFrame, int, list[P2FIssue]]:
    errors: list[P2FIssue] = []
    missing = [column for column in _REQUIRED_COLUMNS if column not in raw]
    if missing:
        return (
            pd.DataFrame(),
            0,
            [
                _issue(
                    P2FErrorCode.MISSING_COLUMN,
                    f"missing required column: {column}",
                    column,
                )
                for column in missing
            ],
        )
    frame = raw.loc[:, _REQUIRED_COLUMNS].copy()
    for column in ("report_period", "announced_at", "version_at"):
        parsed = pd.to_datetime(
            frame[column], errors="coerce", format="mixed"
        )
        if parsed.isna().any():
            errors.append(
                _issue(
                    P2FErrorCode.INVALID_DATE,
                    f"{column} contains an invalid date",
                    column,
                )
            )
        frame[column] = parsed
    symbols = frame["symbol"].astype("string").str.strip()
    if symbols.isna().any() or (symbols == "").any():
        errors.append(
            _issue(
                P2FErrorCode.INVALID_TEXT,
                "symbol must be non-empty text",
                "symbol",
            )
        )
    frame["symbol"] = symbols
    for column in _NUMERIC_COLUMNS:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.isna().any() or not np.isfinite(numeric).all():
            errors.append(
                _issue(
                    P2FErrorCode.INVALID_NUMERIC,
                    f"{column} must contain finite numeric values",
                    column,
                )
            )
        frame[column] = numeric.astype(float)
    if errors:
        return pd.DataFrame(), 0, _deduplicate(errors)
    invalid_period = (
        frame["report_period"].dt.normalize()
        != frame["report_period"].dt.to_period("Q").dt.end_time.dt.normalize()
    )
    if invalid_period.any():
        errors.append(
            _issue(
                P2FErrorCode.INVALID_DATE,
                "report_period must be a natural quarter end",
                "report_period",
            )
        )
    if (frame["version_at"] < frame["announced_at"]).any():
        errors.append(
            _issue(
                P2FErrorCode.VERSION_BEFORE_ANNOUNCEMENT,
                "version_at cannot precede announced_at",
                "version_at",
            )
        )
    if (frame["total_assets"] <= 0).any() or (frame["revenue"] == 0).any():
        errors.append(
            _issue(
                P2FErrorCode.NON_POSITIVE_SCALE,
                "total_assets must be positive and revenue non-zero",
                "total_assets",
            )
        )
    duplicate = frame.duplicated(
        ["symbol", "report_period", "version_at"], keep=False
    )
    if duplicate.any():
        errors.append(
            _issue(
                P2FErrorCode.DUPLICATE_VERSION_KEY,
                "symbol/report_period/version_at must be unique",
                "version_at",
            )
        )
    if errors:
        return pd.DataFrame(), 0, _deduplicate(errors)
    visible = (
        (frame["announced_at"] <= as_of)
        & (frame["version_at"] <= as_of)
    )
    excluded = int((~visible).sum())
    frame = frame.loc[visible].copy()
    frame["report_period"] = frame["report_period"].dt.to_period("Q")
    frame["gross_margin"] = (
        (frame["revenue"] - frame["operating_cost"])
        / frame["revenue"]
    )
    frame = frame.sort_values(
        ["symbol", "report_period", "version_at"], kind="mergesort"
    ).reset_index(drop=True)
    return frame, excluded, []


def _build_target_samples(
    versions: pd.DataFrame,
    target: str,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    column = _TARGET_COLUMNS[target]
    records = []
    for symbol, symbol_frame in versions.groupby("symbol", sort=True):
        by_period = {
            period: group.sort_values("version_at", kind="mergesort")
            for period, group in symbol_frame.groupby(
                "report_period", sort=True
            )
        }
        for feature_period in sorted(by_period):
            target_period = feature_period + 1
            baseline_period = target_period - 4
            current_yoy_period = feature_period - 4
            required = (
                target_period,
                baseline_period,
                current_yoy_period,
            )
            if any(period not in by_period for period in required):
                continue
            current_versions = by_period[feature_period]
            origin = current_versions["version_at"].min()
            current = _latest_visible(current_versions, origin)
            baseline = _latest_visible(by_period[baseline_period], origin)
            current_yoy = _latest_visible(
                by_period[current_yoy_period], origin
            )
            target_row = _latest_visible(by_period[target_period], as_of)
            if any(
                item is None
                for item in (current, baseline, current_yoy, target_row)
            ):
                continue
            assert current is not None
            assert baseline is not None
            assert current_yoy is not None
            assert target_row is not None
            actual = float(target_row[column])
            baseline_value = float(baseline[column])
            assets = float(current["total_assets"])
            scale = assets if target in _AMOUNT_TARGETS else 1.0
            quarter = int(target_period.quarter)
            current_target = float(current[column])
            prior_current_target = float(current_yoy[column])
            records.append(
                {
                    "symbol": str(symbol),
                    "feature_report_period": str(feature_period),
                    "target_report_period": str(target_period),
                    "feature_visible_at": _iso(current["version_at"]),
                    "label_available_at": _iso(
                        target_row["version_at"]
                    ),
                    "actual": actual,
                    "baseline": baseline_value,
                    "restore_scale": scale,
                    "target_increment_scaled": (
                        actual - baseline_value
                    ) / scale,
                    "current_target_scaled": current_target / scale,
                    "current_target_yoy_delta_scaled": (
                        current_target - prior_current_target
                    ) / scale,
                    "revenue_yoy_delta_scaled": (
                        float(current["revenue"])
                        - float(current_yoy["revenue"])
                    ) / assets,
                    "profit_margin": (
                        float(current["parent_net_profit"])
                        / float(current["revenue"])
                    ),
                    "cash_margin": (
                        float(current["operating_cash_flow"])
                        / float(current["revenue"])
                    ),
                    "gross_margin": float(current["gross_margin"]),
                    "leverage": (
                        float(current["total_liabilities"]) / assets
                    ),
                    "quarter_q2": float(quarter == 2),
                    "quarter_q3": float(quarter == 3),
                    "quarter_q4": float(quarter == 4),
                }
            )
    return pd.DataFrame(records).sort_values(
        ["target_report_period", "symbol"], kind="mergesort"
    ).reset_index(drop=True)


def _latest_visible(
    frame: pd.DataFrame,
    cutoff: pd.Timestamp,
) -> pd.Series | None:
    visible = frame[
        (frame["announced_at"] <= cutoff)
        & (frame["version_at"] <= cutoff)
    ]
    if visible.empty:
        return None
    return visible.sort_values("version_at", kind="mergesort").iloc[-1]


def _split_periods(
    periods: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    count = len(periods)
    train_end = max(1, int(math.floor(count * P2_F_SPLIT[0])))
    calibration_end = max(
        train_end + 1,
        int(math.floor(count * (P2_F_SPLIT[0] + P2_F_SPLIT[1]))),
    )
    calibration_end = min(calibration_end, count - 1)
    return (
        tuple(periods[:train_end]),
        tuple(periods[train_end:calibration_end]),
        tuple(periods[calibration_end:]),
    )


def _fit_robust_linear(x: np.ndarray, y: np.ndarray) -> _RobustModel:
    location = np.median(x, axis=0)
    scale = np.median(np.abs(x - location), axis=0) * 1.4826
    scale = np.where(scale > 1e-12, scale, 1.0)
    standardized = (x - location) / scale
    design = np.column_stack([np.ones(len(x)), standardized])
    ridge = np.eye(design.shape[1]) * 1e-8
    ridge[0, 0] = 0.0
    weights = np.ones(len(y))
    coefficients = np.zeros(design.shape[1])
    for _ in range(50):
        weighted = design * weights[:, None]
        next_coefficients = np.linalg.solve(
            design.T @ weighted + ridge,
            design.T @ (weights * y),
        )
        residual = y - design @ next_coefficients
        residual_scale = (
            float(np.median(np.abs(residual))) / 0.6744897501960817
        )
        if residual_scale <= 1e-12:
            coefficients = next_coefficients
            break
        cutoff = 1.345 * residual_scale
        absolute = np.abs(residual)
        next_weights = np.ones(len(y))
        mask = absolute > cutoff
        next_weights[mask] = cutoff / absolute[mask]
        converged = np.max(np.abs(next_coefficients - coefficients)) < 1e-12
        coefficients = next_coefficients
        weights = next_weights
        if converged:
            break
    return _RobustModel(location, scale, coefficients)


def _predict_robust(model: _RobustModel, x: np.ndarray) -> np.ndarray:
    standardized = (x - model.location) / model.scale
    design = np.column_stack([np.ones(len(x)), standardized])
    return design @ model.coefficients


def _restore_prediction(
    frame: pd.DataFrame,
    predicted_increment_scaled: np.ndarray,
    target: str,
) -> np.ndarray:
    scale = (
        frame["restore_scale"].to_numpy(dtype=float)
        if target in _AMOUNT_TARGETS
        else np.ones(len(frame))
    )
    return (
        frame["baseline"].to_numpy(dtype=float)
        + predicted_increment_scaled * scale
    )


def _direction_stability(improvements: Sequence[float]) -> str:
    if not improvements:
        return "insufficient"
    signs = {1 if item > 0 else -1 if item < 0 else 0 for item in improvements}
    if signs == {1}:
        return "consistent_positive"
    if signs == {-1}:
        return "consistent_negative"
    if signs == {0}:
        return "flat"
    return "mixed"


def _reliability(
    target: str,
    calibration_count: int,
    improvement: float | None,
) -> str:
    if (
        target in {
            "next_quarter_operating_cash_flow",
            "next_quarter_gross_margin",
        }
        and calibration_count >= 100
        and improvement is not None
        and improvement > 0.05
    ):
        return "reliable_research"
    return "experimental"


def _validate_top_level(
    batch: Any,
    configuration: Any,
) -> list[P2FIssue]:
    if not isinstance(configuration, FinancialP2FEvidenceConfig):
        return [
            _issue(
                P2FErrorCode.INVALID_CONFIGURATION,
                "configuration must be FinancialP2FEvidenceConfig",
                "configuration",
            )
        ]
    if not isinstance(batch, FinancialP2FForecastBatch):
        return [
            _issue(
                P2FErrorCode.INVALID_FORECAST_BATCH,
                "batch must be FinancialP2FForecastBatch",
                "batch",
            )
        ]
    if batch.provenance.get("synthetic_test_only") is not True:
        return [
            _issue(
                P2FErrorCode.NON_SYNTHETIC_INPUT,
                "FIN-P2-F authorization accepts synthetic inputs only",
                "provenance.synthetic_test_only",
            )
        ]
    return []


def _blocked_result(
    errors: Sequence[P2FIssue],
    batch: Any,
    configuration: Any,
    *,
    raw_count: int = 0,
    visible_count: int = 0,
    excluded_count: int = 0,
) -> FinancialP2FEvidenceResult:
    valid_batch = (
        batch if isinstance(batch, FinancialP2FForecastBatch) else None
    )
    valid_config = (
        configuration
        if isinstance(configuration, FinancialP2FEvidenceConfig)
        else None
    )
    audit = _build_audit(
        status=P2FGateStatus.BLOCKED,
        errors=tuple(_deduplicate(errors)),
        warnings=(),
        batch=valid_batch,
        configuration=valid_config,
        raw_count=raw_count,
        visible_count=visible_count,
        sample_count=0,
        excluded_count=excluded_count,
        selected_fingerprint=_hash("empty", []),
        output_fingerprint=_hash("empty", []),
    )
    return FinancialP2FEvidenceResult((), audit)


def _build_audit(
    *,
    status: P2FGateStatus,
    errors: tuple[P2FIssue, ...],
    warnings: tuple[P2FIssue, ...],
    batch: FinancialP2FForecastBatch | None,
    configuration: FinancialP2FEvidenceConfig | None,
    raw_count: int,
    visible_count: int,
    sample_count: int,
    excluded_count: int,
    selected_fingerprint: str,
    output_fingerprint: str,
) -> FinancialP2FEvidenceAudit:
    input_fingerprint = _hash(
        "financial_p2_f_input",
        (
            {
                "dataset_id": batch.dataset_id,
                "version": batch.version,
                "source": batch.source,
                "frame": _frame_records(batch.get_frame()),
                "provenance": batch.provenance,
            }
            if batch is not None
            else {"batch": "invalid"}
        ),
    )
    configuration_fingerprint = _hash(
        "financial_p2_f_configuration",
        (
            configuration.to_dict()
            if configuration is not None
            else {"configuration": "invalid"}
        ),
    )
    fields = {
        "gate_status": status.value,
        "errors": errors,
        "warnings": warnings,
        "target_ids": P2_F_TARGETS,
        "raw_row_count": raw_count,
        "globally_visible_row_count": visible_count,
        "selected_sample_count": sample_count,
        "excluded_after_as_of_count": excluded_count,
        "version_selection_policy": (
            "feature_and_baseline_latest_visible_at_feature_origin;"
            "label_latest_visible_at_global_as_of"
        ),
        "next_quarter_policy": "same_symbol_strict_next_natural_quarter",
        "input_fingerprint": input_fingerprint,
        "selected_input_fingerprint": selected_fingerprint,
        "configuration_fingerprint": configuration_fingerprint,
        "output_fingerprint": output_fingerprint,
        "validation_track": P2_F_VALIDATION_TRACK,
        "evidence_priority": P2_F_EVIDENCE_PRIORITY,
        "m_replacement_allowed": False,
        "synthetic_test_only": True,
        "schema_version": P2_F_SCHEMA_VERSION,
        "audit_schema_version": P2_F_AUDIT_SCHEMA_VERSION,
        "hash_contract_version": P2_F_HASH_CONTRACT_VERSION,
    }
    return FinancialP2FEvidenceAudit(
        **fields,
        content_hash=_hash("financial_p2_f_audit", fields),
    )


def _issue(
    code: P2FErrorCode,
    message: str,
    field_name: str | None = None,
    record_key: str | None = None,
) -> P2FIssue:
    return P2FIssue(code.value, message, field_name, record_key)


def _deduplicate(issues: Sequence[P2FIssue]) -> list[P2FIssue]:
    unique = {
        (item.code, item.message, item.field_name, item.record_key): item
        for item in issues
    }
    return [
        unique[key]
        for key in sorted(
            unique,
            key=lambda value: tuple(
                "" if item is None else item for item in value
            ),
        )
    ]


def _parse_timestamp(value: Any, field_name: str) -> pd.Timestamp:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} is required")
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"{field_name} must be a valid timestamp")
    return pd.Timestamp(parsed)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} is required")
    return value.strip()


def _iso(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = [
        {
            str(key): _canonical(value)
            for key, value in sorted(row.items())
        }
        for row in frame.to_dict(orient="records")
    ]
    return sorted(
        records,
        key=lambda item: json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
    )


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _canonical(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _canonical(item)
            for key, item in value.__dict__.items()
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(
                value.items(), key=lambda pair: str(pair[0])
            )
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_canonical(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is pd.NA:
        return None
    if isinstance(value, np.ndarray):
        return [_canonical(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError("non-finite value cannot enter audit hash")
        if value == 0:
            return 0.0
    return value


def _hash(domain: str, value: Any) -> str:
    payload = {
        "domain": domain,
        "hash_contract_version": P2_F_HASH_CONTRACT_VERSION,
        "value": _canonical(value),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
