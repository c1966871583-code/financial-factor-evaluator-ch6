"""Expanded deterministic fixture for FIN-P2-M-ENH."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pandas as pd

from backend.amr.evaluation_input_contract import (
    FactorType,
    FinancialBatch,
    ForwardReturnBatch,
    ValueScope,
)
from backend.amr.financial_lineage import compute_factor_value_hash
from backend.amr.financial_mvp_batch import (
    MVP_AUDIT_SCHEMA_VERSION,
    MVP_BATCH_SCHEMA_VERSION,
    SUPPORTED_FACTOR_IDS,
    FinancialBatchAudit,
    MVPBatchObservation,
    MVPBatchObservationReference,
    MVPFinancialBatchResult,
    formula_definition_for,
    recompute_observation_content_hash,
)
from backend.amr.financial_preprocessing import (
    FinancialPreprocessingConfig,
    FinancialPreprocessingResult,
    prepare_financial_formula_inputs,
)
from tests.fixtures.synthetic_financial_preprocessing_cases import (
    make_preprocessing_record,
)


EVALUATION_DATES = (
    "2023-07-31",
    "2023-08-31",
    "2023-09-28",
    "2023-10-31",
    "2023-11-30",
    "2023-12-29",
    "2024-01-31",
    "2024-02-29",
    "2024-03-29",
    "2024-04-30",
    "2024-05-31",
    "2024-06-28",
    "2024-07-31",
    "2024-08-30",
    "2024-09-30",
    "2024-10-31",
    "2024-11-29",
    "2024-12-31",
)
SECURITY_COUNT = 60
HORIZONS = (5, 20, 60)
RETURN_SET_ID = "synthetic-financial-p2-m-enh-5-20-60-v1"
NEGATIVE_MONTHS = {
    5: frozenset({3, 7, 11, 15}),
    20: frozenset({2, 5, 8, 11, 14, 17}),
    60: frozenset({1, 3, 5, 7, 9, 11, 13, 15}),
}


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def codes(security_count: int = SECURITY_COUNT) -> tuple[str, ...]:
    return tuple(
        f"SYNP2M{index:04d}"
        for index in range(1, security_count + 1)
    )


def make_preprocessing_result(
    security_count: int = SECURITY_COUNT,
) -> FinancialPreprocessingResult:
    records = []
    for evaluation_date in EVALUATION_DATES:
        if evaluation_date.startswith("2023-"):
            timing = {
                "report_period": "2023-03-31",
                "publish_date": "2023-04-28",
                "effective_date": "2023-05-04",
            }
        else:
            timing = {
                "report_period": "2023-09-30",
                "publish_date": "2024-01-05",
                "effective_date": "2024-01-08",
            }
        for index, code in enumerate(
            codes(security_count), start=1
        ):
            net_profit = 10.0 + index
            record = make_preprocessing_record(
                code=code,
                evaluation_date=evaluation_date,
                parent_net_profit_ttm=net_profit,
                operating_cash_flow_ttm=net_profit * (
                    0.50 + index / security_count
                ),
                parent_equity=100.0 + index,
                prior_year_same_period_parent_equity=100.0 + index,
                market_cap=200.0,
                **timing,
            )
            record["source_snapshot_fingerprint"] = _sha(
                f"p2-m-snapshot-{code}"
            )
            records.append(record)
    result = prepare_financial_formula_inputs(
        records,
        configuration=FinancialPreprocessingConfig(
            minimum_cross_section_size=30
        ),
    )
    assert result.preprocessing_audit.gate_status == "ready"
    return result


def make_mvp_result(
    preprocessing_result: FinancialPreprocessingResult,
    *,
    security_count: int = SECURITY_COUNT,
) -> MVPFinancialBatchResult:
    observations = []
    for item in preprocessing_result.prepared_inputs:
        definition = formula_definition_for(item.factor_id)
        base = MVPBatchObservation(
            schema_version=MVP_BATCH_SCHEMA_VERSION,
            observation_id=(
                f"p2-m://{item.evaluation_date}/{item.code}/"
                f"{item.factor_id}"
            ),
            evaluation_date=item.evaluation_date,
            code=item.code,
            factor_id=item.factor_id,
            report_period=item.report_period,
            publish_date=item.publish_date,
            effective_date=item.effective_date,
            factor_value=item.raw_pit_factor_value,
            factor_value_hash=compute_factor_value_hash(
                item.raw_pit_factor_value
            ),
            path_type="B",
            upstream_calculation_reference="not_applicable",
            upstream_calculation_version="not_applicable",
            upstream_calculation_hash=_sha("not-applicable-upstream"),
            formula_id=definition.formula_id,
            formula_version=definition.formula_version,
            formula_reference=definition.formula_reference,
            formula_input_hash=item.preparation_input_hash,
            formula_input_references=item.formula_input_references,
            source_snapshot_fingerprint=(
                item.source_snapshot_fingerprint
            ),
            financial_lineage_id=(
                f"lineage://{item.code}/{item.factor_id}"
            ),
            financial_lineage_content_hash=_sha(
                f"lineage-{item.code}-{item.factor_id}"
            ),
            financial_lineage_reference=(
                f"lineage-ref://{item.factor_id}"
            ),
            sample_id=f"sample://{item.evaluation_date}/{item.code}",
            sample_content_hash=_sha(
                f"sample-{item.evaluation_date}-{item.code}"
            ),
            sample_reference=f"sample-ref://{item.factor_id}",
            factor_sample_mask=True,
            content_hash="",
        )
        observations.append(
            replace(
                base,
                content_hash=recompute_observation_content_hash(base),
            )
        )
    observations.sort(
        key=lambda item: (
            item.evaluation_date,
            item.code,
            item.factor_id,
        )
    )
    batches = []
    for factor_id in SUPPORTED_FACTOR_IDS:
        seen = {}
        for item in observations:
            if item.factor_id != factor_id:
                continue
            key = (item.code, item.report_period, item.effective_date)
            seen[key] = {
                "code": item.code,
                "report_period": item.report_period,
                "publish_date": item.publish_date,
                "effective_date": item.effective_date,
                "factor_value": item.factor_value,
            }
        batches.append(
            FinancialBatch(
                factor_id=factor_id,
                factor_type=FactorType.FINANCIAL,
                value_scope=ValueScope.SECURITY_LEVEL,
                version="FIN-P2-M-ENH-synthetic-v1",
                source="synthetic-financial-p2-m-enh",
                _frame=pd.DataFrame(list(seen.values())),
                frequency="quarterly",
                universe=f"synthetic-{security_count}",
                provenance={"synthetic_test_only": True},
            )
        )
    reference = MVPBatchObservationReference(
        location="memory://synthetic-financial-p2-m-enh",
        schema_version=MVP_BATCH_SCHEMA_VERSION,
        row_count=len(observations),
        index_fields=("evaluation_date", "code", "factor_id"),
        content_hash=_sha("p2-m-observation-reference"),
        records=tuple(observations),
    )
    audit = FinancialBatchAudit(
        schema_version=MVP_AUDIT_SCHEMA_VERSION,
        run_id="synthetic-financial-p2-m-enh-run",
        supported_factor_ids=SUPPORTED_FACTOR_IDS,
        path_a_count=0,
        path_b_count=len(observations),
        total_input_count=len(observations),
        accepted_count=len(observations),
        rejected_count=0,
        conflict_count=0,
        timing_references=("synthetic-timing://v1",),
        provenance_references=("synthetic-lineage://v1",),
        sample_references=("synthetic-sample://v1",),
        batch_fingerprints=tuple(
            (factor_id, _sha(f"p2-m-batch-{factor_id}"))
            for factor_id in SUPPORTED_FACTOR_IDS
        ),
        gate_status="ready",
        errors=(),
        warnings=(),
        content_hash=_sha("p2-m-batch-audit"),
    )
    return MVPFinancialBatchResult(
        batches=tuple(batches),
        observation_reference=reference,
        financial_batch_audit=audit,
    )


def make_forward_returns(
    *,
    security_count: int = SECURITY_COUNT,
    horizons: tuple[int, ...] = HORIZONS,
    missing: set[tuple[str, str, int]] | None = None,
    duplicate_key: tuple[str, str, int] | None = None,
    reverse_all: bool = False,
    synthetic_test_only: bool = True,
) -> ForwardReturnBatch:
    missing = missing or set()
    rows = []
    for horizon in horizons:
        for date_index, evaluation_date in enumerate(EVALUATION_DATES):
            ascending = date_index not in NEGATIVE_MONTHS[horizon]
            if reverse_all:
                ascending = not ascending
            for code_index, code in enumerate(
                codes(security_count), start=1
            ):
                key = (evaluation_date, code, horizon)
                if key in missing:
                    continue
                rank = (
                    code_index
                    if ascending
                    else security_count + 1 - code_index
                )
                rows.append(
                    {
                        "date": evaluation_date,
                        "code": code,
                        "horizon": horizon,
                        "forward_return": rank / 1000.0,
                    }
                )
    if duplicate_key is not None:
        for row in rows:
            if (
                row["date"],
                row["code"],
                row["horizon"],
            ) == duplicate_key:
                rows.append(dict(row))
                break
    return ForwardReturnBatch(
        return_set_id=RETURN_SET_ID,
        value_scope=ValueScope.SECURITY_LEVEL,
        version="synthetic-5-20-60-v1",
        source="synthetic-financial-p2-m-enh",
        return_definition="close(t+h)/close(t)-1; h in {5,20,60}",
        _frame=pd.DataFrame(rows),
        frequency="month_end",
        universe=f"synthetic-{security_count}",
        provenance={"synthetic_test_only": synthetic_test_only},
    )


def make_golden_case(
    security_count: int = SECURITY_COUNT,
):
    preprocessing = make_preprocessing_result(security_count)
    return (
        make_mvp_result(
            preprocessing, security_count=security_count
        ),
        preprocessing,
        make_forward_returns(security_count=security_count),
    )
