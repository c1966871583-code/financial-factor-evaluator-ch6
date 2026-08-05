"""INFO-GAIN-03A: M-track combo-to-each-member comparisons on frozen output."""
from __future__ import annotations
import hashlib,json,math
from dataclasses import dataclass
from typing import Any,Mapping
import numpy as np
from backend.amr.financial_p3_combinations import FinancialP3CombinationsResult
from backend.amr.financial_p3_info_gain_m_member_baselines import MMemberBaselineResult

COMBO_FP="7c8686b44f3842f159b3fbbc45aa9908f3bf81acd5ebec381f8ac4f5c1933fa2"
MEMBER_FP="2a92a8b8896c4dc153853e0bf23c3c1dd950747d7552dd2ca5373480fe541970"
CONTRACT_HASH="e6d51313ae0fb326d4b239dbb3aefe542c8d5d623237b05e7678959436766747"
ORDER=("VQ","QG","CASHQ")
METRICS=("rank_ic_mean","pearson_ic_mean","rank_ic_ir","pearson_ic_ir","rank_ic_hac_t_stat","pearson_ic_hac_t_stat","rank_ic_positive_ratio","pearson_ic_positive_ratio","quantile_returns","long_short_mean","monotonicity_spearman","fm_mean_r2","rank_ic_rolling_stability")
COMMON={"rank_ic_mean":("mean_rank_ic","rank_ic_mean","higher"),"rank_ic_ir":("icir","rank_ic_ir","higher"),"rank_ic_positive_ratio":("positive_ic_ratio","rank_ic_positive_ratio","higher"),"quantile_returns":("group_returns","quantile_returns","detail_only"),"long_short_mean":("long_short_spread","long_short_mean","higher"),"monotonicity_spearman":("monotonicity","monotonicity_spearman","higher")}

@dataclass(frozen=True)
class MInfoGainComparisonConfig:
 run_id:str; accepted_combination_fingerprint:str=COMBO_FP; accepted_member_fingerprint:str=MEMBER_FP; accepted_contract_hash:str=CONTRACT_HASH; synthetic_test_only:bool=True
 def __post_init__(self):
  if not isinstance(self.run_id,str) or not self.run_id.strip(): raise ValueError("run_id required")
  if self.accepted_combination_fingerprint!=COMBO_FP or self.accepted_member_fingerprint!=MEMBER_FP or self.accepted_contract_hash!=CONTRACT_HASH: raise ValueError("accepted predecessor fingerprint/hash drifted")
  if self.synthetic_test_only is not True: raise ValueError("synthetic input only")

@dataclass(frozen=True)
class MInfoGainIssue:
 code:str; message:str; combo_id:str|None=None
 def to_dict(self): return {x:getattr(self,x) for x in self.__dataclass_fields__}
@dataclass(frozen=True)
class MMetricIncrement:
 combo_id:str; member_factor_id:str; metric_id:str; combo_metric_value:Any; member_metric_value:Any; absolute_increment:float|None; relative_increment:float|None; calculation_status:str; directional_outcome:str; reason_code:str|None
 def to_dict(self): return {x:getattr(self,x) for x in self.__dataclass_fields__}
@dataclass(frozen=True)
class MComboInformationGain:
 combo_id:str; common_sample_fingerprint:str; member_comparisons:tuple[MMetricIncrement,...]; content_hash:str
 def to_dict(self): return {"combo_id":self.combo_id,"common_sample_fingerprint":self.common_sample_fingerprint,"member_comparisons":[x.to_dict() for x in self.member_comparisons],"content_hash":self.content_hash}
@dataclass(frozen=True)
class MInfoGainAudit:
 gate_status:str; errors:tuple[MInfoGainIssue,...]; combo_count:int; member_count:int; comparison_count:int; completed_comparison_count:int; not_evaluable_count:int; exact_common_samples_verified:bool; combo_results_recomputed:bool; member_results_recomputed:bool; strongest_member_selected:bool; information_gain_assessment_made:bool; input_fingerprint:str; output_fingerprint:str; production_status:str; conclusion_boundary:str; content_hash:str
 def to_dict(self): return {**{x:getattr(self,x) for x in self.__dataclass_fields__ if x!="errors"},"errors":[x.to_dict() for x in self.errors]}
@dataclass(frozen=True)
class MInfoGainResult:
 combinations:tuple[MComboInformationGain,...]; audit:MInfoGainAudit
 def to_dict(self): return {"combinations":[x.to_dict() for x in self.combinations],"audit":self.audit.to_dict()}

def compare_financial_p3_info_gain_m(combinations:FinancialP3CombinationsResult, members:MMemberBaselineResult, *, configuration:MInfoGainComparisonConfig)->MInfoGainResult:
 if not isinstance(combinations,FinancialP3CombinationsResult): raise TypeError("combinations must be FinancialP3CombinationsResult")
 if not isinstance(members,MMemberBaselineResult): raise TypeError("members must be MMemberBaselineResult")
 if not isinstance(configuration,MInfoGainComparisonConfig): raise TypeError("configuration must be MInfoGainComparisonConfig")
 errors=[]
 if combinations.combinations_audit.gate_status!="ready" or combinations.combinations_audit.output_fingerprint!=configuration.accepted_combination_fingerprint: errors.append(MInfoGainIssue("COMBOS_NOT_ACCEPTED","accepted COMBOS output drifted"))
 if members.audit.gate_status!="ready" or members.audit.output_fingerprint!=configuration.accepted_member_fingerprint: errors.append(MInfoGainIssue("MEMBER_BASELINES_NOT_ACCEPTED","accepted 02B output drifted"))
 if tuple(x.definition.combination_id for x in combinations.experiments)!=ORDER or tuple(x.combo_id for x in members.bundles)!=ORDER: errors.append(MInfoGainIssue("COMBO_ORDER_MISMATCH","VQ,QG,CASHQ required"))
 if errors:return _result((),tuple(errors),combinations,members)
 bundles={x.combo_id:x for x in members.bundles}; out=[]
 for experiment in combinations.experiments:
  combo=experiment.definition.combination_id; bundle=bundles[combo]; c=experiment.comparison; cm=c.combined_factor_metrics
  if cm is None or c.evaluation_status!="completed" or c.common_sample_size!=900 or c.common_period_count!=18 or c.common_sample_fingerprint!=bundle.common_sample_fingerprint: errors.append(MInfoGainIssue("COMMON_SAMPLE_OR_COMBO_METRICS_INVALID","combo result is not exact M common-sample evidence",combo)); continue
  rows=[]
  for run in bundle.member_runs:
   if run.calculation_status!="completed" or run.evaluation_result.total_observations!=900 or run.evaluation_result.evaluated_dates!=18: errors.append(MInfoGainIssue("MEMBER_METRICS_INVALID","member baseline is unavailable",combo)); continue
   for metric in METRICS: rows.append(_row(combo,run.member_factor_id,metric,cm,run.evaluation_result))
  payload={"combo_id":combo,"common_sample_fingerprint":c.common_sample_fingerprint,"member_comparisons":[x.to_dict() for x in rows]}
  out.append(MComboInformationGain(combo,c.common_sample_fingerprint,tuple(rows),_hash("p3_info_gain_03a_combo",payload)))
 if errors:return _result(tuple(out),tuple(errors),combinations,members)
 return _result(tuple(out),(),combinations,members)

def _row(combo,member,metric,cm,mr):
 if metric not in COMMON:return MMetricIncrement(combo,member,metric,None,None,None,None,"not_evaluable","not_evaluable","METRIC_NOT_AVAILABLE_ON_BOTH_SIDES")
 ca,ma,direction=COMMON[metric]; cv=getattr(cm,ca); mv=getattr(mr,ma)
 if metric=="quantile_returns": return MMetricIncrement(combo,member,metric,{str(i+1):v for i,v in enumerate(cv)},dict(mv),None,None,"completed","detail_only",None)
 if cv is None or mv is None:return MMetricIncrement(combo,member,metric,cv,mv,None,None,"not_evaluable","not_evaluable","NONFINITE_OR_MISSING")
 inc=float(cv)-float(mv); rel=None if math.isclose(float(mv),0,abs_tol=1e-12) else inc/abs(float(mv))
 return MMetricIncrement(combo,member,metric,float(cv),float(mv),inc,rel,"completed","improved" if inc>0 else "unchanged" if inc==0 else "worse",None)
def _result(items,errors,combos,members):
 rows=tuple(r for x in items for r in x.member_comparisons); completed=sum(r.calculation_status=="completed" for r in rows); not_eval=sum(r.calculation_status=="not_evaluable" for r in rows); gate="ready" if not errors and len(items)==3 else "blocked"; outfp=_hash("p3_info_gain_03a_output",[x.to_dict() for x in items]); payload={"gate_status":gate,"errors":[x.to_dict() for x in errors],"combo_count":len(items),"member_count":sum(len(x.member_comparisons)//len(METRICS) for x in items),"comparison_count":len(rows),"completed_comparison_count":completed,"not_evaluable_count":not_eval,"exact_common_samples_verified":gate=="ready","combo_results_recomputed":False,"member_results_recomputed":False,"strongest_member_selected":False,"information_gain_assessment_made":False,"input_fingerprint":_hash("p3_info_gain_03a_inputs",{"combos":combos.combinations_audit.output_fingerprint,"members":members.audit.output_fingerprint}),"output_fingerprint":outfp,"production_status":"not production ready","conclusion_boundary":"M-track pairwise combo-to-member metric increments only; no strongest-member selection, aggregate information-gain assessment, F/R comparison, admission, production, empirical-return, fraud, or trading conclusion."}; return MInfoGainResult(items,MInfoGainAudit(**{**payload,"errors":errors,"content_hash":_hash("p3_info_gain_03a_audit",payload)}))
def serialize_m_info_gain_result(result):
 if not isinstance(result,MInfoGainResult):raise TypeError("result must be MInfoGainResult")
 return json.dumps(_canon(result.to_dict()),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _canon(v):
 if isinstance(v,Mapping):return {str(k):_canon(x) for k,x in sorted(v.items(),key=lambda p:str(p[0]))}
 if isinstance(v,(list,tuple)):return [_canon(x) for x in v]
 if v is None or isinstance(v,(str,bool,int)):return v
 if isinstance(v,(float,np.floating)):return float(v) if math.isfinite(float(v)) else None
 if isinstance(v,np.integer):return int(v)
 raise TypeError(type(v).__name__)
def _hash(domain,value):return hashlib.sha256(json.dumps({"domain":domain,"value":_canon(value)},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
