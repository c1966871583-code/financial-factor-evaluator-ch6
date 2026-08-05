"""Deterministic synthetic-only cases for FIN-P2-R."""

from __future__ import annotations

import copy
import hashlib
from typing import Any

from backend.amr.financial_p2_r_evidence import (
    FinancialP2REvidenceConfig,
)


AS_OF = "2025-04-30"
REPORT_PERIODS = ("2024-06-30", "2024-12-31")
ANNOUNCED_AT = {
    "2024-06-30": "2024-08-30",
    "2024-12-31": "2025-03-28",
}
SPLIT_SALT = "FIN-P2-R-company-split-v1"
TEST_FRACTION = 0.35


def configuration(**changes: Any) -> FinancialP2REvidenceConfig:
    values = {
        "as_of": AS_OF,
        "top_k": 10,
        "test_fraction": TEST_FRACTION,
        "split_salt": SPLIT_SALT,
    }
    values.update(changes)
    return FinancialP2REvidenceConfig(**values)


def expected_split(symbol: str) -> str:
    digest = hashlib.sha256(
        f"{SPLIT_SALT}|{symbol}".encode("utf-8")
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(2**64)
    return "test" if bucket < TEST_FRACTION else "train"


def company_cohorts() -> dict[str, tuple[str, ...]]:
    train = []
    test = []
    index = 1
    while len(train) < 35 or len(test) < 25:
        symbol = f"SYNR{index:04d}"
        target = test if expected_split(symbol) == "test" else train
        target.append(symbol)
        index += 1
    return {
        "train_hard": tuple(train[:12]),
        "train_negative": tuple(train[12:24]),
        "train_soft": tuple(train[24:29]),
        "train_unlabeled": tuple(train[29:35]),
        "test_hard": tuple(test[:5]),
        "test_negative": tuple(test[5:15]),
        "test_soft": tuple(test[15:20]),
        "test_unlabeled": tuple(test[20:25]),
    }


def _label_for(symbol: str) -> str:
    for cohort, symbols in company_cohorts().items():
        if symbol in symbols:
            if cohort.endswith("hard"):
                return "hard_positive"
            if cohort.endswith("negative"):
                return "confirmed_negative"
            if cohort.endswith("soft"):
                return "soft_positive"
            return "unlabeled"
    raise LookupError(symbol)


def make_record(
    symbol: str,
    report_period: str,
    label_state: str,
) -> dict[str, Any]:
    high = label_state == "hard_positive"
    soft = label_state == "soft_positive"
    unlabeled = label_state == "unlabeled"
    # Some unknown cases intentionally rank high.  They must remain unknown,
    # demonstrating that absence of a label is never evidence of low risk.
    review_unknown = (
        unlabeled
        and hashlib.sha256(symbol.encode("utf-8")).digest()[0] % 2 == 0
    )
    record = {
        "symbol": symbol,
        "report_period": report_period,
        "announced_at": ANNOUNCED_AT[report_period],
        "sector_type": "industrial",
        "total_assets": 100.0,
        "total_liabilities": (
            92.0 if high or review_unknown else 50.0
        ),
        "net_profit": 10.0,
        "operating_cash_flow": (
            -2.0 if high or soft or review_unknown else 8.0
        ),
        "receivables_growth_anomaly": high or soft,
        "inventory_growth_anomaly": high,
        "other_receivables_anomaly": high or review_unknown,
        "non_recurring_or_asset_anomaly": high,
        "audit_opinion": (
            "qualified" if high else "standard_unqualified"
        ),
        "restated": high or soft,
        "label_state": label_state,
        "label_available_at": (
            None if label_state == "unlabeled" else "2025-04-15"
        ),
        "label_source_url": (
            None
            if label_state == "unlabeled"
            else f"https://regulator.invalid/{symbol}"
        ),
        "label_source_quality": (
            None if label_state == "unlabeled" else "official_synthetic"
        ),
        "provenance": {
            "synthetic_test_only": True,
            "fixture": "FIN-P2-R-v1",
        },
    }
    return record


def make_golden_records() -> list[dict[str, Any]]:
    rows = []
    for symbols in company_cohorts().values():
        for symbol in symbols:
            label = _label_for(symbol)
            for period in REPORT_PERIODS:
                rows.append(make_record(symbol, period, label))
    rows.sort(key=lambda row: (row["symbol"], row["report_period"]))
    return rows


def clone_records(
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return copy.deepcopy(records or make_golden_records())
