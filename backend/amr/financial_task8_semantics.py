"""FIN-HO-8-A: frozen Task 8 financial value-semantics handshake.

This module freezes meanings only.  It does not select factors, calculate
research results, load data, or build a P05 candidate handoff package.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


_SCHEMA_VERSION = "FinancialTask8ValueSemantics-v1.0"


@dataclass(frozen=True)
class FinancialTask8ValueSemantics:
    schema_version: str
    raw_value_field: str
    evaluation_value_field: str
    neutralized_value_status: str
    financial_frequency: str
    evaluation_contexts: tuple[str, ...]
    sample_key: tuple[str, ...]
    common_sample_period_count: int
    common_sample_row_count_per_combination: int
    missing_value_policy: str
    stale_value_policy: str
    direction_policy: str
    comparison_policy: str
    production_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_FROZEN_SEMANTICS = FinancialTask8ValueSemantics(
    schema_version=_SCHEMA_VERSION,
    raw_value_field="raw_pit_factor_value",
    evaluation_value_field="evaluation_factor_value",
    neutralized_value_status="not_available_not_substitutable",
    financial_frequency="quarterly",
    evaluation_contexts=("M:20D",),
    sample_key=("evaluation_date", "code", "factor_id"),
    common_sample_period_count=18,
    common_sample_row_count_per_combination=900,
    missing_value_policy="no_zero_fill_record_isolated_or_fail_closed",
    stale_value_policy="effective_date_lte_evaluation_date_no_freshness_claim",
    direction_policy="original_direction_only_no_posthoc_flip",
    comparison_policy=(
        "same_frequency_same_key_same_pit_same_label_version_"
        "same_common_sample_same_evaluation_configuration"
    ),
    production_status="not production ready",
)


def get_financial_task8_value_semantics() -> FinancialTask8ValueSemantics:
    """Return the immutable, jointly confirmed Task 8 semantics."""
    return _FROZEN_SEMANTICS


def validate_financial_task8_value_semantics(
    semantics: FinancialTask8ValueSemantics,
) -> None:
    """Fail closed unless a candidate is exactly the confirmed policy."""
    if not isinstance(semantics, FinancialTask8ValueSemantics):
        raise TypeError("semantics must be FinancialTask8ValueSemantics")
    if semantics != _FROZEN_SEMANTICS:
        raise ValueError("Task 8 value semantics differ from the confirmed policy")


def serialize_financial_task8_value_semantics(
    semantics: FinancialTask8ValueSemantics | None = None,
) -> str:
    """Return canonical JSON with a content hash for later handoff binding."""
    resolved = semantics or _FROZEN_SEMANTICS
    validate_financial_task8_value_semantics(resolved)
    payload = resolved.to_dict()
    payload["content_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
