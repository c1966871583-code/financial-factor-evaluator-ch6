"""Deterministic FIN-23 common-sample comparison cases."""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.amr.financial_p3_common_sample import (
    COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT,
    FinancialP3CommonSampleBatch,
    FinancialP3CommonSampleConfig,
    compute_common_sample_manifest_fingerprint,
)


EXECUTION_TIMESTAMP = "2026-08-03T10:20:00+08:00"
GATE_ANCHOR = {
    "task_id": "FIN-P2-GATE",
    "status": "ACCEPTED",
    "output_fingerprint": COMMON_SAMPLE_GATE_OUTPUT_FINGERPRINT,
    "research_integrity_status": "complete",
    "production_status": "not production ready",
}


def evaluation_dates() -> tuple[str, ...]:
    return tuple(
        value.date().isoformat()
        for value in pd.date_range("2023-01-31", periods=18, freq="ME")
    )


def make_manifest() -> pd.DataFrame:
    records = []
    for date in evaluation_dates():
        for security_index in range(60):
            records.append(
                {
                    "evaluation_date": date,
                    "security_id": f"S{security_index:03d}",
                    "eligible": security_index < 58,
                }
            )
    return pd.DataFrame.from_records(records)


def make_frame() -> pd.DataFrame:
    records = []
    for date_index, date_text in enumerate(evaluation_dates()):
        date = pd.Timestamp(date_text)
        for security_index in range(60):
            centered = (security_index - 29.5) / 17.5
            secondary = math.sin(security_index * 0.47 + date_index * 0.31)
            size = math.cos(security_index * 0.19) + 0.03 * date_index
            industry = f"I{security_index % 3}"
            single = centered + 0.65 * secondary
            combined = centered + 0.20 * secondary
            industry_effect = (security_index % 3 - 1) * 0.002
            forward_return = (
                0.018 * centered
                + 0.004 * size
                + industry_effect
                + 0.003
                * math.sin(security_index * 0.73 + date_index * 0.89)
            )
            if security_index in (0, 1):
                single = np.nan
            if security_index in (2, 3, 4):
                combined = np.nan
            if security_index == 5:
                forward_return = np.nan
            if security_index == 6:
                size = np.nan
            if security_index == 7:
                industry = ""
            records.append(
                {
                    "evaluation_date": date_text,
                    "security_id": f"S{security_index:03d}",
                    "factor_effective_date": (
                        date - pd.Timedelta(days=10)
                    ).date().isoformat(),
                    "control_effective_date": (
                        date - pd.Timedelta(days=5)
                    ).date().isoformat(),
                    "return_start_date": (
                        date + pd.Timedelta(days=1)
                    ).date().isoformat(),
                    "single_factor_value": single,
                    "combined_factor_value": combined,
                    "forward_return": forward_return,
                    "size_control": size,
                    "industry_code": industry,
                }
            )
    return pd.DataFrame.from_records(records)


def make_configuration(
    *,
    manifest: pd.DataFrame | None = None,
    **changes: Any,
) -> FinancialP3CommonSampleConfig:
    frozen_manifest = make_manifest() if manifest is None else manifest.copy(deep=True)
    values: dict[str, Any] = {
        "comparison_id": "SYNTHETIC-ROE-VS-COMBINED-01",
        "single_factor_id": "ROE_SYNTHETIC",
        "combined_factor_id": "SYNTHETIC_COMBINED_CANDIDATE",
        "single_formula_version": "synthetic-single-v1",
        "combined_formula_version": "synthetic-predeclared-combined-v1",
        "expected_manifest_fingerprint": (
            compute_common_sample_manifest_fingerprint(frozen_manifest)
        ),
        "execution_timestamp": EXECUTION_TIMESTAMP,
    }
    values.update(changes)
    return FinancialP3CommonSampleConfig(**values)


def make_batch(
    *,
    manifest: pd.DataFrame | None = None,
    frame: pd.DataFrame | None = None,
    declared_manifest_fingerprint: str | None = None,
    gate_anchor: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> FinancialP3CommonSampleBatch:
    frozen_manifest = make_manifest() if manifest is None else manifest.copy(deep=True)
    return FinancialP3CommonSampleBatch(
        dataset_id="synthetic-financial-p3-common-sample",
        version="v1",
        _manifest=frozen_manifest,
        _frame=make_frame() if frame is None else frame,
        declared_manifest_fingerprint=(
            compute_common_sample_manifest_fingerprint(frozen_manifest)
            if declared_manifest_fingerprint is None
            else declared_manifest_fingerprint
        ),
        gate_anchor=(
            copy.deepcopy(GATE_ANCHOR)
            if gate_anchor is None
            else copy.deepcopy(dict(gate_anchor))
        ),
        provenance=(
            {
                "synthetic_test_only": True,
                "provider": "deterministic_fixture",
                "universe_policy": "independent_frozen_manifest",
            }
            if provenance is None
            else copy.deepcopy(dict(provenance))
        ),
    )
