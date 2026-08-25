"""Phase-1 sector routing and independent M/F/R contract tests."""

from __future__ import annotations

import json

import pytest

from backend.amr.financial_evidence_contracts import (
    FinancialEvidenceType,
    FinancialP2EvidenceGateSummary,
    FinancialP2ResultReference,
    deserialize_financial_evidence_gate_execution,
    execute_financial_evidence_gate,
    financial_evidence_content_hash,
    serialize_financial_evidence,
    serialize_financial_evidence_gate_execution,
)
from backend.amr.financial_mvp_batch import (
    FORMULA_REGISTRY,
    FormulaCalculationStatus,
    evaluate_registered_mvp_formula,
)
from backend.amr.financial_p2_f_evidence import FinancialP2FEvidenceResult
from backend.amr.financial_p2_m_enhancement import FinancialP2MEnhancementResult
from backend.amr.financial_p2_r_evidence import FinancialP2REvidenceResult


def _evaluate(factor_id, sector_type, inputs, **kwargs):
    return evaluate_registered_mvp_formula(
        factor_id, inputs, sector_type=sector_type, **kwargs
    )


@pytest.mark.parametrize(
    "sector", ["BANK", "INSURANCE", "SECURITIES", "DIVERSIFIED_FINANCIAL"]
)
def test_ocf_np_financial_sectors_are_not_applicable(sector):
    result = _evaluate(
        "OCF_NP",
        sector,
        {"operating_cash_flow_ttm": 12.0, "parent_net_profit_ttm": 3.0},
    )
    assert result.status == FormulaCalculationStatus.NOT_APPLICABLE.value
    assert result.value is None


def test_ocf_np_non_financial_calculates_and_crossing_sign_is_preserved():
    result = _evaluate(
        "OCF_NP",
        "NON_FINANCIAL",
        {"operating_cash_flow_ttm": 12.0, "parent_net_profit_ttm": -3.0},
    )
    assert result.status == "VALID"
    assert result.value == -4.0


@pytest.mark.parametrize("sector", [None, "", "UNKNOWN"])
def test_missing_or_unknown_sector_fails_closed(sector):
    result = _evaluate(
        "ROE",
        sector,
        {"parent_net_profit_ttm": 1.0, "average_parent_equity": 2.0},
    )
    assert result.status == "SECTOR_CLASSIFICATION_MISSING"
    assert result.value is None


@pytest.mark.parametrize("equity", [0.0, -1.0])
def test_roe_non_positive_equity_is_invalid(equity):
    result = _evaluate(
        "ROE",
        "NON_FINANCIAL",
        {"parent_net_profit_ttm": -1.0, "average_parent_equity": equity},
    )
    assert result.status == "INVALID_DENOMINATOR"


@pytest.mark.parametrize("market_cap", [0.0, -1.0])
def test_bp_non_positive_market_cap_is_invalid(market_cap):
    result = _evaluate(
        "BP",
        "NON_FINANCIAL",
        {"parent_equity": 2.0, "market_cap": market_cap},
        market_cap_as_of="2026-08-20",
        evaluation_date="2026-08-20",
    )
    assert result.status == "INVALID_DENOMINATOR"


def test_bp_non_positive_equity_and_mismatched_as_of_are_invalid():
    negative_equity = _evaluate(
        "BP",
        "BANK",
        {"parent_equity": 0.0, "market_cap": 10.0},
        market_cap_as_of="2026-08-20",
        evaluation_date="2026-08-20",
    )
    wrong_date = _evaluate(
        "BP",
        "BANK",
        {"parent_equity": 2.0, "market_cap": 10.0},
        market_cap_as_of="2026-08-19",
        evaluation_date="2026-08-20",
    )
    assert negative_equity.status == wrong_date.status == "INVALID_DENOMINATOR"


def test_declared_sector_mismatch_blocks():
    result = _evaluate(
        "ROE",
        "BANK",
        {"parent_net_profit_ttm": 1.0, "average_parent_equity": 2.0},
        declared_sector_type="NON_FINANCIAL",
    )
    assert result.status == "SECTOR_FORMULA_MISMATCH"


def test_registry_expresses_full_applicability_and_policy():
    assert {item.factor_id for item in FORMULA_REGISTRY} == {"ROE", "BP", "OCF_NP"}
    for definition in FORMULA_REGISTRY:
        assert definition.effective_from == "2026-08-20"
        assert definition.denominator_policy
        assert definition.fallback_policy == "NO_FALLBACK"
        assert definition.sector_mapping_version


class _Stub:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload


def _track_results():
    return (
        FinancialP2MEnhancementResult((), _Stub({"gate_status": "ready"})),
        FinancialP2FEvidenceResult((), _Stub({"gate_status": "ready"})),
        FinancialP2REvidenceResult(
            (), (), _Stub({"pr_auc": 0.5}), _Stub({"gate_status": "ready"})
        ),
    )


def test_m_f_r_have_independent_discriminators_schemas_and_hashes():
    results = _track_results()
    serialized = [
        serialize_financial_evidence(result, kind)
        for result, kind in zip(results, FinancialEvidenceType)
    ]
    assert [item["evidence_type"] for item in serialized] == ["M", "F", "R"]
    assert len({item["schema_version"] for item in serialized}) == 3
    assert len({item["content_hash"] for item in serialized}) == 3
    json.dumps(serialized, sort_keys=True, allow_nan=False)


@pytest.mark.parametrize(("wrong_index", "kind"), [(1, "M"), (2, "F"), (0, "R")])
def test_evidence_type_rejects_wrong_payload(wrong_index, kind):
    with pytest.raises(TypeError):
        serialize_financial_evidence(_track_results()[wrong_index], kind)


def test_gate_summary_contains_references_not_track_metrics():
    m_result = _track_results()[0]
    digest = financial_evidence_content_hash(m_result, "M")
    summary = FinancialP2EvidenceGateSummary(
        (
            FinancialP2ResultReference(
                "evidence-m",
                "M",
                "FinancialP2MEnhancement-v1.0",
                "READY",
                digest,
                "audit://m",
            ),
        )
    )
    payload = summary.to_dict()
    assert set(payload) == {"schema_version", "references"}
    keys = set(payload["references"][0])
    assert keys == {
        "evidence_id",
        "evidence_type",
        "schema_version",
        "status",
        "content_hash",
        "audit_ref",
    }
    assert "ic" not in json.dumps(payload).lower()


def test_execution_gate_binds_real_track_results_and_round_trips():
    m_result, f_result, r_result = _track_results()
    execution = execute_financial_evidence_gate(
        m_result=m_result,
        f_result=f_result,
        r_result=r_result,
    )
    assert execution.gate_status == "ready"
    assert execution.admission_allowed is True
    assert execution.archive_allowed is True
    assert tuple(item.evidence_type for item in execution.summary.references) == (
        "M",
        "F",
        "R",
    )
    restored = deserialize_financial_evidence_gate_execution(
        serialize_financial_evidence_gate_execution(execution)
    )
    assert restored == execution


def test_failed_track_blocks_admission_and_archive_with_stage_reason():
    m_result, f_result, r_result = _track_results()
    f_result = FinancialP2FEvidenceResult(
        (), _Stub({"gate_status": "blocked", "errors": [{"code": "F_FAILED"}]})
    )
    execution = execute_financial_evidence_gate(
        m_result=m_result,
        f_result=f_result,
        r_result=r_result,
    )
    assert execution.gate_status == "blocked"
    assert execution.admission_allowed is False
    assert execution.archive_allowed is False
    f_log = next(item for item in execution.stage_logs if item.evidence_type == "F")
    assert f_log.execution_stage == "F_FORECAST"
    assert "F_FAILED" in f_log.reason
