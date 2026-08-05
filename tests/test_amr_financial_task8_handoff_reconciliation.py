from __future__ import annotations

from backend.amr.financial_task8_handoff_reconciliation import reconcile_financial_task8_handoff
from backend.amr.financial_task8_numeric_extraction import extract_financial_task8_approved_numeric_datasets
from tests.fixtures.synthetic_financial_task8_numeric_cases import make_batches


def test_reconciliation_fails_closed_and_does_not_create_a_p05_package():
    extraction = extract_financial_task8_approved_numeric_datasets(make_batches())
    result = reconcile_financial_task8_handoff(extraction)
    assert result.status == "blocked"
    assert result.package_creation_allowed is False
    issues = {item.code: item.missing_fields for item in result.issues}
    assert "package_id" in issues["PACKAGE_SCHEMA_MISSING_REQUIRED_FIELDS"]
    assert "report_period" in issues["ROW_SCHEMA_MISSING_REQUIRED_FIELDS"]
    assert issues["COMPARISON_POLICY_NOT_STRUCTURED"] == (
        "status", "selected_variant", "approved_by", "approved_at",
    )


def test_reconciliation_is_deterministic():
    first = reconcile_financial_task8_handoff(extract_financial_task8_approved_numeric_datasets(make_batches()))
    second = reconcile_financial_task8_handoff(extract_financial_task8_approved_numeric_datasets(make_batches()))
    assert first == second
