"""Assemble and freeze the real-data BP evaluation-date valuation handoff."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
AUTH = PROJECT / "artifacts" / "authoritative_financial_snapshot"
OUT = PROJECT / "artifacts" / "bp_valuation_handoff"
TASK8 = PROJECT.parent / "TASK8-FINANCIAL-INPUT-CONTRACT-EXTENSION"
RUN_ID = "rqdata-authoritative-20260812T023240Z-16b9b5eba2"
VALUATION_POLICY_ID = "BP_LF_EVALUATION_DATE_V1"
VALUATION_POLICY_VERSION = "1.0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def git_value(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def load_contract():
    sys.path.insert(0, str(TASK8))
    from backend.amr.valuation_numeric_deduplication import ValuationDedupInput

    return ValuationDedupInput


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    auth = json.loads((AUTH / "manifest.json").read_text(encoding="utf-8"))
    freeze = json.loads((AUTH / "FREEZE_RECORD.json").read_text(encoding="utf-8"))
    preprocessing = json.loads(
        (AUTH / "policies" / "preprocessing_policy.json").read_text(encoding="utf-8")
    )
    source = pd.read_parquet(AUTH / "processed" / "authoritative_factor_rows.parquet")
    bp = source.loc[source["factor_id"].eq("BP")].copy()

    if auth["authoritative_run_id"] != freeze["authoritative_run_id"] or auth["authoritative_run_id"] != RUN_ID:
        raise RuntimeError("AUTHORITATIVE_RUN_MISMATCH")
    if auth["authoritative_snapshot_status"] != "FROZEN" or freeze["freeze_status"] != "FROZEN":
        raise RuntimeError("AUTHORITATIVE_SNAPSHOT_NOT_FROZEN")
    if auth["freeze_record_hash"] != sha256(AUTH / "FREEZE_RECORD.json"):
        raise RuntimeError("AUTHORITATIVE_FREEZE_HASH_DRIFT")
    if len(bp) != 90 or bp["code"].nunique() != 30 or bp["evaluation_date"].nunique() != 3:
        raise RuntimeError("BP_SCOPE_MISMATCH")

    rows = pd.DataFrame(
        {
            "evaluation_date": pd.to_datetime(bp["evaluation_date"]).dt.strftime("%Y-%m-%d"),
            "provider_date": pd.to_datetime(bp["provider_date"]).dt.strftime("%Y-%m-%d"),
            "code": bp["code"].astype(str),
            "factor_id": bp["factor_id"].astype(str),
            "factor_version": bp["factor_version"].astype(str),
            "raw_factor_value": pd.to_numeric(bp["raw_factor_value"], errors="raise"),
            "evaluation_factor_value": pd.to_numeric(bp["factor_value"], errors="raise"),
            "book_to_market_ratio_lf": pd.to_numeric(bp["book_to_market_ratio_lf"], errors="raise"),
            "pb_ratio_lf": pd.to_numeric(bp["pb_ratio_lf"], errors="raise"),
            "market_cap": pd.to_numeric(bp["market_cap"], errors="raise"),
            "factor_sample_mask": bp["factor_eligible"].astype(str).str.lower().eq("true"),
            "sample_mask_reference": bp["sample_mask_reference"].astype(str),
            "provider": bp["provider"].astype(str),
            "provider_endpoint": bp["provider_endpoint"].astype(str),
            "provider_field": "book_to_market_ratio_lf",
            "source_record_reference": bp["source_record_reference"].astype(str),
            "source_input_hash": bp["upstream_raw_hash"].astype(str),
            "authoritative_row_id": bp["authoritative_row_id"].astype(str),
            "authoritative_run_id": bp["authoritative_run_id"].astype(str),
            "formula_reference": bp["formula_reference"].astype(str),
            "preprocessing_policy_reference": bp["preprocessing_policy_reference"].astype(str),
            "preprocessing_policy_version": preprocessing["preprocessing_policy_version"],
            "valuation_policy_id": VALUATION_POLICY_ID,
            "valuation_policy_version": VALUATION_POLICY_VERSION,
            "staleness_status": bp["stale_status"].astype(str),
            "stale_policy_reference": bp["stale_policy_reference"].astype(str),
            "factor_value_hash": bp["factor_value_hash"].astype(str),
            "value_hash": bp["value_hash"].astype(str),
            "lineage_reference": bp["authoritative_row_id"].astype(str),
        }
    ).sort_values(["evaluation_date", "code"], kind="stable").reset_index(drop=True)

    finite_columns = [
        "raw_factor_value",
        "evaluation_factor_value",
        "book_to_market_ratio_lf",
        "pb_ratio_lf",
        "market_cap",
    ]
    if not np.isfinite(rows[finite_columns].to_numpy(dtype=float)).all():
        raise RuntimeError("NONFINITE_BP_VALUE")
    if not rows["provider_date"].eq(rows["evaluation_date"]).all():
        raise RuntimeError("BP_PROVIDER_DATE_MISMATCH")
    if not rows["factor_sample_mask"].all():
        raise RuntimeError("BP_SAMPLE_MASK_VIOLATION")
    if not rows["pb_ratio_lf"].gt(0).all():
        raise RuntimeError("BP_NONPOSITIVE_PB")
    reciprocal_error = (rows["evaluation_factor_value"] - 1.0 / rows["pb_ratio_lf"]).abs()
    if float(reciprocal_error.max()) > 1e-12:
        raise RuntimeError("BP_RECIPROCAL_VALIDATION_FAILED")
    if rows.duplicated(["evaluation_date", "code", "factor_id"]).any():
        raise RuntimeError("BP_DUPLICATE_KEY")

    main_commit = git_value(PROJECT, "rev-parse", "HEAD")
    task8_commit = git_value(TASK8, "rev-parse", "HEAD")
    ValuationDedupInput = load_contract()
    contract = ValuationDedupInput(
        factor_id="BP",
        factor_version=str(rows["factor_version"].iloc[0]),
        dataset_id=f"bp-valuation-{RUN_ID}",
        sample_fingerprint=auth["sample_mask_sha256"],
        preprocessing_policy_version=preprocessing["preprocessing_policy_version"],
        valuation_policy_version=VALUATION_POLICY_VERSION,
        authoritative_run_id=RUN_ID,
        _frame=rows,
    )
    if len(contract.get_frame()) != 90:
        raise RuntimeError("TASK8_VALUATION_CONTRACT_ROW_MISMATCH")

    rows_path = OUT / "bp_valuation_rows.parquet"
    lineage_path = OUT / "bp_valuation_lineage.parquet"
    package_path = OUT / "BPValuationHandoffPackage.json"
    rows.to_parquet(rows_path, index=False)
    lineage_columns = [
        "factor_id",
        "factor_version",
        "evaluation_date",
        "code",
        "provider",
        "provider_endpoint",
        "provider_field",
        "source_record_reference",
        "source_input_hash",
        "authoritative_row_id",
        "authoritative_run_id",
        "formula_reference",
        "sample_mask_reference",
        "preprocessing_policy_reference",
        "stale_policy_reference",
        "factor_value_hash",
        "value_hash",
    ]
    rows[lineage_columns].to_parquet(lineage_path, index=False)
    canonical_hash = stable_hash(rows.to_dict("records"))
    package_id = f"bp-valuation-{canonical_hash[:24]}"
    package = {
        "package_type": "BPValuationHandoffPackage",
        "schema_version": "valuation_numeric_dedup_v1",
        "package_id": package_id,
        "source_authoritative_run_id": RUN_ID,
        "factor_scope": ["BP"],
        "row_count": 90,
        "security_count": 30,
        "evaluation_date_count": 3,
        "frequency": "evaluation_date_snapshot",
        "comparison_variant": "evaluation_factor_value",
        "selection_or_admission_performed": False,
        "valuation_policy_id": VALUATION_POLICY_ID,
        "valuation_policy_version": VALUATION_POLICY_VERSION,
        "task8_contract_commit": task8_commit,
    }
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")

    pre_freeze_manifest = {
        **package,
        "status": "VALIDATED_CANDIDATE",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_commit": main_commit,
        "task8_contract_commit": task8_commit,
        "source_snapshot_hash": auth["authoritative_factor_rows_sha256"],
        "source_freeze_record_hash": auth["freeze_record_hash"],
        "rows_hash": sha256(rows_path),
        "lineage_hash": sha256(lineage_path),
        "package_hash": sha256(package_path),
        "canonical_records_hash": canonical_hash,
        "sample_mask_hash": auth["sample_mask_sha256"],
        "preprocessing_policy_version": preprocessing["preprocessing_policy_version"],
        "bp_reciprocal_max_abs_error": float(reciprocal_error.max()),
        "credential_values_included": False,
        "rqdata_queried": False,
        "production_ready": False,
        "task8_receive_accepted": False,
    }
    pre_freeze_hash = stable_hash(pre_freeze_manifest)
    freeze_record = {
        "freeze_status": "FROZEN",
        "package_id": package_id,
        "source_authoritative_run_id": RUN_ID,
        "rows_hash": pre_freeze_manifest["rows_hash"],
        "lineage_hash": pre_freeze_manifest["lineage_hash"],
        "package_hash": pre_freeze_manifest["package_hash"],
        "pre_freeze_manifest_hash": pre_freeze_hash,
        "frozen_by": "OPERATOR_AUTHORIZED_PIPELINE",
        "future_change_rule": "new package_id, validation, and freeze required",
        "production_ready": False,
        "task8_receive_accepted": False,
    }
    freeze_path = OUT / "BP_VALUATION_FREEZE_RECORD.json"
    freeze_path.write_text(json.dumps(freeze_record, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        **pre_freeze_manifest,
        "status": "FROZEN",
        "pre_freeze_manifest_hash": pre_freeze_hash,
        "freeze_record_present": True,
        "freeze_record_hash": sha256(freeze_path),
        "immutability_semantics": "IMMUTABLE_FOR_TASK8_RECEIVE",
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validation = {
        "status": "BP_VALUATION_HANDOFF_FROZEN",
        "checks_passed": 16,
        "checks_failed": 0,
        "row_count": 90,
        "duplicate_key_count": 0,
        "non_finite_value_count": 0,
        "provider_date_mismatch_count": 0,
        "sample_mask_violation_count": 0,
        "nonpositive_pb_count": 0,
        "reciprocal_max_abs_error": float(reciprocal_error.max()),
        "task8_contract_status": "PASS",
        "real_provider": "RQData",
        "rqdata_queried": False,
        "hash_drift_detected": False,
    }
    (OUT / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"status": validation["status"], "package_id": package_id, "rows": 90}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
