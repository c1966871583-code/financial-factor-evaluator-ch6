"""Independent Task8 receive validation for the frozen BP valuation package."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
AUTH = PROJECT / "artifacts" / "authoritative_financial_snapshot"
PACKAGE = PROJECT / "artifacts" / "bp_valuation_handoff"
OUT = PROJECT / "artifacts" / "bp_valuation_receive"
TASK8 = PROJECT.parent / "TASK8-FINANCIAL-INPUT-CONTRACT-EXTENSION"
RUN_ID = "rqdata-authoritative-20260812T023240Z-16b9b5eba2"
PACKAGE_ID = "bp-valuation-72c7da759d94b24c734705a1"
TASK8_CONTRACT_COMMIT = "f92dcde"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_value(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def load_contract():
    sys.path.insert(0, str(TASK8))
    from backend.amr.valuation_numeric_deduplication import ValuationDedupInput

    return ValuationDedupInput


def main() -> int:
    manifest = load(PACKAGE / "manifest.json")
    freeze = load(PACKAGE / "BP_VALUATION_FREEZE_RECORD.json")
    package = load(PACKAGE / "BPValuationHandoffPackage.json")
    auth = load(AUTH / "manifest.json")
    preprocessing = load(AUTH / "policies" / "preprocessing_policy.json")
    rows = pd.read_parquet(PACKAGE / "bp_valuation_rows.parquet")
    lineage = pd.read_parquet(PACKAGE / "bp_valuation_lineage.parquet")
    source = pd.read_parquet(AUTH / "processed" / "authoritative_factor_rows.parquet")
    source_bp = source.loc[source["factor_id"].eq("BP")].copy()

    checks: dict[str, bool] = {}
    checks["PACKAGE_IDENTITY_PASS"] = (
        manifest["package_id"] == freeze["package_id"] == package["package_id"] == PACKAGE_ID
        and manifest["source_authoritative_run_id"]
        == freeze["source_authoritative_run_id"]
        == package["source_authoritative_run_id"]
        == RUN_ID
    )
    checks["FREEZE_PASS"] = (
        manifest["status"] == freeze["freeze_status"] == "FROZEN"
        and manifest["freeze_record_hash"] == sha256(PACKAGE / "BP_VALUATION_FREEZE_RECORD.json")
        and manifest["immutability_semantics"] == "IMMUTABLE_FOR_TASK8_RECEIVE"
    )
    checks["PACKAGE_HASH_PASS"] = (
        manifest["rows_hash"] == freeze["rows_hash"] == sha256(PACKAGE / "bp_valuation_rows.parquet")
        and manifest["lineage_hash"]
        == freeze["lineage_hash"]
        == sha256(PACKAGE / "bp_valuation_lineage.parquet")
        and manifest["package_hash"]
        == freeze["package_hash"]
        == sha256(PACKAGE / "BPValuationHandoffPackage.json")
    )
    checks["AUTHORITATIVE_BINDING_PASS"] = (
        auth["authoritative_run_id"] == RUN_ID
        and auth["authoritative_snapshot_status"] == "FROZEN"
        and manifest["source_snapshot_hash"] == auth["authoritative_factor_rows_sha256"]
        and manifest["source_freeze_record_hash"] == auth["freeze_record_hash"]
    )
    checks["SCOPE_PASS"] = (
        len(rows) == 90
        and rows["code"].nunique() == 30
        and rows["evaluation_date"].nunique() == 3
        and set(rows["factor_id"]) == {"BP"}
        and not rows.duplicated(["evaluation_date", "code", "factor_id"]).any()
    )
    checks["VALUATION_DATE_PASS"] = rows["provider_date"].eq(rows["evaluation_date"]).all()
    checks["FINITE_VALUE_PASS"] = np.isfinite(
        rows[
            [
                "raw_factor_value",
                "evaluation_factor_value",
                "book_to_market_ratio_lf",
                "pb_ratio_lf",
                "market_cap",
            ]
        ].to_numpy(dtype=float)
    ).all()
    checks["BP_MAPPING_PASS"] = (
        rows["provider"].eq("RQData").all()
        and rows["provider_endpoint"].eq("rqdatac.get_factor").all()
        and rows["provider_field"].eq("book_to_market_ratio_lf").all()
        and rows["pb_ratio_lf"].gt(0).all()
        and float((rows["evaluation_factor_value"] - 1.0 / rows["pb_ratio_lf"]).abs().max()) <= 1e-12
    )
    checks["POLICY_PASS"] = (
        rows["factor_sample_mask"].eq(True).all()
        and rows["staleness_status"].eq("NOT_APPLICABLE").all()
        and rows["preprocessing_policy_version"].eq(preprocessing["preprocessing_policy_version"]).all()
        and rows["valuation_policy_version"].eq("1.0").all()
    )
    source_columns = [
        "authoritative_row_id",
        "source_record_reference",
        "factor_value_hash",
        "value_hash",
        "authoritative_run_id",
        "factor_value",
    ]
    joined = rows.merge(
        source_bp[source_columns],
        on="authoritative_row_id",
        how="left",
        suffixes=("", "_source"),
        indicator=True,
        validate="one_to_one",
    )
    checks["LINEAGE_PASS"] = (
        joined["_merge"].eq("both").all()
        and joined["source_record_reference"].eq(joined["source_record_reference_source"]).all()
        and joined["factor_value_hash"].eq(joined["factor_value_hash_source"]).all()
        and joined["value_hash"].eq(joined["value_hash_source"]).all()
        and joined["authoritative_run_id"].eq(joined["authoritative_run_id_source"]).all()
        and np.allclose(joined["evaluation_factor_value"], joined["factor_value"], rtol=0, atol=0)
        and set(rows["authoritative_row_id"]) == set(lineage["authoritative_row_id"])
    )
    full_task8_commit = git_value(TASK8, "rev-parse", TASK8_CONTRACT_COMMIT)
    checks["TASK8_COMMIT_PASS"] = (
        full_task8_commit == manifest["task8_contract_commit"] == package["task8_contract_commit"]
    )
    ValuationDedupInput = load_contract()
    contract = ValuationDedupInput(
        factor_id="BP",
        factor_version=str(rows["factor_version"].iloc[0]),
        dataset_id=PACKAGE_ID,
        sample_fingerprint=manifest["sample_mask_hash"],
        preprocessing_policy_version=manifest["preprocessing_policy_version"],
        valuation_policy_version=manifest["valuation_policy_version"],
        authoritative_run_id=RUN_ID,
        _frame=rows,
    )
    checks["TASK8_CONTRACT_PASS"] = len(contract.get_frame()) == 90
    checks["GOVERNANCE_PASS"] = (
        package["selection_or_admission_performed"] is False
        and manifest["production_ready"] is False
        and manifest["task8_receive_accepted"] is False
        and manifest["rqdata_queried"] is False
        and manifest["credential_values_included"] is False
    )
    checks = {name: bool(value) for name, value in checks.items()}
    passed = all(checks.values())
    result = {
        "task_id": "BP-VALUATION-TASK8-RECEIVE",
        "package_id": PACKAGE_ID,
        "source_authoritative_run_id": RUN_ID,
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_failed": len(checks) - sum(checks.values()),
        "failed_checks": [name for name, value in checks.items() if not value],
        "received_rows": 90,
        "missing_rows": int((joined["_merge"] != "both").sum()),
        "duplicate_rows": int(rows.duplicated(["evaluation_date", "code", "factor_id"]).sum()),
        "hash_drift_detected": not checks["PACKAGE_HASH_PASS"],
        "status": "PASS_PENDING_BP_TASK8_RECEIVE" if passed else "BP_TASK8_RECEIVE_REJECTED",
        "production_ready": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "BP_VALUATION_RECEIVE_VALIDATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
