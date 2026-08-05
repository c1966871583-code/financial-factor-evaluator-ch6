"""INFO-GAIN-03C: formal R-track combo/member comparison availability."""
from __future__ import annotations
import hashlib,json,math
from dataclasses import dataclass
from typing import Any,Mapping
import numpy as np
from backend.amr.financial_p3_combinations import FinancialP3CombinationsResult
from backend.amr.financial_p3_info_gain_r_member_baselines import RMemberBaselineResult
COMBO_FP="7c8686b44f3842f159b3fbbc45aa9908f3bf81acd5ebec381f8ac4f5c1933fa2";MEMBER_FP="91ead71b3767a31ad0fb23cdff91c9c6372a8d77bbd68d552b23ebc4cf7a2e2e";CONTRACT_HASH="e6d51313ae0fb326d4b239dbb3aefe542c8d5d623237b05e7678959436766747";ORDER=("VQ","QG","CASHQ");METRICS=("pr_auc","roc_auc","brier_score","top_k_hit_rate","expected_calibration_error")
@dataclass(frozen=True)
class RInfoGainComparisonConfig:
 run_id:str;accepted_combination_fingerprint:str=COMBO_FP;accepted_member_fingerprint:str=MEMBER_FP;accepted_contract_hash:str=CONTRACT_HASH;synthetic_test_only:bool=True
 def __post_init__(self):
  if not isinstance(self.run_id,str) or not self.run_id.strip():raise ValueError("run_id required")
  if self.accepted_combination_fingerprint!=COMBO_FP or self.accepted_member_fingerprint!=MEMBER_FP or self.accepted_contract_hash!=CONTRACT_HASH:raise ValueError("accepted predecessor fingerprint/hash drifted")
  if self.synthetic_test_only is not True:raise ValueError("synthetic input only")
@dataclass(frozen=True)
class RInfoGainIssue:
 code:str;message:str;combo_id:str|None=None
 def to_dict(self):return {x:getattr(self,x) for x in self.__dataclass_fields__}
@dataclass(frozen=True)
class RMetricComparison:
 combo_id:str;member_factor_id:str;metric_id:str;combo_metric_value:None;member_metric_value:None;calculation_status:str;reason_code:str
 def to_dict(self):return {x:getattr(self,x) for x in self.__dataclass_fields__}
@dataclass(frozen=True)
class RInfoGainAudit:
 gate_status:str;errors:tuple[RInfoGainIssue,...];combo_count:int;member_count:int;comparison_count:int;not_evaluable_count:int;combo_results_recomputed:bool;member_results_recomputed:bool;R_evaluator_called:bool;risk_labels_constructed:bool;strongest_member_selected:bool;information_gain_assessment_made:bool;input_fingerprint:str;output_fingerprint:str;production_status:str;conclusion_boundary:str;content_hash:str
 def to_dict(self):return {**{x:getattr(self,x) for x in self.__dataclass_fields__ if x!="errors"},"errors":[x.to_dict() for x in self.errors]}
@dataclass(frozen=True)
class RInfoGainResult:
 comparisons:tuple[RMetricComparison,...];audit:RInfoGainAudit
 def to_dict(self):return {"comparisons":[x.to_dict() for x in self.comparisons],"audit":self.audit.to_dict()}
def compare_financial_p3_info_gain_r(combos:FinancialP3CombinationsResult,members:RMemberBaselineResult,*,configuration:RInfoGainComparisonConfig)->RInfoGainResult:
 if not isinstance(combos,FinancialP3CombinationsResult):raise TypeError("combos must be FinancialP3CombinationsResult")
 if not isinstance(members,RMemberBaselineResult):raise TypeError("members must be RMemberBaselineResult")
 if not isinstance(configuration,RInfoGainComparisonConfig):raise TypeError("configuration must be RInfoGainComparisonConfig")
 errors=[]
 if combos.combinations_audit.gate_status!="ready" or combos.combinations_audit.output_fingerprint!=configuration.accepted_combination_fingerprint:errors.append(RInfoGainIssue("COMBOS_NOT_ACCEPTED","accepted COMBOS output drifted"))
 if members.audit.gate_status!="ready" or members.audit.output_fingerprint!=configuration.accepted_member_fingerprint:errors.append(RInfoGainIssue("R_MEMBER_BASELINES_NOT_ACCEPTED","accepted 02D output drifted"))
 if tuple(x.definition.combination_id for x in combos.experiments)!=ORDER or tuple(x.combo_id for x in members.bundles)!=ORDER:errors.append(RInfoGainIssue("COMBO_ORDER_MISMATCH","VQ,QG,CASHQ required"))
 rows=[]
 if not errors:
  for bundle in members.bundles:
   if bundle.calculation_status!="not_run":errors.append(RInfoGainIssue("R_MEMBER_CONTEXT_DRIFT","R members must remain not_run",bundle.combo_id));continue
   for run in bundle.member_runs:
    for metric in METRICS:rows.append(RMetricComparison(bundle.combo_id,run.member_factor_id,metric,None,None,"not_evaluable","R_COMBO_AND_MEMBER_CONTEXT_NOT_FROZEN"))
 return _result(tuple(rows),tuple(errors),combos,members)
def _result(rows,errors,combos,members):
 gate="ready" if not errors and len(rows)==55 else "blocked";out=_hash("p3_info_gain_03c_output",[x.to_dict() for x in rows]);payload={"gate_status":gate,"errors":[x.to_dict() for x in errors],"combo_count":3 if gate=="ready" else 0,"member_count":11 if gate=="ready" else 0,"comparison_count":len(rows),"not_evaluable_count":len(rows),"combo_results_recomputed":False,"member_results_recomputed":False,"R_evaluator_called":False,"risk_labels_constructed":False,"strongest_member_selected":False,"information_gain_assessment_made":False,"input_fingerprint":_hash("p3_info_gain_03c_inputs",{"combos":combos.combinations_audit.output_fingerprint,"members":members.audit.output_fingerprint}),"output_fingerprint":out,"production_status":"not production ready","conclusion_boundary":"Formal R-track not_evaluable comparisons only; no risk-label construction, R evaluator call, fraud/misstatement determination, strongest-member selection, aggregate information-gain assessment, admission, production, or trading conclusion."};return RInfoGainResult(rows,RInfoGainAudit(**{**payload,"errors":errors,"content_hash":_hash("p3_info_gain_03c_audit",payload)}))
def serialize_r_info_gain_result(result):
 if not isinstance(result,RInfoGainResult):raise TypeError("result must be RInfoGainResult")
 return json.dumps(_canon(result.to_dict()),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _canon(v):
 if isinstance(v,Mapping):return {str(k):_canon(x) for k,x in sorted(v.items(),key=lambda x:str(x[0]))}
 if isinstance(v,(list,tuple)):return [_canon(x) for x in v]
 if v is None or isinstance(v,(str,bool,int)):return v
 if isinstance(v,(float,np.floating)):return float(v) if math.isfinite(float(v)) else None
 if isinstance(v,np.integer):return int(v)
 raise TypeError(type(v).__name__)
def _hash(domain,value):return hashlib.sha256(json.dumps({"domain":domain,"value":_canon(value)},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
