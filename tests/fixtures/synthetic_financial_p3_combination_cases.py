"""Deterministic synthetic-only FIN-P3-COMBOS cases."""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.amr.financial_p3_combinations import (
    COMBINATIONS_PREDECESSOR_OUTPUT_FINGERPRINT,
    FinancialP3CombinationsBatch,
    FinancialP3CombinationsConfig,
)
from backend.amr.financial_p3_common_sample import (
    compute_common_sample_manifest_fingerprint,
)


EXECUTION_TIMESTAMP = "2026-08-03T11:00:00+08:00"
PREDECESSOR_ANCHOR = {
    "task_id": "FIN-P3-COMMON-SAMPLE",
    "status": "ACCEPTED",
    "output_fingerprint": COMBINATIONS_PREDECESSOR_OUTPUT_FINGERPRINT,
    "same_sample_enforced": True,
    "research_assessment": "exploratory",
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
    factor_columns = (
        "bp",
        "ebit_ev",
        "roe",
        "ocf_np",
        "sales_growth",
        "profit_growth",
        "roa",
        "ocf_sales",
        "accruals",
    )
    for date_index, date_text in enumerate(evaluation_dates()):
        date = pd.Timestamp(date_text)
        for security_index in range(60):
            latent = (security_index - 29.5) / 17.5
            phase = date_index * 0.37
            size = math.cos(security_index * 0.19) + 0.02 * date_index
            industry = f"I{security_index % 3}"
            values = {
                "bp": latent + 0.72 * math.sin(security_index * 0.31 + phase),
                "ebit_ev": latent + 0.65 * math.cos(security_index * 0.41 + phase),
                "roe": latent + 0.68 * math.sin(security_index * 0.53 - phase),
                "ocf_np": latent + 0.61 * math.cos(security_index * 0.59 - phase),
                "sales_growth": latent + 0.74 * math.sin(security_index * 0.23 + phase),
                "profit_growth": latent + 0.66 * math.cos(security_index * 0.47 + phase),
                "roa": latent + 0.69 * math.sin(security_index * 0.67 - phase),
                "ocf_sales": latent + 0.63 * math.cos(security_index * 0.71 + phase),
                "accruals": -latent + 0.67 * math.sin(security_index * 0.43 - phase),
            }
            if security_index == 0:
                values["bp"] = np.nan
            if security_index in (1, 2):
                values["ebit_ev"] = np.nan
            if security_index == 3:
                values["roe"] = np.nan
            if security_index == 4:
                values["ocf_np"] = np.nan
            if security_index in (5, 6):
                values["sales_growth"] = np.nan
            if security_index == 7:
                values["profit_growth"] = np.nan
            if security_index == 8:
                values["roa"] = np.nan
            if security_index in (9, 10):
                values["ocf_sales"] = np.nan
            if security_index == 11:
                values["accruals"] = np.nan
            forward_return = (
                0.017 * latent
                + 0.0035 * size
                + (security_index % 3 - 1) * 0.0015
                + 0.003
                * math.sin(security_index * 0.79 + date_index * 0.83)
            )
            if security_index == 12:
                forward_return = np.nan
            if security_index == 13:
                size = np.nan
            if security_index == 14:
                industry = ""
            record = {
                "evaluation_date": date_text,
                "security_id": f"S{security_index:03d}",
                **values,
                "control_effective_date": (
                    date - pd.Timedelta(days=3)
                ).date().isoformat(),
                "return_start_date": (
                    date + pd.Timedelta(days=1)
                ).date().isoformat(),
                "forward_return": forward_return,
                "size_control": size,
                "industry_code": industry,
            }
            for offset, column in enumerate(factor_columns, start=5):
                record[f"{column}_effective_date"] = (
                    date - pd.Timedelta(days=offset)
                ).date().isoformat()
            records.append(record)
    return pd.DataFrame.from_records(records)


def make_configuration(
    *,
    manifest: pd.DataFrame | None = None,
    **changes: Any,
) -> FinancialP3CombinationsConfig:
    frozen_manifest = (
        make_manifest() if manifest is None else manifest.copy(deep=True)
    )
    values: dict[str, Any] = {
        "run_id": "SYNTHETIC-FIN24-COMBOS-01",
        "expected_manifest_fingerprint": (
            compute_common_sample_manifest_fingerprint(frozen_manifest)
        ),
        "execution_timestamp": EXECUTION_TIMESTAMP,
    }
    values.update(changes)
    return FinancialP3CombinationsConfig(**values)


def make_batch(
    *,
    manifest: pd.DataFrame | None = None,
    frame: pd.DataFrame | None = None,
    declared_manifest_fingerprint: str | None = None,
    predecessor_anchor: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> FinancialP3CombinationsBatch:
    frozen_manifest = (
        make_manifest() if manifest is None else manifest.copy(deep=True)
    )
    return FinancialP3CombinationsBatch(
        dataset_id="synthetic-financial-p3-combinations",
        version="v1",
        _manifest=frozen_manifest,
        _frame=make_frame() if frame is None else frame,
        declared_manifest_fingerprint=(
            compute_common_sample_manifest_fingerprint(frozen_manifest)
            if declared_manifest_fingerprint is None
            else declared_manifest_fingerprint
        ),
        predecessor_anchor=(
            copy.deepcopy(PREDECESSOR_ANCHOR)
            if predecessor_anchor is None
            else copy.deepcopy(dict(predecessor_anchor))
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
