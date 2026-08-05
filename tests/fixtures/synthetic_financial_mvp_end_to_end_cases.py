"""Reusable synthetic provider for FIN-MVP-TEST."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

from backend.amr.financial_mvp_output import (
    FinancialMVPOutputConfig,
    FinancialMVPOutputResult,
    build_financial_mvp_output,
)
from backend.amr.financial_mvp_robustness import (
    FinancialMVPRobustnessConfig,
    FinancialMVPRobustnessResult,
    evaluate_financial_mvp_robustness,
)
from backend.amr.financial_mvp_m_evaluation import (
    FinancialMVPMEvaluationResult,
    evaluate_financial_mvp_m,
)
from tests.fixtures.synthetic_financial_mvp_m_evaluation_cases import (
    EVALUATION_DATES,
    make_forward_returns,
    make_golden_case,
)
from tests.fixtures.synthetic_financial_mvp_robustness_cases import (
    make_m_configuration,
)


FIXTURE_SCHEMA_VERSION = "SyntheticFinancialMVPEndToEnd-v1.0"
FIXTURE_ID = "financial-mvp-three-factor-2024-v1"
GOLDEN_SNAPSHOT_SCHEMA_VERSION = "FinancialMVPGoldenSnapshot-v1.0"


class ExplodingFutureLabels:
    """Fails if an upstream formula/batch path observes future labels."""

    def __iter__(self):
        raise AssertionError("future labels must not be iterated")

    def __deepcopy__(self, memo):
        raise AssertionError("future labels must not be copied")

    def __repr__(self):
        raise AssertionError("future labels must not be serialized")


@dataclass(frozen=True)
class SyntheticFinancialMVPEndToEndCase:
    fixture_schema_version: str
    fixture_id: str
    mvp_batch_result: Any
    preprocessing_result: Any
    forward_returns: Any
    m_evaluation_result: FinancialMVPMEvaluationResult
    robustness_result: FinancialMVPRobustnessResult
    output_result: FinancialMVPOutputResult
    m_evaluation_configuration: Any
    robustness_configuration: FinancialMVPRobustnessConfig
    output_configuration: FinancialMVPOutputConfig
    mutation_guard_before: str
    mutation_guard_after: str

    @property
    def inputs_unchanged(self) -> bool:
        return self.mutation_guard_before == self.mutation_guard_after


class SyntheticFinancialMVPFixtureProvider:
    """Construct the approved three-factor MVP chain in memory."""

    def load(
        self,
        *,
        label_multiplier: float = 1.0,
        missing_labels: set[tuple[str, str]] | None = None,
        constant_return_dates: set[str] | None = None,
    ) -> SyntheticFinancialMVPEndToEndCase:
        mvp, preprocessing, _ = make_golden_case()
        forward_returns = make_forward_returns(
            missing=missing_labels,
            constant_dates=constant_return_dates,
        )
        if label_multiplier != 1.0:
            frame = forward_returns.get_frame()
            frame["forward_return"] = (
                frame["forward_return"] * float(label_multiplier)
            )
            forward_returns = replace(
                forward_returns,
                _frame=frame,
                version=(
                    f"{forward_returns.version}-"
                    f"multiplier-{label_multiplier}"
                ),
            )
        m_configuration = make_m_configuration()
        robustness_configuration = FinancialMVPRobustnessConfig(
            m_configuration
        )
        output_configuration = FinancialMVPOutputConfig(
            m_configuration,
            robustness_configuration,
        )
        before = _input_guard(
            mvp, preprocessing, forward_returns
        )
        m_result = evaluate_financial_mvp_m(
            mvp,
            preprocessing,
            forward_returns,
            configuration=m_configuration,
        )
        robustness = evaluate_financial_mvp_robustness(
            mvp,
            preprocessing,
            forward_returns,
            m_result,
            configuration=robustness_configuration,
        )
        output = build_financial_mvp_output(
            mvp,
            preprocessing,
            forward_returns,
            m_result,
            robustness,
            configuration=output_configuration,
        )
        after = _input_guard(
            mvp, preprocessing, forward_returns
        )
        return SyntheticFinancialMVPEndToEndCase(
            fixture_schema_version=FIXTURE_SCHEMA_VERSION,
            fixture_id=FIXTURE_ID,
            mvp_batch_result=mvp,
            preprocessing_result=preprocessing,
            forward_returns=forward_returns,
            m_evaluation_result=m_result,
            robustness_result=robustness,
            output_result=output,
            m_evaluation_configuration=m_configuration,
            robustness_configuration=robustness_configuration,
            output_configuration=output_configuration,
            mutation_guard_before=before,
            mutation_guard_after=after,
        )


def build_golden_snapshot(
    case: SyntheticFinancialMVPEndToEndCase,
) -> dict[str, Any]:
    """Return the review-sized deterministic snapshot."""

    mvp = case.mvp_batch_result
    preprocessing = case.preprocessing_result
    m_result = case.m_evaluation_result
    robustness = case.robustness_result
    output = case.output_result
    run = output.financial_evaluation_run
    assert run is not None
    observation_reference = mvp.observation_reference
    assert observation_reference is not None
    return {
        "snapshot_schema_version": GOLDEN_SNAPSHOT_SCHEMA_VERSION,
        "fixture_schema_version": case.fixture_schema_version,
        "fixture_id": case.fixture_id,
        "factor_ids": list(run.supported_factor_ids),
        "evaluation_dates": list(EVALUATION_DATES),
        "return_horizon": run.return_horizon,
        "counts": {
            "financial_batches": len(mvp.batches),
            "public_batch_rows": {
                item.factor_id: len(item.get_frame())
                for item in mvp.batches
            },
            "observation_sidecar_rows":
                observation_reference.row_count,
            "prepared_factor_rows": len(
                preprocessing.prepared_inputs
            ),
            "mad_audit_rows": len(preprocessing.mad_audits),
            "factor_summaries": len(
                output.factor_evaluation_summaries
            ),
        },
        "gates": {
            "mvp_batch":
                mvp.financial_batch_audit.gate_status,
            "preprocessing":
                preprocessing.preprocessing_audit.gate_status,
            "m_evaluation":
                m_result.evaluation_audit.gate_status,
            "robustness":
                robustness.robustness_audit.gate_status,
            "output": output.output_audit.gate_status,
        },
        "m_evaluation": {
            item.factor_id: {
                "status": item.overall_status.value,
                "rank_ic_mean": item.rank_ic_mean,
                "pearson_ic_mean": item.pearson_ic_mean,
                "rank_ic_ir": item.rank_ic_ir,
                "rank_ic_t_stat": item.rank_ic_t_stat,
                "rank_ic_positive_ratio":
                    item.rank_ic_positive_ratio,
                "long_short_mean": item.long_short_mean,
                "monotonicity_spearman":
                    item.monotonicity_spearman,
                "effective_dates": item.evaluated_dates,
                "paired_observations": item.total_observations,
            }
            for item in m_result.common_results
        },
        "robustness": {
            item.factor_id: {
                "preprocessing_consistency":
                    item.preprocessing_consistency,
                "subperiod_direction_consistency":
                    item.subperiod_direction_consistency,
                "best_cell_selected": item.best_cell_selected,
                "cell_count": len(item.cells),
            }
            for item in robustness.factor_summaries
        },
        "output": {
            "run_id": run.run_id,
            "run_content_hash": run.content_hash,
            "output_audit_hash": output.output_audit.content_hash,
            "summary_hashes": {
                item.factor_id: item.content_hash
                for item in output.factor_evaluation_summaries
            },
            "summary_statuses": {
                item.factor_id: item.status_summary.to_dict()
                for item in output.factor_evaluation_summaries
            },
        },
        "input_mutation_guard": {
            "before": case.mutation_guard_before,
            "after": case.mutation_guard_after,
            "unchanged": case.inputs_unchanged,
        },
    }


def _input_guard(mvp, preprocessing, forward_returns) -> str:
    reference = mvp.observation_reference
    payload = {
        "mvp": {
            **mvp.to_dict(include_rows=True),
            "observation_reference": (
                reference.to_dict(include_records=True)
                if reference is not None
                else None
            ),
        },
        "preprocessing": {
            "prepared_inputs": [
                item.to_dict()
                for item in preprocessing.prepared_inputs
            ],
            "mad_audits": [
                item.to_dict() for item in preprocessing.mad_audits
            ],
            "audit":
                preprocessing.preprocessing_audit.to_dict(),
        },
        "returns": forward_returns.get_frame().to_dict(
            orient="records"
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
