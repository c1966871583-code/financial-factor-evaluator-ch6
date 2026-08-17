"""Independent disk-only validation for the authoritative snapshot candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "artifacts" / "authoritative_financial_snapshot"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    stale = json.loads((ROOT / "policies/stale_policy.json").read_text(encoding="utf-8"))
    paths = {
        "financial": ROOT / "raw/financial_source_raw.parquet",
        "market": ROOT / "raw/market_reference_raw.parquet",
        "mask": ROOT / "masks/sample_mask.parquet",
        "rows": ROOT / "processed/authoritative_factor_rows.parquet",
        "lineage": ROOT / "lineage/row_lineage.parquet",
        "dependency": ROOT / "lineage/factor_dependency_lineage.parquet",
    }
    frames = {name: pd.read_parquet(path) for name, path in paths.items()}
    rows, lineage, mask = frames["rows"], frames["lineage"], frames["mask"]
    required_rows = {
        "authoritative_row_id", "authoritative_run_id", "code", "factor_id", "factor_version",
        "evaluation_date", "report_period", "publish_date", "effective_date", "factor_value",
        "source_record_reference", "source_field_refs", "revision_reference",
        "sample_mask_reference", "preprocessing_policy_reference", "stale_policy_reference",
        "formula_reference", "upstream_raw_hash", "factor_value_hash",
    }
    tests = {}
    tests["REAL_PROVIDER_PASS"] = manifest["provider"] == "RQData" and not manifest["shadow_test_reused_as_authority"]
    tests["RAW_SOURCE_PRESENT"] = not frames["financial"].empty and not frames["market"].empty
    tests["SCHEMA_VALIDATION_PASS"] = required_rows.issubset(rows.columns)
    financial_rows = rows[rows["factor_id"].isin(["ROE", "OCF_NP"])]
    date_order = (
        pd.to_datetime(financial_rows["report_period"]) <= pd.to_datetime(financial_rows["publish_date"])
    ) & (
        pd.to_datetime(financial_rows["publish_date"]) < pd.to_datetime(financial_rows["effective_date"])
    ) & (
        pd.to_datetime(financial_rows["effective_date"]) <= pd.to_datetime(financial_rows["evaluation_date"])
    )
    tests["PIT_SOURCE_PASS"] = bool(date_order.all())
    tests["DISCLOSURE_DATE_PASS"] = frames["financial"]["publish_date"].notna().all()
    revision = pd.read_csv(ROOT / "audit/revision_history.csv")
    tests["REVISION_HISTORY_PASS"] = (
        not revision.empty and {"revision_sequence", "revision_status", "source_record_reference"}.issubset(revision.columns)
        and not revision.duplicated(["factor_id", "code", "report_period", "revision_sequence"]).any()
    )
    reason_columns = {"sample_status", "inclusion_reason", "exclusion_reason", "reason_explanation"}
    tests["SAMPLE_MASK_PASS"] = (
        len(mask) == 90 and reason_columns.issubset(mask.columns)
        and not mask.duplicated(["code", "evaluation_date"]).any()
        and mask["sample_mask_reference"].isin(rows["sample_mask_reference"]).all()
    )
    tests["PREPROCESSING_POLICY_PASS"] = rows["preprocessing_policy_reference"].notna().all()
    tests["STALE_POLICY_PASS"] = (
        stale["decision_status"] == "FROZEN"
        and rows["stale_policy_reference"].notna().all()
        and not rows["stale_status"].isin(["STALE", "UNKNOWN"]).any()
    )
    tests["ROW_LINEAGE_PASS"] = (
        len(rows) == len(lineage) and rows["authoritative_row_id"].is_unique
        and lineage["authoritative_row_id"].is_unique
        and set(rows["authoritative_row_id"]) == set(lineage["authoritative_row_id"])
    )
    # Required references may be N/A only for BP market-reference rows.
    common_refs = ["sample_mask_reference", "preprocessing_policy_reference", "stale_policy_reference", "formula_reference", "factor_value_hash"]
    tests["ROW_LINEAGE_PASS"] = tests["ROW_LINEAGE_PASS"] and lineage[common_refs].notna().all().all()
    tests["VALUE_HASH_PASS"] = rows["factor_value_hash"].str.fullmatch(r"[0-9a-f]{64}").all() and rows["factor_value_hash"].is_unique
    hash_pairs = {
        "financial_source_dataset_sha256": paths["financial"],
        "market_reference_dataset_sha256": paths["market"],
        "sample_mask_sha256": paths["mask"],
        "lineage_dataset_sha256": paths["lineage"],
        "authoritative_factor_rows_sha256": paths["rows"],
        "factor_dependency_lineage_sha256": paths["dependency"],
    }
    tests["DATASET_HASH_PASS"] = all(manifest[key] == sha256(path) for key, path in hash_pairs.items())
    tests["STABLE_RUN_REFERENCE_PASS"] = (
        manifest["run_id"].startswith("rqdata-authoritative-")
        and rows["authoritative_run_id"].eq(manifest["run_id"]).all()
    )
    tests["ROW_COUNT_VALIDATION_PASS"] = (
        len(rows) == manifest["row_count"] and rows["code"].nunique() == manifest["security_count"]
        and rows["factor_id"].nunique() == manifest["factor_count"]
    )
    tests = {name: bool(value) for name, value in tests.items()}
    passed = all(tests.values())
    result = {
        "task_id": "FIN-HO-8-B3A-AUTHORITATIVE-UPSTREAM-SNAPSHOT-28",
        "validation_process": "INDEPENDENT_DISK_ONLY_VALIDATOR",
        "tests": tests,
        "independent_validation": "PASS" if passed else "FAIL",
        "status": "AUTHORITATIVE_UPSTREAM_SNAPSHOT_READY_FOR_FREEZE" if passed else "BLOCKED_BY_AUTHORITY_VALIDATION",
        "authoritative_run_id": manifest["run_id"],
        "failed_checks": [name for name, value in tests.items() if not value],
    }
    (ROOT / "audit/authority_validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if passed:
        manifest["authoritative_validation_status"] = "VALIDATED_CANDIDATE"
        (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
