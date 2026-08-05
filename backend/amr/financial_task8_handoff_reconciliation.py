"""FIN-HO-8-B3-RECONCILE: fail-closed reconciliation to the P05 contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .financial_task8_handoff_schema import get_p05_candidate_handoff_schema
from .financial_task8_numeric_extraction import Task8NumericExtractionResult


P05_AUTHORITATIVE_PACKAGE_FIELDS = (
    "schema_version", "package_id", "created_at", "source_module", "producer_run_id",
    "producer_code_version", "factor_ids", "evaluation_frequency",
    "evaluation_calendar_version", "comparison_policy", "value_dataset_references",
    "sample_policy", "staleness_policy", "preprocessing_policy_version",
    "neutralization_policy_version", "source_snapshot_fingerprint",
    "factor_sample_fingerprint", "observation_lineage_reference", "content_hash",
    "row_count", "gate_result",
)
P05_AUTHORITATIVE_ROW_FIELDS = (
    "factor_id", "date", "code", "report_period", "publish_date", "effective_date",
    "raw_pit_factor_value", "evaluation_factor_value", "factor_value_variant",
    "factor_sample_mask", "staleness_status", "preprocessing_policy_version",
    "source_record_reference", "source_input_hash", "factor_value_hash",
)


@dataclass(frozen=True)
class ReconciliationIssue:
    code: str
    missing_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class P05HandoffReconciliation:
    status: str
    package_creation_allowed: bool
    issues: tuple[ReconciliationIssue, ...]
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def reconcile_financial_task8_handoff(
    extraction: Task8NumericExtractionResult,
) -> P05HandoffReconciliation:
    """Report contract gaps; it never adapts, fills, or emits a P05 package."""
    if not isinstance(extraction, Task8NumericExtractionResult):
        raise TypeError("extraction must be Task8NumericExtractionResult")
    schema = get_p05_candidate_handoff_schema()
    package_missing = tuple(field for field in P05_AUTHORITATIVE_PACKAGE_FIELDS if field not in schema.fields)
    extraction_fields = {
        "evaluation_date", "code", "factor_id", "raw_pit_factor_value",
        "evaluation_factor_value", "effective_date", "source_record_id", "source_content_hash",
    }
    row_missing = tuple(field for field in P05_AUTHORITATIVE_ROW_FIELDS if field not in extraction_fields)
    issues = (
        ReconciliationIssue("PACKAGE_SCHEMA_MISSING_REQUIRED_FIELDS", package_missing),
        ReconciliationIssue("ROW_SCHEMA_MISSING_REQUIRED_FIELDS", row_missing),
        ReconciliationIssue("COMPARISON_POLICY_NOT_STRUCTURED", (
            "status", "selected_variant", "approved_by", "approved_at",
        )),
    )
    payload = {
        "status": "blocked", "package_creation_allowed": False,
        "issues": [item.to_dict() for item in issues],
        "extraction_content_hash": extraction.content_hash,
    }
    return P05HandoffReconciliation(
        status="blocked", package_creation_allowed=False, issues=issues,
        content_hash=hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    )
