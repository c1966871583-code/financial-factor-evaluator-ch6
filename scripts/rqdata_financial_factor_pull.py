"""Pull the Chapter 6 financial-factor set from an initialized RQData session.

Run this script inside the RQData server environment. Authentication must be
provided by the environment; the script never accepts or stores credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


FACTOR_CANDIDATES: dict[str, tuple[str, ...]] = {
    "BP": ("book_to_price_ratio", "book_to_price", "bp"),
    "EP": ("earnings_to_price_ratio", "earning_to_price_ratio", "earnings_yield", "ep"),
    "CFP": (
        "cash_flow_to_price_ratio",
        "operating_cash_flow_to_price_ratio",
        "cashflow_to_price_ratio",
        "cfp",
    ),
    "EBIT_EV": ("ebit_to_ev", "ebit_enterprise_value", "ebit_ev"),
    "SalesGrowth": (
        "operating_revenue_growth_rate",
        "revenue_growth_rate",
        "sales_growth_rate",
        "sales_growth",
    ),
    "ProfitGrowth": ("net_profit_growth_rate", "profit_growth_rate", "net_profit_growth"),
    "ROE": ("return_on_equity", "return_on_equity_ttm", "roe"),
    "ROA": ("return_on_asset", "return_on_assets", "return_on_asset_ttm", "roa"),
    "GPM": ("gross_profit_margin", "gross_margin", "gross_profit_margin_ttm"),
    "OCF_NP": (
        "operating_cash_flow_to_net_profit",
        "cash_flow_to_net_profit",
        "operating_cashflow_to_net_profit",
        "ocf_to_net_profit",
    ),
    "DebtAsset": ("debt_to_asset_ratio", "debt_asset_ratio", "liability_to_asset_ratio"),
    "InterestCoverage": (
        "interest_coverage_ratio",
        "interest_coverage",
        "times_interest_earned",
    ),
}


@dataclass(frozen=True)
class PullResult:
    factor_id: str
    rqdata_factor: str
    path: str
    sha256: str
    rows: int
    non_null_rows: int
    symbols: int
    date_min: str | None
    date_max: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull 12 financial factors from RQData.")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-04-30")
    parser.add_argument("--frequency", default="1m", help="RQData frequency, default: 1m")
    parser.add_argument("--market", default="cn")
    parser.add_argument("--output", default="/tmp/rqdata_financial_factors")
    parser.add_argument("--symbols", default="", help="Comma-separated RQData order_book_ids")
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _canonical(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _extract_factor_names(value: Any) -> list[str]:
    if isinstance(value, pd.DataFrame):
        preferred = [c for c in value.columns if str(c).lower() in {"factor", "factor_name", "name"}]
        columns = preferred or list(value.columns)
        return sorted({str(item) for column in columns for item in value[column].dropna().tolist()})
    if isinstance(value, pd.Series):
        return sorted({str(item) for item in value.dropna().tolist()})
    if isinstance(value, dict):
        names: set[str] = set()
        for key, item in value.items():
            names.add(str(key))
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, Iterable) and not isinstance(item, (str, bytes, dict)):
                names.update(str(member) for member in item)
        return sorted(names)
    return sorted({str(item) for item in value})


def resolve_factor_mapping(available_names: list[str]) -> dict[str, str]:
    by_lower = {name.lower(): name for name in available_names}
    by_canonical: dict[str, list[str]] = {}
    for name in available_names:
        by_canonical.setdefault(_canonical(name), []).append(name)

    resolved: dict[str, str] = {}
    errors: dict[str, dict[str, Any]] = {}
    for factor_id, candidates in FACTOR_CANDIDATES.items():
        exact = [by_lower[c.lower()] for c in candidates if c.lower() in by_lower]
        if len(set(exact)) == 1:
            resolved[factor_id] = exact[0]
            continue

        canonical = {
            match
            for candidate in candidates
            for match in by_canonical.get(_canonical(candidate), [])
        }
        if len(canonical) == 1:
            resolved[factor_id] = canonical.pop()
            continue

        suggestions: list[str] = []
        for candidate in candidates:
            suggestions.extend(get_close_matches(candidate, available_names, n=5, cutoff=0.55))
        errors[factor_id] = {
            "candidates": list(candidates),
            "exact_matches": sorted(set(exact) | canonical),
            "suggestions": list(dict.fromkeys(suggestions))[:10],
        }

    if errors:
        raise RuntimeError("Factor mapping is incomplete or ambiguous: " + json.dumps(errors, ensure_ascii=False))
    return resolved


def resolve_symbols(rqdatac: Any, raw_symbols: str, market: str, max_symbols: int) -> list[str]:
    if raw_symbols.strip():
        symbols = [item.strip() for item in raw_symbols.split(",") if item.strip()]
    else:
        instruments = rqdatac.all_instruments(type="CS", market=market)
        if "order_book_id" not in instruments.columns:
            raise RuntimeError("all_instruments() did not return order_book_id")
        symbols = instruments["order_book_id"].dropna().astype(str).drop_duplicates().sort_values().tolist()
    if max_symbols > 0:
        symbols = symbols[:max_symbols]
    if not symbols:
        raise RuntimeError("No symbols selected")
    return symbols


def normalize_factor_frame(frame: Any, factor_id: str, rqdata_factor: str) -> pd.DataFrame:
    if isinstance(frame, pd.Series):
        frame = frame.rename("value").to_frame()
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"get_factor() returned unsupported type: {type(frame).__name__}")

    long = frame.reset_index()
    value_columns = [column for column in long.columns if column not in {"order_book_id", "date"}]
    if rqdata_factor in long.columns:
        value_column = rqdata_factor
    elif len(value_columns) == 1:
        value_column = value_columns[0]
    else:
        raise RuntimeError(f"Could not identify value column: {list(long.columns)}")

    long = long.rename(columns={value_column: "value"})
    required = {"order_book_id", "date", "value"}
    missing = required - set(long.columns)
    if missing:
        raise RuntimeError(f"Missing normalized columns: {sorted(missing)}")
    long = long[["order_book_id", "date", "value"]].copy()
    long["date"] = pd.to_datetime(long["date"], errors="raise")
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long["factor_id"] = factor_id
    long["rqdata_factor"] = rqdata_factor
    return long[["order_book_id", "date", "factor_id", "rqdata_factor", "value"]]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pull_one(
    rqdatac: Any,
    *,
    factor_id: str,
    rqdata_factor: str,
    symbols: list[str],
    start: str,
    end: str,
    frequency: str,
    market: str,
    output_dir: Path,
    overwrite: bool,
) -> PullResult:
    output_path = output_dir / f"{factor_id}.parquet"
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output exists: {output_path}; pass --overwrite to replace it")

    frame = rqdatac.get_factor(
        order_book_ids=symbols,
        factor=rqdata_factor,
        start_date=start,
        end_date=end,
        market=market,
        frequency=frequency,
    )
    long = normalize_factor_frame(frame, factor_id, rqdata_factor)
    if long.empty:
        raise RuntimeError(f"RQData returned no rows for {factor_id} ({rqdata_factor})")
    long.to_parquet(output_path, index=False)
    valid = long["value"].notna()
    return PullResult(
        factor_id=factor_id,
        rqdata_factor=rqdata_factor,
        path=str(output_path),
        sha256=file_sha256(output_path),
        rows=int(len(long)),
        non_null_rows=int(valid.sum()),
        symbols=int(long["order_book_id"].nunique()),
        date_min=long["date"].min().strftime("%Y-%m-%d") if not long.empty else None,
        date_max=long["date"].max().strftime("%Y-%m-%d") if not long.empty else None,
    )


def main() -> int:
    args = parse_args()
    import rqdatac

    rqdatac.init()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    available_names = _extract_factor_names(rqdatac.get_all_factor_names())
    mapping = resolve_factor_mapping(available_names)
    symbols = resolve_symbols(rqdatac, args.symbols, args.market, args.max_symbols)

    catalog_path = output_dir / "rqdata_factor_catalog.json"
    catalog_path.write_text(json.dumps(available_names, ensure_ascii=False, indent=2), encoding="utf-8")
    mapping_path = output_dir / "financial_factor_mapping.json"
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")

    results = [
        pull_one(
            rqdatac,
            factor_id=factor_id,
            rqdata_factor=rqdata_factor,
            symbols=symbols,
            start=args.start,
            end=args.end,
            frequency=args.frequency,
            market=args.market,
            output_dir=output_dir,
            overwrite=args.overwrite,
        )
        for factor_id, rqdata_factor in mapping.items()
    ]
    summary = {
        "schema_version": "rqdata-financial-factor-pull-v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "rqdatac_version": getattr(rqdatac, "__version__", None),
        "start": args.start,
        "end": args.end,
        "frequency": args.frequency,
        "market": args.market,
        "requested_symbol_count": len(symbols),
        "factor_mapping": mapping,
        "results": [result.__dict__ for result in results],
    }
    summary_path = output_dir / "pull_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
