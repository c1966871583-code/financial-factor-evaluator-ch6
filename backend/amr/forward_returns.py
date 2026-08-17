"""PV-GAP-2: Security-level forward return batch builder (corrected).

close[t+h]/close[t] - 1 per code.  Accepts Iterable[int] horizons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from .evaluation_input_contract import (
    EvaluationInputContractError,
    ForwardReturnBatch,
    ValueScope,
)
from .financial_timing import FinancialTimingPolicyError, VersionedTradingCalendar


@dataclass(frozen=True)
class FinancialForwardReturnPolicy:
    """Operator-frozen v1 policy for financial-factor IC labels."""

    calendar: VersionedTradingCalendar
    horizon: int = 20
    price_field: str = "close"
    adjustment_policy: str = "CONSISTENT_CORPORATE_ACTION_ADJUSTED_CLOSE"
    provider_adjustment_mode: str = "pre"
    adapter_mapping: str = (
        "rqdatac.get_price(fields=['close','volume'], adjust_type='pre', "
        "skip_suspended=True)"
    )
    policy_version: str = "FINANCIAL_FORWARD_RETURN_20MKT_V1"

    def __post_init__(self) -> None:
        if self.horizon != 20:
            raise EvaluationInputContractError("INVALID_HORIZON", "financial forward-return horizon must equal 20 market sessions")
        if self.price_field != "close":
            raise EvaluationInputContractError("INVALID_PRICE_FIELD", "financial forward returns require close")
        if self.adjustment_policy != "CONSISTENT_CORPORATE_ACTION_ADJUSTED_CLOSE":
            raise EvaluationInputContractError("INVALID_ADJUSTMENT_POLICY", "adjusted close policy is required")
        # rqdatac 3.5.2 documents pre as a supported ex-right/ex-dividend repair
        # mode.  The adapter must request it explicitly and skip filled
        # suspension observations so fixed-calendar gaps remain observable.
        if self.provider_adjustment_mode != "pre":
            raise EvaluationInputContractError(
                "BLOCKED_BY_ADJUSTMENT_POLICY_MAPPING",
                "v1 RQData mapping is frozen to adjust_type='pre'",
            )
        for name, value in (
            ("adapter_mapping", self.adapter_mapping),
            ("policy_version", self.policy_version),
        ):
            if not value.strip():
                raise EvaluationInputContractError("MISSING_POLICY_METADATA", f"{name} is required")

    def to_provenance(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "return_horizon": "20 market trading sessions",
            "evaluation_date_semantics": "factor cross-section formed at evaluation-date close",
            "entry_timing": "evaluation_date close",
            "exit_timing": "close of 20th market session strictly after entry",
            "price_field": self.price_field,
            "adjustment_policy": self.adjustment_policy,
            "provider_adjustment_mode": self.provider_adjustment_mode,
            "adapter_mapping": self.adapter_mapping,
            "suspension_policy": "fixed calendar horizon; no roll",
            "tradability_policy": "entry must be tradable",
            "missing_price_policy": "NaN with audit reason",
            "delisting_policy": "provider termination value or explicit NaN",
            "sample_policy": "keep factor formation sample fixed",
            **self.calendar.to_provenance(),
        }


@dataclass(frozen=True)
class FinancialForwardReturnBuildResult:
    batch: ForwardReturnBatch
    audit_frame: pd.DataFrame
    summary: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "audit_frame", self.audit_frame.copy())
        object.__setattr__(self, "summary", dict(self.summary))


def build_financial_forward_return_batch(
    panel: pd.DataFrame,
    *,
    formation_universe: pd.DataFrame,
    policy: FinancialForwardReturnPolicy,
    return_set_id: str,
    version: str,
    source: str,
    delistings: pd.DataFrame | None = None,
    universe: str | None = None,
) -> FinancialForwardReturnBuildResult:
    """Build fixed-calendar 20-session labels without changing formation.

    ``panel`` must be the provider-adjusted, non-filled daily observation set.
    Required status columns make suspension/tradability semantics explicit.
    ``formation_universe`` is frozen before label availability is inspected.
    """

    formation_required = {"date", "code"}
    missing_formation = sorted(formation_required - set(formation_universe.columns))
    if missing_formation:
        raise EvaluationInputContractError("MISSING_REQUIRED_COLUMN", f"formation universe missing: {missing_formation}")
    market_required = {"date", "code", policy.price_field, "is_tradable", "is_suspended", "volume"}
    missing_market = sorted(market_required - set(panel.columns))
    if missing_market:
        raise EvaluationInputContractError("MISSING_REQUIRED_COLUMN", f"market panel missing: {missing_market}")

    formation = formation_universe[["date", "code"]].copy()
    formation["date"] = pd.to_datetime(formation["date"], errors="raise").dt.strftime("%Y-%m-%d")
    if formation[["date", "code"]].isnull().any().any():
        raise EvaluationInputContractError("NULL_KEY", "formation date/code must not be null")
    if formation.duplicated(["date", "code"]).any():
        raise EvaluationInputContractError("DUPLICATE_KEY", "duplicate formation (date, code)")

    market = panel.copy()
    market["date"] = pd.to_datetime(market["date"], errors="raise").dt.strftime("%Y-%m-%d")
    if market[["date", "code"]].isnull().any().any():
        raise EvaluationInputContractError("NULL_KEY", "market date/code must not be null")
    if market.duplicated(["date", "code"]).any():
        raise EvaluationInputContractError("DUPLICATE_KEY", "duplicate market (date, code)")
    market_index = market.set_index(["date", "code"], drop=False)

    delisting_by_code: dict[str, tuple[pd.Timestamp, float | None]] = {}
    if delistings is not None and not delistings.empty:
        required = {"code", "delisting_date", "termination_value"}
        missing = sorted(required - set(delistings.columns))
        if missing:
            raise EvaluationInputContractError("MISSING_REQUIRED_COLUMN", f"delistings missing: {missing}")
        if delistings["code"].duplicated().any():
            raise EvaluationInputContractError("DUPLICATE_KEY", "one delisting record per code is required")
        for row in delistings.itertuples(index=False):
            termination = pd.to_numeric(pd.Series([row.termination_value]), errors="coerce").iloc[0]
            delisting_by_code[str(row.code)] = (
                pd.Timestamp(row.delisting_date).normalize(),
                float(termination) if pd.notna(termination) and np.isfinite(termination) and termination >= 0 else None,
            )

    output_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    delisting_count = 0
    delisting_available = 0
    delisting_unavailable = 0

    for item in formation.sort_values(["date", "code"]).itertuples(index=False):
        entry_date = str(item.date)
        code = str(item.code)
        try:
            exit_date = policy.calendar.shift_market_sessions(entry_date, policy.horizon)
        except FinancialTimingPolicyError as exc:
            raise EvaluationInputContractError(exc.code, str(exc)) from exc

        reason = "OK"
        value = float("nan")
        entry_key = (entry_date, code)
        exit_key = (exit_date, code)
        entry_row = market_index.loc[entry_key] if entry_key in market_index.index else None
        exit_row = market_index.loc[exit_key] if exit_key in market_index.index else None

        entry_price = _positive_price(entry_row, policy.price_field)
        if entry_row is None:
            reason = "ENTRY_PRICE_MISSING"
        elif bool(entry_row["is_suspended"]):
            reason = "ENTRY_SUSPENDED_OR_UNPRICED"
        elif not bool(entry_row["is_tradable"]) or not _positive_number(entry_row["volume"]):
            reason = "ENTRY_NOT_TRADABLE"
        elif entry_price is None:
            reason = "ENTRY_PRICE_MISSING"
        else:
            delisting = delisting_by_code.get(code)
            if delisting is not None and pd.Timestamp(entry_date) < delisting[0] <= pd.Timestamp(exit_date):
                delisting_count += 1
                if delisting[1] is None:
                    delisting_unavailable += 1
                    reason = "DELISTING_RETURN_UNAVAILABLE"
                else:
                    delisting_available += 1
                    value = float(delisting[1] / entry_price - 1.0)
                    reason = "DELISTING_TERMINATION_VALUE_USED"
            elif exit_row is None:
                reason = "EXIT_PRICE_MISSING"
            elif bool(exit_row["is_suspended"]) or not _positive_number(exit_row["volume"]):
                reason = "EXIT_SUSPENDED_OR_UNPRICED"
            else:
                exit_price = _positive_price(exit_row, policy.price_field)
                if exit_price is None:
                    reason = "EXIT_PRICE_MISSING"
                else:
                    value = float(exit_price / entry_price - 1.0)
                    if not np.isfinite(value):
                        value = float("nan")
                        reason = "EXIT_PRICE_MISSING"

        output_rows.append(
            {"date": entry_date, "code": code, "horizon": policy.horizon, "forward_return": value}
        )
        audit_rows.append(
            {
                "date": entry_date,
                "code": code,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "horizon": policy.horizon,
                "forward_return": value,
                "audit_reason": reason,
                "factor_formation_member": True,
            }
        )

    output = pd.DataFrame(output_rows, columns=["date", "code", "horizon", "forward_return"])
    audit = pd.DataFrame(audit_rows)
    valid_return_count = int(output["forward_return"].notna().sum())
    formation_count = int(len(output))
    reason_counts = audit["audit_reason"].value_counts(dropna=False).to_dict()
    summary = {
        "formation_sample_count": formation_count,
        "valid_return_count": valid_return_count,
        "excluded_return_count": formation_count - valid_return_count,
        "coverage_rate": float(valid_return_count / formation_count) if formation_count else 0.0,
        "exclusion_reason_distribution": {str(k): int(v) for k, v in reason_counts.items() if k != "OK"},
        "delisting_count": delisting_count,
        "delisting_return_available_count": delisting_available,
        "delisting_return_unavailable_count": delisting_unavailable,
    }
    batch = ForwardReturnBatch(
        return_set_id=return_set_id,
        value_scope=ValueScope.SECURITY_LEVEL,
        version=version,
        source=source,
        return_definition="adjusted_close_t_plus_20_market_sessions_over_adjusted_close_t_minus_1",
        _frame=output,
        frequency="day",
        universe=universe,
        provenance={**policy.to_provenance(), **summary},
    )
    return FinancialForwardReturnBuildResult(batch=batch, audit_frame=audit, summary=summary)


def _positive_number(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(number) and number > 0)


def _positive_price(row: pd.Series | None, column: str) -> float | None:
    if row is None:
        return None
    value = row[column]
    if not _positive_number(value):
        return None
    return float(value)


def build_security_forward_return_batch(
    panel: pd.DataFrame,
    *,
    horizons: Iterable[int],
    return_set_id: str,
    version: str,
    source: str,
    price_col: str = "close",
    frequency: str = "day",
    universe: str | None = None,
) -> ForwardReturnBatch:
    # -- materialise & validate horizons --
    hlist = list(horizons)
    if not hlist:
        raise EvaluationInputContractError("EMPTY_HORIZONS", "horizons must be non-empty")
    for h in hlist:
        if isinstance(h, bool) or not isinstance(h, int) or h < 1:
            raise EvaluationInputContractError("INVALID_HORIZON", f"horizon must be positive int, got {h!r}")
    if len(set(hlist)) != len(hlist):
        raise EvaluationInputContractError("DUPLICATE_HORIZON", "duplicate horizon values; supply unique horizons")

    if frequency != "day":
        raise EvaluationInputContractError("INVALID_FREQUENCY", "only frequency=day supported in v1")

    # -- schema --
    required = {"date", "code", price_col}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise EvaluationInputContractError("MISSING_REQUIRED_COLUMN", f"Missing columns: {missing}")

    if len(panel) == 0:
        # empty panel → zero-row output
        out = pd.DataFrame(columns=["date", "code", "horizon", "forward_return"])
        return _build_result(return_set_id, version, source, out, frequency, universe, price_col, hlist, 0, 0)

    df = panel.copy()

    # -- dates: canonicalise early --
    try:
        dates = pd.to_datetime(df["date"], errors="raise")
    except Exception as e:
        raise EvaluationInputContractError("INVALID_DATE", str(e)) from e
    # write back canonical string form BEFORE dedup check
    df["date"] = dates.dt.strftime("%Y-%m-%d")

    # -- key null / type checks --
    if df["date"].isnull().any() or df["code"].isnull().any():
        raise EvaluationInputContractError("NULL_KEY", "date/code must not be null")
    code_col = df["code"]
    if not all(isinstance(v, str) for v in code_col):
        raise EvaluationInputContractError("INVALID_FIELD_TYPE", "code must be str", field_name="code")
    if (code_col.str.strip() == "").any():
        raise EvaluationInputContractError("NULL_KEY", "code must be non-empty string", field_name="code")

    # -- dedup (after date canonicalisation) --
    if df.duplicated(subset=["date", "code"]).any():
        raise EvaluationInputContractError("DUPLICATE_KEY", "duplicate (date, code)")

    # -- numeric price --
    try:
        prices = pd.to_numeric(df[price_col], errors="raise")
    except Exception as e:
        raise EvaluationInputContractError("NON_NUMERIC_VALUE", str(e), field_name=price_col) from e

    finite_mask = prices.notna()
    if finite_mask.any():
        pvals = prices[finite_mask]
        if (pvals == float("inf")).any() or (pvals == float("-inf")).any():
            raise EvaluationInputContractError("INFINITE_VALUE", "price contains Inf", field_name=price_col)
        if (pvals <= 0).any():
            raise EvaluationInputContractError("INVALID_PRICE", "price must be finite positive or missing", field_name=price_col)

    # -- build per-code per-horizon --
    input_rows = len(df)
    rows: list[dict] = []
    for code, grp in df.groupby("code", sort=True):
        grp = grp.sort_values("date")
        price_series = pd.to_numeric(grp[price_col], errors="coerce").values
        dates_arr = grp["date"].values
        code_arr = grp["code"].values
        n = len(grp)
        for h in sorted(set(hlist)):
            for i in range(n):
                p0 = price_series[i]
                if pd.isna(p0) or p0 <= 0:
                    fr = np.nan
                elif i + h < n:
                    p1 = price_series[i + h]
                    if pd.isna(p1) or p1 <= 0:
                        fr = np.nan
                    else:
                        fr = float(p1 / p0 - 1.0)
                else:
                    fr = np.nan
                rows.append({"date": str(dates_arr[i]), "code": str(code_arr[i]), "horizon": h, "forward_return": fr})

    out = pd.DataFrame(rows)
    out = out.sort_values(["date", "code", "horizon"]).reset_index(drop=True)
    return _build_result(return_set_id, version, source, out, frequency, universe, price_col, hlist, input_rows, len(out))


def _build_result(return_set_id, version, source, out, frequency, universe, price_col, hlist, in_rows, out_rows):
    return ForwardReturnBatch(
        return_set_id=return_set_id,
        value_scope=ValueScope.SECURITY_LEVEL,
        version=version,
        source=source,
        return_definition="close_to_close_observation_horizon",
        _frame=out,
        frequency=frequency,
        universe=universe,
        provenance={
            "method_version": "1.0",
            "price_col": price_col,
            "horizons": sorted(set(hlist)),
            "horizon_semantics": "close[t+h]/close[t]-1 per code, h=observation steps forward",
            "input_row_count": in_rows,
            "output_row_count": out_rows,
        },
    )
