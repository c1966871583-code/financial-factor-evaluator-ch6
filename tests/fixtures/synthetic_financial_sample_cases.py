"""Synthetic-only FIN-R1C independent-sample fixtures."""

from copy import deepcopy

from backend.amr.financial_lineage import build_financial_provenance
from backend.amr.financial_sample import SampleFormationConfig
from tests.fixtures.synthetic_financial_lineage_cases import (
    make_synthetic_financial_inputs,
)


UNIVERSE_RECORDS = (
    {
        "evaluation_date": "2024-01-08",
        "code": "SYN001",
        "universe_record_id": "universe-20240108-SYN001",
        "in_universe": True,
        "factor_applicable": True,
        "listed_date": "2020-01-01",
        "delisted_date": None,
        "synthetic_test_only": True,
    },
    {
        "evaluation_date": "2024-01-08",
        "code": "SYN002",
        "universe_record_id": "universe-20240108-SYN002",
        "in_universe": True,
        "factor_applicable": True,
        "listed_date": "2020-01-01",
        "delisted_date": None,
        "synthetic_test_only": True,
    },
    {
        "evaluation_date": "2024-01-08",
        "code": "SYN003",
        "universe_record_id": "universe-20240108-SYN003",
        "in_universe": False,
        "factor_applicable": True,
        "listed_date": "2024-01-09",
        "delisted_date": None,
        "synthetic_test_only": True,
    },
    {
        "evaluation_date": "2024-01-08",
        "code": "SYN004",
        "universe_record_id": "universe-20240108-SYN004",
        "in_universe": True,
        "factor_applicable": False,
        "listed_date": "2020-01-01",
        "delisted_date": None,
        "synthetic_test_only": True,
    },
    {
        "evaluation_date": "2024-01-09",
        "code": "SYN001",
        "universe_record_id": "universe-20240109-SYN001",
        "in_universe": True,
        "factor_applicable": True,
        "listed_date": "2020-01-01",
        "delisted_date": None,
        "synthetic_test_only": True,
    },
    {
        "evaluation_date": "2024-01-09",
        "code": "SYN002",
        "universe_record_id": "universe-20240109-SYN002",
        "in_universe": True,
        "factor_applicable": True,
        "listed_date": "2020-01-01",
        "delisted_date": None,
        "synthetic_test_only": True,
    },
    {
        "evaluation_date": "2024-01-09",
        "code": "SYN003",
        "universe_record_id": "universe-20240109-SYN003",
        "in_universe": False,
        "factor_applicable": True,
        "listed_date": "2024-01-10",
        "delisted_date": None,
        "synthetic_test_only": True,
    },
    {
        "evaluation_date": "2024-01-09",
        "code": "SYN004",
        "universe_record_id": "universe-20240109-SYN004",
        "in_universe": True,
        "factor_applicable": False,
        "listed_date": "2020-01-01",
        "delisted_date": None,
        "synthetic_test_only": True,
    },
)


LABEL_RECORDS = (
    {
        "validation_track": "M",
        "evaluation_date": "2024-01-08",
        "code": "SYN001",
        "factor_id": "synthetic_financial_factor",
        "label_id": "M-SYN001-20240108",
        "label_type": "return",
        "label_value": 0.03,
        "label_publish_date": "2024-01-09",
        "label_effective_date": "2024-01-09",
        "label_available_at": "2024-01-10",
        "label_source_record_id": "market-return-001",
        "label_source": "synthetic-market-source",
        "label_version": "m-label-v1",
        "label_snapshot_fingerprint": "m-snapshot-hash-v1",
        "synthetic_test_only": True,
    },
    {
        "validation_track": "M",
        "evaluation_date": "2024-01-09",
        "code": "SYN001",
        "factor_id": "synthetic_financial_factor",
        "label_id": "M-SYN001-20240109",
        "label_type": "return",
        "label_value": -0.01,
        "label_publish_date": "2024-01-10",
        "label_effective_date": "2024-01-10",
        "label_available_at": "2024-01-10",
        "label_source_record_id": "market-return-002",
        "label_source": "synthetic-market-source",
        "label_version": "m-label-v1",
        "label_snapshot_fingerprint": "m-snapshot-hash-v1",
        "synthetic_test_only": True,
    },
    {
        "validation_track": "M",
        "evaluation_date": "2024-01-09",
        "code": "SYN002",
        "factor_id": "synthetic_financial_factor",
        "label_id": "M-SYN002-20240109",
        "label_type": "return",
        "label_value": 0.02,
        "label_publish_date": "2024-01-10",
        "label_effective_date": "2024-01-10",
        "label_available_at": "2024-01-10",
        "label_source_record_id": "market-return-003",
        "label_source": "synthetic-market-source",
        "label_version": "m-label-v1",
        "label_snapshot_fingerprint": "m-snapshot-hash-v1",
        "synthetic_test_only": True,
    },
    {
        "validation_track": "F",
        "evaluation_date": "2024-01-08",
        "code": "SYN001",
        "factor_id": "synthetic_financial_factor",
        "label_id": "F-SYN001-20240108",
        "label_type": "target",
        "label_value": 1.2,
        "label_publish_date": "2024-04-20",
        "label_effective_date": "2024-04-22",
        "label_available_at": "2024-04-22",
        "label_source_record_id": "financial-target-001",
        "label_source": "synthetic-financial-target-source",
        "label_version": "f-label-v1",
        "label_snapshot_fingerprint": "f-snapshot-hash-v1",
        "target_report_period": "2023-12-31",
        "synthetic_test_only": True,
    },
    {
        "validation_track": "R",
        "evaluation_date": "2024-01-09",
        "code": "SYN002",
        "factor_id": "synthetic_financial_factor",
        "label_id": "R-SYN002-20240109",
        "label_type": "soft",
        "label_value": "yellow",
        "label_publish_date": "2024-02-01",
        "label_effective_date": "2024-02-01",
        "label_available_at": "2024-02-01",
        "label_source_record_id": "risk-label-001",
        "label_source": "synthetic-risk-source",
        "label_version": "r-label-v1",
        "label_snapshot_fingerprint": "r-snapshot-hash-v1",
        "synthetic_test_only": True,
    },
)


def make_synthetic_sample_inputs():
    batch, lineage_records, lineage_configuration = (
        make_synthetic_financial_inputs()
    )
    provenance = build_financial_provenance(
        batch,
        lineage_records,
        configuration=lineage_configuration,
    )
    assert provenance.observation_lineage_reference is not None
    configuration = SampleFormationConfig(
        evaluation_dates=("2024-01-08", "2024-01-09"),
        evaluation_calendar_version="synthetic-evaluation-calendar-v1",
        universe_version="synthetic-historical-universe-v1",
        freshness_max_age_days=30,
    )
    return (
        batch,
        provenance.observation_lineage_reference,
        deepcopy(list(UNIVERSE_RECORDS)),
        deepcopy(list(LABEL_RECORDS)),
        configuration,
    )
