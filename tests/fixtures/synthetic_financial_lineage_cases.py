"""Synthetic-only FIN-R1B lineage fixtures.

The records intentionally identify no real issuer, vendor, or dataset.
"""

from copy import deepcopy

from backend.amr.financial_source_adapter import adapt_financial_source_records
from backend.amr.financial_timing import FinancialTimingPolicy


FACTOR_ID = "synthetic_financial_factor"
FACTOR_VERSION = "synthetic-v1"
SOURCE_NAME = "synthetic-controlled-source"
CONFIGURATION = {
    "factor_definition_id": "synthetic-definition-v1",
    "normalization": "none",
    "missing_value_policy": "fail_closed",
}
SNAPSHOT_MANIFEST = {
    "object_count": 3,
    "objects": (
        "synthetic-record-001",
        "synthetic-record-001-r2",
        "synthetic-record-002",
    ),
    "manifest_version": "synthetic-manifest-v1",
}
TRADING_DAYS = (
    "2024-01-05",
    "2024-01-08",
    "2024-01-09",
    "2024-01-10",
)

RAW_SOURCE_RECORDS = (
    {
        "code": "SYN001",
        "report_period": "2023-09-30",
        "publish_date": "2024-01-05",
        "announcement_timestamp": "2024-01-05T16:10:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "statement_version": "statement-original",
        "source_record_id": "synthetic-record-001",
        "factor_value": 1.25,
        "synthetic_test_only": True,
    },
    {
        "code": "SYN001",
        "report_period": "2023-09-30",
        "publish_date": "2024-01-08",
        "announcement_timestamp": "2024-01-08T16:30:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "statement_version": "statement-revision-2",
        "source_record_id": "synthetic-record-001-r2",
        "factor_value": 1.5,
        "synthetic_test_only": True,
    },
    {
        "code": "SYN002",
        "report_period": "2023-09-30",
        "publish_date": "2024-01-08",
        "announcement_timestamp": None,
        "announcement_timezone": None,
        "statement_version": "statement-original",
        "source_record_id": "synthetic-record-002",
        "factor_value": -0.5,
        "synthetic_test_only": True,
    },
)


def make_synthetic_financial_inputs():
    """Return an accepted FIN-R1A batch and its FIN-R1B metadata."""

    policy = FinancialTimingPolicy(
        trading_days=TRADING_DAYS,
        trading_calendar_version="synthetic-calendar-v1",
    )
    adaptation = adapt_financial_source_records(
        deepcopy(RAW_SOURCE_RECORDS),
        factor_id=FACTOR_ID,
        version=FACTOR_VERSION,
        source=SOURCE_NAME,
        policy=policy,
    )
    assert adaptation.batch is not None
    audits = {
        audit.source_record_id: audit
        for audit in adaptation.timing_audits
    }
    effective = {
        audit.source_record_id: audit.derived_effective_date
        for audit in adaptation.timing_audits
    }

    records = [
        _lineage_metadata(
            raw,
            audits[raw["source_record_id"]],
            effective[raw["source_record_id"]],
        )
        for raw in RAW_SOURCE_RECORDS
    ]
    return adaptation.batch, records, deepcopy(CONFIGURATION)


def _lineage_metadata(raw, audit, effective_date):
    is_revision = raw["source_record_id"].endswith("-r2")
    is_path_b = raw["code"] == "SYN002"
    return {
        "evaluation_date": effective_date,
        "code": raw["code"],
        "factor_id": FACTOR_ID,
        "report_period": raw["report_period"],
        "publish_date": raw["publish_date"],
        "effective_date": effective_date,
        "factor_value": raw["factor_value"],
        "path_type": "B" if is_path_b else "A",
        "source_provider": "synthetic-provider",
        "source_dataset": "synthetic-financial-statements",
        "source_snapshot_id": "snapshot-2024-01-10",
        "source_as_of_version": "2024-01-10T18:00:00+08:00",
        "source_record_id": raw["source_record_id"],
        "announcement_id": "not_applicable",
        "financial_statement_version": raw["statement_version"],
        "revision_version": "revision-2" if is_revision else "original",
        "supersedes_reference": (
            "synthetic-record-001" if is_revision else "not_applicable"
        ),
        "transformation_reference": "synthetic-transform-v1",
        "formula_reference": (
            "registered-formula://synthetic/v1"
            if is_path_b
            else "not_applicable"
        ),
        "upstream_calculation_reference": (
            "upstream-run://synthetic/001"
            if not is_path_b
            else "not_applicable"
        ),
        "source_input_payload": {
            "raw_record": {
                "code": raw["code"],
                "report_period": raw["report_period"],
                "statement_version": raw["statement_version"],
                "source_record_id": raw["source_record_id"],
                "financial_item": "synthetic-item",
                "financial_value": raw["factor_value"] * 10,
            }
        },
        "source_snapshot_manifest": deepcopy(SNAPSHOT_MANIFEST),
        "timing_audit": audit,
        "synthetic_test_only": True,
    }
