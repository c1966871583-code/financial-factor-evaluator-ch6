"""P0-4B-STEP4: Quantile and long-short return evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


@dataclass(frozen=True)
class DailyGroupReturnResult:
    date: str
    sample_size: int
    quantile_returns: dict[str, float] = field(default_factory=dict)
    long_short_return: float | None = None
    evaluated: bool = False
    issue_codes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantile_returns", dict(self.quantile_returns))
        object.__setattr__(self, "issue_codes", list(self.issue_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "sample_size": self.sample_size,
            "quantile_returns": dict(self.quantile_returns),
            "long_short_return": self.long_short_return,
            "evaluated": self.evaluated,
            "issue_codes": list(self.issue_codes),
        }


@dataclass(frozen=True)
class GroupReturnSummary:
    quantiles: int
    quantile_returns: dict[str, float] = field(default_factory=dict)
    long_short_mean: float | None = None
    monotonicity_spearman: float | None = None
    daily_group_returns: list[DailyGroupReturnResult] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantile_returns", dict(self.quantile_returns))
        object.__setattr__(self, "daily_group_returns", list(self.daily_group_returns))
        object.__setattr__(self, "issue_codes", list(self.issue_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantiles": self.quantiles,
            "quantile_returns": dict(self.quantile_returns),
            "long_short_mean": self.long_short_mean,
            "monotonicity_spearman": self.monotonicity_spearman,
            "daily_group_returns": [
                result.to_dict() for result in self.daily_group_returns
            ],
            "group_return_issue_codes": list(self.issue_codes),
        }


def validate_quantiles(quantiles: int) -> int:
    """Return a validated quantile count."""
    if (
        isinstance(quantiles, bool)
        or not isinstance(quantiles, (int, np.integer))
        or quantiles < 2
    ):
        raise ValueError("quantiles must be an integer greater than or equal to 2")
    return int(quantiles)


def evaluate_group_returns(
    frame: pd.DataFrame,
    *,
    quantiles: int = 5,
) -> GroupReturnSummary:
    """Evaluate equal-weight daily quantile returns and the high-minus-low mean."""
    quantile_count = validate_quantiles(quantiles)
    required = {"date", "factor_value", "forward_return"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    daily_results: list[DailyGroupReturnResult] = []
    for date_value, date_slice in frame.groupby("date", sort=True):
        daily_results.append(
            _evaluate_daily_group_returns(
                date_slice,
                date=str(date_value),
                quantiles=quantile_count,
            )
        )

    valid_results = [result for result in daily_results if result.evaluated]
    issue_codes: list[str] = []
    if not valid_results:
        issue_codes.append("NO_VALID_GROUP_RETURN_DATES")
    elif len(valid_results) < len(daily_results):
        issue_codes.append("PARTIAL_GROUP_RETURN_DATES")

    if not valid_results:
        return GroupReturnSummary(
            quantiles=quantile_count,
            daily_group_returns=daily_results,
            issue_codes=issue_codes,
        )

    quantile_returns = {
        str(quantile): float(
            np.mean(
                [
                    result.quantile_returns[str(quantile)]
                    for result in valid_results
                ]
            )
        )
        for quantile in range(1, quantile_count + 1)
    }
    long_short_values = [
        result.long_short_return
        for result in valid_results
        if result.long_short_return is not None
    ]
    long_short_mean = (
        float(np.mean(long_short_values)) if long_short_values else None
    )
    monotonicity = _monotonicity_spearman(quantile_returns)

    return GroupReturnSummary(
        quantiles=quantile_count,
        quantile_returns=quantile_returns,
        long_short_mean=long_short_mean,
        monotonicity_spearman=monotonicity,
        daily_group_returns=daily_results,
        issue_codes=issue_codes,
    )


def _evaluate_daily_group_returns(
    date_slice: pd.DataFrame,
    *,
    date: str,
    quantiles: int,
) -> DailyGroupReturnResult:
    factor_values = pd.to_numeric(date_slice["factor_value"], errors="coerce")
    forward_returns = pd.to_numeric(date_slice["forward_return"], errors="coerce")
    valid = (
        factor_values.notna()
        & forward_returns.notna()
        & np.isfinite(factor_values)
        & np.isfinite(forward_returns)
    )
    values = factor_values.loc[valid]
    returns = forward_returns.loc[valid]
    sample_size = int(len(values))

    if sample_size < quantiles:
        return DailyGroupReturnResult(
            date=date,
            sample_size=sample_size,
            issue_codes=["INSUFFICIENT_GROUP_SAMPLE"],
        )
    if int(values.nunique()) < quantiles:
        return DailyGroupReturnResult(
            date=date,
            sample_size=sample_size,
            issue_codes=["INSUFFICIENT_UNIQUE_FACTOR_VALUES_FOR_GROUPS"],
        )

    ranks = values.rank(method="average")
    try:
        buckets = pd.qcut(ranks, quantiles, labels=False, duplicates="drop")
    except (TypeError, ValueError):
        buckets = pd.Series(np.nan, index=values.index)
    if buckets.isna().any() or int(buckets.nunique()) != quantiles:
        return DailyGroupReturnResult(
            date=date,
            sample_size=sample_size,
            issue_codes=["INSUFFICIENT_UNIQUE_FACTOR_VALUES_FOR_GROUPS"],
        )

    quantile_labels = buckets.astype(int) + 1
    grouped = returns.groupby(quantile_labels).mean()
    if 1 not in grouped.index or quantiles not in grouped.index:
        return DailyGroupReturnResult(
            date=date,
            sample_size=sample_size,
            issue_codes=["MISSING_EXTREME_QUANTILE"],
        )

    quantile_returns = {
        str(quantile): float(grouped.loc[quantile])
        for quantile in range(1, quantiles + 1)
    }
    long_short_return = (
        quantile_returns[str(quantiles)] - quantile_returns["1"]
    )
    return DailyGroupReturnResult(
        date=date,
        sample_size=sample_size,
        quantile_returns=quantile_returns,
        long_short_return=float(long_short_return),
        evaluated=True,
    )


def _monotonicity_spearman(
    quantile_returns: dict[str, float],
) -> float | None:
    if len(quantile_returns) < 2:
        return None
    quantile_numbers = np.array(
        [int(key) for key in quantile_returns],
        dtype=float,
    )
    returns = np.array(list(quantile_returns.values()), dtype=float)
    if np.unique(returns).size <= 1:
        return None
    result = spearmanr(quantile_numbers, returns)
    correlation = float(result.correlation)
    return correlation if math.isfinite(correlation) else None
