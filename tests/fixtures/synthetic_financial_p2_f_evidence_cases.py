"""Deterministic synthetic cases for FIN-P2-F."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.amr.financial_p2_f_evidence import (
    FinancialP2FEvidenceConfig,
    FinancialP2FForecastBatch,
)


AS_OF = "2025-02-28T00:00:00"
SECURITY_COUNT = 20
QUARTER_COUNT = 28
START_QUARTER = "2018Q1"


def symbols(security_count: int = SECURITY_COUNT) -> tuple[str, ...]:
    return tuple(
        f"SYNP2F{index:04d}"
        for index in range(1, security_count + 1)
    )


def make_forecast_frame(
    *,
    security_count: int = SECURITY_COUNT,
    quarter_count: int = QUARTER_COUNT,
    add_future_version: bool = False,
) -> pd.DataFrame:
    periods = pd.period_range(
        START_QUARTER, periods=quarter_count, freq="Q"
    )
    rows: list[dict[str, Any]] = []
    season = {1: -0.012, 2: 0.004, 3: 0.009, 4: 0.021}
    for symbol_index, symbol in enumerate(
        symbols(security_count), start=1
    ):
        assets = 800.0 + symbol_index * 11.0
        for time_index, period in enumerate(periods):
            exposure = symbol_index / max(security_count, 1)
            revenue_ratio = (
                0.20
                + 0.0040 * time_index
                + 0.014 * exposure
                + season[period.quarter]
            )
            profit_ratio = (
                0.018
                + 0.00070 * time_index
                + 0.0030 * exposure
                + season[period.quarter] * 0.08
            )
            cash_ratio = (
                -0.004
                + 0.00120 * time_index
                + 0.0040 * exposure
                + season[period.quarter] * 0.11
            )
            gross_margin = (
                0.275
                + 0.00150 * time_index * (1.0 + 0.20 * exposure)
                + 0.010 * exposure
                + season[period.quarter] * 0.07
            )
            revenue = assets * revenue_ratio
            report_period = period.end_time.normalize()
            announced_at = report_period + pd.Timedelta(days=25)
            rows.append(
                {
                    "symbol": symbol,
                    "report_period": report_period.date().isoformat(),
                    "announced_at": announced_at.date().isoformat(),
                    "version_at": announced_at.date().isoformat(),
                    "revenue": revenue,
                    "parent_net_profit": assets * profit_ratio,
                    "operating_cash_flow": assets * cash_ratio,
                    "operating_cost": revenue * (1.0 - gross_margin),
                    "total_assets": assets,
                    "total_liabilities": assets * (
                        0.42 + 0.03 * exposure
                    ),
                    "equity": assets * (
                        0.58 - 0.03 * exposure
                    ),
                }
            )
    if add_future_version:
        future = dict(rows[-1])
        future["version_at"] = "2025-03-15"
        future["revenue"] = float(future["revenue"]) * 9.0
        future["parent_net_profit"] = (
            float(future["parent_net_profit"]) * -7.0
        )
        rows.append(future)
    return pd.DataFrame(rows)


def make_batch(
    *,
    frame: pd.DataFrame | None = None,
    synthetic_test_only: bool = True,
) -> FinancialP2FForecastBatch:
    return FinancialP2FForecastBatch(
        dataset_id="synthetic-financial-p2-f-quarterly-v1",
        version="synthetic-p2-f-v1",
        source="synthetic-financial-p2-f",
        _frame=(
            make_forecast_frame()
            if frame is None
            else frame
        ),
        provenance={
            "synthetic_test_only": synthetic_test_only,
            "generator": "deterministic-linear-quarterly-v1",
            "amount_unit": "synthetic_rmb",
            "flow_basis": "single_quarter",
        },
    )


def make_configuration(
    **overrides: Any,
) -> FinancialP2FEvidenceConfig:
    values: dict[str, Any] = {
        "as_of": AS_OF,
        "minimum_training_rows": 40,
        "minimum_training_periods": 5,
    }
    values.update(overrides)
    return FinancialP2FEvidenceConfig(**values)


def make_golden_case():
    return make_batch(), make_configuration()
