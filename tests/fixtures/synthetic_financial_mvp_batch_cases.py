"""Synthetic-only FIN-MVP-DATA fixtures for ROE, BP, and OCF_NP."""

import hashlib
from copy import deepcopy

from backend.amr.financial_lineage import build_financial_provenance
from backend.amr.financial_mvp_batch import (
    MVPBatchConfig,
    SUPPORTED_FACTOR_IDS,
    formula_definition_for,
)
from backend.amr.financial_sample import (
    SampleFormationConfig,
    form_financial_sample,
)
from backend.amr.financial_source_adapter import (
    adapt_financial_source_records,
)
from backend.amr.financial_timing import FinancialTimingPolicy


CODE = "SYNMVP001"
REPORT_PERIOD = "2023-09-30"
PUBLISH_DATE = "2024-01-05"
EFFECTIVE_DATE = "2024-01-08"
EVALUATION_DATE = "2024-01-08"

FORMULA_INPUTS = {
    "ROE": {
        "parent_net_profit_ttm": 20.0,
        "average_parent_equity": 100.0,
    },
    "BP": {
        "parent_equity": 50.0,
        "market_cap": 200.0,
    },
    "OCF_NP": {
        "operating_cash_flow_ttm": 30.0,
        "parent_net_profit_ttm": 20.0,
    },
}

EXPECTED_FACTOR_VALUES = {
    "ROE": 0.2,
    "BP": 0.25,
    "OCF_NP": 1.5,
}

SYNTHETIC_FUTURE_LABELS = (
    {
        "evaluation_date": EVALUATION_DATE,
        "code": CODE,
        "future_return": 0.99,
        "future_target": 12345,
        "risk_label": "red",
    },
)


def make_mvp_batch_inputs(path_type="A"):
    if path_type not in {"A", "B"}:
        raise ValueError("path_type must be A or B")
    records = []
    lineage_references = {}
    sample_references = {}
    for factor_id in SUPPORTED_FACTOR_IDS:
        record, lineage_reference, sample_reference = _factor_case(
            factor_id, path_type
        )
        records.append(record)
        lineage_references[factor_id] = lineage_reference
        sample_references[factor_id] = sample_reference
    return (
        records,
        lineage_references,
        sample_references,
        MVPBatchConfig(),
        deepcopy(list(SYNTHETIC_FUTURE_LABELS)),
    )


def _factor_case(factor_id, path_type):
    value = EXPECTED_FACTOR_VALUES[factor_id]
    source_record_id = f"mvp-{factor_id.lower()}-{path_type.lower()}-001"
    statement_version = "statement-original"
    policy = FinancialTimingPolicy(
        trading_days=(
            "2024-01-05",
            "2024-01-08",
            "2024-01-09",
        ),
        trading_calendar_version="synthetic-mvp-calendar-v1",
    )
    raw_source = {
        "code": CODE,
        "report_period": REPORT_PERIOD,
        "publish_date": PUBLISH_DATE,
        "announcement_timestamp": "2024-01-05T16:10:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "statement_version": statement_version,
        "source_record_id": source_record_id,
        "factor_value": value,
        "synthetic_test_only": True,
    }
    adaptation = adapt_financial_source_records(
        [deepcopy(raw_source)],
        factor_id=factor_id,
        version="FIN-MVP-UPSTREAM-v1.0",
        source="synthetic-mvp-upstream",
        policy=policy,
    )
    assert adaptation.batch is not None
    timing_audit = adaptation.timing_audits[0]
    assert timing_audit.derived_effective_date == EFFECTIVE_DATE

    formula = formula_definition_for(factor_id)
    upstream_reference = f"upstream-run://mvp/{factor_id}/v1"
    lineage_input = {
        "evaluation_date": EVALUATION_DATE,
        "code": CODE,
        "factor_id": factor_id,
        "report_period": REPORT_PERIOD,
        "publish_date": PUBLISH_DATE,
        "effective_date": EFFECTIVE_DATE,
        "factor_value": value,
        "path_type": path_type,
        "source_provider": "synthetic-mvp-provider",
        "source_dataset": f"synthetic-mvp-{factor_id.lower()}",
        "source_snapshot_id": "snapshot-2024-01-08",
        "source_as_of_version": "2024-01-08T18:00:00+08:00",
        "source_record_id": source_record_id,
        "announcement_id": "not_applicable",
        "financial_statement_version": statement_version,
        "revision_version": "original",
        "supersedes_reference": "not_applicable",
        "transformation_reference": "synthetic-mvp-transform-v1",
        "formula_reference": (
            formula.formula_reference
            if path_type == "B"
            else "not_applicable"
        ),
        "upstream_calculation_reference": (
            upstream_reference if path_type == "A" else "not_applicable"
        ),
        "source_input_payload": {
            "prepared_formula_inputs": deepcopy(FORMULA_INPUTS[factor_id]),
            "source_record_id": source_record_id,
        },
        "source_snapshot_manifest": {
            "factor_id": factor_id,
            "source_record_id": source_record_id,
            "object_count": 1,
            "manifest_version": "synthetic-mvp-manifest-v1",
        },
        "timing_audit": timing_audit,
        "synthetic_test_only": True,
    }
    provenance = build_financial_provenance(
        adaptation.batch,
        [lineage_input],
        configuration={
            "factor_id": factor_id,
            "upstream_version": "FIN-MVP-UPSTREAM-v1.0",
        },
    )
    assert provenance.observation_lineage_reference is not None

    sample = form_financial_sample(
        adaptation.batch,
        provenance.observation_lineage_reference,
        [
            {
                "evaluation_date": EVALUATION_DATE,
                "code": CODE,
                "universe_record_id":
                    f"mvp-universe-{factor_id}-{EVALUATION_DATE}",
                "in_universe": True,
                "factor_applicable": True,
                "listed_date": "2020-01-01",
                "delisted_date": None,
                "synthetic_test_only": True,
            }
        ],
        [],
        configuration=SampleFormationConfig(
            evaluation_dates=(EVALUATION_DATE,),
            evaluation_calendar_version="synthetic-mvp-eval-calendar-v1",
            universe_version="synthetic-mvp-universe-v1",
            freshness_max_age_days=30,
        ),
    )
    assert sample.sample_reference is not None
    lineage = provenance.lineage_records[0]
    record = {
        "evaluation_date": EVALUATION_DATE,
        "code": CODE,
        "factor_id": factor_id,
        "report_period": REPORT_PERIOD,
        "publish_date": PUBLISH_DATE,
        "effective_date": EFFECTIVE_DATE,
        "path_type": path_type,
        "source_snapshot_fingerprint":
            lineage.source_snapshot_fingerprint,
        "synthetic_test_only": True,
    }
    if path_type == "A":
        upstream_version = f"UPSTREAM-{factor_id}-v1.0"
        upstream_hash = hashlib.sha256(
            (
                factor_id
                + upstream_version
                + source_record_id
                + str(value)
            ).encode("utf-8")
        ).hexdigest()
        record.update(
            {
                "factor_value": value,
                "upstream_calculation_reference": upstream_reference,
                "upstream_calculation_version": upstream_version,
                "upstream_calculation_hash": upstream_hash,
            }
        )
    else:
        record.update(
            {
                "formula_id": formula.formula_id,
                "formula_version": formula.formula_version,
                "formula_inputs": deepcopy(FORMULA_INPUTS[factor_id]),
                "formula_input_references": (
                    f"{source_record_id}:numerator",
                    f"{source_record_id}:denominator",
                ),
            }
        )
    return (
        record,
        provenance.observation_lineage_reference,
        sample.sample_reference,
    )
