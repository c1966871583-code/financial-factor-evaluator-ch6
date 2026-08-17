"""Minimal RQData capability preflight for the frozen full-market OOS protocol.

The preflight queries only calendar/universe metadata and one security's schema.
It does not pull the historical factor panel and never emits identifiers,
credential values, provider responses, or account information.
"""

from __future__ import annotations

import importlib.metadata
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import rqdatac


PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "artifacts" / "full_market_oos_validation" / "preflight"
PROTOCOL = PROJECT / "docs" / "provenance" / "FULL_MARKET_OOS_VALIDATION_PROTOCOL_V1.json"
EXPECTED_RQDATAC_VERSION = "3.5.2"


class PreflightBlocked(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def provider_call(category: str, fn: Callable[[], Any]) -> Any:
    delays = (1, 2, 4)
    for attempt in range(4):
        try:
            return fn()
        except Exception as exc:
            if type(exc).__name__ == "QuotaExceeded":
                raise PreflightBlocked("PROVIDER_QUOTA_EXCEEDED") from None
            text = str(exc).lower()
            retryable = "429" in text or "503" in text
            if retryable and attempt < 3:
                time.sleep(delays[attempt])
                continue
            raise PreflightBlocked(category) from None
    raise PreflightBlocked(category)


def columns(value: Any) -> set[str]:
    if isinstance(value, pd.DataFrame):
        return {str(item) for item in value.reset_index().columns}
    return set()


def main() -> int:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["status"] != "FROZEN":
        raise PreflightBlocked("PROTOCOL_NOT_FROZEN")
    if importlib.metadata.version("rqdatac") != EXPECTED_RQDATAC_VERSION:
        raise PreflightBlocked("RQDATAC_VERSION_MISMATCH")

    result: dict[str, Any] = {
        "task_id": "RQDATA-FULL-MARKET-PRODUCTION-PREFLIGHT",
        "protocol_id": protocol["protocol_id"],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "rqdatac_version": EXPECTED_RQDATAC_VERSION,
        "real_data_query_performed": False,
        "full_market_historical_pull_performed": False,
        "identifiers_persisted": False,
        "credential_values_exposed": False,
        "production_ready": False,
    }
    checks: dict[str, bool] = {}
    try:
        provider_call("RQDATA_INITIALIZATION_UNAVAILABLE", rqdatac.init)
        checks["INITIALIZATION_PASS"] = True

        calendar = []
        for year in range(2016, 2027):
            end_date = f"{year}-12-31" if year < 2026 else "2026-02-28"
            calendar.extend(
                provider_call(
                    f"TRADING_CALENDAR_UNAVAILABLE_{year}",
                    lambda year=year, end_date=end_date: rqdatac.get_trading_dates(
                        f"{year}-01-01", end_date, market="cn"
                    ),
                )
            )
        result["real_data_query_performed"] = True
        calendar_dates = tuple(pd.Timestamp(item).strftime("%Y-%m-%d") for item in calendar)
        checks["CALENDAR_COVERAGE_PASS"] = (
            len(calendar_dates) >= 2400
            and calendar_dates[0] <= "2016-01-04"
            and calendar_dates[-1] >= "2026-01-31"
        )

        universe_early = provider_call(
            "HISTORICAL_UNIVERSE_UNAVAILABLE",
            lambda: rqdatac.all_instruments(type="CS", date="2016-01-29", market="cn"),
        )
        universe_late = provider_call(
            "CURRENT_UNIVERSE_UNAVAILABLE",
            lambda: rqdatac.all_instruments(type="CS", date="2025-12-31", market="cn"),
        )
        required_instrument = {"order_book_id", "listed_date", "de_listed_date"}
        early_columns = columns(universe_early)
        late_columns = columns(universe_late)
        checks["HISTORICAL_UNIVERSE_SCHEMA_PASS"] = required_instrument.issubset(early_columns)
        checks["CURRENT_UNIVERSE_SCHEMA_PASS"] = required_instrument.issubset(late_columns)
        checks["UNIVERSE_COUNTS_PLAUSIBLE_PASS"] = (
            isinstance(universe_early, pd.DataFrame)
            and isinstance(universe_late, pd.DataFrame)
            and len(universe_early) >= 2000
            and len(universe_late) > len(universe_early)
        )

        eligible = universe_late.copy()
        eligible["listed_date"] = pd.to_datetime(eligible["listed_date"], errors="coerce")
        eligible = eligible.loc[eligible["listed_date"] <= pd.Timestamp("2024-01-01")]
        if eligible.empty:
            raise PreflightBlocked("NO_SCHEMA_PROBE_SECURITY")
        probe_code = str(sorted(eligible["order_book_id"].astype(str))[0])

        financial = provider_call(
            "PIT_FINANCIAL_SCHEMA_UNAVAILABLE",
            lambda: rqdatac.get_pit_financials_ex(
                order_book_ids=[probe_code],
                fields=[
                    "np_parent_company_ownersTTM",
                    "equity_parent_company",
                    "net_operate_cashflowTTM",
                ],
                start_quarter="2025q2",
                end_quarter="2025q3",
                date="2025-12-31",
                statements="all",
                market="cn",
            ),
        )
        financial_columns = columns(financial)
        checks["PIT_FINANCIAL_SCHEMA_PASS"] = {
            "info_date",
            "quarter",
            "if_adjusted",
            "np_parent_company_ownersTTM",
            "equity_parent_company",
            "net_operate_cashflowTTM",
        }.issubset(financial_columns)

        valuation = provider_call(
            "VALUATION_FACTOR_SCHEMA_UNAVAILABLE",
            lambda: rqdatac.get_factor(
                [probe_code],
                ["book_to_market_ratio_lf", "pb_ratio_lf", "market_cap"],
                start_date="2025-12-31",
                end_date="2025-12-31",
                expect_df=True,
                market="cn",
            ),
        )
        checks["VALUATION_FACTOR_SCHEMA_PASS"] = {
            "book_to_market_ratio_lf",
            "pb_ratio_lf",
            "market_cap",
        }.issubset(columns(valuation))

        price = provider_call(
            "PRICE_AND_LIMIT_SCHEMA_UNAVAILABLE",
            lambda: rqdatac.get_price(
                [probe_code],
                start_date="2025-12-01",
                end_date="2025-12-31",
                frequency="1d",
                fields=["close", "volume", "limit_up", "limit_down"],
                adjust_type="pre",
                skip_suspended=False,
                expect_df=True,
                market="cn",
            ),
        )
        price_columns = columns(price)
        checks["PRICE_SCHEMA_PASS"] = {"close", "volume"}.issubset(price_columns)
        checks["PRICE_LIMIT_SCHEMA_PASS"] = {"limit_up", "limit_down"}.issubset(price_columns)

        suspended = provider_call(
            "SUSPENSION_HISTORY_UNAVAILABLE",
            lambda: rqdatac.is_suspended(
                [probe_code], start_date="2025-12-01", end_date="2025-12-31", market="cn"
            ),
        )
        st_status = provider_call(
            "ST_HISTORY_UNAVAILABLE",
            lambda: rqdatac.is_st_stock(
                [probe_code], start_date="2025-12-01", end_date="2025-12-31", market="cn"
            ),
        )
        industry = provider_call(
            "PIT_INDUSTRY_UNAVAILABLE",
            lambda: rqdatac.get_instrument_industry(
                [probe_code], source="citics_2019", level=1, date="2025-12-31", market="cn"
            ),
        )
        checks["SUSPENSION_HISTORY_PASS"] = suspended is not None
        checks["ST_HISTORY_PASS"] = st_status is not None
        checks["PIT_INDUSTRY_PASS"] = industry is not None

        checks = {name: bool(value) for name, value in checks.items()}
        passed = all(checks.values())
        result.update(
            {
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "checks": checks,
                "checks_passed": sum(checks.values()),
                "checks_failed": len(checks) - sum(checks.values()),
                "failed_checks": [name for name, value in checks.items() if not value],
                "calendar_session_count": len(calendar_dates),
                "historical_universe_count_2016": len(universe_early),
                "historical_universe_count_2025": len(universe_late),
                "status": "FULL_MARKET_DATA_CAPABILITY_PREFLIGHT_PASSED" if passed else "BLOCKED_BY_PROVIDER_CAPABILITY_GAP",
            }
        )
    except PreflightBlocked as exc:
        blocked_status = (
            "BLOCKED_BY_PROVIDER_QUOTA"
            if exc.category == "PROVIDER_QUOTA_EXCEEDED"
            else "BLOCKED_BY_PROVIDER_CAPABILITY_GAP"
        )
        result.update(
            {
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "checks": {name: bool(value) for name, value in checks.items()},
                "status": blocked_status,
                "error_type": "PreflightBlocked",
                "error_category": exc.category,
            }
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RQDATA_FULL_MARKET_PREFLIGHT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "FULL_MARKET_DATA_CAPABILITY_PREFLIGHT_PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
