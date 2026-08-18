"""Performance and capability probes for the shared AMR evaluation core."""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import pytest

from backend.amr.evaluation_alignment import (
    AlignedEvaluationData,
    AlignmentReport,
    GateResult,
    GateStatus,
)
from backend.amr.evaluation_core import evaluate_price_volume_security_level

SEED = 20260727


def _make_aligned(n_days: int, n_codes: int) -> AlignedEvaluationData:
    rng = np.random.default_rng(SEED)
    dates = pd.date_range("2015-01-05", periods=n_days, freq="B")
    codes = [f"{index:06d}.XSHE" for index in range(n_codes)]
    rows: list[dict[str, object]] = []
    signal = np.arange(n_codes, dtype=float)
    for current_date in dates:
        forward = signal * 0.05 + rng.normal(scale=0.02, size=n_codes)
        date_text = current_date.strftime("%Y-%m-%d")
        rows.extend(
            {
                "date": date_text,
                "code": code,
                "factor_value": float(signal[index]),
                "forward_return": float(forward[index]),
                "horizon": "1",
            }
            for index, code in enumerate(codes)
        )
    frame = pd.DataFrame(rows)
    return AlignedEvaluationData(
        factor_id="stress",
        return_set_id="r1",
        horizon="1",
        _valid_frame=frame,
        _all_matched_frame=frame.copy(),
    )


@pytest.mark.parametrize(
    "scale_name,n_days,n_codes,benchmark_s",
    [("S", 250, 300, 30.0)],
    ids=["S"],
)
def test_stress_scale(
    scale_name: str,
    n_days: int,
    n_codes: int,
    benchmark_s: float,
) -> None:
    aligned = _make_aligned(n_days, n_codes)
    report = AlignmentReport(
        factor_id="stress",
        factor_type="price_volume",
        value_scope="security_level",
        return_set_id="r1",
        horizon="1",
    )
    gate = GateResult(factor_id="stress", overall_status=GateStatus.READY)

    durations = []
    for _ in range(3):
        started = time.perf_counter()
        result = evaluate_price_volume_security_level(
            aligned,
            report,
            gate,
            min_cross_section_size=3,
        )
        durations.append(time.perf_counter() - started)

    median_duration = sorted(durations)[1]
    assert median_duration < benchmark_s, (
        f"{scale_name} median {median_duration:.3f}s exceeded {benchmark_s:.1f}s"
    )
    assert result.overall_status.value == "completed"


class TestGapProbes:
    def test_forward_return_generator_is_available(self) -> None:
        from backend.amr.forward_returns import build_security_forward_return_batch

        assert callable(build_security_forward_return_batch)

    def test_financial_timing_policy_is_available(self) -> None:
        from backend.amr.financial_timing import FinancialTimingPolicy

        assert FinancialTimingPolicy is not None

    def test_result_is_json_serializable_at_stress_scale(self) -> None:
        aligned = _make_aligned(2, 10)
        report = AlignmentReport(
            factor_id="stress",
            factor_type="price_volume",
            value_scope="security_level",
            return_set_id="r1",
            horizon="1",
        )
        gate = GateResult(factor_id="stress", overall_status=GateStatus.READY)
        result = evaluate_price_volume_security_level(
            aligned,
            report,
            gate,
            min_cross_section_size=3,
        )
        json.dumps(result.to_dict())
