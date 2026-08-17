"""Build an independently queried authoritative financial snapshot candidate."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rqdatac

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend.amr.financial_factor_registry import ROE_TTM_ENDING_EQUITY
from backend.amr.financial_timing import FinancialTimingPolicy, VersionedTradingCalendar

ROOT = PROJECT / "artifacts" / "authoritative_financial_snapshot"
RAW, PROCESSED = ROOT / "raw", ROOT / "processed"
LINEAGE, MASKS, AUDIT = ROOT / "lineage", ROOT / "masks", ROOT / "audit"
POLICIES = ROOT / "policies"
INDEX_ID, UNIVERSE_DATE, SECURITY_COUNT = "000300.XSHG", "2025-06-30", 30
EVALUATION_DATES = ("2025-06-30", "2025-09-30", "2025-12-31")
START_QUARTER, END_QUARTER, AS_OF_DATE = "2024q2", "2025q3", "2025-12-31"
FINANCIAL_FIELDS = (
    "np_parent_company_ownersTTM",
    "equity_parent_company",
    "net_operate_cashflowTTM",
)
MARKET_FIELDS = ("book_to_market_ratio_lf", "pb_ratio_lf", "market_cap")
FACTOR_VERSION = "AUTHORITATIVE_FINANCIAL_FACTORS_V1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_policy(name: str) -> dict[str, Any]:
    return json.loads((POLICIES / name).read_text(encoding="utf-8"))


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip()
    except Exception:
        return "UNKNOWN"


def quarter_end(value: str) -> str:
    return pd.Period(value.upper(), freq="Q-DEC").end_time.strftime("%Y-%m-%d")


def normalize_financial(response: pd.DataFrame) -> pd.DataFrame:
    frame = response.reset_index().rename(
        columns={
            "order_book_id": "code",
            "quarter": "provider_quarter",
            "info_date": "publish_date",
            "rice_create_tm": "provider_record_created_at",
        }
    )
    frame["code"] = frame["code"].astype(str)
    frame["report_period"] = frame["provider_quarter"].map(quarter_end)
    frame["publish_date"] = pd.to_datetime(frame["publish_date"], errors="raise").dt.strftime("%Y-%m-%d")
    if "provider_record_created_at" not in frame:
        frame["provider_record_created_at"] = None
    else:
        frame["provider_record_created_at"] = pd.to_datetime(
            frame["provider_record_created_at"], errors="coerce"
        ).dt.strftime("%Y-%m-%dT%H:%M:%S")
    frame = frame.sort_values(
        ["code", "report_period", "publish_date", "provider_record_created_at"], kind="stable"
    ).reset_index(drop=True)
    frame["revision_sequence"] = frame.groupby(["code", "report_period"]).cumcount() + 1
    frame["revision_count"] = frame.groupby(["code", "report_period"])["code"].transform("size")
    frame["revision_status"] = np.where(
        frame["revision_sequence"].eq(1), "ORIGINAL_OR_FIRST_PROVIDER_EVENT", "REVISION_OR_REDISCLOSURE"
    )
    frame["provider_event_type"] = np.where(
        pd.to_numeric(frame["if_adjusted"], errors="coerce").eq(1),
        "NON_CURRENT_COMPARATIVE_DISCLOSURE",
        "CURRENT_PERIOD_DISCLOSURE",
    )
    identifiers = []
    raw_hashes = []
    for row in frame.to_dict("records"):
        payload = {
            "provider": "RQData",
            "provider_endpoint": "get_pit_financials_ex",
            "code": row["code"],
            "report_period": row["report_period"],
            "publish_date": row["publish_date"],
            "provider_record_created_at": row.get("provider_record_created_at"),
            "if_adjusted": row.get("if_adjusted"),
            "values": {field: row.get(field) for field in FINANCIAL_FIELDS},
        }
        raw_hash = stable_hash(payload)
        raw_hashes.append(raw_hash)
        identifiers.append("isr-" + raw_hash[:24])
    frame["raw_source_hash"] = raw_hashes
    frame["internal_source_record_id"] = identifiers
    frame["source_record_reference"] = frame["internal_source_record_id"]
    frame["id_authority"] = "INTERNAL_LINEAGE_ONLY"
    frame["provider"] = "RQData"
    frame["provider_endpoint"] = "rqdatac.get_pit_financials_ex"
    return frame


def financial_source_long(frame: pd.DataFrame) -> pd.DataFrame:
    ids = [
        "provider", "provider_endpoint", "code", "provider_quarter", "report_period",
        "publish_date", "provider_record_created_at", "if_adjusted", "provider_event_type",
        "revision_status", "revision_sequence", "revision_count", "source_record_reference",
        "internal_source_record_id", "id_authority", "raw_source_hash",
    ]
    long = frame.melt(id_vars=ids, value_vars=list(FINANCIAL_FIELDS), var_name="source_field", value_name="source_value")
    long["source_value"] = pd.to_numeric(long["source_value"], errors="coerce")
    return long.sort_values(["code", "report_period", "publish_date", "source_field"], kind="stable")


def normalize_market(response: pd.DataFrame, evaluation_date: str) -> pd.DataFrame:
    frame = response.reset_index().rename(columns={"order_book_id": "code", "date": "provider_date"})
    frame["code"] = frame["code"].astype(str)
    frame["evaluation_date"] = evaluation_date
    if "provider_date" in frame:
        frame["provider_date"] = pd.to_datetime(frame["provider_date"]).dt.strftime("%Y-%m-%d")
    hashes, refs = [], []
    for row in frame.to_dict("records"):
        payload = {"provider": "RQData", "endpoint": "get_factor", **row}
        raw_hash = stable_hash(payload)
        hashes.append(raw_hash)
        refs.append("isr-" + raw_hash[:24])
    frame["raw_source_hash"] = hashes
    frame["source_record_reference"] = refs
    frame["id_authority"] = "INTERNAL_LINEAGE_ONLY"
    frame["provider"] = "RQData"
    frame["provider_endpoint"] = "rqdatac.get_factor"
    return frame


def build_calendar() -> tuple[VersionedTradingCalendar, Path]:
    dates = tuple(
        pd.Timestamp(item).strftime("%Y-%m-%d")
        for item in rqdatac.get_trading_dates("2024-01-01", "2026-03-31", market="cn")
    )
    identifier = f"RQDATA_CN_{dates[0]}_{dates[-1]}_{stable_hash(dates)[:12]}"
    calendar = VersionedTradingCalendar(
        dates, "RQData 3.5.2 get_trading_dates", "CN", identifier
    )
    path = RAW / "trading_calendar.csv"
    pd.DataFrame({"trading_date": dates}).to_csv(path, index=False, encoding="utf-8")
    return calendar, path


def instrument_table(codes: list[str]) -> pd.DataFrame:
    objects = rqdatac.instruments(codes, market="cn")
    if not isinstance(objects, list):
        objects = [objects]
    rows = []
    for item in objects:
        rows.append(
            {
                "code": str(getattr(item, "order_book_id")),
                "listed_date": str(getattr(item, "listed_date", "")),
                "de_listed_date": str(getattr(item, "de_listed_date", "")),
                "instrument_status": str(getattr(item, "status", "UNKNOWN")),
            }
        )
    return pd.DataFrame(rows)


def sample_mask(codes: list[str], instruments: pd.DataFrame, sample_policy: dict[str, Any]) -> pd.DataFrame:
    metadata = instruments.set_index("code").to_dict("index")
    rows = []
    for date in EVALUATION_DATES:
        formation = pd.Timestamp(date)
        for code in codes:
            item = metadata.get(code, {})
            listed = pd.to_datetime(item.get("listed_date"), errors="coerce")
            delisted = pd.to_datetime(item.get("de_listed_date"), errors="coerce")
            if pd.isna(listed) or listed > formation:
                status, reason, detail = "EXCLUDED", "EXCLUDED_NOT_LISTED", "not listed by formation date"
            elif pd.notna(delisted) and delisted < formation:
                status, reason, detail = "EXCLUDED", "EXCLUDED_DELISTED_BEFORE_FORMATION", "delisted before formation"
            else:
                status, reason, detail = "INCLUDED", "INCLUDED_BASE_UNIVERSE", "selected by frozen base-universe rule"
            reference = "smr-" + stable_hash(
                [sample_policy["sample_policy_id"], code, date, status, reason]
            )[:24]
            rows.append(
                {
                    "sample_mask_reference": reference,
                    "code": code,
                    "evaluation_date": date,
                    "sample_status": status,
                    "inclusion_reason": reason if status == "INCLUDED" else "",
                    "exclusion_reason": reason if status == "EXCLUDED" else "",
                    "reason_explanation": detail,
                    "universe_source": f"RQData {INDEX_ID} components at {UNIVERSE_DATE}",
                    "universe_version": sample_policy["sample_policy_version"],
                    "sample_policy_id": sample_policy["sample_policy_id"],
                }
            )
    return pd.DataFrame(rows)


def winsorize(values: pd.Series, threshold: float = 3.0) -> tuple[pd.Series, str]:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return numeric, "MAD_NOT_APPLIED_NO_VALID_VALUES"
    center = float(valid.median())
    mad = float((valid - center).abs().median())
    if not np.isfinite(mad) or mad <= 0:
        return numeric, "MAD_NOT_APPLIED_ZERO_OR_NONFINITE_MAD"
    scale = 1.4826 * mad
    return numeric.clip(center - threshold * scale, center + threshold * scale), "MAD_3_APPLIED"


def dependency_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"factor_id": ROE_TTM_ENDING_EQUITY.machine_factor_id, "semantic_name": ROE_TTM_ENDING_EQUITY.canonical_semantic_name, "formula_reference": ROE_TTM_ENDING_EQUITY.formula_reference, "formula_version": ROE_TTM_ENDING_EQUITY.formula_version, "formula": ROE_TTM_ENDING_EQUITY.formula, "numerator_source": ROE_TTM_ENDING_EQUITY.numerator_source, "denominator_source": ROE_TTM_ENDING_EQUITY.denominator_source, "accounting_scope": ROE_TTM_ENDING_EQUITY.accounting_scope, "period_semantics": ROE_TTM_ENDING_EQUITY.period_semantics},
            {"factor_id": "BP", "formula_reference": "FORMULA_BP_LF_V1", "formula": "book_to_market_ratio_lf; validated against 1/pb_ratio_lf where PB>0", "numerator_source": "provider latest-filed book value semantic", "denominator_source": "evaluation-date market value semantic", "accounting_scope": "provider LF valuation", "period_semantics": "evaluation-date market reference; no report_period"},
            {"factor_id": "OCF_NP", "formula_reference": "FORMULA_OCF_NP_TTM_PARENT_V1", "formula": "net_operate_cashflowTTM / np_parent_company_ownersTTM", "numerator_source": "net_operate_cashflowTTM", "denominator_source": "np_parent_company_ownersTTM", "accounting_scope": "consolidated operating cash flow / attributable parent profit", "period_semantics": "TTM numerator and denominator"},
        ]
    )


def build_financial_factor_rows(
    raw: pd.DataFrame,
    policy: FinancialTimingPolicy,
    mask: pd.DataFrame,
    preprocessing: dict[str, Any],
    stale: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    applied = policy.apply(raw)
    audit = applied.audit_frame.copy()
    valid = applied.valid_frame.copy()
    formulas = {
        ROE_TTM_ENDING_EQUITY.machine_factor_id: (ROE_TTM_ENDING_EQUITY.numerator_source, ROE_TTM_ENDING_EQUITY.denominator_source, ROE_TTM_ENDING_EQUITY.formula_reference),
        "OCF_NP": ("net_operate_cashflowTTM", "np_parent_company_ownersTTM", "FORMULA_OCF_NP_TTM_PARENT_V1"),
    }
    factor_parts, revision_audit = [], []
    included = mask[mask["sample_status"] == "INCLUDED"]
    for factor_id, (num_field, den_field, formula_ref) in formulas.items():
        for evaluation_date in EVALUATION_DATES:
            eligible = valid[pd.to_datetime(valid["effective_date"]) <= pd.Timestamp(evaluation_date)].copy()
            eligible = eligible.sort_values(["code", "report_period", "effective_date", "publish_date"], kind="stable")
            eligible = eligible.drop_duplicates(["code", "report_period"], keep="last")
            eligible = eligible.sort_values(["code", "report_period", "effective_date"], kind="stable").drop_duplicates("code", keep="last")
            eligible["evaluation_date"] = evaluation_date
            eligible["source_age_days"] = (pd.Timestamp(evaluation_date) - pd.to_datetime(eligible["report_period"])).dt.days
            eligible["stale_status"] = np.select(
                [eligible["source_age_days"].isna(), eligible["source_age_days"] > stale["stale_threshold_days"]],
                ["UNKNOWN", "STALE"], default="FRESH"
            )
            numerator = pd.to_numeric(eligible[num_field], errors="coerce")
            denominator = pd.to_numeric(eligible[den_field], errors="coerce")
            eligible["raw_factor_value"] = (numerator / denominator.where(denominator != 0)).where(lambda x: np.isfinite(x))
            eligible = included[included["evaluation_date"] == evaluation_date][["code", "sample_mask_reference"]].merge(eligible, on="code", how="left", validate="one_to_one")
            eligible["factor_id"] = factor_id
            eligible["factor_version"] = FACTOR_VERSION
            eligible["formula_reference"] = formula_ref
            eligible["source_field_refs"] = json.dumps([num_field, den_field], separators=(",", ":"))
            eligible["revision_reference"] = eligible["source_record_reference"]
            eligible["preprocessing_policy_reference"] = preprocessing["preprocessing_policy_id"]
            eligible["stale_policy_reference"] = stale["stale_policy_id"]
            eligible["factor_value"], eligible["transformation_status"] = winsorize(eligible["raw_factor_value"])
            eligible["factor_eligible"] = eligible["factor_value"].notna() & eligible["stale_status"].eq("FRESH")
            factor_parts.append(eligible)
        revision_source = valid[
            ["code", "report_period", "publish_date", "effective_date", "revision_sequence", "revision_count", "revision_status", "provider_event_type", "source_record_reference", "raw_source_hash"]
        ].copy()
        revisions = revision_source
        revisions["factor_id"] = factor_id
        revision_audit.append(revisions)
    return pd.concat(factor_parts, ignore_index=True), audit, pd.concat(revision_audit, ignore_index=True)


def build_bp_rows(
    market: pd.DataFrame,
    mask: pd.DataFrame,
    preprocessing: dict[str, Any],
    stale: dict[str, Any],
) -> pd.DataFrame:
    included = mask[mask["sample_status"] == "INCLUDED"]
    rows = []
    for date in EVALUATION_DATES:
        selected = included[included["evaluation_date"] == date][["code", "sample_mask_reference"]].merge(
            market[market["evaluation_date"] == date], on="code", how="left", validate="one_to_one"
        )
        selected["factor_id"] = "BP"
        selected["factor_version"] = FACTOR_VERSION
        selected["report_period"] = None
        selected["publish_date"] = None
        selected["effective_date"] = None
        selected["raw_factor_value"] = pd.to_numeric(selected["book_to_market_ratio_lf"], errors="coerce")
        selected["factor_value"] = selected["raw_factor_value"]
        selected["transformation_status"] = "NOT_APPLIED_BP_EVALUATION_DATE_FACTOR"
        selected["source_age_days"] = None
        selected["stale_status"] = "NOT_APPLICABLE"
        selected["formula_reference"] = "FORMULA_BP_LF_V1"
        selected["source_field_refs"] = json.dumps(["book_to_market_ratio_lf", "pb_ratio_lf", "market_cap"], separators=(",", ":"))
        selected["revision_reference"] = None
        selected["preprocessing_policy_reference"] = preprocessing["preprocessing_policy_id"]
        selected["stale_policy_reference"] = stale["stale_policy_id"] + ":NOT_APPLICABLE_TO_BP"
        selected["factor_eligible"] = selected["factor_value"].notna() & np.isfinite(selected["factor_value"])
        rows.append(selected)
    return pd.concat(rows, ignore_index=True)


def add_lineage_hashes(rows: pd.DataFrame, run_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    value_hashes, row_ids, upstream_hashes = [], [], []
    for row in rows.to_dict("records"):
        source_refs = [row.get("source_record_reference")]
        source_refs = [item for item in source_refs if item not in (None, "", np.nan)]
        normalized_value = None if pd.isna(row.get("factor_value")) else format(float(row["factor_value"]), ".17g")
        payload = {
            "factor_id": row["factor_id"], "factor_version": row["factor_version"],
            "code": row["code"], "evaluation_date": row["evaluation_date"],
            "report_period": row.get("report_period"), "publish_date": row.get("publish_date"),
            "effective_date": row.get("effective_date"), "normalized_factor_value": normalized_value,
            "source_references": source_refs, "source_field_refs": row["source_field_refs"],
            "sample_mask_reference": row["sample_mask_reference"],
            "preprocessing_policy_reference": row["preprocessing_policy_reference"],
            "stale_policy_reference": row["stale_policy_reference"],
            "formula_reference": row["formula_reference"],
        }
        value_hash = stable_hash(payload)
        value_hashes.append(value_hash)
        row_ids.append("afr-" + stable_hash([run_id, value_hash])[:24])
        upstream_hashes.append(row.get("raw_source_hash"))
    rows = rows.copy()
    rows["value_hash"] = value_hashes
    rows["factor_value_hash"] = value_hashes
    rows["authoritative_row_id"] = row_ids
    rows["authoritative_run_id"] = run_id
    rows["upstream_raw_hash"] = upstream_hashes
    lineage_columns = [
        "authoritative_row_id", "authoritative_run_id", "code", "factor_id", "factor_version",
        "evaluation_date", "report_period", "publish_date", "effective_date",
        "source_record_reference", "source_field_refs", "revision_reference",
        "sample_mask_reference", "preprocessing_policy_reference", "stale_policy_reference",
        "formula_reference", "upstream_raw_hash", "factor_value_hash",
    ]
    return rows, rows[lineage_columns].copy()


def main() -> int:
    for directory in (RAW, PROCESSED, LINEAGE, MASKS, AUDIT, POLICIES):
        directory.mkdir(parents=True, exist_ok=True)
    if importlib.metadata.version("rqdatac") != "3.5.2":
        raise RuntimeError("rqdatac version mismatch")
    stale = load_policy("stale_policy.json")
    preprocessing = load_policy("preprocessing_policy.json")
    sample_policy = load_policy("sample_policy.json")
    rqdatac.init()

    components = sorted(set(rqdatac.index_components(INDEX_ID, date=UNIVERSE_DATE)))
    codes = components[:SECURITY_COUNT]
    if len(codes) != SECURITY_COUNT:
        raise RuntimeError("insufficient universe members")
    calendar, calendar_path = build_calendar()
    timing_policy = FinancialTimingPolicy(calendar)
    instruments = instrument_table(codes)
    instruments.to_parquet(RAW / "instrument_reference_raw.parquet", index=False)
    mask = sample_mask(codes, instruments, sample_policy)
    mask_path = MASKS / "sample_mask.parquet"
    mask.to_parquet(mask_path, index=False)

    response = rqdatac.get_pit_financials_ex(
        order_book_ids=codes, fields=list(FINANCIAL_FIELDS), start_quarter=START_QUARTER,
        end_quarter=END_QUARTER, date=AS_OF_DATE, statements="all", market="cn"
    )
    financial_wide = normalize_financial(response)
    if financial_wide.empty:
        raise RuntimeError("empty financial source")
    financial_long = financial_source_long(financial_wide)
    financial_path = RAW / "financial_source_raw.parquet"
    financial_long.to_parquet(financial_path, index=False)

    market_parts = []
    for date in EVALUATION_DATES:
        market_parts.append(
            normalize_market(
                rqdatac.get_factor(codes, list(MARKET_FIELDS), start_date=date, end_date=date, expect_df=True, market="cn"),
                date,
            )
        )
    market = pd.concat(market_parts, ignore_index=True)
    market_path = RAW / "market_reference_raw.parquet"
    market.to_parquet(market_path, index=False)

    run_seed = stable_hash({"codes": codes, "dates": EVALUATION_DATES, "financial_hash": file_hash(financial_path), "market_hash": file_hash(market_path), "policies": [stale, preprocessing, sample_policy]})
    run_id = f"rqdata-authoritative-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{run_seed[:10]}"
    financial_rows, timing_audit, revision_history = build_financial_factor_rows(
        financial_wide, timing_policy, mask, preprocessing, stale
    )
    bp_rows = build_bp_rows(market, mask, preprocessing, stale)
    combined = pd.concat([financial_rows, bp_rows], ignore_index=True, sort=False)
    combined, lineage = add_lineage_hashes(combined, run_id)
    authoritative = combined[combined["factor_eligible"]].copy()
    processed_path = PROCESSED / "authoritative_factor_rows.parquet"
    lineage_path = LINEAGE / "row_lineage.parquet"
    dependency_path = LINEAGE / "factor_dependency_lineage.parquet"
    authoritative.to_parquet(processed_path, index=False)
    lineage[lineage["authoritative_row_id"].isin(authoritative["authoritative_row_id"])].to_parquet(lineage_path, index=False)
    dependency_rows().to_parquet(dependency_path, index=False)
    timing_audit.to_csv(AUDIT / "timing_audit.csv", index=False, encoding="utf-8")
    revision_history.to_csv(AUDIT / "revision_history.csv", index=False, encoding="utf-8")

    manifest = {
        "run_type": "AUTHORITATIVE_UPSTREAM_SNAPSHOT_CANDIDATE",
        "provider": "RQData", "provider_version": "rqdatac 3.5.2", "rqdatac_version": "3.5.2",
        "run_id": run_id, "authoritative_run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "code_commit": git_commit(),
        "python_version": platform.python_version(),
        "factor_scope": ["ROE", "BP", "OCF_NP"],
        "security_scope": {"index": INDEX_ID, "universe_date": UNIVERSE_DATE, "selection": "sorted first 30", "count": len(codes)},
        "date_scope": {"quarters": [START_QUARTER, END_QUARTER], "evaluation_dates": list(EVALUATION_DATES), "pit_as_of_date": AS_OF_DATE},
        "row_count": len(authoritative), "security_count": int(authoritative["code"].nunique()), "factor_count": int(authoritative["factor_id"].nunique()),
        "calendar_snapshot_id": calendar.calendar_version_or_snapshot_id, "calendar_hash": calendar.calendar_hash,
        "sample_policy_id": sample_policy["sample_policy_id"],
        "preprocessing_policy_id": preprocessing["preprocessing_policy_id"],
        "stale_policy_id": stale["stale_policy_id"],
        "source_capabilities": "source_capability_matrix.csv",
        "financial_source_dataset_sha256": file_hash(financial_path),
        "market_reference_dataset_sha256": file_hash(market_path),
        "sample_mask_sha256": file_hash(mask_path),
        "lineage_dataset_sha256": file_hash(lineage_path),
        "authoritative_factor_rows_sha256": file_hash(processed_path),
        "factor_dependency_lineage_sha256": file_hash(dependency_path),
        "calendar_file_sha256": file_hash(calendar_path),
        "authoritative_validation_status": "PENDING_INDEPENDENT_VALIDATION",
        "shadow_test_reused_as_authority": False,
        "credential_values_included": False,
        "production_ready": False, "p05_ready": False, "task8_ready": False,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "AUTHORITATIVE_CANDIDATE_GENERATED", "run_id": run_id, "row_count": len(authoritative)}, ensure_ascii=False))
    return 0


def resume_from_authoritative_raw() -> int:
    """Resume local candidate assembly after a successful independent pull."""
    for directory in (RAW, PROCESSED, LINEAGE, MASKS, AUDIT, POLICIES):
        directory.mkdir(parents=True, exist_ok=True)
    stale = load_policy("stale_policy.json")
    preprocessing = load_policy("preprocessing_policy.json")
    sample_policy = load_policy("sample_policy.json")
    calendar_dates = tuple(pd.read_csv(RAW / "trading_calendar.csv")["trading_date"].astype(str))
    calendar = VersionedTradingCalendar(
        calendar_dates,
        "RQData 3.5.2 get_trading_dates",
        "CN",
        f"RQDATA_CN_{calendar_dates[0]}_{calendar_dates[-1]}_{stable_hash(calendar_dates)[:12]}",
    )
    timing_policy = FinancialTimingPolicy(calendar)
    financial_long = pd.read_parquet(RAW / "financial_source_raw.parquet")
    id_columns = [
        "provider", "provider_endpoint", "code", "provider_quarter", "report_period",
        "publish_date", "provider_record_created_at", "if_adjusted", "provider_event_type",
        "revision_status", "revision_sequence", "revision_count", "source_record_reference",
        "internal_source_record_id", "id_authority", "raw_source_hash",
    ]
    financial_wide = financial_long.pivot(index=id_columns, columns="source_field", values="source_value").reset_index()
    financial_wide.columns.name = None
    market = pd.read_parquet(RAW / "market_reference_raw.parquet")
    mask = pd.read_parquet(MASKS / "sample_mask.parquet")
    financial_path = RAW / "financial_source_raw.parquet"
    market_path = RAW / "market_reference_raw.parquet"
    run_seed = stable_hash({"codes": sorted(mask["code"].unique()), "dates": EVALUATION_DATES, "financial_hash": file_hash(financial_path), "market_hash": file_hash(market_path), "policies": [stale, preprocessing, sample_policy]})
    run_id = f"rqdata-authoritative-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{run_seed[:10]}"
    financial_rows, timing_audit, revision_history = build_financial_factor_rows(financial_wide, timing_policy, mask, preprocessing, stale)
    bp_rows = build_bp_rows(market, mask, preprocessing, stale)
    combined, lineage = add_lineage_hashes(pd.concat([financial_rows, bp_rows], ignore_index=True, sort=False), run_id)
    authoritative = combined[combined["factor_eligible"]].copy()
    processed_path = PROCESSED / "authoritative_factor_rows.parquet"
    lineage_path = LINEAGE / "row_lineage.parquet"
    dependency_path = LINEAGE / "factor_dependency_lineage.parquet"
    authoritative.to_parquet(processed_path, index=False)
    lineage[lineage["authoritative_row_id"].isin(authoritative["authoritative_row_id"])].to_parquet(lineage_path, index=False)
    dependency_rows().to_parquet(dependency_path, index=False)
    timing_audit.to_csv(AUDIT / "timing_audit.csv", index=False, encoding="utf-8")
    revision_history.to_csv(AUDIT / "revision_history.csv", index=False, encoding="utf-8")
    manifest = {
        "run_type": "AUTHORITATIVE_UPSTREAM_SNAPSHOT_CANDIDATE", "provider": "RQData",
        "provider_version": "rqdatac 3.5.2", "rqdatac_version": "3.5.2", "run_id": run_id,
        "authoritative_run_id": run_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": git_commit(), "python_version": platform.python_version(),
        "factor_scope": ["ROE", "BP", "OCF_NP"],
        "security_scope": {"index": INDEX_ID, "universe_date": UNIVERSE_DATE, "selection": "sorted first 30", "count": int(mask["code"].nunique())},
        "date_scope": {"quarters": [START_QUARTER, END_QUARTER], "evaluation_dates": list(EVALUATION_DATES), "pit_as_of_date": AS_OF_DATE},
        "row_count": len(authoritative), "security_count": int(authoritative["code"].nunique()), "factor_count": int(authoritative["factor_id"].nunique()),
        "calendar_snapshot_id": calendar.calendar_version_or_snapshot_id, "calendar_hash": calendar.calendar_hash,
        "sample_policy_id": sample_policy["sample_policy_id"], "preprocessing_policy_id": preprocessing["preprocessing_policy_id"], "stale_policy_id": stale["stale_policy_id"],
        "source_capabilities": "source_capability_matrix.csv",
        "financial_source_dataset_sha256": file_hash(financial_path), "market_reference_dataset_sha256": file_hash(market_path),
        "sample_mask_sha256": file_hash(MASKS / "sample_mask.parquet"), "lineage_dataset_sha256": file_hash(lineage_path),
        "authoritative_factor_rows_sha256": file_hash(processed_path), "factor_dependency_lineage_sha256": file_hash(dependency_path),
        "calendar_file_sha256": file_hash(RAW / "trading_calendar.csv"), "authoritative_validation_status": "PENDING_INDEPENDENT_VALIDATION",
        "shadow_test_reused_as_authority": False, "credential_values_included": False,
        "production_ready": False, "p05_ready": False, "task8_ready": False,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "AUTHORITATIVE_CANDIDATE_GENERATED_FROM_INDEPENDENT_RAW", "run_id": run_id, "row_count": len(authoritative)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if "--resume-from-authoritative-raw" in sys.argv:
        raise SystemExit(resume_from_authoritative_raw())
    raise SystemExit(main())
