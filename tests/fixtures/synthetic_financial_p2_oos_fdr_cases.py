"""Deterministic synthetic cases for FIN-P2-OOS-FDR."""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

import pandas as pd

from backend.amr.financial_p2_oos_fdr import (
    FAMILY_R_HARD,
    FROZEN_HYPOTHESES,
    FinancialP2OOSBatch,
    FinancialP2OOSFDRConfig,
    compute_partition_fingerprint,
)


EXECUTION_TIMESTAMP = "2026-07-31T10:30:00+08:00"
INDEPENDENCE_ANCHOR = {
    "task_id": "FIN-P2-INDEP",
    "status": "ACCEPTED",
    "output_fingerprint": (
        "34048940ea418305b51ff36072d41ea7bd4c6220dbf47938377ed"
        "331811c9ae7"
    ),
}


def make_partition_manifest() -> pd.DataFrame:
    dates = tuple(
        value.date().isoformat()
        for value in pd.date_range(
            "2020-01-31",
            periods=60,
            freq="ME",
        )
    )
    records: list[dict[str, str]] = []
    for index, period in enumerate(dates):
        split = (
            "train"
            if index < 36
            else "calibration"
            if index < 48
            else "test"
        )
        records.append(
            {
                "observation_id": f"PERIOD-{index:03d}",
                "split": split,
                "period": period,
                "company_id": f"PERIOD-COMPANY-{index:03d}",
            }
        )
    for index in range(300):
        split = (
            "train"
            if index < 180
            else "calibration"
            if index < 240
            else "test"
        )
        if split == "train":
            period = dates[index % 36]
        elif split == "calibration":
            period = dates[36 + (index - 180) % 12]
        else:
            period = dates[48 + (index - 240) % 12]
        records.append(
            {
                "observation_id": f"RH-{index:03d}",
                "split": split,
                "period": period,
                "company_id": f"RH-COMPANY-{index:03d}",
            }
        )
    return pd.DataFrame.from_records(records)


def _mean_effect(spec, index: int, split: str) -> float | None:
    if split != "test":
        return (
            -0.20
            + 0.05 * math.sin(index + len(spec.hypothesis_id))
        )
    test_index = index - 48
    noise = 0.012 * math.sin(test_index * 1.7)
    if spec.hypothesis_id == "F-P06" and test_index >= 8:
        return None
    if spec.hypothesis_id == "R-S05" and test_index >= 8:
        return None
    if spec.hypothesis_id.startswith("F-P"):
        sign = -1.0 if spec.prior_direction == "negative" else 1.0
        return sign * (0.10 + noise)
    if spec.hypothesis_id.startswith("R-S"):
        return 0.08 + noise
    m_index = int(spec.hypothesis_id[-2:])
    strengths = {
        1: 0.070,
        2: -0.060,
        3: 0.004,
        4: 0.050,
        5: -0.045,
        6: 0.003,
        7: 0.035,
    }
    return strengths[m_index] + noise


def make_frame() -> pd.DataFrame:
    manifest = make_partition_manifest()
    period_manifest = manifest[
        manifest["observation_id"].str.startswith("PERIOD-")
    ]
    hard_manifest = manifest[
        manifest["observation_id"].str.startswith("RH-")
    ]
    records: list[dict[str, Any]] = []
    for spec in FROZEN_HYPOTHESES:
        if spec.test_family_id == FAMILY_R_HARD:
            hypothesis_number = int(spec.hypothesis_id[-2:])
            for row_index, row in hard_manifest.reset_index(
                drop=True
            ).iterrows():
                split = row["split"]
                if split == "test":
                    test_index = row_index - 240
                    positive_cutoff = (
                        10 if spec.hypothesis_id == "R-H05" else 30
                    )
                    positive = test_index < positive_cutoff
                else:
                    positive = (row_index + hypothesis_number) % 3 == 0
                state = (
                    "hard_positive"
                    if positive
                    else "confirmed_negative"
                )
                baseline_score = (
                    0.45
                    + 0.08
                    * math.sin(row_index * 0.41 + hypothesis_number)
                )
                augmented_score = (
                    0.82
                    + 0.06 * math.sin(row_index)
                    if positive
                    else 0.18
                    + 0.06 * math.cos(row_index * 0.7)
                )
                records.append(
                    {
                        "hypothesis_id": spec.hypothesis_id,
                        "observation_id": row["observation_id"],
                        "split": split,
                        "period": row["period"],
                        "company_id": row["company_id"],
                        "effect_value": None,
                        "label_state": state,
                        "label": 1.0 if positive else 0.0,
                        "baseline_score": baseline_score,
                        "augmented_score": augmented_score,
                    }
                )
            continue
        for row_index, row in period_manifest.reset_index(
            drop=True
        ).iterrows():
            records.append(
                {
                    "hypothesis_id": spec.hypothesis_id,
                    "observation_id": row["observation_id"],
                    "split": row["split"],
                    "period": row["period"],
                    "company_id": row["company_id"],
                    "effect_value": _mean_effect(
                        spec,
                        row_index,
                        row["split"],
                    ),
                    "label_state": (
                        "soft_positive"
                        if spec.hypothesis_id.startswith("R-S")
                        else "not_applicable"
                    ),
                    "label": None,
                    "baseline_score": None,
                    "augmented_score": None,
                }
            )
    return pd.DataFrame.from_records(records)


def make_configuration(
    *,
    manifest: pd.DataFrame | None = None,
    **changes: Any,
) -> FinancialP2OOSFDRConfig:
    frozen_manifest = (
        make_partition_manifest()
        if manifest is None
        else manifest.copy(deep=True)
    )
    values: dict[str, Any] = {
        "expected_partition_fingerprint":
            compute_partition_fingerprint(frozen_manifest),
        "execution_timestamp": EXECUTION_TIMESTAMP,
    }
    values.update(changes)
    return FinancialP2OOSFDRConfig(**values)


def make_batch(
    *,
    frame: pd.DataFrame | None = None,
    manifest: pd.DataFrame | None = None,
    declared_partition_fingerprint: str | None = None,
    anchor: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> FinancialP2OOSBatch:
    frozen_manifest = (
        make_partition_manifest()
        if manifest is None
        else manifest.copy(deep=True)
    )
    return FinancialP2OOSBatch(
        dataset_id="synthetic-financial-p2-oos-fdr",
        version="v1",
        source="deterministic_fixture",
        _frame=make_frame() if frame is None else frame,
        _partition_manifest=frozen_manifest,
        declared_partition_fingerprint=(
            compute_partition_fingerprint(frozen_manifest)
            if declared_partition_fingerprint is None
            else declared_partition_fingerprint
        ),
        independence_anchor=(
            copy.deepcopy(INDEPENDENCE_ANCHOR)
            if anchor is None
            else copy.deepcopy(dict(anchor))
        ),
        provenance=(
            {
                "synthetic_test_only": True,
                "registry_version": "FIN-EXP-00-HYP-v1.0",
                "partition_policy": "frozen_60_20_20",
            }
            if provenance is None
            else copy.deepcopy(dict(provenance))
        ),
    )
