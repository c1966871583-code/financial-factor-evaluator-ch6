"""Synthetic-only inputs for FIN-R2-PREP."""

from __future__ import annotations

import hashlib
from copy import deepcopy

from tests.fixtures.synthetic_financial_mvp_batch_cases import (
    CODE,
    EFFECTIVE_DATE,
    EVALUATION_DATE,
    PUBLISH_DATE,
    REPORT_PERIOD,
    make_mvp_batch_inputs,
)


def _snapshot(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def make_preprocessing_record(
    *,
    code: str = "SYNPREP001",
    evaluation_date: str = "2024-01-08",
    report_period: str = "2023-09-30",
    publish_date: str = "2024-01-05",
    effective_date: str = "2024-01-08",
    parent_net_profit_ttm: float = 20.0,
    operating_cash_flow_ttm: float = 30.0,
    parent_equity: float = 110.0,
    prior_year_same_period_parent_equity: float = 90.0,
    market_cap: float = 200.0,
) -> dict:
    """Build an interim cumulative record that resolves to requested TTM."""

    prior_fy_parent_net_profit = 10.0
    prior_same_parent_net_profit = 5.0
    prior_fy_operating_cash_flow = 20.0
    prior_same_operating_cash_flow = 10.0
    return {
        "evaluation_date": evaluation_date,
        "code": code,
        "report_period": report_period,
        "publish_date": publish_date,
        "effective_date": effective_date,
        "parent_net_profit_ytd": (
            parent_net_profit_ttm
            - prior_fy_parent_net_profit
            + prior_same_parent_net_profit
        ),
        "operating_cash_flow_ytd": (
            operating_cash_flow_ttm
            - prior_fy_operating_cash_flow
            + prior_same_operating_cash_flow
        ),
        "parent_equity": parent_equity,
        "market_cap": market_cap,
        "prior_fy_parent_net_profit": prior_fy_parent_net_profit,
        "prior_fy_operating_cash_flow": prior_fy_operating_cash_flow,
        "prior_year_same_period_parent_net_profit_ytd":
            prior_same_parent_net_profit,
        "prior_year_same_period_operating_cash_flow_ytd":
            prior_same_operating_cash_flow,
        "prior_year_same_period_parent_equity":
            prior_year_same_period_parent_equity,
        "source_snapshot_fingerprint": _snapshot(
            f"synthetic-prep-snapshot-{code}"
        ),
        "input_record_references": [
            f"synthetic-statement://{code}/{report_period}",
            f"synthetic-market-cap://{code}/{evaluation_date}",
        ],
        "synthetic_test_only": True,
    }


def make_annual_preprocessing_record(**overrides) -> dict:
    record = make_preprocessing_record(
        report_period="2023-12-31",
        publish_date="2024-03-29",
        effective_date="2024-04-01",
        evaluation_date="2024-04-01",
        **overrides,
    )
    record["parent_net_profit_ytd"] = 20.0
    record["operating_cash_flow_ytd"] = 30.0
    for key in (
        "prior_fy_parent_net_profit",
        "prior_fy_operating_cash_flow",
        "prior_year_same_period_parent_net_profit_ytd",
        "prior_year_same_period_operating_cash_flow_ytd",
    ):
        record.pop(key)
    return record


def make_mad_cross_section() -> list[dict]:
    net_profits = (10.0, 11.0, 12.0, 13.0, 100.0)
    records = []
    for index, net_profit in enumerate(net_profits, start=1):
        records.append(
            make_preprocessing_record(
                code=f"SYNPREP{index:03d}",
                parent_net_profit_ttm=net_profit,
                operating_cash_flow_ttm=net_profit * 2.0,
                parent_equity=100.0,
                prior_year_same_period_parent_equity=100.0,
                market_cap=200.0,
            )
        )
    return records


def make_mvp_compatible_preprocessing_case():
    (
        mvp_records,
        lineage_references,
        sample_references,
        mvp_configuration,
        future_labels,
    ) = make_mvp_batch_inputs("B")
    snapshots = {
        item["factor_id"]: item["source_snapshot_fingerprint"]
        for item in mvp_records
    }
    record = make_preprocessing_record(
        code=CODE,
        evaluation_date=EVALUATION_DATE,
        report_period=REPORT_PERIOD,
        publish_date=PUBLISH_DATE,
        effective_date=EFFECTIVE_DATE,
        parent_net_profit_ttm=20.0,
        operating_cash_flow_ttm=30.0,
        parent_equity=50.0,
        prior_year_same_period_parent_equity=150.0,
        market_cap=200.0,
    )
    record["source_snapshot_fingerprint"] = snapshots["ROE"]
    record["input_record_references"] = [
        "synthetic-mvp-input://profit",
        "synthetic-mvp-input://equity",
        "synthetic-mvp-input://cash-flow",
        "synthetic-mvp-input://market-cap",
    ]
    return (
        record,
        lineage_references,
        sample_references,
        mvp_configuration,
        deepcopy(future_labels),
        snapshots,
    )
