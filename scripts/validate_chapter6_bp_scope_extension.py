"""Validate a non-destructive Chapter 6 scope extension for frozen BP data."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend.amr.financial_factor_registry import ROE_TTM_ENDING_EQUITY

ART = PROJECT / "artifacts"
PROV = PROJECT / "docs" / "provenance"
OUT = ART / "chapter_6_bp_scope_extension"
TASK8 = PROJECT.parent / "TASK8-FINANCIAL-INPUT-CONTRACT-EXTENSION"

RUN_ID = "rqdata-authoritative-20260812T023240Z-16b9b5eba2"
P05_PACKAGE_ID = "p05-financial-0e95e865a647bee1f9e61929"
BP_PACKAGE_ID = "bp-valuation-72c7da759d94b24c734705a1"
VALUATION_CONTRACT_COMMIT = "f92dcde221659f8daed7ca991b1e263a532c6d91"
BASE_ACCEPTANCE_SHA256 = "d91e03dc908863f84012f3083272fa71195ab0f812f140e564293364dbf90628"
BP_RECEIVE_SHA256 = "c8a2bd11f2ce16180747c142c3ca8730b84b96e60de39fcdb15dbf4558485799"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_value(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def main() -> int:
    base_path = PROV / "CHAPTER_6_FINAL_ACCEPTANCE_RECORD.json"
    bp_receive_path = PROV / "BP_VALUATION_RECEIVE_ACCEPTANCE_RECORD.json"
    base = load(base_path)
    bp_receive = load(bp_receive_path)
    auth = load(ART / "authoritative_financial_snapshot" / "manifest.json")
    p05 = load(ART / "p05_candidate_handoff" / "p05_manifest.json")
    bp_manifest = load(ART / "bp_valuation_handoff" / "manifest.json")
    bp_freeze_path = ART / "bp_valuation_handoff" / "BP_VALUATION_FREEZE_RECORD.json"
    bp_validation_path = ART / "bp_valuation_receive" / "BP_VALUATION_RECEIVE_VALIDATION.json"
    bp_validation = load(bp_validation_path)
    bp_rows = pd.read_parquet(ART / "bp_valuation_handoff" / "bp_valuation_rows.parquet")

    checks: dict[str, bool] = {}
    checks["BASE_ACCEPTANCE_IMMUTABLE_PASS"] = (
        sha256(base_path) == BASE_ACCEPTANCE_SHA256
        and base["status"] == "CHAPTER_6_FINAL_ACCEPTANCE_ACCEPTED"
        and base["accepted_scope"]["rows"] == 180
        and base["bp_boundary"]["included_in_this_chapter6_acceptance"] is False
    )
    checks["BP_RECEIVE_RECORD_PASS"] = (
        sha256(bp_receive_path) == BP_RECEIVE_SHA256
        and bp_receive["status"] == "BP_VALUATION_TASK8_RECEIVE_ACCEPTED"
        and bp_receive["task8_ready_for_bp_valuation_scope"] is True
        and bp_receive["chapter6_scope_extended"] is False
    )
    checks["COMMON_AUTHORITY_PASS"] = (
        base["accepted_scope"]["source_authoritative_run_id"]
        == bp_receive["source_authoritative_run_id"]
        == auth["authoritative_run_id"]
        == RUN_ID
        and auth["authoritative_snapshot_status"] == "FROZEN"
        and auth["row_count"] == 270
    )
    checks["DISTINCT_CONTRACTS_PASS"] = (
        base["accepted_scope"]["p05_package_id"] == p05["package_id"] == P05_PACKAGE_ID
        and bp_receive["package_id"] == bp_manifest["package_id"] == BP_PACKAGE_ID
        and p05["schema_version"] == "P05CandidateHandoffPackage-v1.0"
        and bp_manifest["schema_version"] == "valuation_numeric_dedup_v1"
        and p05["package_status"] == bp_manifest["status"] == "FROZEN"
    )
    checks["QUARTERLY_SCOPE_PRESERVED_PASS"] = (
        base["accepted_scope"]["semantic_factors"] == [ROE_TTM_ENDING_EQUITY.canonical_semantic_name, "OCF_NP"]
        and p05["accepted_row_count"] == 180
        and len(p05["factor_scope"]) == 2
        and p05["bp_status"] == "EXCLUDED_BY_FROZEN_QUARTERLY_FINANCIAL_CONTRACT"
    )
    checks["BP_SCOPE_PASS"] = (
        bp_manifest["factor_scope"] == ["BP"]
        and bp_manifest["row_count"] == 90
        and bp_manifest["security_count"] == 30
        and bp_manifest["evaluation_date_count"] == 3
        and bp_manifest["frequency"] == "evaluation_date_snapshot"
        and len(bp_rows) == 90
        and set(bp_rows["factor_id"]) == {"BP"}
        and bp_rows["code"].nunique() == 30
        and bp_rows["evaluation_date"].nunique() == 3
    )
    values = bp_rows["evaluation_factor_value"].to_numpy(dtype=float)
    pb = bp_rows["pb_ratio_lf"].to_numpy(dtype=float)
    checks["BP_SEMANTICS_PASS"] = (
        np.isfinite(values).all()
        and np.isfinite(pb).all()
        and (pb > 0).all()
        and np.allclose(values, 1.0 / pb, rtol=0.0, atol=1e-12)
        and bp_rows["provider_date"].equals(bp_rows["evaluation_date"])
        and set(bp_rows["staleness_status"]) == {"NOT_APPLICABLE"}
    )
    checks["BP_HASH_AND_FREEZE_PASS"] = (
        bp_manifest["rows_hash"] == sha256(ART / "bp_valuation_handoff" / "bp_valuation_rows.parquet")
        and bp_manifest["lineage_hash"] == sha256(ART / "bp_valuation_handoff" / "bp_valuation_lineage.parquet")
        and bp_manifest["freeze_record_hash"] == sha256(bp_freeze_path)
        and bp_receive["receive_validation"]["validation_sha256"] == sha256(bp_validation_path)
        and bp_validation["checks_failed"] == 0
        and bp_validation["hash_drift_detected"] is False
    )
    checks["TASK8_VALUATION_CONTRACT_PASS"] = (
        bp_manifest["task8_contract_commit"] == VALUATION_CONTRACT_COMMIT
        and bp_receive["binding"]["task8_valuation_contract_commit"] == VALUATION_CONTRACT_COMMIT
        and git_value(TASK8, "rev-parse", VALUATION_CONTRACT_COMMIT) == VALUATION_CONTRACT_COMMIT
    )
    checks["NO_SEMANTIC_COLLAPSE_PASS"] = (
        bp_manifest["frequency"] != "quarterly"
        and bp_manifest["comparison_variant"] == "evaluation_factor_value"
        and bp_manifest["selection_or_admission_performed"] is False
        and bp_receive["comparison_semantics"]["direction_flip_performed"] is False
        and bp_receive["comparison_semantics"]["dedup_comparison_value_generated"] is False
    )
    checks["GOVERNANCE_BOUNDARY_PASS"] = (
        base["production_ready"] is False
        and bp_receive["production_ready"] is False
        and auth["production_ready"] is False
        and bp_manifest["production_ready"] is False
        and bp_manifest["rqdata_queried"] is False
    )

    checks = {name: bool(value) for name, value in checks.items()}
    passed = all(checks.values())
    result = {
        "task_id": "CHAPTER-6-BP-SCOPE-EXTENSION-REVIEW",
        "validation_process": "INDEPENDENT_MULTI_CONTRACT_SCOPE_EXTENSION_VALIDATOR",
        "source_authoritative_run_id": RUN_ID,
        "base_acceptance_sha256": sha256(base_path),
        "bp_receive_acceptance_sha256": sha256(bp_receive_path),
        "scope_model": "PARALLEL_FROZEN_CONTRACTS_NO_SCHEMA_COLLAPSE",
        "expanded_semantic_factors": [ROE_TTM_ENDING_EQUITY.canonical_semantic_name, "OCF_NP", "BP_LF"],
        "expanded_rows": 270,
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_failed": len(checks) - sum(checks.values()),
        "failed_checks": [name for name, value in checks.items() if not value],
        "status": "PASS_PENDING_BP_SCOPE_EXTENSION_ACCEPTANCE" if passed else "BLOCKED_BY_BP_SCOPE_EXTENSION_VALIDATION",
        "production_ready": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "CHAPTER_6_BP_SCOPE_EXTENSION_VALIDATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
