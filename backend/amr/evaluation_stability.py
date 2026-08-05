"""IC decay and rolling-stability statistics for AMR evaluations."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence

import numpy as np
from scipy.stats import linregress


DEFAULT_DECAY_HORIZONS = ("1d", "5d", "10d", "20d")
_NEAR_ZERO_ABS_TOL = 1e-12


class HorizonEvaluation(Protocol):
    """Minimum result contract required to build an IC decay curve."""

    horizon: str | None
    rank_ic_mean: float | None
    pearson_ic_mean: float | None


@dataclass(frozen=True)
class RollingICWindow:
    start_date: str
    end_date: str
    mean_ic: float
    ic_std: float | None
    ic_ir: float | None
    positive_ratio: float
    n_obs: int

    def to_dict(self) -> dict[str, object]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "mean_ic": self.mean_ic,
            "ic_std": self.ic_std,
            "ic_ir": self.ic_ir,
            "positive_ratio": self.positive_ratio,
            "n_obs": self.n_obs,
        }


@dataclass(frozen=True)
class ICStabilityResult:
    rolling_means: list[RollingICWindow] = field(default_factory=list)
    trend_slope: float | None = None
    trend_intercept: float | None = None
    trend_r_squared: float | None = None
    trend_pvalue: float | None = None
    first_half_mean: float | None = None
    second_half_mean: float | None = None
    split_difference: float | None = None
    n_total: int = 0
    window: int = 60
    step: int = 20
    issue_codes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rolling_means", list(self.rolling_means))
        object.__setattr__(self, "issue_codes", list(self.issue_codes))

    def to_dict(self) -> dict[str, object]:
        return {
            "rolling_means": [item.to_dict() for item in self.rolling_means],
            "trend_slope": self.trend_slope,
            "trend_intercept": self.trend_intercept,
            "trend_r_squared": self.trend_r_squared,
            "trend_pvalue": self.trend_pvalue,
            "first_half_mean": self.first_half_mean,
            "second_half_mean": self.second_half_mean,
            "split_difference": self.split_difference,
            "n_total": self.n_total,
            "window": self.window,
            "step": self.step,
            "issue_codes": list(self.issue_codes),
        }


@dataclass(frozen=True)
class ICDecayResult:
    ic_decay: dict[str, float | None]
    pearson_ic_decay: dict[str, float | None]
    issue_codes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ic_decay", dict(self.ic_decay))
        object.__setattr__(self, "pearson_ic_decay", dict(self.pearson_ic_decay))
        object.__setattr__(self, "issue_codes", list(self.issue_codes))

    def to_dict(self) -> dict[str, object]:
        return {
            "ic_decay": dict(self.ic_decay),
            "pearson_ic_decay": dict(self.pearson_ic_decay),
            "issue_codes": list(self.issue_codes),
        }


def _validate_positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _normalise_horizon(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("horizon must be a positive integer or '<N>d' string")
    if isinstance(value, int):
        days = value
    else:
        text = str(value).strip().lower()
        if text.endswith("d"):
            text = text[:-1]
        if not text.isdigit():
            raise ValueError("horizon must be a positive integer or '<N>d' string")
        days = int(text)
    if days < 1:
        raise ValueError("horizon must be positive")
    return f"{days}d"


def _finite_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def evaluate_ic_stability(
    dates: Sequence[object],
    ic_values: Sequence[float | None],
    *,
    window: int = 60,
    step: int = 20,
) -> ICStabilityResult:
    """Evaluate rolling statistics and a signed linear trend for one IC series.

    Missing and non-finite IC values are removed independently. Remaining
    observations keep chronological input order; calendar gaps are not filled
    or interpolated.
    """

    window = _validate_positive_int(window, "window")
    step = _validate_positive_int(step, "step")
    if len(dates) != len(ic_values):
        raise ValueError("dates and ic_values must have equal length")

    valid = [
        (str(date), number)
        for date, value in zip(dates, ic_values)
        if (number := _finite_or_none(value)) is not None
    ]
    n_total = len(valid)
    if n_total < window:
        return ICStabilityResult(
            n_total=n_total,
            window=window,
            step=step,
            issue_codes=["INSUFFICIENT_IC_OBSERVATIONS"],
        )

    valid_dates = [item[0] for item in valid]
    values = np.asarray([item[1] for item in valid], dtype=float)
    rolling_means: list[RollingICWindow] = []
    for start in range(0, n_total - window + 1, step):
        end = start + window
        sample = values[start:end]
        mean_ic = float(np.mean(sample))
        ic_std = float(np.std(sample, ddof=1)) if len(sample) > 1 else None
        if ic_std is not None and math.isclose(
            ic_std, 0.0, rel_tol=0.0, abs_tol=_NEAR_ZERO_ABS_TOL
        ):
            ic_std = 0.0
            ic_ir = None
        else:
            ic_ir = mean_ic / ic_std if ic_std is not None else None
        rolling_means.append(
            RollingICWindow(
                start_date=valid_dates[start],
                end_date=valid_dates[end - 1],
                mean_ic=mean_ic,
                ic_std=ic_std,
                ic_ir=ic_ir,
                positive_ratio=float(np.mean(sample > 0)),
                n_obs=len(sample),
            )
        )

    if n_total < 2:
        first_half_mean = None
        second_half_mean = None
        split_difference = None
    else:
        midpoint = n_total // 2
        first_half_mean = float(np.mean(values[:midpoint]))
        second_half_mean = float(np.mean(values[midpoint:]))
        split_difference = second_half_mean - first_half_mean
    issue_codes: list[str] = []

    full_std = float(np.std(values, ddof=1)) if n_total > 1 else 0.0
    if math.isclose(full_std, 0.0, rel_tol=0.0, abs_tol=_NEAR_ZERO_ABS_TOL):
        issue_codes.append("ZERO_IC_VARIANCE")
        trend_slope = 0.0
        trend_intercept = float(values[0])
        trend_r_squared = None
        trend_pvalue = None
    else:
        trend = linregress(np.arange(n_total, dtype=float), values)
        trend_slope = float(trend.slope)
        trend_intercept = float(trend.intercept)
        trend_r_squared = float(trend.rvalue**2)
        trend_pvalue = _finite_or_none(trend.pvalue)

    return ICStabilityResult(
        rolling_means=rolling_means,
        trend_slope=trend_slope,
        trend_intercept=trend_intercept,
        trend_r_squared=trend_r_squared,
        trend_pvalue=trend_pvalue,
        first_half_mean=first_half_mean,
        second_half_mean=second_half_mean,
        split_difference=split_difference,
        n_total=n_total,
        window=window,
        step=step,
        issue_codes=issue_codes,
    )


def evaluate_ic_decay(
    evaluations: Iterable[HorizonEvaluation],
    *,
    horizons: Sequence[object] = DEFAULT_DECAY_HORIZONS,
) -> ICDecayResult:
    """Aggregate independently evaluated horizons into signed IC decay curves."""

    requested = [_normalise_horizon(horizon) for horizon in horizons]
    if len(set(requested)) != len(requested):
        raise ValueError("horizons must be unique")

    by_horizon: dict[str, HorizonEvaluation] = {}
    for evaluation in evaluations:
        if evaluation.horizon is None:
            continue
        horizon = _normalise_horizon(evaluation.horizon)
        if horizon in by_horizon:
            raise ValueError(f"duplicate evaluation for horizon {horizon}")
        by_horizon[horizon] = evaluation

    rank_decay: dict[str, float | None] = {}
    pearson_decay: dict[str, float | None] = {}
    missing = False
    for horizon in requested:
        evaluation = by_horizon.get(horizon)
        rank_value = (
            _finite_or_none(evaluation.rank_ic_mean)
            if evaluation is not None
            else None
        )
        pearson_value = (
            _finite_or_none(evaluation.pearson_ic_mean)
            if evaluation is not None
            else None
        )
        rank_decay[horizon] = rank_value
        pearson_decay[horizon] = pearson_value
        missing = missing or rank_value is None or pearson_value is None

    valid_count = sum(value is not None for value in rank_decay.values())
    valid_count += sum(value is not None for value in pearson_decay.values())
    issue_codes: list[str] = []
    if valid_count == 0:
        issue_codes.append("NO_VALID_IC_DECAY_HORIZONS")
    elif missing:
        issue_codes.append("PARTIAL_IC_DECAY_HORIZONS")

    return ICDecayResult(
        ic_decay=rank_decay,
        pearson_ic_decay=pearson_decay,
        issue_codes=issue_codes,
    )
