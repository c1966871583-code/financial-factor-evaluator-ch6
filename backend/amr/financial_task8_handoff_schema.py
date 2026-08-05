"""FIN-HO-8-B1: schema-only contract for a later P05 handoff package."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .financial_task8_semantics import serialize_financial_task8_value_semantics


P05_HANDOFF_SCHEMA_VERSION = "P05CandidateHandoffPackage-v1.0"
P05_HANDOFF_PACKAGE_FIELDS = (
    "schema_version",
    "semantic_policy_content_hash",
    "comparison_policy",
    "candidate_id",
    "candidate_kind",
    "candidate_definition_hash",
    "row_count",
    "sample_fingerprint",
    "records_fingerprint",
    "row_lineage",
    "manifest",
    "content_hash",
    "production_status",
)
P05_FORBIDDEN_SELECTION_FIELDS = (
    "best_candidate",
    "selected_candidate",
    "selected_factor",
    "selected_combination",
    "selection_score",
)


@dataclass(frozen=True)
class P05CandidateHandoffSchema:
    schema_version: str
    fields: tuple[str, ...]
    required_nonempty_fields: tuple[str, ...]
    forbidden_fields: tuple[str, ...]
    semantic_policy_content_hash: str
    production_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def get_p05_candidate_handoff_schema() -> P05CandidateHandoffSchema:
    """Return the immutable schema, without creating a handoff package."""
    semantics = json.loads(serialize_financial_task8_value_semantics())
    return P05CandidateHandoffSchema(
        schema_version=P05_HANDOFF_SCHEMA_VERSION,
        fields=P05_HANDOFF_PACKAGE_FIELDS,
        required_nonempty_fields=(
            "semantic_policy_content_hash",
            "comparison_policy",
            "candidate_id",
            "candidate_kind",
            "candidate_definition_hash",
            "sample_fingerprint",
            "records_fingerprint",
            "row_lineage",
            "manifest",
            "content_hash",
            "production_status",
        ),
        forbidden_fields=P05_FORBIDDEN_SELECTION_FIELDS,
        semantic_policy_content_hash=str(semantics["content_hash"]),
        production_status="not production ready",
    )


def serialize_p05_candidate_handoff_schema(
    schema: P05CandidateHandoffSchema | None = None,
) -> str:
    """Canonical deterministic serialization for the schema freeze."""
    resolved = schema or get_p05_candidate_handoff_schema()
    expected = get_p05_candidate_handoff_schema()
    if not isinstance(resolved, P05CandidateHandoffSchema):
        raise TypeError("schema must be P05CandidateHandoffSchema")
    if resolved != expected:
        raise ValueError("P05 handoff schema differs from the frozen contract")
    payload = resolved.to_dict()
    payload["content_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
