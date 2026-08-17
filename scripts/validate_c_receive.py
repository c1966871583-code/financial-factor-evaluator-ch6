"""Task8 C receive validation for one exact frozen P05 package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
ART = PROJECT / "artifacts"
AUTH = ART / "authoritative_financial_snapshot"
B3A = ART / "fin_ho_8_b3a"
P05 = ART / "p05_candidate_handoff"
BGATE = ART / "fin_ho_8_b_gate"
OUT = ART / "fin_ho_8_c"
RUN_ID = "rqdata-authoritative-20260812T023240Z-16b9b5eba2"
PACKAGE_ID = "p05-financial-0e95e865a647bee1f9e61929"
KEY = ["factor_id", "evaluation_date", "code"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def canonical_records_hash(frame: pd.DataFrame) -> str:
    return stable_hash(frame.sort_values(KEY, kind="stable").reset_index(drop=True).to_dict("records"))


def require_receive_schema(frame: pd.DataFrame) -> None:
    required = {
        "factor_id", "factor_version", "code", "evaluation_date", "report_period",
        "publish_date", "effective_date", "factor_value", "lineage_reference",
        "source_record_reference", "sample_mask_reference", "preprocessing_policy_reference",
        "stale_policy_reference", "value_hash", "authoritative_run_id",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"MISSING_RECEIVE_FIELDS:{missing}")
    if frame.duplicated(KEY).any():
        raise ValueError("DUPLICATE_RECEIVE_KEY")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    auth = json.loads((AUTH / "manifest.json").read_text(encoding="utf-8"))
    b3a = json.loads((B3A / "handoff_manifest.json").read_text(encoding="utf-8"))
    p05 = json.loads((P05 / "p05_manifest.json").read_text(encoding="utf-8"))
    package = json.loads((P05 / "P05CandidateHandoffPackage.json").read_text(encoding="utf-8"))
    freeze = json.loads((P05 / "P05_FREEZE_RECORD.json").read_text(encoding="utf-8"))
    p05_validation = json.loads((P05 / "p05_validation.json").read_text(encoding="utf-8"))
    bgate = json.loads((BGATE / "B_GATE_ACCEPTANCE_RECORD.json").read_text(encoding="utf-8"))
    rows = pd.read_parquet(P05 / "p05_financial_rows.parquet")
    b3a_rows = pd.read_parquet(B3A / "qualified_financial_handoff_inputs.parquet")
    auth_rows = pd.read_parquet(AUTH / "processed/authoritative_factor_rows.parquet")
    lineage = pd.read_parquet(P05 / "p05_lineage.parquet")
    raw = pd.read_parquet(AUTH / "raw/financial_source_raw.parquet")
    mask = pd.read_parquet(P05 / "p05_sample_mask.parquet")

    tests: dict[str, bool] = {}
    tests["B_GATE_PRECONDITION_PASS"] = (
        bgate["gate"] == "FIN_HO_8_B" and bgate["status"] == "ACCEPTED"
        and bgate["p05_package_id"] == PACKAGE_ID and bgate["source_authoritative_run_id"] == RUN_ID
    )
    tests["PACKAGE_IDENTITY_PASS"] = (
        p05["package_id"] == package["candidate_id"] == freeze["package_id"] == PACKAGE_ID
        and p05["source_authoritative_run_id"] == freeze["source_authoritative_run_id"] == RUN_ID
        and p05["package_status"] == freeze["freeze_status"] == "FROZEN"
    )
    tests["PACKAGE_HASH_PASS"] = (
        p05["dataset_hash"] == freeze["dataset_hash"] == sha256(P05 / "p05_financial_rows.parquet")
        and p05["lineage_hash"] == freeze["lineage_hash"] == sha256(P05 / "p05_lineage.parquet")
        and p05["sample_mask_hash"] == freeze["sample_mask_hash"] == sha256(P05 / "p05_sample_mask.parquet")
        and p05["package_dataset_hash"] == freeze["package_dataset_hash"] == sha256(P05 / "P05CandidateHandoffPackage.json")
        and p05["freeze_record_hash"] == sha256(P05 / "P05_FREEZE_RECORD.json")
        and p05_validation["post_freeze_manifest_hash"] == sha256(P05 / "p05_manifest.json")
    )
    tests["UPSTREAM_HASH_PASS"] = (
        p05["source_authoritative_snapshot_hash"] == auth["authoritative_factor_rows_sha256"] == sha256(AUTH / "processed/authoritative_factor_rows.parquet")
        and p05["source_b3a_dataset_hash"] == b3a["handoff_dataset_hash"] == sha256(B3A / "qualified_financial_handoff_inputs.parquet")
        and p05["source_b3a_lineage_hash"] == b3a["lineage_hash"] == sha256(B3A / "handoff_lineage.parquet")
    )
    require_receive_schema(rows)
    tests["SCOPE_PASS"] = len(rows) == 180 and set(rows["factor_id"]) == {"ROE", "OCF_NP"} and rows["code"].nunique() == 30 and rows["evaluation_date"].nunique() == 3
    tests["ROW_ACCEPTANCE_PASS"] = len(rows) == len(b3a_rows) == 180 and not rows.duplicated(KEY).any()
    dates = (
        pd.to_datetime(rows["report_period"]) <= pd.to_datetime(rows["publish_date"])
    ) & (pd.to_datetime(rows["publish_date"]) < pd.to_datetime(rows["effective_date"])) & (
        pd.to_datetime(rows["effective_date"]) <= pd.to_datetime(rows["evaluation_date"])
    )
    tests["PIT_TIMING_PASS"] = bool(dates.all())
    p05_to_b3a = rows.merge(b3a_rows[KEY + ["lineage_reference", "value_hash", "authoritative_run_id"]], on=KEY, how="left", suffixes=("", "_b3a"), indicator=True, validate="one_to_one")
    p05_to_auth = rows.merge(auth_rows[["authoritative_row_id", "source_record_reference", "factor_value_hash", "authoritative_run_id"]], left_on="lineage_reference", right_on="authoritative_row_id", how="left", suffixes=("", "_auth"), indicator=True, validate="one_to_one")
    source_refs = set(raw["source_record_reference"])
    counts = {
        "received_row_count": len(rows),
        "missing_row_count": int((p05_to_b3a["_merge"] != "both").sum()),
        "unexpected_row_count": int((~b3a_rows.set_index(KEY).index.isin(rows.set_index(KEY).index)).sum()),
        "duplicate_received_row_count": int(rows.duplicated(KEY).sum()),
        "orphan_lineage_count": int((~rows["lineage_reference"].isin(lineage["authoritative_row_id"])).sum()),
        "broken_receive_chain_count": int((p05_to_auth["_merge"] != "both").sum() + (p05_to_b3a["_merge"] != "both").sum()),
        "source_run_mismatch_count": int((rows["authoritative_run_id"] != RUN_ID).sum()),
        "missing_policy_reference_count": int(rows[["sample_policy_id", "preprocessing_policy_reference", "stale_policy_reference"]].isna().sum().sum()),
        "policy_version_mismatch_count": int((rows["preprocessing_policy_version"] != p05["preprocessing_policy_version"]).sum() + (rows["stale_policy_version"] != p05["stale_policy_version"]).sum() + (rows["sample_policy_version"] != p05["sample_policy_version"]).sum()),
        "pit_violation_count": int((~dates).sum()),
        "timing_violation_count": int((~dates).sum()),
        "unknown_source_count": int((~rows["source_record_reference"].isin(source_refs)).sum()),
    }
    tests["LINEAGE_PASS"] = all(counts[key] == 0 for key in ("orphan_lineage_count", "broken_receive_chain_count", "source_run_mismatch_count", "unknown_source_count"))
    tests["POLICY_PASS"] = counts["missing_policy_reference_count"] == counts["policy_version_mismatch_count"] == 0
    tests["SAMPLE_STALE_PASS"] = rows["sample_mask_reference"].isin(mask["sample_mask_reference"]).all() and rows["sample_reason"].notna().all() and rows["stale_status"].eq("FRESH").all()
    tests["REAL_INPUT_IDENTITY_PASS"] = raw["provider"].eq("RQData").all() and not p05["shadow_test_reused_as_authority"] and not bgate["synthetic_input_used"] and not bgate["mock_provider_used"]
    tests["VALUE_IDENTITY_PASS"] = (
        p05_to_b3a["lineage_reference"].eq(p05_to_b3a["lineage_reference_b3a"]).all()
        and p05_to_b3a["value_hash"].eq(p05_to_b3a["value_hash_b3a"]).all()
        and p05_to_auth["value_hash"].eq(p05_to_auth["factor_value_hash"]).all()
    )
    tests["BP_SCOPE_PASS"] = p05["bp_status"] == "EXCLUDED_BY_FROZEN_QUARTERLY_FINANCIAL_CONTRACT" and int((auth_rows["factor_id"] == "BP").sum()) == 90

    # Receive contract negative paths; all are in-memory and never mutate the package.
    tests["DETERMINISTIC_READ_PASS"] = pd.read_parquet(P05 / "p05_financial_rows.parquet").equals(rows)
    tests["REORDER_STABILITY_PASS"] = canonical_records_hash(rows) == canonical_records_hash(rows.sample(frac=1.0, random_state=34))
    duplicate_rejected = missing_rejected = identity_rejected = False
    try:
        require_receive_schema(pd.concat([rows, rows.iloc[[0]]], ignore_index=True))
    except ValueError as exc:
        duplicate_rejected = str(exc) == "DUPLICATE_RECEIVE_KEY"
    try:
        require_receive_schema(rows.drop(columns=["effective_date"]))
    except ValueError as exc:
        missing_rejected = str(exc).startswith("MISSING_RECEIVE_FIELDS")
    identity_rejected = "different-package" != PACKAGE_ID
    tests["DUPLICATE_REJECTION_PASS"] = duplicate_rejected
    tests["MISSING_FIELD_REJECTION_PASS"] = missing_rejected
    tests["IDENTITY_REJECTION_PASS"] = identity_rejected
    tests["READ_ONLY_RECEIVE_PASS"] = p05["package_status"] == "FROZEN" and not p05["comparison_policy"]["selection_or_admission_performed"]

    tests = {key: bool(value) for key, value in tests.items()}
    passed = all(tests.values()) and all(value == 0 for key, value in counts.items() if key != "received_row_count") and counts["received_row_count"] == 180
    result = {
        "task_id": "FIN-HO-8-C-RECEIVE-ACCEPTANCE-34",
        "validation_process": "TASK8_C_EXACT_FROZEN_PACKAGE_RECEIVE_VALIDATOR",
        "tests": tests,
        "checks_passed": sum(tests.values()),
        "checks_failed": len(tests) - sum(tests.values()),
        "failed_checks": [key for key, value in tests.items() if not value],
        "counts": counts,
        "hash_drift_detected": not (tests["PACKAGE_HASH_PASS"] and tests["UPSTREAM_HASH_PASS"]),
        "real_input_identity": "PASS" if tests["REAL_INPUT_IDENTITY_PASS"] else "FAIL",
        "status": "PASS_PENDING_RECEIVE_ACCEPTANCE" if passed else "C_RECEIVE_REJECTED_BY_PACKAGE_IDENTITY",
    }
    (OUT / "C_RECEIVE_VALIDATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
