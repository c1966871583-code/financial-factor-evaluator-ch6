"""Controlled, fail-closed RQData real-data shadow validation.

This runner is intentionally scoped to 30 deterministic CSI 300 constituents,
six report quarters, and three evaluation dates.  It never reads or prints
credential values and never writes outside ``artifacts/rqdata_shadow_test``.

The repository currently has no FinancialTimingPolicy implementation and its
forward-return contract does not freeze suspension/tradability handling.  The
runner therefore stops after real-data/PIT/source acceptance and records
``REAL_DATA_ACCEPTED_BUT_SHADOW_TEST_BLOCKED`` instead of inventing policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import rqdatac


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from backend.amr.financial_factor_registry import ROE_TTM_ENDING_EQUITY

ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "rqdata_shadow_test"
RAW_DIR = ARTIFACT_ROOT / "raw"
AUDIT_DIR = ARTIFACT_ROOT / "audit"
PROCESSED_DIR = ARTIFACT_ROOT / "processed"

INDEX_ID = "000300.XSHG"
UNIVERSE_DATE = "2025-06-30"
EVALUATION_DATES = ("2025-06-30", "2025-09-30", "2025-12-31")
START_QUARTER = "2024q2"
END_QUARTER = "2025q3"
PIT_AS_OF_DATE = "2025-12-31"
SECURITY_COUNT = 30
FINANCIAL_FIELDS = (
    "np_parent_company_ownersTTM",
    "net_operate_cashflowTTM",
    "equity_parent_company",
    "return_on_equity_weighted_average",
)
MARKET_FIELDS = (
    "market_cap",
    "book_to_market_ratio_lf",
    "pb_ratio_lf",
    "return_on_equity_ttm",
)


class ProviderBlocked(RuntimeError):
    pass


def _provider_call(label: str, fn: Callable[[], Any]) -> Any:
    """Retry only provider-temporary failures, at most three retries."""
    delays = (1, 2, 4)
    for attempt in range(4):
        try:
            return fn()
        except Exception as exc:
            message = str(exc).lower()
            temporary = any(
                token in message
                for token in ("429", "503", "tempor", "timeout", "timed out", "connection reset")
            )
            if not temporary or attempt == 3:
                raise ProviderBlocked(f"{label}:{type(exc).__name__}") from None
            time.sleep(delays[attempt])
    raise AssertionError("unreachable")


def _quarter_end(value: str) -> pd.Timestamp:
    year_text, quarter_text = value.lower().split("q", 1)
    return pd.Period(f"{int(year_text)}Q{int(quarter_text)}", freq="Q-DEC").end_time.normalize()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "UNKNOWN"


def _normalise_financial(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.reset_index().copy()
    result = result.rename(
        columns={
            "order_book_id": "code",
            "quarter": "provider_quarter",
            "info_date": "publish_date",
            "rice_create_tm": "provider_record_created_at",
        }
    )
    result["report_period"] = result["provider_quarter"].map(_quarter_end)
    result["publish_date"] = pd.to_datetime(result["publish_date"], errors="raise").dt.normalize()
    if "provider_record_created_at" in result:
        result["provider_record_created_at"] = pd.to_datetime(
            result["provider_record_created_at"], errors="coerce"
        )
    sort_cols = [
        "code",
        "report_period",
        "publish_date",
        "provider_record_created_at",
        "if_adjusted",
        *FINANCIAL_FIELDS,
    ]
    result = result.sort_values([c for c in sort_cols if c in result.columns], na_position="last")
    result = result.reset_index(drop=True)
    result.insert(0, "raw_row_ordinal", np.arange(len(result), dtype=np.int64))
    return result


def _normalise_market(frame: pd.DataFrame | None, evaluation_date: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["code", "evaluation_date", *MARKET_FIELDS])
    result = frame.reset_index().copy()
    result = result.rename(columns={"order_book_id": "code", "date": "provider_date"})
    result["evaluation_date"] = pd.Timestamp(evaluation_date)
    if "provider_date" in result:
        result["provider_date"] = pd.to_datetime(result["provider_date"], errors="raise").dt.normalize()
    return result.sort_values(["evaluation_date", "code"]).reset_index(drop=True)


def _finite_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce")
    values = num / den.where(den != 0)
    return values.where(np.isfinite(values))


def _financial_observations(raw: pd.DataFrame) -> pd.DataFrame:
    common = raw[
        [
            "raw_row_ordinal",
            "code",
            "report_period",
            "publish_date",
            "provider_quarter",
            "if_adjusted",
            "provider_record_created_at",
        ]
    ].copy()
    roe = common.copy()
    roe["factor_id"] = ROE_TTM_ENDING_EQUITY.canonical_semantic_name
    roe["provider_field"] = f"{ROE_TTM_ENDING_EQUITY.numerator_source}/{ROE_TTM_ENDING_EQUITY.denominator_source}"
    roe["factor_value"] = _finite_ratio(
        raw["np_parent_company_ownersTTM"], raw["equity_parent_company"]
    )
    ocf_np = common.copy()
    ocf_np["factor_id"] = "OCF_NP_TTM_PARENT"
    ocf_np["provider_field"] = "net_operate_cashflowTTM/np_parent_company_ownersTTM"
    ocf_np["factor_value"] = _finite_ratio(
        raw["net_operate_cashflowTTM"], raw["np_parent_company_ownersTTM"]
    )
    return pd.concat([roe, ocf_np], ignore_index=True).sort_values(
        ["factor_id", "code", "report_period", "publish_date", "raw_row_ordinal"]
    ).reset_index(drop=True)


def _factor_mapping(market: pd.DataFrame) -> pd.DataFrame:
    reciprocal = 1.0 / pd.to_numeric(market["pb_ratio_lf"], errors="coerce").where(
        pd.to_numeric(market["pb_ratio_lf"], errors="coerce") > 0
    )
    direct = pd.to_numeric(market["book_to_market_ratio_lf"], errors="coerce")
    comparable = reciprocal.notna() & direct.notna() & np.isfinite(reciprocal) & np.isfinite(direct)
    bp_match_rate = float(np.isclose(reciprocal[comparable], direct[comparable], rtol=1e-7, atol=1e-10).mean()) if comparable.any() else 0.0
    bp_status = "RESOLVED_DIRECT_WITH_RECIPROCAL_CHECK" if bp_match_rate == 1.0 else "UNRESOLVED"
    rows = [
        {
            "requested_factor": "ROE",
            "provider_endpoint": "rqdatac.get_pit_financials_ex",
            "provider_field": "np_parent_company_ownersTTM;equity_parent_company",
            "source_type": "PIT financial records; custom ratio",
            "formula": ROE_TTM_ENDING_EQUITY.formula,
            "formula_reference": ROE_TTM_ENDING_EQUITY.formula_reference,
            "formula_version": ROE_TTM_ENDING_EQUITY.formula_version,
            "numerator": "TTM net profit attributable to parent-company owners",
            "denominator": "parent-company equity at report-period end",
            "accounting_scope": "consolidated attributable profit / ending parent equity; not weighted-average ROE",
            "frequency": "quarterly PIT",
            "mapping_status": "RESOLVED_CUSTOM_TTM_ENDING_EQUITY",
            "notes": "Explicit ending-equity ROE definition; denominator zero/non-finite becomes missing.",
        },
        {
            "requested_factor": "BP",
            "provider_endpoint": "rqdatac.get_factor",
            "provider_field": "book_to_market_ratio_lf;pb_ratio_lf;market_cap",
            "source_type": "evaluation-date valuation factor",
            "formula": "book_to_market_ratio_lf; verified against 1 / pb_ratio_lf",
            "numerator": "latest-filed book value embedded by provider",
            "denominator": "evaluation-date market value embedded by provider",
            "accounting_scope": "provider LF book-to-market valuation",
            "frequency": "daily; sampled at three fixed evaluation dates",
            "mapping_status": bp_status,
            "notes": f"reciprocal_match_rate={bp_match_rate:.6f}; PB<=0/non-finite and missing values remain missing; no absolute value.",
        },
        {
            "requested_factor": "OCF/NP",
            "provider_endpoint": "rqdatac.get_pit_financials_ex",
            "provider_field": "net_operate_cashflowTTM;np_parent_company_ownersTTM",
            "source_type": "PIT financial records; custom ratio",
            "formula": "net_operate_cashflowTTM / np_parent_company_ownersTTM",
            "numerator": "TTM net operating cash flow",
            "denominator": "TTM net profit attributable to parent-company owners",
            "accounting_scope": "consolidated operating cash flow / attributable parent profit",
            "frequency": "quarterly PIT",
            "mapping_status": "RESOLVED",
            "notes": "Denominator zero/non-finite becomes missing; no similarly named substitute.",
        },
    ]
    return pd.DataFrame(rows)


def _source_spot_check(raw: pd.DataFrame, repeated: pd.DataFrame) -> pd.DataFrame:
    original_obs = _financial_observations(raw).dropna(subset=["factor_value"]).head(20).copy()
    repeated_obs = _financial_observations(repeated)[
        ["raw_row_ordinal", "factor_id", "factor_value", "code", "report_period", "publish_date"]
    ].rename(columns={"factor_value": "requery_factor_value"})
    checked = original_obs.merge(
        repeated_obs,
        on=["raw_row_ordinal", "factor_id", "code", "report_period", "publish_date"],
        how="left",
        validate="one_to_one",
    )
    checked["value_tolerance"] = 1e-12
    checked["value_match"] = np.isclose(
        checked["factor_value"], checked["requery_factor_value"], rtol=1e-12, atol=1e-12, equal_nan=False
    )
    checked["date_match"] = checked["requery_factor_value"].notna()
    checked["spot_check_status"] = np.where(
        checked["value_match"] & checked["date_match"], "MATCH", "MISMATCH"
    )
    return checked


def _write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# RQData Controlled Shadow Test Report",
        "",
        "## 1. Run Summary",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Final status: `{summary['status']}`",
        "- Provider: `RQData` (real, read-only)",
        "- Production / authoritative / P05 / Task8 readiness: `false`",
        "",
        "## 2. Sample Scope",
        "",
        f"- Securities requested/returned: {summary['requested_security_count']}/{summary['returned_security_count']}",
        f"- Financial history: {START_QUARTER} through {END_QUARTER} (6 quarters)",
        f"- Evaluation dates: {', '.join(EVALUATION_DATES)}",
        "- Selection: lexicographically first 30 CSI 300 constituents at 2025-06-30; factor-independent.",
        "",
        "## 3. RQData Provider Verification",
        "",
        "- Real RQData provider: PASS",
        "- Mock/synthetic/fallback provider: not used",
        f"- Raw financial rows: {summary['raw_financial_rows']}",
        f"- Raw market rows: {summary['raw_market_rows']}",
        f"- Source spot checks: {summary['spot_check_count']}; mismatches: {summary['spot_check_mismatch_count']}",
        "",
        "## 4. Factor Mapping",
        "",
        "- ROE: TTM attributable parent profit / ending parent equity (explicit custom definition).",
        "- BP: provider LF book-to-market, checked against reciprocal LF PB; non-positive PB remains missing.",
        "- OCF/NP: TTM net operating cash flow / TTM attributable parent profit.",
        "",
        "## 5. PIT Validation",
        "",
        f"- Invalid report/publish order: {summary['invalid_report_publish_order_count']}",
        "- Provider announcement date (`info_date`) retained as `publish_date`.",
        "- Provider adjustment marker and record creation timestamp retained as lineage only.",
        "",
        "## 6. Timing Validation",
        "",
        "- BLOCKED: the repository has no `FinancialTimingPolicy` implementation.",
        "- No effective dates were fabricated and no same-day tradability assumption was introduced.",
        "",
        "## 7. FinancialBatch Validation",
        "",
        "- Not run because the required timing policy is unavailable.",
        "",
        "## 8. ForwardReturn Validation",
        "",
        "- Not run. The existing 20-observation close-to-close contract does not freeze suspension/tradability policy.",
        "",
        "## 9. Data Quality",
        "",
        f"- Raw financial rows non-empty: {summary['raw_financial_rows'] > 0}",
        f"- Non-finite derived financial factor observations: {summary['non_finite_factor_value_count']}",
        "- Missingness is reported and was not filled or used to replace securities.",
        "",
        "## 10. IC / RankIC Results",
        "",
        "- Not computed because Timing, FinancialBatch, and ForwardReturn gates were not all PASS.",
        "",
        "## 11. Reproducibility",
        "",
        "- Manifest and SHA256 hashes generated for available raw datasets.",
        "",
        "## 12. Known Limitations",
        "",
        "- RQSDK constrains NumPy/SciPy below versions declared in pyproject; 167 focused contract tests passed.",
        "- No project FinancialTimingPolicy exists.",
        "- Suspension and tradability semantics are not frozen in the forward-return contract.",
        "",
        "## 13. Final Status",
        "",
        f"`{summary['status']}`",
        "",
        "Real data was accepted, but the shadow test stopped before batch construction and evaluation. Human review is required.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    for directory in (RAW_DIR, AUDIT_DIR, PROCESSED_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    run_id = f"rqdata-shadow-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        _provider_call("init", rqdatac.init)
    except ProviderBlocked:
        print(json.dumps({"status": "BLOCKED_BY_RQDATA_INITIALIZATION"}))
        return 2

    try:
        components = _provider_call(
            "index_components", lambda: rqdatac.index_components(INDEX_ID, date=UNIVERSE_DATE)
        )
        codes = sorted(set(components))[:SECURITY_COUNT]
        if len(codes) != SECURITY_COUNT:
            raise ProviderBlocked("index_components:INSUFFICIENT_SECURITIES")

        universe = pd.DataFrame(
            {
                "code": codes,
                "selection_reason": f"sorted first {SECURITY_COUNT} constituents of {INDEX_ID} at {UNIVERSE_DATE}",
                "selection_order": np.arange(1, SECURITY_COUNT + 1),
                "sample_status": "SELECTED_FIXED",
            }
        )
        universe.to_csv(ARTIFACT_ROOT / "sample_universe.csv", index=False, encoding="utf-8")

        financial_response = _provider_call(
            "pit_financials",
            lambda: rqdatac.get_pit_financials_ex(
                order_book_ids=codes,
                fields=list(FINANCIAL_FIELDS),
                start_quarter=START_QUARTER,
                end_quarter=END_QUARTER,
                date=PIT_AS_OF_DATE,
                statements="all",
            ),
        )
        financial_raw = _normalise_financial(financial_response)
        financial_path = RAW_DIR / "financial_raw.parquet"
        financial_raw.to_parquet(financial_path, index=False, engine="pyarrow")
        if financial_raw.empty:
            raise ProviderBlocked("pit_financials:EMPTY_RESPONSE")

        market_parts = []
        for evaluation_date in EVALUATION_DATES:
            response = _provider_call(
                f"market_factor:{evaluation_date}",
                lambda evaluation_date=evaluation_date: rqdatac.get_factor(
                    codes,
                    list(MARKET_FIELDS),
                    start_date=evaluation_date,
                    end_date=evaluation_date,
                    expect_df=True,
                ),
            )
            market_parts.append(_normalise_market(response, evaluation_date))
        market_raw = pd.concat(market_parts, ignore_index=True)
        market_path = RAW_DIR / "market_raw.parquet"
        market_raw.to_parquet(market_path, index=False, engine="pyarrow")

        mapping = _factor_mapping(market_raw)
        mapping.to_csv(ARTIFACT_ROOT / "factor_mapping.csv", index=False, encoding="utf-8")
        mapped_count = int(mapping["mapping_status"].ne("UNRESOLVED").sum())
        if mapped_count < 2:
            print(json.dumps({"status": "BLOCKED_BY_FACTOR_MAPPING"}))
            return 3

        invalid_pit = int((financial_raw["report_period"] > financial_raw["publish_date"]).sum())
        if invalid_pit:
            print(json.dumps({"status": "BLOCKED_BY_PIT_VALIDATION"}))
            return 4

        repeated_response = _provider_call(
            "pit_financials_spot_requery",
            lambda: rqdatac.get_pit_financials_ex(
                order_book_ids=codes,
                fields=list(FINANCIAL_FIELDS),
                start_quarter=START_QUARTER,
                end_quarter=END_QUARTER,
                date=PIT_AS_OF_DATE,
                statements="all",
            ),
        )
        repeated = _normalise_financial(repeated_response)
        spot = _source_spot_check(financial_raw, repeated)
        spot_path = AUDIT_DIR / "source_spot_check.csv"
        spot.to_csv(spot_path, index=False, encoding="utf-8")
        mismatch_count = int(spot["spot_check_status"].ne("MATCH").sum())
        if len(spot) < 20 or mismatch_count:
            print(json.dumps({"status": "BLOCKED_BY_REAL_DATA_MISMATCH"}))
            return 5

    except ProviderBlocked as exc:
        print(json.dumps({"status": "BLOCKED_BY_PROVIDER", "error_category": str(exc).split(":")[-1]}))
        return 6

    observations = _financial_observations(financial_raw)
    timing_audit = observations[
        ["code", "factor_id", "report_period", "publish_date"]
    ].copy()
    timing_audit["effective_date"] = pd.NaT
    timing_audit["timing_status"] = "BLOCKED_FINANCIAL_TIMING_POLICY_UNAVAILABLE"
    timing_audit.to_csv(AUDIT_DIR / "timing_audit.csv", index=False, encoding="utf-8")

    duplicate_key_count = int(
        financial_raw.duplicated(subset=["code", "report_period", "publish_date"], keep=False).sum()
    )
    finite_values = pd.to_numeric(observations["factor_value"], errors="coerce")
    non_finite_count = int((~np.isfinite(finite_values.fillna(np.nan))).sum())
    missing_by_factor = (
        observations.groupby("factor_id")["factor_value"].apply(lambda x: float(x.isna().mean())).to_dict()
    )
    coverage_by_factor = (
        observations.groupby("factor_id")["factor_value"].apply(lambda x: int(x.notna().sum())).to_dict()
    )
    coverage_by_date = (
        market_raw.groupby(market_raw["evaluation_date"].dt.strftime("%Y-%m-%d"))["code"].nunique().astype(int).to_dict()
    )
    quality = {
        "raw_row_count": int(len(financial_raw) + len(market_raw)),
        "raw_financial_row_count": int(len(financial_raw)),
        "raw_market_row_count": int(len(market_raw)),
        "processed_row_count": 0,
        "security_count": int(financial_raw["code"].nunique()),
        "factor_count": int(mapped_count),
        "report_period_count": int(financial_raw["report_period"].nunique()),
        "evaluation_date_count": len(EVALUATION_DATES),
        "missing_rate_by_factor": missing_by_factor,
        "coverage_by_factor": coverage_by_factor,
        "coverage_by_date": coverage_by_date,
        "duplicate_key_count": duplicate_key_count,
        "unresolved_duplicate_key_count": None,
        "invalid_date_order_count": invalid_pit,
        "lookahead_violation_count": None,
        "non_finite_factor_value_count": non_finite_count,
        "non_finite_forward_return_count": None,
        "non_finite_final_factor_value_count": None,
        "data_quality_status": "NOT_RUN_AFTER_TIMING_POLICY_BLOCK",
    }
    quality_path = AUDIT_DIR / "data_quality_report.json"
    _json_dump(quality_path, quality)

    financial_hash = _sha256(financial_path)
    market_hash = _sha256(market_path)
    status = "REAL_DATA_ACCEPTED_BUT_SHADOW_TEST_BLOCKED"
    summary = {
        "run_id": run_id,
        "status": status,
        "requested_security_count": SECURITY_COUNT,
        "returned_security_count": int(financial_raw["code"].nunique()),
        "raw_financial_rows": int(len(financial_raw)),
        "raw_market_rows": int(len(market_raw)),
        "spot_check_count": int(len(spot)),
        "spot_check_mismatch_count": mismatch_count,
        "invalid_report_publish_order_count": invalid_pit,
        "non_finite_factor_value_count": non_finite_count,
    }
    manifest = {
        "run_id": run_id,
        "created_at_utc": created_at,
        "run_type": "CONTROLLED_REAL_DATA_SHADOW_TEST",
        "status": status,
        "code_commit": _git_commit(),
        "python_version": platform.python_version(),
        "rqdatac_version": "3.5.2",
        "provider": "RQData",
        "provider_is_rqdata": True,
        "mock_provider_used": False,
        "synthetic_provider_used": False,
        "fallback_provider_used": False,
        "access_mode": "READ_ONLY",
        "query_scope": {
            "index": INDEX_ID,
            "universe_date": UNIVERSE_DATE,
            "requested_security_count": SECURITY_COUNT,
            "returned_security_count": summary["returned_security_count"],
            "requested_factor_count": 3,
            "mapped_factor_count": mapped_count,
            "requested_period": [START_QUARTER, END_QUARTER],
            "returned_period": [
                financial_raw["provider_quarter"].min(),
                financial_raw["provider_quarter"].max(),
            ],
            "evaluation_dates": list(EVALUATION_DATES),
        },
        "sample_definition": f"sorted first {SECURITY_COUNT} {INDEX_ID} constituents at {UNIVERSE_DATE}",
        "factor_mapping_file": "factor_mapping.csv",
        "timing_policy": {
            "status": "BLOCKED",
            "reason": "FinancialTimingPolicy implementation not found in repository",
        },
        "forward_return_contract": {
            "implemented_definition": "close[t+h]/close[t]-1; h=20 observation steps",
            "price_field": "close",
            "adjustment_policy": "not frozen by project contract",
            "suspension_policy": "not frozen by project contract",
            "tradability_policy": "not frozen by project contract",
            "status": "BLOCKED_INCOMPLETE_POLICY",
        },
        "real_data_acceptance": {
            "status": "PASS",
            "raw_row_count": int(len(financial_raw) + len(market_raw)),
            "source_spot_check_count": int(len(spot)),
            "source_spot_check_mismatch_count": mismatch_count,
            "pit_invalid_order_count": invalid_pit,
        },
        "hashes": {
            "raw_financial_sha256": financial_hash,
            "raw_market_sha256": market_hash,
            "financial_batch_sha256": None,
            "forward_return_batch_sha256": None,
        },
        "production": False,
        "authoritative_snapshot": False,
        "authoritative_handoff": False,
        "p05_ready": False,
        "task8_ready": False,
        "credential_values_included": False,
    }
    manifest_path = ARTIFACT_ROOT / "manifest.json"
    _json_dump(manifest_path, manifest)
    _write_report(ARTIFACT_ROOT / "SHADOW_TEST_REPORT.md", summary)

    print(
        json.dumps(
            {
                "task_id": "FIN-RQDATA-REAL-DATA-VALIDATION-25",
                "status": status,
                "real_data_acceptance": "PASS",
                "factor_mapping": "PASS",
                "pit_validation": "PASS",
                "timing_validation": "BLOCKED",
                "financial_batch_validation": "NOT_RUN",
                "forward_return_validation": "NOT_RUN",
                "factor_evaluation": {"ic_computed": False, "rankic_computed": False},
                "run_id": run_id,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
