"""Independently validate real P05 inputs, then freeze the candidate package."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
AUTH = PROJECT / "artifacts" / "authoritative_financial_snapshot"
B3A = PROJECT / "artifacts" / "fin_ho_8_b3a"
OUT = PROJECT / "artifacts" / "p05_candidate_handoff"
TASK8 = PROJECT.parent / "TASK8-FINANCIAL-INPUT-CONTRACT-EXTENSION"
CH6 = PROJECT.parent / "financial-factor-evaluator-ch6"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def load_contracts():
    sys.path.insert(0, str(TASK8))
    from backend.amr.financial_numeric_deduplication import FinancialDedupInput
    return FinancialDedupInput


def main() -> int:
    manifest_path = OUT / "p05_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    package = json.loads((OUT / "P05CandidateHandoffPackage.json").read_text(encoding="utf-8"))
    auth = json.loads((AUTH / "manifest.json").read_text(encoding="utf-8"))
    b3a = json.loads((B3A / "handoff_manifest.json").read_text(encoding="utf-8"))
    b3a_validation = json.loads((B3A / "handoff_validation.json").read_text(encoding="utf-8"))
    rows = pd.read_parquet(OUT / "p05_financial_rows.parquet")
    lineage = pd.read_parquet(OUT / "p05_lineage.parquet")
    mask = pd.read_parquet(OUT / "p05_sample_mask.parquet")
    required = {
        "factor_id", "factor_version", "code", "evaluation_date", "report_period", "publish_date",
        "effective_date", "factor_value", "sample_mask_reference", "preprocessing_policy_reference",
        "stale_policy_reference", "lineage_reference", "source_record_reference", "value_hash", "authoritative_run_id",
    }
    tests = {}
    tests["UPSTREAM_AUTHORITY_PASS"] = (
        manifest["source_authoritative_run_id"] == auth["run_id"]
        and auth["authoritative_snapshot_status"] == "FROZEN"
        and auth["freeze_record_hash"] == sha256(AUTH / "FREEZE_RECORD.json")
        and b3a_validation["status"] == "B3A_QUALIFIED_FINANCIAL_HANDOFF_INPUTS_READY"
    )
    tests["UPSTREAM_HASH_PASS"] = (
        manifest["source_b3a_dataset_hash"] == b3a["handoff_dataset_hash"] == sha256(B3A / "qualified_financial_handoff_inputs.parquet")
        and manifest["source_b3a_lineage_hash"] == b3a["lineage_hash"] == sha256(B3A / "handoff_lineage.parquet")
    )
    tests["SCHEMA_PASS"] = required.issubset(rows.columns) and set(rows["factor_id"]) == {"ROE", "OCF_NP"}
    tests["ROW_COUNT_PASS"] = len(rows) == manifest["input_row_count"] == manifest["accepted_row_count"] == 180 and manifest["rejected_row_count"] == 0
    tests["KEY_UNIQUENESS_PASS"] = not rows.duplicated(["factor_id", "evaluation_date", "code"]).any()
    dates = (
        pd.to_datetime(rows["report_period"]) <= pd.to_datetime(rows["publish_date"])
    ) & (pd.to_datetime(rows["publish_date"]) < pd.to_datetime(rows["effective_date"])) & (
        pd.to_datetime(rows["effective_date"]) <= pd.to_datetime(rows["evaluation_date"])
    )
    tests["PIT_PASS"] = bool(dates.all())
    tests["FINITE_VALUE_PASS"] = bool(np.isfinite(pd.to_numeric(rows["factor_value"], errors="coerce")).all())
    tests["SAMPLE_POLICY_PASS"] = rows["factor_sample_mask"].eq(True).all() and rows["sample_mask_reference"].isin(mask["sample_mask_reference"]).all()
    tests["POLICY_PASS"] = (
        rows["preprocessing_policy_reference"].notna().all() and rows["stale_policy_reference"].notna().all()
        and manifest["financial_timing_policy_version"] == "FINANCIAL_TIMING_STRICT_NEXT_V1"
        and manifest["comparison_policy"]["selected_variant"] == "evaluation_factor_value"
        and not manifest["comparison_policy"]["dedup_comparison_value_generated"]
    )
    tests["STALE_METADATA_PASS"] = rows["stale_status"].eq("FRESH").all() and rows["source_age_days"].le(550).all()
    tests["LINEAGE_PASS"] = (
        len(lineage) == len(rows) and rows["lineage_reference"].isin(lineage["authoritative_row_id"]).all()
        and rows[["source_record_reference", "revision_reference", "lineage_reference", "value_hash"]].notna().all().all()
    )
    tests["VALUE_HASH_PASS"] = rows["value_hash"].eq(rows["factor_value_hash"]).all() and rows["value_hash"].str.fullmatch(r"[0-9a-f]{64}").all()
    tests["PACKAGE_HASH_PASS"] = (
        manifest["dataset_hash"] == sha256(OUT / "p05_financial_rows.parquet")
        and manifest["lineage_hash"] == sha256(OUT / "p05_lineage.parquet")
        and manifest["sample_mask_hash"] == sha256(OUT / "p05_sample_mask.parquet")
        and manifest["package_dataset_hash"] == sha256(OUT / "P05CandidateHandoffPackage.json")
    )
    package_core = {key: value for key, value in package.items() if key != "content_hash"}
    tests["P05_SCHEMA_PASS"] = (
        tuple(package.keys()) == (
            "schema_version", "semantic_policy_content_hash", "comparison_policy", "candidate_id",
            "candidate_kind", "candidate_definition_hash", "row_count", "sample_fingerprint",
            "records_fingerprint", "row_lineage", "manifest", "production_status", "content_hash"
        )
        and package["schema_version"] == "P05CandidateHandoffPackage-v1.0"
        and package["semantic_policy_content_hash"] == "01120ed75792272066bcbaf97e07a8ae7195987869848afd418368b1a0dd58e7"
        and package["production_status"] == "not production ready"
        and package["content_hash"] == stable_hash(package_core)
    )
    FinancialDedupInput = load_contracts()
    counts = []
    for factor_id, part in rows.groupby("factor_id", sort=True):
        contract = FinancialDedupInput(
            factor_id, str(part["factor_version"].iloc[0]), f"p05-{factor_id}", package["sample_fingerprint"],
            str(part["preprocessing_policy_version"].iloc[0]),
            part[["evaluation_date", "code", "factor_id", "raw_pit_factor_value", "evaluation_factor_value",
                  "report_period", "publish_date", "effective_date", "factor_sample_mask", "source_record_reference",
                  "source_input_hash", "preprocessing_policy_version", "staleness_status", "factor_value_hash"]],
            "quarterly",
        )
        counts.append(len(contract.get_frame()))
    tests["REAL_ROW_CONTRACT_PASS"] = counts == [90, 90]
    tests["BP_HANDLING_PASS"] = manifest["bp_status"] == "EXCLUDED_BY_FROZEN_QUARTERLY_FINANCIAL_CONTRACT"
    tests["GOVERNANCE_PASS"] = not manifest["production_ready"] and not manifest["task8_ready"] and not manifest["shadow_test_reused_as_authority"]
    tests = {key: bool(value) for key, value in tests.items()}
    passed = all(tests.values())
    validation = {
        "task_id": "FIN-HO-8-P05-REAL-CONTRACT-VALIDATION-AND-ASSEMBLY-32",
        "validation_process": "INDEPENDENT_REAL_P05_VALIDATOR",
        "tests": tests, "checks_passed": sum(tests.values()), "checks_failed": len(tests) - sum(tests.values()),
        "failed_checks": [key for key, value in tests.items() if not value],
        "input_row_count": 180, "accepted_row_count": 180, "rejected_row_count": 0,
        "orphan_lineage_count": int((~rows["lineage_reference"].isin(lineage["authoritative_row_id"])).sum()),
        "missing_source_reference_count": int(rows["source_record_reference"].isna().sum()),
        "missing_value_hash_count": int(rows["value_hash"].isna().sum()),
        "hash_drift_detected": not (tests["UPSTREAM_HASH_PASS"] and tests["PACKAGE_HASH_PASS"]),
        "status": "PASS_PENDING_FREEZE" if passed else "BLOCKED_BY_P05_CONTRACT_VALIDATION",
    }
    (OUT / "p05_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    if not passed:
        print(json.dumps(validation, ensure_ascii=False))
        return 2

    prefreeze_manifest_hash = sha256(manifest_path)
    freeze_core = {
        "freeze_status": "FROZEN", "package_id": manifest["package_id"],
        "freeze_timestamp_utc": datetime.now(UTC).isoformat(),
        "source_authoritative_run_id": manifest["source_authoritative_run_id"],
        "input_row_count": 180, "accepted_row_count": 180,
        "dataset_hash": manifest["dataset_hash"], "lineage_hash": manifest["lineage_hash"],
        "sample_mask_hash": manifest["sample_mask_hash"], "package_dataset_hash": manifest["package_dataset_hash"],
        "pre_freeze_manifest_hash": prefreeze_manifest_hash,
        "future_change_rule": "Any change requires a new P05 package_id, validation, and freeze",
        "frozen_by": "OPERATOR_AUTHORIZED_PIPELINE", "production_ready": False, "task8_ready": False,
    }
    freeze_path = OUT / "P05_FREEZE_RECORD.json"
    freeze_path.write_text(json.dumps(freeze_core, ensure_ascii=False, indent=2), encoding="utf-8")
    freeze_hash = sha256(freeze_path)
    manifest.update({
        "package_status": "FROZEN", "freeze_record_present": True,
        "freeze_record_hash": freeze_hash, "pre_freeze_manifest_hash": prefreeze_manifest_hash,
        "immutability_semantics": "IMMUTABLE_FOR_HANDOFF; any change requires a new package_id",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    validation["status"] = "PASS_AND_FROZEN"
    validation["freeze_record_hash"] = freeze_hash
    validation["post_freeze_manifest_hash"] = sha256(manifest_path)
    (OUT / "p05_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "P05_CANDIDATE_HANDOFF_PACKAGE_FROZEN", "checks_passed": sum(tests.values()), "checks_failed": 0, "freeze_record_hash": freeze_hash}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
