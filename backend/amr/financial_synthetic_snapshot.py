"""Deterministic synthetic-only contract test for PRE-01 financial snapshots.

This module is deliberately not an authoritative-source adapter.  It accepts
only explicitly labelled synthetic records and exists to exercise the frozen
PRE-01 snapshot contract before real upstream data are available.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping


SNAPSHOT_SCHEMA_VERSION = "FinancialQuarterlySyntheticSnapshot-v1.0"
HASH_CONTRACT_VERSION = "FIN-HO-8-B3A-PRE-01-SYNTHETIC-HASH-v1.0"
PRIMARY_KEY = ("code", "report_period", "factor_id", "evaluation_date")
REQUIRED_FIELDS = (
    "synthetic_test_only", "code", "report_period", "publish_date",
    "effective_date", "evaluation_date", "factor_id", "source_record_id",
    "announcement_or_revision_version", "upstream_run_id", "factor_sample_mask",
    "inclusion_or_exclusion_reason", "common_sample_id", "sample_fingerprint",
    "value_variant", "factor_direction", "preprocessing_policy_version",
    "winsorization_status", "standardization_status", "neutralization_status",
    "staleness_status", "data_age_days", "staleness_threshold_days",
    "staleness_determination_basis", "formula_version", "config_version",
    "code_head", "row_lineage", "factor_value",
)


@dataclass(frozen=True)
class SyntheticSnapshotIssue:
    code: str
    record_index: int | None = None
    field_name: str | None = None


@dataclass(frozen=True)
class SyntheticFinancialSnapshot:
    status: str
    rows: tuple[dict[str, Any], ...]
    dataset_hash: str | None
    schema_hash: str
    manifest_hash: str | None
    issues: tuple[SyntheticSnapshotIssue, ...]


def build_synthetic_snapshot(records: Iterable[Mapping[str, Any]]) -> SyntheticFinancialSnapshot:
    """Build a canonical synthetic snapshot or fail closed without dropping rows."""
    raw_records = list(records)
    issues: list[SyntheticSnapshotIssue] = []
    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, Mapping):
            issues.append(SyntheticSnapshotIssue("INVALID_RECORD", index))
            continue
        missing = [field for field in REQUIRED_FIELDS if field not in raw or raw[field] in (None, "")]
        if missing:
            issues.extend(SyntheticSnapshotIssue("MISSING_REQUIRED_FIELD", index, field) for field in missing)
            continue
        if raw["synthetic_test_only"] is not True:
            issues.append(SyntheticSnapshotIssue("NON_SYNTHETIC_INPUT_NOT_AUTHORIZED", index, "synthetic_test_only"))
            continue
        try:
            report, publish, effective, evaluation = (_date(raw[name]) for name in ("report_period", "publish_date", "effective_date", "evaluation_date"))
        except (TypeError, ValueError):
            issues.append(SyntheticSnapshotIssue("INVALID_DATE", index))
            continue
        if not report <= publish <= effective <= evaluation:
            issues.append(SyntheticSnapshotIssue("PIT_DATE_ORDER_VIOLATION", index))
            continue
        if not isinstance(raw["factor_sample_mask"], bool):
            issues.append(SyntheticSnapshotIssue("INVALID_SAMPLE_MASK", index, "factor_sample_mask"))
            continue
        if not raw["factor_sample_mask"] and raw["inclusion_or_exclusion_reason"] == "included":
            issues.append(SyntheticSnapshotIssue("EXCLUSION_REASON_REQUIRED", index, "inclusion_or_exclusion_reason"))
            continue
        if not isinstance(raw["row_lineage"], Mapping) or not raw["row_lineage"]:
            issues.append(SyntheticSnapshotIssue("LINEAGE_REFERENCE_MISSING", index, "row_lineage"))
            continue
        key = tuple(str(raw[name]) for name in PRIMARY_KEY)
        if key in seen_keys:
            issues.append(SyntheticSnapshotIssue("DUPLICATE_PRIMARY_KEY", index))
            continue
        seen_keys.add(key)
        row = {name: _normalise(raw[name]) for name in REQUIRED_FIELDS if name != "synthetic_test_only"}
        row["schema_version"] = SNAPSHOT_SCHEMA_VERSION
        row["hash_contract_version"] = HASH_CONTRACT_VERSION
        row["row_value_hash"] = _hash("row", row)
        normalized.append(row)
    schema_hash = _hash("schema", {"required_fields": REQUIRED_FIELDS, "schema_version": SNAPSHOT_SCHEMA_VERSION})
    if issues:
        return SyntheticFinancialSnapshot("blocked", (), None, schema_hash, None, tuple(issues))
    rows = tuple(sorted(normalized, key=lambda row: tuple(row[name] for name in PRIMARY_KEY)))
    dataset_hash = _hash("dataset", list(rows))
    manifest_hash = _hash("manifest", {"schema_hash": schema_hash, "dataset_hash": dataset_hash, "row_count": len(rows), "synthetic_test_only": True})
    return SyntheticFinancialSnapshot("ready", rows, dataset_hash, schema_hash, manifest_hash, ())


def _date(value: Any) -> str:
    return date.fromisoformat(str(value)).isoformat()


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    return value


def _hash(domain: str, payload: Any) -> str:
    content = {"hash_contract_version": HASH_CONTRACT_VERSION, "domain": domain, "payload": _normalise(payload)}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
