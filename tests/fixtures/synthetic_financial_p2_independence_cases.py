"""Deterministic synthetic cases for FIN-P2-INDEP."""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

import pandas as pd

from backend.amr.financial_p2_independence import (
    FinancialP2IndependenceBatch,
    FinancialP2IndependenceConfig,
)


SECURITY_COUNT = 60
PERIOD_COUNT = 18
FACTOR_IDS = ("ROE", "BP", "OCF_NP")
ANALYSIS_AS_OF = "2025-12-31"

TRACK_ANCHORS = {
    "M": {
        "task_id": "FIN-P2-M-ENH",
        "status": "ACCEPTED",
        "evidence_priority": "primary",
        "output_fingerprint": (
            "7496da71a9a4b6e429201c3173d903efd28e422acf07786a0c7"
            "d4d532be5b4d1"
        ),
    },
    "F": {
        "task_id": "FIN-P2-F",
        "status": "ACCEPTED",
        "evidence_priority": "supporting",
        "output_fingerprint": (
            "01f82894b9b327ed661b9fe3d9fe96fcc605a3df9502cee61d6c"
            "9c0becf11282"
        ),
    },
    "R": {
        "task_id": "FIN-P2-R",
        "status": "ACCEPTED",
        "evidence_priority": "risk",
        "output_fingerprint": (
            "dd376c087244dc57098828ee5a14b840ebe7404ddc48693ebb70a"
            "609035f0327"
        ),
    },
}


def evaluation_dates() -> tuple[str, ...]:
    return tuple(
        value.date().isoformat()
        for value in pd.date_range(
            "2024-01-31",
            periods=PERIOD_COUNT,
            freq="ME",
        )
    )


def codes() -> tuple[str, ...]:
    return tuple(f"{index:06d}.SZ" for index in range(1, 61))


def make_frame() -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    dates = evaluation_dates()
    for factor_index, factor_id in enumerate(FACTOR_IDS):
        for period_index, evaluation_date in enumerate(dates):
            evaluation = pd.Timestamp(evaluation_date)
            time_effect = 0.002 * math.sin(period_index * 0.7)
            for security_index, code in enumerate(codes()):
                industry_index = security_index % 6
                phase = (
                    security_index * 0.31
                    + period_index * 0.43
                    + factor_index * 0.67
                )
                factor_value = (
                    0.85 * math.sin(phase)
                    + 0.40 * math.cos(security_index * 0.17)
                    + 0.08 * (industry_index - 2.5)
                )
                peer_noise = math.cos(
                    security_index * 0.47
                    - period_index * 0.21
                    + factor_index
                )
                peer_value = 0.52 * factor_value + 0.72 * peer_noise
                log_market_cap = (
                    8.2
                    + security_index / 95.0
                    + 0.09 * math.sin(period_index + security_index)
                )
                idiosyncratic = 0.004 * math.sin(
                    security_index * 1.13 + period_index * 0.29
                )
                m_forward_return = (
                    0.018 * factor_value
                    + 0.006 * peer_value
                    + 0.0015 * (log_market_cap - 8.5)
                    + 0.001 * (industry_index - 2.5)
                    + time_effect
                    + idiosyncratic
                )
                f_residual = (
                    0.75 * factor_value
                    + 0.18 * peer_value
                    + 0.05 * (industry_index - 2.5)
                    + 0.03 * math.cos(
                        security_index * 0.91 + period_index
                    )
                )
                risk_latent = (
                    1.30 * factor_value
                    + 0.18 * peer_value
                    + 0.10 * math.sin(
                        security_index * 0.61 - period_index
                    )
                )
                selector = (
                    security_index
                    + 3 * period_index
                    + 5 * factor_index
                ) % 17
                if risk_latent > 0.55:
                    r_label_state = "hard_positive"
                elif selector in {0, 1, 2}:
                    r_label_state = "soft_positive"
                elif selector in {3, 4}:
                    r_label_state = "unlabeled"
                else:
                    r_label_state = "confirmed_negative"
                r_available = (
                    None
                    if r_label_state == "unlabeled"
                    else (
                        evaluation + pd.Timedelta(days=90)
                    ).date().isoformat()
                )
                records.append(
                    {
                        "evaluation_date": evaluation_date,
                        "code": code,
                        "factor_id": factor_id,
                        "factor_value": factor_value,
                        "peer_factor_value": peer_value,
                        "industry_code": f"IND-{industry_index + 1}",
                        "log_market_cap": log_market_cap,
                        "control_effective_date": (
                            evaluation - pd.Timedelta(days=5)
                        ).date().isoformat(),
                        "m_forward_return": m_forward_return,
                        "m_label_available_at": (
                            evaluation + pd.Timedelta(days=30)
                        ).date().isoformat(),
                        "f_residual": f_residual,
                        "f_label_available_at": (
                            evaluation + pd.Timedelta(days=75)
                        ).date().isoformat(),
                        "r_label_state": r_label_state,
                        "r_label_available_at": r_available,
                    }
                )
    return pd.DataFrame.from_records(records)


def make_configuration(
    **changes: Any,
) -> FinancialP2IndependenceConfig:
    values: dict[str, Any] = {
        "analysis_as_of": ANALYSIS_AS_OF,
        "evaluation_dates": evaluation_dates(),
    }
    values.update(changes)
    return FinancialP2IndependenceConfig(**values)


def make_batch(
    *,
    frame: pd.DataFrame | None = None,
    anchors: Mapping[str, Mapping[str, Any]] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> FinancialP2IndependenceBatch:
    return FinancialP2IndependenceBatch(
        dataset_id="synthetic-financial-p2-independence",
        version="v1",
        source="deterministic_fixture",
        _frame=make_frame() if frame is None else frame,
        track_anchors=(
            copy.deepcopy(TRACK_ANCHORS)
            if anchors is None
            else copy.deepcopy(dict(anchors))
        ),
        provenance=(
            {
                "synthetic_test_only": True,
                "generator": (
                    "synthetic_financial_p2_independence_cases.py"
                ),
                "seed_policy": "closed_form_no_random_state",
            }
            if provenance is None
            else copy.deepcopy(dict(provenance))
        ),
    )


def clone_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy(deep=True)
