"""Contract tests for the operator-frozen financial timing policy."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.amr.financial_timing import (
    FinancialTimingPolicy,
    FinancialTimingPolicyError,
    VersionedTradingCalendar,
)


def _calendar() -> VersionedTradingCalendar:
    return VersionedTradingCalendar(
        trading_dates=(
            "2024-01-04",
            "2024-01-05",
            "2024-01-08",
            "2024-02-08",
            "2024-02-19",
            "2024-02-20",
        ),
        calendar_provider="RQData",
        calendar_scope="CN",
        calendar_version_or_snapshot_id="synthetic-contract-calendar-v1",
    )


def test_ft_t01_normal_trading_day_maps_to_next_session() -> None:
    assert FinancialTimingPolicy(_calendar()).derive_effective_date("2024-01-04") == "2024-01-05"


def test_ft_t02_friday_maps_to_following_valid_session() -> None:
    assert FinancialTimingPolicy(_calendar()).derive_effective_date("2024-01-05") == "2024-01-08"


def test_ft_t03_weekend_maps_to_first_session_after_it() -> None:
    assert FinancialTimingPolicy(_calendar()).derive_effective_date("2024-01-06") == "2024-01-08"


def test_ft_t04_exchange_holiday_maps_to_calendar_session() -> None:
    assert FinancialTimingPolicy(_calendar()).derive_effective_date("2024-02-12") == "2024-02-19"


def test_ft_t06_missing_publish_date_is_audited_and_excluded() -> None:
    records = pd.DataFrame(
        {
            "code": ["A"],
            "report_period": ["2023-12-31"],
            "publish_date": [None],
            "factor_value": [1.0],
        }
    )
    result = FinancialTimingPolicy(_calendar()).apply(records)
    assert result.valid_frame.empty
    assert result.audit_frame.loc[0, "timing_status"] == "MISSING_PUBLISH_DATE"


def test_ft_t07_each_revision_gets_an_independent_effective_date() -> None:
    records = pd.DataFrame(
        {
            "code": ["A", "A"],
            "report_period": ["2023-12-31", "2023-12-31"],
            "publish_date": ["2024-01-04", "2024-02-12"],
            "factor_value": [1.0, 2.0],
        }
    )
    result = FinancialTimingPolicy(_calendar()).apply(records)
    assert result.valid_frame["effective_date"].tolist() == ["2024-01-05", "2024-02-19"]


def test_ft_t09_insufficient_calendar_fails_closed() -> None:
    with pytest.raises(FinancialTimingPolicyError) as exc:
        FinancialTimingPolicy(_calendar()).derive_effective_date("2024-02-20")
    assert exc.value.code == "TIMING_CALENDAR_RANGE_INSUFFICIENT"


def test_calendar_provenance_is_complete_and_hashed() -> None:
    provenance = FinancialTimingPolicy(_calendar()).to_provenance()
    assert provenance["calendar_provider"] == "RQData"
    assert provenance["calendar_scope"] == "CN"
    assert provenance["calendar_start"] == "2024-01-04"
    assert provenance["calendar_end"] == "2024-02-20"
    assert provenance["calendar_version_or_snapshot_id"]
    assert len(provenance["calendar_hash"]) == 64
