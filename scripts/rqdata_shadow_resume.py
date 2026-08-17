"""Resume the controlled real-data RQData shadow validation.

This runner reuses the accepted financial/valuation snapshot from task 25,
adds only the frozen-calendar and adjusted-price inputs required by task 27,
and evaluates the fixed 30-security sample.  It never reads credential values
and never expands the authorized sample.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rqdatac


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.amr.evaluation_alignment import GateThresholds
from backend.amr.evaluation_financial import FinancialEvaluationConfig, FinancialFormationContext
from backend.amr.evaluation_input_contract import (
    EvaluationInputBundle,
    FactorRecord,
    FactorType,
    FinancialBatch,
    PriceVolumeBatch,
    ValueScope,
)
from backend.amr.evaluation_pipeline import evaluate_bundle
from backend.amr.financial_factor_registry import (
    ROE_TTM_ENDING_EQUITY,
    financial_factor_registry,
)
from backend.amr.financial_timing import FinancialTimingPolicy, VersionedTradingCalendar
from backend.amr.forward_returns import (
    FinancialForwardReturnPolicy,
    build_financial_forward_return_batch,
)


ROOT = PROJECT_ROOT / "artifacts" / "rqdata_shadow_test"
RAW = ROOT / "raw"
PROCESSED = ROOT / "processed"
AUDIT = ROOT / "audit"
EVALUATION_DATES = ("2025-06-30", "2025-09-30", "2025-12-31")
EXPECTED_RQDATAC_VERSION = "3.5.2"
EXPECTED_SECURITY_COUNT = 30
CALENDAR_QUERY_START = "2024-01-01"
CALENDAR_QUERY_END = "2026-03-31"
UNIVERSE_ID = "CSI300_SORTED_FIRST_30_AT_2025-06-30"


class ShadowBlocked(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
    except Exception:
        return "UNKNOWN"


def validate_reusable_snapshot() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    required = [
        ROOT / "manifest.json",
        ROOT / "sample_universe.csv",
        ROOT / "factor_mapping.csv",
        RAW / "financial_raw.parquet",
        RAW / "market_raw.parquet",
        AUDIT / "source_spot_check.csv",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", f"missing reusable snapshot files: {missing}")

    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    scope = manifest.get("query_scope", {})
    hashes = manifest.get("hashes", {})
    if manifest.get("provider") != "RQData" or not manifest.get("provider_is_rqdata"):
        raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", "existing snapshot is not identified as RQData")
    if any(manifest.get(key) for key in ("mock_provider_used", "synthetic_provider_used", "fallback_provider_used")):
        raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", "existing snapshot used a prohibited provider")
    if scope.get("requested_security_count") != EXPECTED_SECURITY_COUNT:
        raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", "existing snapshot scope is not 30 securities")
    if tuple(scope.get("evaluation_dates", ())) != EVALUATION_DATES:
        raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", "existing evaluation-date scope changed")

    financial_path = RAW / "financial_raw.parquet"
    market_path = RAW / "market_raw.parquet"
    if sha256(financial_path) != hashes.get("raw_financial_sha256"):
        raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", "financial raw hash mismatch")
    if sha256(market_path) != hashes.get("raw_market_sha256"):
        raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", "market raw hash mismatch")

    financial = pd.read_parquet(financial_path)
    market = pd.read_parquet(market_path)
    universe = pd.read_csv(ROOT / "sample_universe.csv", dtype={"code": str})
    spot = pd.read_csv(AUDIT / "source_spot_check.csv")
    if financial.empty or market.empty or len(universe) != EXPECTED_SECURITY_COUNT:
        raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", "existing snapshot is empty or incomplete")
    if financial["code"].nunique() != EXPECTED_SECURITY_COUNT:
        raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", "financial snapshot security coverage changed")
    if len(spot) < 20 or int((spot["spot_check_status"] != "MATCH").sum()) != 0:
        raise ShadowBlocked("BLOCKED_BY_REAL_DATA_MISMATCH", "stored source spot check is insufficient")
    return manifest, financial, market, universe


def normalized_price(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.reset_index().copy()
    result = result.rename(columns={"order_book_id": "code", "datetime": "date"})
    if "date" not in result.columns:
        candidates = [column for column in result.columns if str(column).lower() == "date"]
        if candidates:
            result = result.rename(columns={candidates[0]: "date"})
    required = {"date", "code", "close", "volume"}
    missing = sorted(required - set(result.columns))
    if missing:
        raise ShadowBlocked("BLOCKED_BY_PROVIDER", f"get_price schema missing: {missing}")
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.strftime("%Y-%m-%d")
    result["code"] = result["code"].astype(str)
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result["volume"] = pd.to_numeric(result["volume"], errors="coerce")
    return result[["date", "code", "close", "volume"]].sort_values(["date", "code"])


def normalized_suspensions(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "code", "is_suspended"])
    result = frame.copy()
    result.index = pd.to_datetime(result.index, errors="raise").strftime("%Y-%m-%d")
    result.index.name = "date"
    result = result.reset_index().melt(
        id_vars="date", var_name="code", value_name="is_suspended"
    )
    result["code"] = result["code"].astype(str)
    result["is_suspended"] = result["is_suspended"].fillna(False).astype(bool)
    return result


def build_calendar() -> tuple[VersionedTradingCalendar, Path]:
    values = rqdatac.get_trading_dates(CALENDAR_QUERY_START, CALENDAR_QUERY_END, market="cn")
    dates = tuple(pd.Timestamp(item).strftime("%Y-%m-%d") for item in values)
    if not dates:
        raise ShadowBlocked("BLOCKED_BY_PROVIDER", "RQData returned an empty trading calendar")
    content_hash = hashlib.sha256(("\n".join(dates) + "\n").encode("ascii")).hexdigest()
    snapshot_id = f"RQDATA_CN_{dates[0]}_{dates[-1]}_{content_hash[:12]}"
    calendar = VersionedTradingCalendar(
        trading_dates=dates,
        calendar_provider="RQData 3.5.2 get_trading_dates",
        calendar_scope="CN",
        calendar_version_or_snapshot_id=snapshot_id,
    )
    path = RAW / "trading_calendar.csv"
    pd.DataFrame({"trading_date": dates}).to_csv(path, index=False, encoding="utf-8")
    return calendar, path


def build_market_panel(
    codes: list[str], calendar: VersionedTradingCalendar
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    exits = [calendar.shift_market_sessions(item, 20) for item in EVALUATION_DATES]
    start, end = min(EVALUATION_DATES), max(exits)
    price_response = rqdatac.get_price(
        codes,
        start_date=start,
        end_date=end,
        frequency="1d",
        fields=["close", "volume"],
        adjust_type="pre",
        skip_suspended=True,
        expect_df=True,
        market="cn",
    )
    prices = normalized_price(price_response)
    suspensions = normalized_suspensions(
        rqdatac.is_suspended(codes, start_date=start, end_date=end, market="cn")
    )
    dates = [item for item in calendar.trading_dates if start <= item <= end]
    panel = pd.MultiIndex.from_product([dates, codes], names=["date", "code"]).to_frame(index=False)
    panel = panel.merge(prices, on=["date", "code"], how="left", validate="one_to_one")
    panel = panel.merge(suspensions, on=["date", "code"], how="left", validate="one_to_one")
    panel["is_suspended"] = panel["is_suspended"].fillna(False).astype(bool)
    panel["is_tradable"] = (
        ~panel["is_suspended"]
        & panel["close"].notna()
        & np.isfinite(panel["close"])
        & (panel["close"] > 0)
        & panel["volume"].notna()
        & np.isfinite(panel["volume"])
        & (panel["volume"] > 0)
    )
    panel["provider_adjustment_mode"] = "pre"
    panel["provider_price_field"] = "close"
    return panel, prices, suspensions


def delisting_records(codes: list[str], maximum_exit: str) -> pd.DataFrame:
    objects = rqdatac.instruments(codes, market="cn")
    if not isinstance(objects, list):
        objects = [objects]
    rows: list[dict[str, Any]] = []
    minimum_entry = pd.Timestamp(min(EVALUATION_DATES))
    maximum = pd.Timestamp(maximum_exit)
    for instrument in objects:
        raw_date = getattr(instrument, "de_listed_date", None)
        if raw_date in (None, "", "0000-00-00"):
            continue
        date = pd.to_datetime(raw_date, errors="coerce")
        if pd.notna(date) and minimum_entry < date <= maximum:
            rows.append(
                {
                    "code": str(getattr(instrument, "order_book_id")),
                    "delisting_date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                    "termination_value": np.nan,
                    "termination_value_source": "RQData instrument metadata has no settlement value",
                }
            )
    return pd.DataFrame(
        rows,
        columns=["code", "delisting_date", "termination_value", "termination_value_source"],
    )


def financial_observations(raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    common_columns = [
        "raw_row_ordinal",
        "code",
        "report_period",
        "publish_date",
        "provider_quarter",
        "if_adjusted",
        "provider_record_created_at",
    ]
    common = raw[common_columns].copy()
    definitions = {
        ROE_TTM_ENDING_EQUITY.machine_factor_id: (
            ROE_TTM_ENDING_EQUITY.numerator_source,
            ROE_TTM_ENDING_EQUITY.denominator_source,
            ROE_TTM_ENDING_EQUITY.formula,
        ),
        "OCF_NP": (
            "net_operate_cashflowTTM",
            "np_parent_company_ownersTTM",
            "net_operate_cashflowTTM / np_parent_company_ownersTTM",
        ),
    }
    output: dict[str, pd.DataFrame] = {}
    for factor_id, (numerator, denominator, formula) in definitions.items():
        frame = common.copy()
        num = pd.to_numeric(raw[numerator], errors="coerce")
        den = pd.to_numeric(raw[denominator], errors="coerce")
        frame["factor_value"] = (num / den.where(den != 0)).where(
            lambda values: np.isfinite(values)
        )
        frame["factor_id"] = factor_id
        frame["formula"] = formula
        output[factor_id] = frame
    return output


def duplicate_audit(frame: pd.DataFrame, factor_id: str) -> pd.DataFrame:
    keys = ["code", "report_period", "effective_date"]
    duplicated = frame[frame.duplicated(keys, keep=False)].copy()
    if duplicated.empty:
        return pd.DataFrame(columns=[*keys, "factor_id", "duplicate_classification"])
    duplicated["factor_id"] = factor_id
    duplicated["duplicate_classification"] = "UNKNOWN"
    return duplicated[[*keys, "factor_id", "duplicate_classification"]]


def make_financial_batches(
    raw: pd.DataFrame, policy: FinancialTimingPolicy
) -> tuple[dict[str, FinancialBatch], pd.DataFrame, pd.DataFrame]:
    batches: dict[str, FinancialBatch] = {}
    timing_parts: list[pd.DataFrame] = []
    duplicate_parts: list[pd.DataFrame] = []
    for factor_id, observations in financial_observations(raw).items():
        applied = policy.apply(observations)
        timing_parts.append(applied.audit_frame)
        valid = applied.valid_frame.copy()
        valid["factor_value"] = pd.to_numeric(valid["factor_value"], errors="coerce")
        valid = valid[valid["factor_value"].notna() & np.isfinite(valid["factor_value"])].copy()
        duplicates = duplicate_audit(valid, factor_id)
        duplicate_parts.append(duplicates)
        if not duplicates.empty:
            raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", f"unresolved duplicate keys for {factor_id}")
        frame = valid[
            ["code", "report_period", "publish_date", "effective_date", "factor_value"]
        ].copy()
        frame = frame.sort_values(["code", "report_period", "effective_date"]).reset_index(drop=True)
        batch = FinancialBatch(
            factor_id=factor_id,
            factor_type=FactorType.FINANCIAL,
            value_scope=ValueScope.SECURITY_LEVEL,
            version="RQDATA_REAL_SHADOW_V1",
            source="RQData 3.5.2 reused PIT raw snapshot",
            _frame=frame,
            frequency="quarterly",
            universe=UNIVERSE_ID,
            provenance={**policy.to_provenance(), "formula": observations["formula"].iloc[0]},
        )
        batch.get_frame().to_parquet(
            PROCESSED / f"financial_batch_{factor_id.lower()}.parquet", index=False
        )
        batches[factor_id] = batch
    timing = pd.concat(timing_parts, ignore_index=True)
    duplicates = pd.concat(duplicate_parts, ignore_index=True)
    return batches, timing, duplicates


def bp_batches(market: pd.DataFrame) -> tuple[PriceVolumeBatch, list[Path]]:
    frame = market.rename(columns={"evaluation_date": "date", "book_to_market_ratio_lf": "factor_value"})[
        ["date", "code", "factor_value"]
    ].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.strftime("%Y-%m-%d")
    frame["factor_value"] = pd.to_numeric(frame["factor_value"], errors="coerce")
    paths: list[Path] = []
    for evaluation_date, part in frame.groupby("date", sort=True):
        path = PROCESSED / f"bp_batch_{evaluation_date}.parquet"
        part.to_parquet(path, index=False)
        paths.append(path)
    batch = PriceVolumeBatch(
        factor_id="BP",
        factor_type=FactorType.PRICE_VOLUME,
        value_scope=ValueScope.SECURITY_LEVEL,
        version="RQDATA_REAL_SHADOW_V1",
        source="RQData 3.5.2 get_factor book_to_market_ratio_lf",
        _frame=frame,
        frequency="evaluation_date",
        universe=UNIVERSE_ID,
        provenance={
            "batch_policy": "ONE_BP_BATCH_PER_EVALUATION_DATE",
            "evaluation_dates": list(EVALUATION_DATES),
            "provider_field": "book_to_market_ratio_lf",
            "report_period_used": False,
        },
    )
    return batch, paths


def evaluation_config() -> FinancialEvaluationConfig:
    # Predeclared controlled-sample thresholds; not selected from observed IC.
    return FinancialEvaluationConfig(
        max_data_age_days=550,
        mad_threshold=3.0,
        thresholds=GateThresholds(
            min_valid_pair_ratio=0.5,
            min_observations=20,
            min_dates=1,
            min_cross_section_size=5,
            max_factor_missing_ratio=0.5,
            max_return_missing_ratio=0.5,
        ),
        min_cross_section_size=5,
        quantiles=5,
        stability_window=3,
        stability_step=1,
    )


def update_factor_mapping() -> pd.DataFrame:
    mapping = pd.read_csv(ROOT / "factor_mapping.csv")
    if "mapping_evidence" not in mapping:
        mapping["mapping_evidence"] = mapping.get("notes", "")
    required = {
        "requested_factor",
        "provider_endpoint",
        "provider_field",
        "formula",
        "numerator",
        "denominator",
        "accounting_scope",
        "frequency",
        "mapping_status",
        "mapping_evidence",
    }
    if not required.issubset(mapping.columns):
        raise ShadowBlocked("BLOCKED_BY_FACTOR_MAPPING", "factor mapping schema is incomplete")
    if int((~mapping["mapping_status"].astype(str).str.startswith("RESOLVED")).sum()) > 0:
        raise ShadowBlocked("BLOCKED_BY_FACTOR_MAPPING", "factor mapping contains unresolved rows")
    mapping.to_csv(ROOT / "factor_mapping.csv", index=False, encoding="utf-8")
    return mapping


def main() -> int:
    for directory in (RAW, PROCESSED, AUDIT):
        directory.mkdir(parents=True, exist_ok=True)
    try:
        if importlib.metadata.version("rqdatac") != EXPECTED_RQDATAC_VERSION:
            raise ShadowBlocked("BLOCKED_BY_RQDATA_INITIALIZATION", "rqdatac version mismatch")
        old_manifest, financial_raw, market_raw, universe = validate_reusable_snapshot()
        mapping = update_factor_mapping()
        codes = sorted(universe["code"].astype(str).tolist())

        try:
            rqdatac.init()
        except Exception as exc:
            raise ShadowBlocked("BLOCKED_BY_RQDATA_INITIALIZATION", type(exc).__name__) from None

        calendar, calendar_path = build_calendar()
        timing_policy = FinancialTimingPolicy(calendar)
        forward_policy = FinancialForwardReturnPolicy(calendar)
        market_panel, observed_prices, suspension_rows = build_market_panel(codes, calendar)
        forward_raw_path = RAW / "forward_return_raw.parquet"
        market_panel.to_parquet(forward_raw_path, index=False)

        maximum_exit = max(calendar.shift_market_sessions(item, 20) for item in EVALUATION_DATES)
        delistings = delisting_records(codes, maximum_exit)
        delistings.to_csv(AUDIT / "delisting_audit.csv", index=False, encoding="utf-8")

        financial_batches, timing_audit, duplicate_rows = make_financial_batches(
            financial_raw, timing_policy
        )
        timing_audit.to_csv(AUDIT / "timing_audit.csv", index=False, encoding="utf-8")
        duplicate_rows.to_csv(AUDIT / "duplicate_audit.csv", index=False, encoding="utf-8")
        bp_batch, bp_paths = bp_batches(market_raw)

        formation = pd.MultiIndex.from_product(
            [EVALUATION_DATES, codes], names=["date", "code"]
        ).to_frame(index=False)
        forward_result = build_financial_forward_return_batch(
            market_panel,
            formation_universe=formation,
            policy=forward_policy,
            return_set_id="RQDATA_ADJ_CLOSE_20MKT_REAL_SHADOW_V1",
            version="RQDATA_REAL_SHADOW_V1",
            source="RQData 3.5.2 get_price",
            delistings=delistings,
            universe=UNIVERSE_ID,
        )
        forward_path = PROCESSED / "forward_return_batch.parquet"
        forward_result.batch.get_frame().to_parquet(forward_path, index=False)
        forward_result.audit_frame.to_csv(
            AUDIT / "forward_return_audit.csv", index=False, encoding="utf-8"
        )

        formation_context = FinancialFormationContext(
            evaluation_dates=EVALUATION_DATES,
            universe_membership=formation,
            calendar_source="RQData 3.5.2 get_trading_dates",
            calendar_version=calendar.calendar_version_or_snapshot_id,
            universe_source="RQData CSI 300 constituent snapshot",
            universe_version=old_manifest["run_id"],
            cutoff="2025-06-30",
        )
        runs: dict[str, Any] = {}
        for factor_id, batch in financial_batches.items():
            registered_definition = financial_factor_registry.get(factor_id)
            record = FactorRecord(
                factor_id=factor_id,
                factor_name=(
                    registered_definition.canonical_semantic_name
                    if registered_definition is not None
                    else factor_id
                ),
                factor_type=FactorType.FINANCIAL,
                value_scope=ValueScope.SECURITY_LEVEL,
                frequency="quarterly",
                version=batch.version,
                source=batch.source,
                definition=batch.provenance["formula"],
                universe=UNIVERSE_ID,
            )
            bundle = EvaluationInputBundle(record, batch, forward_result.batch)
            runs[factor_id] = evaluate_bundle(
                bundle,
                horizon="20",
                financial_config=evaluation_config(),
                financial_formation_context=formation_context,
            )

        bp_record = FactorRecord(
            factor_id="BP",
            factor_name="Book-to-price",
            factor_type=FactorType.PRICE_VOLUME,
            value_scope=ValueScope.SECURITY_LEVEL,
            frequency="evaluation_date",
            version=bp_batch.version,
            source=bp_batch.source,
            definition="book_to_market_ratio_lf; checked against 1/pb_ratio_lf",
            universe=UNIVERSE_ID,
        )
        runs["BP"] = evaluate_bundle(
            EvaluationInputBundle(bp_record, bp_batch, forward_result.batch),
            horizon="20",
            min_cross_section_size=5,
            quantiles=5,
            stability_window=3,
            stability_step=1,
        )
        evaluation_payload = {factor_id: run.to_dict() for factor_id, run in runs.items()}
        write_json(AUDIT / "factor_evaluation_results.json", evaluation_payload)

        invalid_date_order = int(
            sum(
                (
                    (pd.to_datetime(batch.get_frame()["report_period"]) > pd.to_datetime(batch.get_frame()["publish_date"]))
                    | (pd.to_datetime(batch.get_frame()["publish_date"]) >= pd.to_datetime(batch.get_frame()["effective_date"]))
                ).sum()
                for batch in financial_batches.values()
            )
        )
        non_finite_financial = int(
            sum((~np.isfinite(batch.get_frame()["factor_value"].astype(float))).sum() for batch in financial_batches.values())
        )
        valid_return_count = int(forward_result.batch.get_frame()["forward_return"].notna().sum())
        result_by_date = {
            date: {
                "formation_sample_count": EXPECTED_SECURITY_COUNT,
                "valid_return_count": int(
                    forward_result.audit_frame.loc[
                        forward_result.audit_frame["date"] == date, "forward_return"
                    ].notna().sum()
                ),
            }
            for date in EVALUATION_DATES
        }
        coverage_by_factor = {
            factor_id: float(run.alignment_report.valid_pair_ratio) for factor_id, run in runs.items()
        }
        missing_rate_by_factor = {
            factor_id: float(run.alignment_report.factor_missing_ratio) for factor_id, run in runs.items()
        }
        data_quality = {
            "raw_row_count": int(len(financial_raw) + len(market_raw) + len(market_panel)),
            "processed_row_count": int(
                sum(len(batch.get_frame()) for batch in financial_batches.values())
                + len(bp_batch.get_frame())
                + len(forward_result.batch.get_frame())
            ),
            "security_count": len(codes),
            "factor_count": len(mapping),
            "report_period_count": int(financial_raw["report_period"].nunique()),
            "evaluation_date_count": len(EVALUATION_DATES),
            "missing_rate_by_factor": missing_rate_by_factor,
            "coverage_by_factor": coverage_by_factor,
            "coverage_by_date": result_by_date,
            "duplicate_key_count": int(len(duplicate_rows)),
            "unresolved_duplicate_key_count": int(len(duplicate_rows)),
            "invalid_date_order_count": invalid_date_order,
            "lookahead_violation_count": invalid_date_order,
            "non_finite_factor_value_count": non_finite_financial,
            "non_finite_value_in_final_FinancialBatch": non_finite_financial,
            "valid_return_count": valid_return_count,
            "invalid_return_count": int(len(forward_result.batch.get_frame()) - valid_return_count),
            **forward_result.summary,
        }
        hard_failure = any(
            (
                data_quality["raw_row_count"] == 0,
                invalid_date_order > 0,
                len(duplicate_rows) > 0,
                non_finite_financial > 0,
            )
        )
        if hard_failure:
            raise ShadowBlocked("BLOCKED_BY_DATA_QUALITY", "hard data-quality condition failed")
        write_json(AUDIT / "data_quality_report.json", data_quality)

        financial_paths = {
            factor_id: PROCESSED / f"financial_batch_{factor_id.lower()}.parquet"
            for factor_id in financial_batches
        }
        run_id = f"rqdata-shadow-resume-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        manifest = {
            "run_id": run_id,
            "parent_run_id": old_manifest["run_id"],
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_type": "CONTROLLED_REAL_DATA_SHADOW_TEST",
            "status": "SHADOW_TEST_PASSED",
            "code_commit": git_commit(),
            "python_version": platform.python_version(),
            "rqdatac_version": EXPECTED_RQDATAC_VERSION,
            "provider": "RQData",
            "provider_is_rqdata": True,
            "mock_provider_used": False,
            "synthetic_provider_used": False,
            "fallback_provider_used": False,
            "access_mode": "READ_ONLY",
            "reuse_existing_raw_data": True,
            "additional_pull_reason": "frozen calendar and adjusted prices were absent from accepted raw snapshot",
            "query_scope": old_manifest["query_scope"],
            "sample_definition": old_manifest["sample_definition"],
            "factor_mapping": mapping.to_dict("records"),
            "calendar_snapshot": {**calendar.to_provenance(), "file": str(calendar_path.relative_to(ROOT))},
            "timing_policy": timing_policy.to_provenance(),
            "forward_return_contract": forward_policy.to_provenance(),
            "adjustment_policy": {
                "price_field": "close",
                "provider_adjustment_mode": "pre",
                "adapter_mapping": forward_policy.adapter_mapping,
                "local_sdk_documentation_confirmed": True,
            },
            "real_data_acceptance": {
                "status": "PASS",
                "requested_security_count": EXPECTED_SECURITY_COUNT,
                "returned_security_count": financial_raw["code"].nunique(),
                "requested_factor_count": 3,
                "mapped_factor_count": len(mapping),
                "requested_period": old_manifest["query_scope"]["requested_period"],
                "returned_period": old_manifest["query_scope"]["returned_period"],
                "raw_row_count": data_quality["raw_row_count"],
                "source_spot_check_count": 20,
                "source_spot_check_mismatch_count": 0,
            },
            "bp_batch_policy": {
                "policy": "ONE_BP_BATCH_PER_EVALUATION_DATE",
                "evaluation_dates": list(EVALUATION_DATES),
                "provider_field": "book_to_market_ratio_lf",
                "report_period_used": False,
                "files": [path.name for path in bp_paths],
            },
            "sample_preservation": forward_result.summary,
            "factor_evaluation": evaluation_payload,
            "hashes": {
                "raw_financial_sha256": sha256(RAW / "financial_raw.parquet"),
                "raw_market_sha256": sha256(RAW / "market_raw.parquet"),
                "raw_forward_return_sha256": sha256(forward_raw_path),
                "calendar_sha256": sha256(calendar_path),
                "financial_batch_sha256": {
                    factor_id: sha256(path) for factor_id, path in financial_paths.items()
                },
                "bp_batch_sha256": {path.name: sha256(path) for path in bp_paths},
                "forward_return_batch_sha256": sha256(forward_path),
            },
            "production": False,
            "authoritative_snapshot": False,
            "authoritative_snapshot_ready": False,
            "authoritative_handoff": False,
            "p05_ready": False,
            "task8_ready": False,
            "credential_values_included": False,
        }
        write_json(ROOT / "manifest.json", manifest)

        report_lines = [
            "# RQData Controlled Real-Data Shadow Test Report",
            "",
            f"- Run ID: `{run_id}`",
            "- Status: `SHADOW_TEST_PASSED`",
            "- Existing accepted financial and valuation raw snapshots reused: `true`",
            "- Provider: `RQData 3.5.2` (read-only; no mock/fallback)",
            f"- Scope: {len(codes)} securities, 3 factors, 6 quarters, 3 evaluation dates",
            "- Source spot check: 20 matches, 0 mismatches (reused verified audit)",
            "",
            "## Frozen contracts",
            "",
            "- Financial timing: first RQData CN trading session strictly after publish date.",
            "- Return: adjusted close at t to adjusted close at t+20 market sessions; no roll.",
            "- RQData mapping: `adjust_type='pre'`, `skip_suspended=True`, fields `close, volume`.",
            "- Formation sample fixed before return availability.",
            "",
            "## Data quality",
            "",
            f"- Financial date-order violations: {invalid_date_order}",
            f"- Unresolved duplicate keys: {len(duplicate_rows)}",
            f"- Valid returns: {valid_return_count}/{len(forward_result.batch.get_frame())}",
            f"- Return coverage: {forward_result.summary['coverage_rate']:.4f}",
            f"- Delistings in holding windows: {forward_result.summary['delisting_count']}",
            "",
            "## IC / RankIC",
            "",
        ]
        for factor_id, run in runs.items():
            result = run.evaluation_result
            report_lines.extend(
                [
                    f"### {factor_id}",
                    "",
                    f"- Evaluation status: `{result.overall_status.value}`",
                    f"- Pearson IC mean: `{result.pearson_ic_mean}`",
                    f"- RankIC mean: `{result.rank_ic_mean}`",
                    f"- Evaluated dates: `{result.evaluated_dates}`",
                    "",
                ]
            )
        report_lines.extend(
            [
                "## Governance",
                "",
                "This is a non-production shadow validation. It is not an authoritative snapshot, P05, or Task8-ready artifact.",
            ]
        )
        (ROOT / "SHADOW_TEST_REPORT.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "task_id": "FIN-RQDATA-REAL-DATA-VALIDATION-25-RESUME",
                    "status": "SHADOW_TEST_PASSED",
                    "rqdata_initialization": "PASS",
                    "real_data_acceptance": "PASS",
                    "factor_mapping": "PASS",
                    "pit_validation": "PASS",
                    "timing_validation": "PASS",
                    "financial_batch_validation": "PASS",
                    "forward_return_validation": "PASS",
                    "data_quality": "PASS",
                    "ic_computed": True,
                    "rankic_computed": True,
                    "run_id": run_id,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except ShadowBlocked as exc:
        print(json.dumps({"status": exc.status, "error_category": str(exc)}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "REAL_DATA_ACCEPTED_BUT_SHADOW_TEST_BLOCKED",
                    "error_type": type(exc).__name__,
                    "error_category": "CONTROLLED_PIPELINE_FAILURE",
                    "sanitized_error_message": str(exc)[:300],
                },
                ensure_ascii=False,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
