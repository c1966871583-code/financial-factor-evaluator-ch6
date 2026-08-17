"""Generate qualified B3A quarterly-financial handoff inputs from one frozen run."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "artifacts" / "authoritative_financial_snapshot"
OUTPUT = PROJECT / "artifacts" / "fin_ho_8_b3a"
RUN_ID = "rqdata-authoritative-20260812T023240Z-16b9b5eba2"
HANDOFF_KEY = ("factor_id", "evaluation_date", "code")
FINANCIAL_FACTORS = ("ROE", "OCF_NP")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(frame: pd.DataFrame) -> str:
    normalized = frame.copy().sort_values(list(HANDOFF_KEY), kind="stable").reset_index(drop=True)
    payload = normalized.to_json(orient="records", date_format="iso", date_unit="ns", double_precision=15)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
    except Exception:
        return "UNKNOWN"


def validate_frozen_source() -> tuple[dict, dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    manifest_path = SOURCE / "manifest.json"
    freeze_path = SOURCE / "FREEZE_RECORD.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if manifest["run_id"] != RUN_ID or freeze["authoritative_run_id"] != RUN_ID:
        raise RuntimeError("BLOCKED_BY_AUTHORITATIVE_INPUT_MISMATCH:run_id")
    if manifest.get("authoritative_snapshot_status") != "FROZEN" or freeze["freeze_status"] != "FROZEN":
        raise RuntimeError("BLOCKED_BY_AUTHORITATIVE_INPUT_MISMATCH:not_frozen")
    if manifest["freeze_record_hash"] != sha256(freeze_path):
        raise RuntimeError("BLOCKED_BY_HASH_DRIFT:freeze_record")
    hash_paths = {
        "financial_source_dataset_sha256": SOURCE / "raw/financial_source_raw.parquet",
        "market_reference_dataset_sha256": SOURCE / "raw/market_reference_raw.parquet",
        "sample_mask_sha256": SOURCE / "masks/sample_mask.parquet",
        "lineage_dataset_sha256": SOURCE / "lineage/row_lineage.parquet",
        "authoritative_factor_rows_sha256": SOURCE / "processed/authoritative_factor_rows.parquet",
        "factor_dependency_lineage_sha256": SOURCE / "lineage/factor_dependency_lineage.parquet",
        "calendar_file_sha256": SOURCE / "raw/trading_calendar.csv",
    }
    if any(manifest[key] != sha256(path) for key, path in hash_paths.items()):
        raise RuntimeError("BLOCKED_BY_HASH_DRIFT:authoritative_dataset")
    rows = pd.read_parquet(hash_paths["authoritative_factor_rows_sha256"])
    lineage = pd.read_parquet(hash_paths["lineage_dataset_sha256"])
    mask = pd.read_parquet(hash_paths["sample_mask_sha256"])
    return manifest, freeze, rows, lineage, mask


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest, freeze, source_rows, source_lineage, source_mask = validate_frozen_source()
    qualified = source_rows[source_rows["factor_id"].isin(FINANCIAL_FACTORS)].copy()
    excluded = source_rows[~source_rows["factor_id"].isin(FINANCIAL_FACTORS)].copy()
    if set(excluded["factor_id"].unique()) != {"BP"} or len(excluded) != 90:
        raise RuntimeError("BLOCKED_BY_AUTHORITATIVE_INPUT_MISMATCH:unexpected_factor_scope")

    mask_lookup = source_mask[["sample_mask_reference", "sample_status", "inclusion_reason", "exclusion_reason", "sample_policy_id", "universe_version"]].copy()
    qualified = qualified.merge(mask_lookup, on="sample_mask_reference", how="left", validate="many_to_one")
    qualified["sample_reason"] = np.where(
        qualified["sample_status"].eq("INCLUDED"), qualified["inclusion_reason"], qualified["exclusion_reason"]
    )
    stale_policy = json.loads((SOURCE / "policies/stale_policy.json").read_text(encoding="utf-8"))
    sample_policy = json.loads((SOURCE / "policies/sample_policy.json").read_text(encoding="utf-8"))
    preprocessing = json.loads((SOURCE / "policies/preprocessing_policy.json").read_text(encoding="utf-8"))
    qualified["preprocessing_policy_id"] = preprocessing["preprocessing_policy_id"]
    qualified["preprocessing_policy_version"] = preprocessing["preprocessing_policy_version"]
    qualified["stale_policy_id"] = stale_policy["stale_policy_id"]
    qualified["stale_policy_version"] = stale_policy["stale_policy_version"]
    qualified["sample_policy_id"] = sample_policy["sample_policy_id"]
    qualified["sample_policy_version"] = sample_policy["sample_policy_version"]
    qualified["lineage_reference"] = qualified["authoritative_row_id"]
    qualified["value_hash"] = qualified["factor_value_hash"]
    qualified["source_input_hash"] = qualified["upstream_raw_hash"]
    qualified["raw_pit_factor_value"] = qualified["raw_factor_value"]
    qualified["evaluation_factor_value"] = qualified["factor_value"]
    qualified["factor_sample_mask"] = qualified["sample_status"].eq("INCLUDED")
    qualified["staleness_status"] = qualified["stale_status"]
    qualified["factor_value_variant"] = "evaluation_factor_value"
    qualified["statement_version"] = qualified["revision_sequence"]

    columns = [
        "factor_id", "factor_version", "code", "evaluation_date", "report_period",
        "publish_date", "effective_date", "factor_value", "raw_pit_factor_value",
        "evaluation_factor_value", "factor_value_variant", "statement_version",
        "factor_sample_mask", "sample_status", "sample_reason", "sample_mask_reference",
        "sample_policy_id", "sample_policy_version", "preprocessing_policy_id",
        "preprocessing_policy_version", "preprocessing_policy_reference",
        "stale_policy_id", "stale_policy_version", "stale_policy_reference",
        "stale_status", "staleness_status", "source_age_days", "source_record_reference",
        "revision_reference", "source_input_hash", "lineage_reference", "value_hash",
        "factor_value_hash", "authoritative_run_id",
    ]
    handoff = qualified[columns].sort_values(list(HANDOFF_KEY), kind="stable").reset_index(drop=True)
    if handoff.duplicated(list(HANDOFF_KEY)).any():
        raise RuntimeError("BLOCKED_BY_HANDOFF_KEY_CONTRACT")

    handoff_path = OUTPUT / "qualified_financial_handoff_inputs.parquet"
    lineage_path = OUTPUT / "handoff_lineage.parquet"
    mask_path = OUTPUT / "handoff_sample_mask.parquet"
    handoff.to_parquet(handoff_path, index=False)
    handoff_ids = set(handoff["lineage_reference"])
    handoff_lineage = source_lineage[source_lineage["authoritative_row_id"].isin(handoff_ids)].copy()
    handoff_lineage.to_parquet(lineage_path, index=False)
    source_mask.to_parquet(mask_path, index=False)

    qualification_audit = pd.DataFrame(
        [
            {"factor_id": "ROE", "source_rows": 90, "qualified_rows": 90, "qualification_status": "QUALIFIED_QUARTERLY_FINANCIAL_INPUT", "reason": "PIT quarterly financial factor"},
            {"factor_id": "OCF_NP", "source_rows": 90, "qualified_rows": 90, "qualification_status": "QUALIFIED_QUARTERLY_FINANCIAL_INPUT", "reason": "PIT quarterly financial factor"},
            {"factor_id": "BP", "source_rows": 90, "qualified_rows": 0, "qualification_status": "NOT_APPLICABLE_TO_QUARTERLY_FINANCIAL_HANDOFF", "reason": "Frozen evaluation-date valuation factor has no report/publish/effective dates; Task8 financial_numeric_dedup_v1 is quarterly and forbids null PIT dates"},
        ]
    )
    qualification_audit.to_csv(OUTPUT / "factor_qualification_audit.csv", index=False, encoding="utf-8")

    generated_at = datetime.now(timezone.utc).isoformat()
    handoff_manifest = {
        "handoff_type": "QUALIFIED_FINANCIAL_HANDOFF_INPUTS",
        "source_authoritative_run_id": RUN_ID,
        "source_authoritative_snapshot_status": "FROZEN",
        "generated_at_utc": generated_at,
        "code_commit": git_commit(),
        "security_count": int(handoff["code"].nunique()),
        "factor_count": int(handoff["factor_id"].nunique()),
        "source_factor_count": int(source_rows["factor_id"].nunique()),
        "evaluation_date_count": int(handoff["evaluation_date"].nunique()),
        "row_count": len(handoff),
        "handoff_key": list(HANDOFF_KEY),
        "financial_timing_policy_version": freeze["financial_timing_policy_version"],
        "forward_return_policy_version": freeze["forward_return_policy_version"],
        "sample_policy_version": sample_policy["sample_policy_version"],
        "preprocessing_policy_version": preprocessing["preprocessing_policy_version"],
        "stale_policy_version": stale_policy["stale_policy_version"],
        "source_snapshot_hash": manifest["authoritative_factor_rows_sha256"],
        "source_freeze_record_hash": manifest["freeze_record_hash"],
        "handoff_dataset_hash": sha256(handoff_path),
        "handoff_canonical_records_hash": canonical_hash(handoff),
        "lineage_hash": sha256(lineage_path),
        "sample_mask_hash": sha256(mask_path),
        "shadow_test_reused_as_authority": False,
        "bp_qualification_status": "NOT_APPLICABLE_TO_QUARTERLY_FINANCIAL_HANDOFF",
        "credential_values_included": False,
        "production_ready": False,
        "p05_ready": False,
        "task8_ready": False,
    }
    (OUTPUT / "handoff_manifest.json").write_text(
        json.dumps(handoff_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"status": "B3A_HANDOFF_GENERATED_PENDING_VALIDATION", "row_count": len(handoff)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
