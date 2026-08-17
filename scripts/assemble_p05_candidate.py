"""Assemble and freeze a P05 candidate package from validated B3A inputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
AUTH = PROJECT / "artifacts" / "authoritative_financial_snapshot"
B3A = PROJECT / "artifacts" / "fin_ho_8_b3a"
OUT = PROJECT / "artifacts" / "p05_candidate_handoff"
RUN_ID = "rqdata-authoritative-20260812T023240Z-16b9b5eba2"
SCHEMA_VERSION = "P05CandidateHandoffPackage-v1.0"
SEMANTICS_HASH = "01120ed75792272066bcbaf97e07a8ae7195987869848afd418368b1a0dd58e7"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
    except Exception:
        return "UNKNOWN"


def validate_upstream() -> tuple[dict, dict, dict]:
    auth_manifest = json.loads((AUTH / "manifest.json").read_text(encoding="utf-8"))
    b3a_manifest = json.loads((B3A / "handoff_manifest.json").read_text(encoding="utf-8"))
    b3a_validation = json.loads((B3A / "handoff_validation.json").read_text(encoding="utf-8"))
    if auth_manifest["run_id"] != RUN_ID or auth_manifest["authoritative_snapshot_status"] != "FROZEN":
        raise RuntimeError("BLOCKED_BY_P05_CONTRACT_VALIDATION:authoritative binding")
    if auth_manifest["freeze_record_hash"] != sha256(AUTH / "FREEZE_RECORD.json"):
        raise RuntimeError("BLOCKED_BY_P05_UPSTREAM_HASH_DRIFT:freeze record")
    if b3a_manifest["source_authoritative_run_id"] != RUN_ID or b3a_validation["status"] != "B3A_QUALIFIED_FINANCIAL_HANDOFF_INPUTS_READY":
        raise RuntimeError("BLOCKED_BY_P05_CONTRACT_VALIDATION:B3A status")
    checks = {
        B3A / "qualified_financial_handoff_inputs.parquet": b3a_manifest["handoff_dataset_hash"],
        B3A / "handoff_lineage.parquet": b3a_manifest["lineage_hash"],
        B3A / "handoff_sample_mask.parquet": b3a_manifest["sample_mask_hash"],
    }
    if any(sha256(path) != expected for path, expected in checks.items()):
        raise RuntimeError("BLOCKED_BY_P05_UPSTREAM_HASH_DRIFT:B3A")
    return auth_manifest, b3a_manifest, b3a_validation


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    auth_manifest, b3a_manifest, _ = validate_upstream()
    rows = pd.read_parquet(B3A / "qualified_financial_handoff_inputs.parquet")
    lineage = pd.read_parquet(B3A / "handoff_lineage.parquet")
    sample_mask = pd.read_parquet(B3A / "handoff_sample_mask.parquet")
    if len(rows) != 180 or set(rows["factor_id"]) != {"ROE", "OCF_NP"}:
        raise RuntimeError("BLOCKED_BY_P05_CONTRACT_VALIDATION:row scope")

    rows_path = OUT / "p05_financial_rows.parquet"
    lineage_path = OUT / "p05_lineage.parquet"
    mask_path = OUT / "p05_sample_mask.parquet"
    rows.to_parquet(rows_path, index=False)
    lineage.to_parquet(lineage_path, index=False)
    sample_mask.to_parquet(mask_path, index=False)
    dataset_hash, lineage_hash, mask_hash = sha256(rows_path), sha256(lineage_path), sha256(mask_path)
    records_fingerprint = stable_hash(
        rows.sort_values(["factor_id", "evaluation_date", "code"], kind="stable").to_dict("records")
    )
    sample_fingerprint = stable_hash(
        sample_mask.sort_values(["evaluation_date", "code"], kind="stable").to_dict("records")
    )
    candidate_definition_hash = sha256(AUTH / "lineage/factor_dependency_lineage.parquet")
    package_id = "p05-financial-" + stable_hash([RUN_ID, dataset_hash, SCHEMA_VERSION])[:24]
    comparison_policy = {
        "status": "APPROVED_INPUT_SEMANTICS_NOT_EXECUTED",
        "selected_variant": "evaluation_factor_value",
        "direction_flip_included": False,
        "frequency": "quarterly",
        "common_sample_method": "frozen_eligible_intersection_by_evaluation_date_and_code",
        "missing_policy": "no_fill_fail_closed",
        "staleness_policy": "FINANCIAL_SOURCE_AGE_550D_V1",
        "industry_applicability_policy": "NOT_APPLIED",
        "correlation_methods": ["spearman", "pearson"],
        "threshold_policy_version": "TASK8_OWNED_NOT_APPLIED_DURING_P05_ASSEMBLY",
        "approval_reference": "TASK8-FINANCIAL-INPUT-CONTRACT-EXTENSION:ACCEPTED_LOCAL:95_tests",
        "dedup_comparison_value_generated": False,
        "selection_or_admission_performed": False,
    }
    created_at = datetime.now(timezone.utc).isoformat()
    package_core = {
        "schema_version": SCHEMA_VERSION,
        "semantic_policy_content_hash": SEMANTICS_HASH,
        "comparison_policy": comparison_policy,
        "candidate_id": package_id,
        "candidate_kind": "quarterly_financial_factor_set",
        "candidate_definition_hash": candidate_definition_hash,
        "row_count": len(rows),
        "sample_fingerprint": sample_fingerprint,
        "records_fingerprint": records_fingerprint,
        "row_lineage": "p05_lineage.parquet",
        "manifest": "p05_manifest.json",
        "production_status": "not production ready",
    }
    content_hash = stable_hash(package_core)
    package = {**package_core, "content_hash": content_hash}
    package_path = OUT / "P05CandidateHandoffPackage.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    package_dataset_hash = sha256(package_path)
    manifest_core = {
        "package_type": "P05CandidateHandoffPackage",
        "schema_version": SCHEMA_VERSION,
        "package_id": package_id,
        "package_status": "ASSEMBLED_PENDING_INDEPENDENT_VALIDATION",
        "source_authoritative_run_id": RUN_ID,
        "source_authoritative_snapshot_hash": auth_manifest["authoritative_factor_rows_sha256"],
        "source_authoritative_freeze_record_hash": auth_manifest["freeze_record_hash"],
        "source_b3a_status": "B3A_QUALIFIED_FINANCIAL_HANDOFF_INPUTS_READY",
        "source_b3a_dataset_hash": b3a_manifest["handoff_dataset_hash"],
        "source_b3a_lineage_hash": b3a_manifest["lineage_hash"],
        "factor_scope": ["ROE", "OCF_NP"],
        "bp_status": "EXCLUDED_BY_FROZEN_QUARTERLY_FINANCIAL_CONTRACT",
        "security_count": 30,
        "evaluation_date_count": 3,
        "input_row_count": 180,
        "accepted_row_count": 180,
        "rejected_row_count": 0,
        "rejection_reason_distribution": {},
        "dataset_hash": dataset_hash,
        "lineage_hash": lineage_hash,
        "sample_mask_hash": mask_hash,
        "package_dataset_hash": package_dataset_hash,
        "package_content_hash": content_hash,
        "created_at_utc": created_at,
        "code_commit": git_commit(),
        "comparison_policy": comparison_policy,
        "financial_timing_policy_version": "FINANCIAL_TIMING_STRICT_NEXT_V1",
        "sample_policy_version": b3a_manifest["sample_policy_version"],
        "preprocessing_policy_version": b3a_manifest["preprocessing_policy_version"],
        "stale_policy_version": b3a_manifest["stale_policy_version"],
        "shadow_test_reused_as_authority": False,
        "credential_values_included": False,
        "production_ready": False,
        "task8_ready": False,
    }
    manifest_hash = stable_hash(manifest_core)
    p05_manifest = {**manifest_core, "manifest_hash": manifest_hash, "manifest_hash_semantics": "canonical SHA256 of manifest fields excluding manifest_hash"}
    (OUT / "p05_manifest.json").write_text(json.dumps(p05_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "P05_ASSEMBLED_PENDING_VALIDATION", "package_id": package_id, "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
