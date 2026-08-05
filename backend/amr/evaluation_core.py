"""P0-4B-STEP4: Core IC evaluation with quantile return integration."""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from .evaluation_alignment import AlignedEvaluationData, AlignmentReport, GateResult, GateStatus
from .evaluation_group_returns import (
    DailyGroupReturnResult,
    evaluate_group_returns,
    validate_quantiles,
)
from .evaluation_stability import ICStabilityResult, evaluate_ic_stability
from .evaluation_statistics import hac_t_stat


class EvaluationStatus(str, Enum):
    COMPLETED = "completed"; PARTIAL = "partial"; NOT_RUN = "not_run"; NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class DailyICResult:
    date: str; sample_size: int; rank_ic: float | None; pearson_ic: float | None
    evaluated: bool; issue_codes: list[str] = field(default_factory=list)
    def __post_init__(self): object.__setattr__(self, "issue_codes", list(self.issue_codes))
    def to_dict(self): return {"date": self.date, "sample_size": self.sample_size, "rank_ic": self.rank_ic, "pearson_ic": self.pearson_ic, "evaluated": self.evaluated, "issue_codes": list(self.issue_codes)}


@dataclass(frozen=True)
class SecurityLevelEvaluationResult:
    factor_id: str; return_set_id: str | None; horizon: str | None
    factor_type: str; value_scope: str; overall_status: EvaluationStatus
    rank_ic_mean: float | None = None; rank_ic_std: float | None = None; rank_ic_ir: float | None = None
    rank_ic_t_stat: float | None = None; rank_ic_positive_ratio: float | None = None
    pearson_ic_mean: float | None = None; pearson_ic_std: float | None = None; pearson_ic_ir: float | None = None
    pearson_ic_t_stat: float | None = None; pearson_ic_positive_ratio: float | None = None
    rank_ic_stability: ICStabilityResult | None = None
    pearson_ic_stability: ICStabilityResult | None = None
    quantiles: int = 5; quantile_returns: dict[str, float] = field(default_factory=dict)
    long_short_mean: float | None = None; monotonicity_spearman: float | None = None
    daily_group_returns: list[DailyGroupReturnResult] = field(default_factory=list)
    group_return_issue_codes: list[str] = field(default_factory=list)
    total_dates: int = 0; evaluated_dates: int = 0; excluded_dates: int = 0; total_observations: int = 0
    daily_results: list[DailyICResult] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)
    gate_status: str | None = None; gate_issue_codes: list[str] = field(default_factory=list)
    def __post_init__(self):
        object.__setattr__(self, "quantile_returns", dict(self.quantile_returns))
        for a in ("daily_group_returns", "group_return_issue_codes", "daily_results", "issue_codes", "gate_issue_codes"): object.__setattr__(self, a, list(getattr(self, a)))
    def to_dict(self):
        return {
            "factor_id": self.factor_id,
            "return_set_id": self.return_set_id,
            "horizon": self.horizon,
            "factor_type": self.factor_type,
            "value_scope": self.value_scope,
            "overall_status": self.overall_status.value,
            "rank_ic_mean": self.rank_ic_mean,
            "rank_ic_std": self.rank_ic_std,
            "rank_ic_ir": self.rank_ic_ir,
            "rank_ic_t_stat": self.rank_ic_t_stat,
            "rank_ic_positive_ratio": self.rank_ic_positive_ratio,
            "pearson_ic_mean": self.pearson_ic_mean,
            "pearson_ic_std": self.pearson_ic_std,
            "pearson_ic_ir": self.pearson_ic_ir,
            "pearson_ic_t_stat": self.pearson_ic_t_stat,
            "pearson_ic_positive_ratio": self.pearson_ic_positive_ratio,
            "rank_ic_stability": (
                self.rank_ic_stability.to_dict()
                if self.rank_ic_stability is not None
                else None
            ),
            "pearson_ic_stability": (
                self.pearson_ic_stability.to_dict()
                if self.pearson_ic_stability is not None
                else None
            ),
            "quantiles": self.quantiles,
            "quantile_returns": dict(self.quantile_returns),
            "long_short_mean": self.long_short_mean,
            "monotonicity_spearman": self.monotonicity_spearman,
            "daily_group_returns": [d.to_dict() for d in self.daily_group_returns],
            "group_return_issue_codes": list(self.group_return_issue_codes),
            "total_dates": self.total_dates,
            "evaluated_dates": self.evaluated_dates,
            "excluded_dates": self.excluded_dates,
            "total_observations": self.total_observations,
            "daily_results": [d.to_dict() for d in self.daily_results],
            "issue_codes": list(self.issue_codes),
            "gate_status": self.gate_status,
            "gate_issue_codes": list(self.gate_issue_codes),
        }


def _nanmean(s): s2 = s.dropna(); return float(s2.mean()) if len(s2) > 0 else None
def _nanstd(s): s2 = s.dropna(); return float(s2.std(ddof=1)) if len(s2) > 1 else None
def _safe_ratio(a, b): return None if (b is None or b == 0 or a is None) else float(a) / float(b)
def _nunique(s): return int(s.dropna().nunique())
def _is_near_zero(v: float) -> bool: return math.isclose(v, 0.0, rel_tol=0.0, abs_tol=1e-12)


def evaluate_price_volume_security_level(
    aligned,
    alignment_report,
    gate_result,
    *,
    min_cross_section_size=5,
    quantiles=5,
    stability_window=60,
    stability_step=20,
):
    quantile_count = validate_quantiles(quantiles)
    fid = alignment_report.factor_id
    if gate_result.factor_id != fid: return _not_run(fid, alignment_report, "FACTOR_ID_MISMATCH", gate_result, quantile_count)
    if aligned is not None and aligned.factor_id != fid: return _not_run(fid, alignment_report, "FACTOR_ID_MISMATCH_ALIGNED", gate_result, quantile_count)
    if aligned is not None and aligned.return_set_id != alignment_report.return_set_id: return _not_run(fid, alignment_report, "RETURN_SET_ID_MISMATCH", gate_result, quantile_count)
    if aligned is not None and aligned.horizon != alignment_report.horizon: return _not_run(fid, alignment_report, "HORIZON_MISMATCH", gate_result, quantile_count)
    if alignment_report.factor_type not in ("price_volume",): return _not_applicable(fid, alignment_report, f"factor_type={alignment_report.factor_type}", gate_result, quantile_count)
    if alignment_report.value_scope not in ("security_level",): return _not_applicable(fid, alignment_report, f"value_scope={alignment_report.value_scope}", gate_result, quantile_count)
    gs = gate_result.overall_status; gate_codes = [e.code for e in gate_result.errors] + [w.code for w in gate_result.warnings]
    if gs in (GateStatus.BLOCKED, GateStatus.NOT_RUN): return _not_run(fid, alignment_report, f"gate_status={gs.value}", gate_result, quantile_count)
    if aligned is None or aligned.get_valid_frame().empty: return _not_run(fid, alignment_report, "NO_ALIGNED_DATA", gate_result, quantile_count)

    df = aligned.get_valid_frame()
    daily_results = []; excluded_count = 0; total_obs = 0; rank_ics = []; pearson_ics = []

    for date_val, grp in df.groupby("date", sort=True):
        ds = str(date_val); fv = grp["factor_value"].astype(float); fr = grp["forward_return"].astype(float)
        valid = fv.notna() & fr.notna() & np.isfinite(fv) & np.isfinite(fr)
        sfv = fv[valid]; sfr = fr[valid]; n = len(sfv)
        codes = []; r_ic = None; p_ic = None; ev = True
        if n < min_cross_section_size: codes.append("INSUFFICIENT_CROSS_SECTION"); ev = False
        elif _nunique(sfv) <= 1: codes.append("CONSTANT_FACTOR_CROSS_SECTION"); ev = False
        elif _nunique(sfr) <= 1: codes.append("CONSTANT_RETURN_CROSS_SECTION"); ev = False
        else:
            try: r = spearmanr(sfv, sfr); r_ic = float(r.correlation) if np.isfinite(r.correlation) else None
            except Exception: r_ic = None; codes.append("SPEARMAN_ERROR")
            if r_ic is None and "SPEARMAN_ERROR" not in codes: codes.append("NONFINITE_RANK_IC")
            try: p = pearsonr(sfv, sfr); p_ic = float(p.statistic) if np.isfinite(p.statistic) else None
            except Exception: p_ic = None; codes.append("PEARSON_ERROR")
            if p_ic is None and "PEARSON_ERROR" not in codes: codes.append("NONFINITE_PEARSON_IC")
            if r_ic is None and p_ic is None: ev = False; codes.append("NO_VALID_IC_FOR_DATE")
            else:
                if r_ic is not None: rank_ics.append(r_ic)
                if p_ic is not None: pearson_ics.append(p_ic)
        if not ev: excluded_count += 1
        total_obs += n
        daily_results.append(DailyICResult(date=ds, sample_size=n, rank_ic=r_ic, pearson_ic=p_ic, evaluated=ev, issue_codes=codes))

    r_mean = _nanmean(pd.Series(rank_ics)); r_std = _nanstd(pd.Series(rank_ics)); r_ir = _safe_ratio(r_mean, r_std)
    r_pos = _nanmean(pd.Series([1.0 if v > 0 else 0.0 for v in rank_ics])) if rank_ics else None
    p_mean = _nanmean(pd.Series(pearson_ics)); p_std = _nanstd(pd.Series(pearson_ics)); p_ir = _safe_ratio(p_mean, p_std)
    p_pos = _nanmean(pd.Series([1.0 if v > 0 else 0.0 for v in pearson_ics])) if pearson_ics else None
    daily_dates = [daily.date for daily in daily_results]
    rank_stability = evaluate_ic_stability(
        daily_dates,
        [daily.rank_ic for daily in daily_results],
        window=stability_window,
        step=stability_step,
    )
    pearson_stability = evaluate_ic_stability(
        daily_dates,
        [daily.pearson_ic for daily in daily_results],
        window=stability_window,
        step=stability_step,
    )
    r_t_stat = hac_t_stat(rank_ics)
    p_t_stat = hac_t_stat(pearson_ics)
    group_summary = evaluate_group_returns(df, quantiles=quantile_count)

    td = len(daily_results); ed = td - excluded_count; issues = []
    if ed == 0: overall = EvaluationStatus.NOT_RUN; issues.append("NO_EVALUATED_DATES")
    elif excluded_count > 0: overall = EvaluationStatus.PARTIAL
    elif ed == 1: overall = EvaluationStatus.COMPLETED; issues.append("INSUFFICIENT_DATES_FOR_DISPERSION")
    else: overall = EvaluationStatus.COMPLETED

    if r_std is not None and _is_near_zero(r_std): issues.append("ZERO_RANK_IC_VARIANCE"); r_ir = None
    if p_std is not None and _is_near_zero(p_std): issues.append("ZERO_PEARSON_IC_VARIANCE"); p_ir = None

    return SecurityLevelEvaluationResult(factor_id=fid, return_set_id=alignment_report.return_set_id, horizon=alignment_report.horizon, factor_type=alignment_report.factor_type, value_scope=alignment_report.value_scope, overall_status=overall, rank_ic_mean=r_mean, rank_ic_std=r_std, rank_ic_ir=r_ir, rank_ic_t_stat=r_t_stat, rank_ic_positive_ratio=r_pos, pearson_ic_mean=p_mean, pearson_ic_std=p_std, pearson_ic_ir=p_ir, pearson_ic_t_stat=p_t_stat, pearson_ic_positive_ratio=p_pos, rank_ic_stability=rank_stability, pearson_ic_stability=pearson_stability, quantiles=group_summary.quantiles, quantile_returns=group_summary.quantile_returns, long_short_mean=group_summary.long_short_mean, monotonicity_spearman=group_summary.monotonicity_spearman, daily_group_returns=group_summary.daily_group_returns, group_return_issue_codes=group_summary.issue_codes, total_dates=td, evaluated_dates=ed, excluded_dates=excluded_count, total_observations=total_obs, daily_results=daily_results, issue_codes=issues, gate_status=gs.value, gate_issue_codes=gate_codes)


def _not_run(fid, rep, reason, gate, quantiles=5):
    return SecurityLevelEvaluationResult(factor_id=fid, return_set_id=rep.return_set_id, horizon=rep.horizon, factor_type=rep.factor_type, value_scope=rep.value_scope, overall_status=EvaluationStatus.NOT_RUN, quantiles=quantiles, issue_codes=[reason], gate_status=gate.overall_status.value, gate_issue_codes=[e.code for e in gate.errors] + [w.code for w in gate.warnings])

def _not_applicable(fid, rep, reason, gate, quantiles=5):
    return SecurityLevelEvaluationResult(factor_id=fid, return_set_id=rep.return_set_id, horizon=rep.horizon, factor_type=rep.factor_type, value_scope=rep.value_scope, overall_status=EvaluationStatus.NOT_APPLICABLE, quantiles=quantiles, issue_codes=[reason], gate_status=gate.overall_status.value, gate_issue_codes=[e.code for e in gate.errors] + [w.code for w in gate.warnings])
