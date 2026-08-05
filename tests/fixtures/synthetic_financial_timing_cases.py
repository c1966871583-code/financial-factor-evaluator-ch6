"""Synthetic-only FIN-R1A timing fixtures.

No record in this file represents production or vendor data.
"""

SYNTHETIC_TRADING_DAYS = (
    "2024-01-05",
    "2024-01-08",
    "2024-01-09",
    "2024-01-10",
    "2024-02-08",
    "2024-02-19",
    "2024-02-20",
)


SYNTHETIC_TIMING_CASES = (
    {
        "case_id": "monday_pre_market",
        "publish_date": "2024-01-08",
        "announcement_timestamp": "2024-01-08T08:30:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "expected_session": "pre_market",
        "expected_effective_date": "2024-01-09",
    },
    {
        "case_id": "monday_in_session",
        "publish_date": "2024-01-08",
        "announcement_timestamp": "2024-01-08T10:00:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "expected_session": "in_session",
        "expected_effective_date": "2024-01-09",
    },
    {
        "case_id": "monday_post_market",
        "publish_date": "2024-01-08",
        "announcement_timestamp": "2024-01-08T15:30:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "expected_session": "post_market",
        "expected_effective_date": "2024-01-09",
    },
    {
        "case_id": "friday_post_market",
        "publish_date": "2024-01-05",
        "announcement_timestamp": "2024-01-05T18:00:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "expected_session": "post_market",
        "expected_effective_date": "2024-01-08",
    },
    {
        "case_id": "weekend",
        "publish_date": "2024-01-06",
        "announcement_timestamp": "2024-01-06T11:00:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "expected_session": "non_trading_day",
        "expected_effective_date": "2024-01-08",
    },
    {
        "case_id": "long_holiday",
        "publish_date": "2024-02-10",
        "announcement_timestamp": "2024-02-10T11:00:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "expected_session": "non_trading_day",
        "expected_effective_date": "2024-02-19",
    },
    {
        "case_id": "date_only",
        "publish_date": "2024-01-08",
        "announcement_timestamp": None,
        "announcement_timezone": None,
        "expected_session": "date_only",
        "expected_effective_date": "2024-01-09",
    },
)


SYNTHETIC_SOURCE_RECORDS = (
    {
        "code": "SYN001",
        "report_period": "2023-09-30",
        "publish_date": "2024-01-05",
        "announcement_timestamp": "2024-01-05T16:10:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "statement_version": "original",
        "source_record_id": "synthetic-record-001",
        "factor_value": 1.25,
        "synthetic_test_only": True,
    },
    {
        "code": "SYN002",
        "report_period": "2023-09-30",
        "publish_date": "2024-01-08",
        "announcement_timestamp": None,
        "announcement_timezone": None,
        "statement_version": "original",
        "source_record_id": "synthetic-record-002",
        "factor_value": -0.5,
        "synthetic_test_only": True,
    },
)
