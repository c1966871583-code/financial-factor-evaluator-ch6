"""Independent validation of regenerated real B3A quarterly-financial inputs."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "artifacts/authoritative_financial_snapshot"
OUTPUT = PROJECT / "artifacts/fin_ho_8_b3a"
TASK8 = PROJECT.parent / "TASK8-FINANCIAL-INPUT-CONTRACT-EXTENSION"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_task8_contract():
    sys.path.insert(0, str(TASK8))
    from backend.amr.financial_numeric_deduplication import FinancialDedupInput
    return FinancialDedupInput


def main() -> int:
    manifest = json.loads((OUTPUT / "handoff_manifest.json").read_text(encoding="utf-8"))
    source_manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    freeze = json.loads((SOURCE / "FREEZE_RECORD.json").read_text(encoding="utf-8"))
    handoff = pd.read_parquet(OUTPUT / "qualified_financial_handoff_inputs.parquet")
    lineage = pd.read_parquet(OUTPUT / "handoff_lineage.parquet")
    mask = pd.read_parquet(OUTPUT / "handoff_sample_mask.parquet")
    source_rows = pd.read_parquet(SOURCE / "processed/authoritative_factor_rows.parquet")
    required = {
        "factor_id", "factor_version", "code", "evaluation_date", "report_period",
        "publish_date", "effective_date", "factor_value", "sample_status", "sample_reason",
        "preprocessing_policy_id", "preprocessing_policy_version", "stale_policy_id",
        "stale_policy_version", "stale_status", "source_age_days", "source_record_reference",
        "revision_reference", "lineage_reference", "value_hash", "authoritative_run_id",
    }
    tests = {}
    tests["AUTHORITATIVE_BINDING_PASS"] = (
        manifest["source_authoritative_run_id"] == source_manifest["run_id"] == freeze["authoritative_run_id"]
        and source_manifest["authoritative_snapshot_status"] == "FROZEN"
        and source_manifest["freeze_record_hash"] == sha256(SOURCE / "FREEZE_RECORD.json")
    )
    tests["SCHEMA_VALIDATION_PASS"] = required.issubset(handoff.columns)
    tests["ROW_COUNT_PASS"] = len(handoff) == 180 and manifest["row_count"] == 180
    tests["KEY_UNIQUENESS_PASS"] = not handoff.duplicated(["factor_id", "evaluation_date", "code"]).any()
    timing = (
        pd.to_datetime(handoff["report_period"]) <= pd.to_datetime(handoff["publish_date"])
    ) & (
        pd.to_datetime(handoff["publish_date"]) < pd.to_datetime(handoff["effective_date"])
    ) & (
        pd.to_datetime(handoff["effective_date"]) <= pd.to_datetime(handoff["evaluation_date"])
    )
    tests["PIT_VALIDATION_PASS"] = bool(timing.all())
    tests["FINITE_VALUES_PASS"] = bool(
        np.isfinite(pd.to_numeric(handoff["factor_value"], errors="coerce")).all()
        and np.isfinite(pd.to_numeric(handoff["raw_pit_factor_value"], errors="coerce")).all()
    )
    tests["SAMPLE_POLICY_PASS"] = (
        handoff["sample_status"].eq("INCLUDED").all()
        and handoff["factor_sample_mask"].eq(True).all()
        and handoff["sample_mask_reference"].isin(mask["sample_mask_reference"]).all()
        and handoff["sample_reason"].notna().all()
    )
    tests["PREPROCESSING_POLICY_PASS"] = handoff["preprocessing_policy_reference"].eq(handoff["preprocessing_policy_id"]).all()
    tests["STALE_POLICY_PASS"] = handoff["stale_status"].eq("FRESH").all() and handoff["source_age_days"].le(550).all()
    lineage_ids = set(lineage["authoritative_row_id"])
    tests["LINEAGE_VALIDATION_PASS"] = (
        len(lineage) == len(handoff) and handoff["lineage_reference"].isin(lineage_ids).all()
        and handoff[["source_record_reference", "revision_reference", "lineage_reference", "value_hash"]].notna().all().all()
    )
    source_values = source_rows[["authoritative_row_id", "factor_value_hash", "authoritative_run_id"]]
    rebound = handoff.merge(source_values, left_on="lineage_reference", right_on="authoritative_row_id", how="left", validate="one_to_one", suffixes=("", "_source"))
    tests["VALUE_HASH_PASS"] = (
        rebound["value_hash"].eq(rebound["factor_value_hash_source"]).all()
        and rebound["authoritative_run_id"].eq(rebound["authoritative_run_id_source"]).all()
    )
    tests["HASH_VALIDATION_PASS"] = (
        manifest["source_snapshot_hash"] == source_manifest["authoritative_factor_rows_sha256"]
        and manifest["handoff_dataset_hash"] == sha256(OUTPUT / "qualified_financial_handoff_inputs.parquet")
        and manifest["lineage_hash"] == sha256(OUTPUT / "handoff_lineage.parquet")
        and manifest["sample_mask_hash"] == sha256(OUTPUT / "handoff_sample_mask.parquet")
    )
    tests["BP_QUALIFICATION_EXPLICIT_PASS"] = (
        manifest["bp_qualification_status"] == "NOT_APPLICABLE_TO_QUARTERLY_FINANCIAL_HANDOFF"
        and set(handoff["factor_id"]) == {"ROE", "OCF_NP"}
        and len(source_rows[source_rows["factor_id"] == "BP"]) == 90
    )
    FinancialDedupInput = load_task8_contract()
    contract_instances = []
    for factor_id, part in handoff.groupby("factor_id"):
        contract_frame = part[
            ["evaluation_date", "code", "factor_id", "raw_pit_factor_value", "evaluation_factor_value",
             "report_period", "publish_date", "effective_date", "factor_sample_mask",
             "source_record_reference", "source_input_hash", "preprocessing_policy_version",
             "staleness_status", "factor_value_hash"]
        ].copy()
        instance = FinancialDedupInput(
            factor_id=factor_id, factor_version=str(part["factor_version"].iloc[0]),
            dataset_id=f"b3a-{factor_id}", sample_fingerprint=manifest["sample_mask_hash"],
            preprocessing_policy_version=str(part["preprocessing_policy_version"].iloc[0]),
            _frame=contract_frame, frequency="quarterly",
        )
        contract_instances.append(len(instance.get_frame()))
    tests["REAL_CONTRACT_VALIDATION_PASS"] = contract_instances == [90, 90]
    tests["GOVERNANCE_PASS"] = (
        not manifest["shadow_test_reused_as_authority"] and not manifest["production_ready"]
        and not manifest["p05_ready"] and not manifest["task8_ready"]
    )
    tests = {key: bool(value) for key, value in tests.items()}
    passed = all(tests.values())
    result = {
        "task_id": "FIN-HO-8-B3A-REGENERATE-QUALIFIED-FINANCIAL-HANDOFF-31",
        "validation_process": "INDEPENDENT_REAL_HANDOFF_VALIDATOR",
        "tests": tests,
        "checks_passed": sum(tests.values()), "checks_failed": len(tests) - sum(tests.values()),
        "failed_checks": [key for key, value in tests.items() if not value],
        "status": "B3A_QUALIFIED_FINANCIAL_HANDOFF_INPUTS_READY" if passed else "BLOCKED_BY_B3A_CONTRACT_TEST_FAILURE",
    }
    (OUTPUT / "handoff_validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
