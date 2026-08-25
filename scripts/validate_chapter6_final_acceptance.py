"""Independent local validator for the scoped Chapter 6 final acceptance."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend.amr.financial_factor_registry import ROE_TTM_ENDING_EQUITY

ART = PROJECT / "artifacts"
DOC_PROV = PROJECT / "docs" / "provenance"
OUT = ART / "chapter_6_final_acceptance"
RUN_ID = "rqdata-authoritative-20260812T023240Z-16b9b5eba2"
PACKAGE_ID = "p05-financial-0e95e865a647bee1f9e61929"
CODE_SNAPSHOT_COMMIT = "c40193de9d2e04145226599c03fecff48037d007"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=PROJECT, text=True).strip()


def main() -> int:
    auth_dir = ART / "authoritative_financial_snapshot"
    b3a_dir = ART / "fin_ho_8_b3a"
    p05_dir = ART / "p05_candidate_handoff"
    b_gate_dir = ART / "fin_ho_8_b_gate"
    c_dir = ART / "fin_ho_8_c"

    auth = load(auth_dir / "manifest.json")
    auth_freeze = load(auth_dir / "FREEZE_RECORD.json")
    auth_validation = load(auth_dir / "audit" / "authority_validation.json")
    b3a = load(b3a_dir / "handoff_manifest.json")
    b3a_validation = load(b3a_dir / "handoff_validation.json")
    p05 = load(p05_dir / "p05_manifest.json")
    p05_freeze = load(p05_dir / "P05_FREEZE_RECORD.json")
    p05_validation = load(p05_dir / "p05_validation.json")
    b_gate = load(b_gate_dir / "B_GATE_ACCEPTANCE_RECORD.json")
    c_receive = load(c_dir / "C_RECEIVE_ACCEPTANCE_RECORD.json")
    c_validation = load(c_dir / "C_RECEIVE_VALIDATION.json")
    amendment_artifact = load(c_dir / "C_RECEIVE_SCOPE_AMENDMENT.json")
    amendment_tracked = load(DOC_PROV / "C_RECEIVE_SCOPE_AMENDMENT.json")
    code_provenance = load(DOC_PROV / "RQDATA_REAL_RUN_CODE_SNAPSHOT.json")

    checks: dict[str, bool] = {}
    checks["AUTHORITATIVE_IDENTITY_PASS"] = (
        auth["authoritative_run_id"] == auth_freeze["authoritative_run_id"] == RUN_ID
        and auth["provider"] == "RQData"
        and auth["shadow_test_reused_as_authority"] is False
    )
    checks["AUTHORITATIVE_FREEZE_PASS"] = (
        auth["authoritative_snapshot_status"] == "FROZEN"
        and auth_freeze["freeze_status"] == "FROZEN"
        and auth["freeze_record_hash"] == sha256(auth_dir / "FREEZE_RECORD.json")
        and auth_validation["independent_validation"] == "PASS"
        and not auth_validation["failed_checks"]
    )
    checks["AUTHORITATIVE_HASH_PASS"] = (
        auth["authoritative_factor_rows_sha256"]
        == sha256(auth_dir / "processed" / "authoritative_factor_rows.parquet")
        and auth["lineage_dataset_sha256"] == sha256(auth_dir / "lineage" / "row_lineage.parquet")
        and auth["sample_mask_sha256"] == sha256(auth_dir / "masks" / "sample_mask.parquet")
        and auth["financial_source_dataset_sha256"]
        == sha256(auth_dir / "raw" / "financial_source_raw.parquet")
    )
    checks["B3A_BINDING_PASS"] = (
        b3a["source_authoritative_run_id"] == RUN_ID
        and b3a["source_authoritative_snapshot_status"] == "FROZEN"
        and b3a["row_count"] == 180
        and b3a["factor_count"] == 2
        and b3a["handoff_dataset_hash"]
        == sha256(b3a_dir / "qualified_financial_handoff_inputs.parquet")
        and b3a_validation["status"] == "B3A_QUALIFIED_FINANCIAL_HANDOFF_INPUTS_READY"
        and b3a_validation["checks_failed"] == 0
    )
    checks["P05_IDENTITY_PASS"] = (
        p05["package_id"] == p05_freeze["package_id"] == PACKAGE_ID
        and p05["source_authoritative_run_id"] == p05_freeze["source_authoritative_run_id"] == RUN_ID
        and p05["package_status"] == p05_freeze["freeze_status"] == "FROZEN"
    )
    checks["P05_HASH_PASS"] = (
        p05["dataset_hash"] == sha256(p05_dir / "p05_financial_rows.parquet")
        and p05["lineage_hash"] == sha256(p05_dir / "p05_lineage.parquet")
        and p05["sample_mask_hash"] == sha256(p05_dir / "p05_sample_mask.parquet")
        and p05["package_dataset_hash"] == sha256(p05_dir / "P05CandidateHandoffPackage.json")
        and p05["freeze_record_hash"] == sha256(p05_dir / "P05_FREEZE_RECORD.json")
        and p05_validation["post_freeze_manifest_hash"] == sha256(p05_dir / "p05_manifest.json")
    )
    checks["B_GATE_PASS"] = (
        b_gate["gate"] == "FIN_HO_8_B"
        and b_gate["status"] == "ACCEPTED"
        and b_gate["source_authoritative_run_id"] == RUN_ID
        and b_gate["p05_package_id"] == PACKAGE_ID
        and b_gate["hash_drift_detected"] is False
        and b_gate["tests"]["tests_failed"] == 0
    )
    checks["C_RECEIVE_PASS"] = (
        c_receive["gate"] == "FIN_HO_8_C"
        and c_receive["status"] == "ACCEPTED"
        and c_receive["source_authoritative_run_id"] == RUN_ID
        and c_receive["p05_package_id"] == PACKAGE_ID
        and c_receive["task8_ready"] is True
        and c_receive["tests"]["failed"] == 0
        and c_validation["checks_failed"] == 0
        and c_validation["hash_drift_detected"] is False
    )
    checks["SCOPE_AMENDMENT_PASS"] = (
        amendment_artifact == amendment_tracked
        and amendment_tracked["status"] == "APPLIED"
        and amendment_tracked["decision_authority"] == "OPERATOR"
        and amendment_tracked["amends"]["record_sha256_after_scope_clarification"]
        == sha256(c_dir / "C_RECEIVE_ACCEPTANCE_RECORD.json")
        and amendment_tracked["binding"]["source_authoritative_run_id"] == RUN_ID
        and amendment_tracked["binding"]["p05_package_id"] == PACKAGE_ID
    )
    accepted = amendment_tracked["clarified_acceptance_scope"]
    checks["ACCEPTED_SCOPE_PASS"] = (
        [item["accepted_semantic_name"] for item in accepted["accepted_factors"]]
        == [ROE_TTM_ENDING_EQUITY.canonical_semantic_name, "OCF_NP"]
        and accepted["accepted_row_count"] == 180
        and accepted["task8_ready"] is True
        and accepted["task8_ready_applies_only_to_accepted_factors"] is True
    )
    bp = amendment_tracked["bp_scope"]
    checks["BP_BOUNDARY_PASS"] = (
        bp["real_data_validated"] is True
        and bp["authoritative_snapshot_status"] == "FROZEN"
        and bp["authoritative_rows_preserved"] == 90
        and bp["included_in_current_quarterly_p05"] is False
        and bp["valuation_factor_handoff_contract_ready"] is False
        and bp["task8_receive_accepted"] is False
    )
    checks["CODE_PROVENANCE_PASS"] = (
        code_provenance["code_snapshot"]["commit"] == CODE_SNAPSHOT_COMMIT
        and git_value("rev-parse", CODE_SNAPSHOT_COMMIT) == CODE_SNAPSHOT_COMMIT
        and git_value("rev-parse", f"{CODE_SNAPSHOT_COMMIT}^{{tree}}")
        == code_provenance["code_snapshot"]["tree"]
        and code_provenance["validation"]["full_local_test_suite"]["failed"] == 0
        and code_provenance["data_boundary"]["artifacts_committed"] is False
        and code_provenance["data_boundary"]["credentials_committed"] is False
    )
    checks["REAL_INPUT_PASS"] = (
        b_gate["real_provider"] == c_receive["real_provider"] == "RQData"
        and not b_gate["synthetic_input_used"]
        and not b_gate["mock_provider_used"]
        and not b_gate["shadow_test_reused_as_authority"]
    )
    zero_fields = (
        "missing_row_count",
        "unexpected_row_count",
        "duplicate_received_row_count",
        "orphan_lineage_count",
        "broken_receive_chain_count",
        "source_run_mismatch_count",
        "missing_policy_reference_count",
        "policy_version_mismatch_count",
        "pit_violation_count",
        "timing_violation_count",
        "unknown_source_count",
    )
    checks["C_RECEIVE_ZERO_DEFECT_COUNTS_PASS"] = all(c_receive[name] == 0 for name in zero_fields)
    checks["GOVERNANCE_BOUNDARY_PASS"] = (
        c_receive["chapter6_complete"] is False
        and c_receive["production_ready"] is False
        and auth["production_ready"] is False
        and p05["production_ready"] is False
        and amendment_tracked["amendment_semantics"]["production_ready_declared"] is False
    )

    checks = {name: bool(value) for name, value in checks.items()}
    passed = all(checks.values())
    result = {
        "task_id": "CHAPTER-6-FINAL-ACCEPTANCE-REVIEW",
        "validation_process": "INDEPENDENT_DISK_AND_GIT_FINAL_ACCEPTANCE_VALIDATOR",
        "source_authoritative_run_id": RUN_ID,
        "p05_package_id": PACKAGE_ID,
        "accepted_semantic_factors": [ROE_TTM_ENDING_EQUITY.canonical_semantic_name, "OCF_NP"],
        "accepted_rows": 180,
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_failed": len(checks) - sum(checks.values()),
        "failed_checks": [name for name, value in checks.items() if not value],
        "status": "PASS_PENDING_FINAL_ACCEPTANCE" if passed else "BLOCKED_BY_FINAL_ACCEPTANCE_VALIDATION",
        "chapter6_complete": False,
        "production_ready": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "CHAPTER_6_FINAL_VALIDATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
