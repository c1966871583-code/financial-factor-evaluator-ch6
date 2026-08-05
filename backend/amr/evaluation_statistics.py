"""HAC statistics for AMR factor evaluation.

This module is intentionally independent from ``evaluation_core``. Integration
belongs to P0-4B-STEP3.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _as_finite_series(series: Any) -> np.ndarray | None:
    """Return a finite one-dimensional float array with at least three items."""
    try:
        values = np.asarray(series, dtype=float)
    except (TypeError, ValueError):
        return None

    if values.ndim != 1 or values.size < 3:
        return None
    if not np.all(np.isfinite(values)):
        return None
    return values


def _resolve_max_lag(sample_size: int, max_lag: int | None) -> int:
    """Resolve and clamp the Bartlett bandwidth."""
    if max_lag is None:
        # Newey-West (1994) automatic bandwidth rule.
        resolved = math.floor(4.0 * (sample_size / 100.0) ** (2.0 / 9.0))
    else:
        if isinstance(max_lag, bool) or not isinstance(max_lag, (int, np.integer)):
            raise ValueError("max_lag must be a non-negative integer or None")
        if max_lag < 0:
            raise ValueError("max_lag must be non-negative")
        resolved = int(max_lag)

    return min(resolved, sample_size - 1)


def _newey_west_se_from_values(
    values: np.ndarray,
    max_lag: int | None,
) -> float | None:
    sample_size = values.size
    mean = float(np.mean(values))
    if not math.isfinite(mean):
        return None

    centered = values - mean
    gamma_zero = float(np.dot(centered, centered) / sample_size)
    if not math.isfinite(gamma_zero) or gamma_zero <= 0.0:
        return None

    lag_limit = _resolve_max_lag(sample_size, max_lag)
    long_run_variance = gamma_zero
    for lag in range(1, lag_limit + 1):
        weight = 1.0 - lag / (lag_limit + 1.0)
        autocovariance = float(
            np.dot(centered[lag:], centered[:-lag]) / sample_size
        )
        long_run_variance += 2.0 * weight * autocovariance

    if not math.isfinite(long_run_variance) or long_run_variance <= 0.0:
        return None

    standard_error = math.sqrt(long_run_variance / sample_size)
    if not math.isfinite(standard_error) or standard_error <= 0.0:
        return None
    return standard_error


def newey_west_se(series: Any, max_lag: int | None = None) -> float | None:
    """Return the Newey-West/HAC standard error of a series mean.

    Autocovariances use a Bartlett kernel. When ``max_lag`` is omitted, the
    Newey-West (1994) automatic bandwidth
    ``floor(4 * (T / 100) ** (2 / 9))`` is used. Explicit lags at or beyond
    the sample length are clamped to ``T - 1``.

    ``None`` is returned for fewer than three observations, non-finite input,
    constant input, or an unusable long-run variance.
    """
    values = _as_finite_series(series)
    if values is None:
        return None
    return _newey_west_se_from_values(values, max_lag)


def hac_t_stat(series: Any, max_lag: int | None = None) -> float | None:
    """Return ``mean(series) / newey_west_se(series)`` when defined."""
    values = _as_finite_series(series)
    if values is None:
        return None

    standard_error = _newey_west_se_from_values(values, max_lag)
    if standard_error is None:
        return None

    statistic = float(np.mean(values)) / standard_error
    return statistic if math.isfinite(statistic) else None
