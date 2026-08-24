"""INFO-GAIN-04: report frozen common-sample coverage cost without selection."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from backend.amr.financial_p3_combinations import FinancialP3CombinationsResult
from backend.amr.financial_p3_info_gain_inputs import InfoGainInputPreparationResult

COMBO_FP="73f37667bbb7323cee65dfd89b16a31109f3bd2bc4e65e775dcf37e47a2195d8";INPUT_FP="1599c601f11da9d67adf7d538f80fe75488ac2481c0794678d6660589ea1c48e";ORDER=("VQ","QG","CASHQ")
@dataclass(frozen=True)
class CoverageConfig:
 run_id:str;accepted_combination_fingerprint:str=COMBO_FP;accepted_input_fingerprint:str=INPUT_FP;synthetic_test_only:bool=True
 def __post_init__(self):
  if not isinstance(self.run_id,str) or not self.run_id.strip():raise ValueError("run_id required")
  if self.accepted_combination_fingerprint!=COMBO_FP or self.accepted_input_fingerprint!=INPUT_FP:raise ValueError("accepted predecessor fingerprint drifted")
  if self.synthetic_test_only is not True:raise ValueError("synthetic input only")
@dataclass(frozen=True)
class CoverageIssue:
 code:str;message:str;combo_id:str|None=None
 def to_dict(self):return {x:getattr(self,x) for x in self.__dataclass_fields__}
@dataclass(frozen=True)
class MemberCoverage:
 member_factor_id:str;original_evaluable_sample_count:int;original_coverage_ratio:float;common_sample_count:int;common_sample_coverage_ratio:float;absolute_coverage_loss:int;relative_coverage_loss:float
 def to_dict(self):return {x:getattr(self,x) for x in self.__dataclass_fields__}
@dataclass(frozen=True)
class ComboCoverage:
 combo_id:str;eligible_sample_count:int;common_sample_count:int;common_sample_coverage_ratio:float;member_coverages:tuple[MemberCoverage,...];per_period_common_counts:tuple[tuple[str,int],...];insufficient_sample_periods:tuple[str,...];exclusion_reason_categories:tuple[str,...];content_hash:str
 def to_dict(self):return {"combo_id":self.combo_id,"eligible_sample_count":self.eligible_sample_count,"common_sample_count":self.common_sample_count,"common_sample_coverage_ratio":self.common_sample_coverage_ratio,"member_coverages":[x.to_dict() for x in self.member_coverages],"per_period_common_counts":[{"evaluation_date":d,"count":n} for d,n in self.per_period_common_counts],"insufficient_sample_periods":list(self.insufficient_sample_periods),"exclusion_reason_categories":list(self.exclusion_reason_categories),"content_hash":self.content_hash}
@dataclass(frozen=True)
class CoverageAudit:
 gate_status:str;errors:tuple[CoverageIssue,...];combo_count:int;member_coverage_count:int;exact_common_samples_verified:bool;sample_reconstructed:bool;combination_removed_for_coverage:bool;information_gain_assessment_made:bool;input_fingerprint:str;output_fingerprint:str;production_status:str;content_hash:str
 def to_dict(self):return {**{x:getattr(self,x) for x in self.__dataclass_fields__ if x!="errors"},"errors":[x.to_dict() for x in self.errors]}
@dataclass(frozen=True)
class CoverageResult:
 combos:tuple[ComboCoverage,...];audit:CoverageAudit
 def to_dict(self):return {"combos":[x.to_dict() for x in self.combos],"audit":self.audit.to_dict()}
def report_financial_p3_info_gain_coverage(combos:FinancialP3CombinationsResult,inputs:InfoGainInputPreparationResult,*,configuration:CoverageConfig)->CoverageResult:
 if not isinstance(combos,FinancialP3CombinationsResult):raise TypeError("combos must be FinancialP3CombinationsResult")
 if not isinstance(inputs,InfoGainInputPreparationResult):raise TypeError("inputs must be InfoGainInputPreparationResult")
 if not isinstance(configuration,CoverageConfig):raise TypeError("configuration must be CoverageConfig")
 errors=[]
 if combos.combinations_audit.gate_status!="ready" or combos.combinations_audit.output_fingerprint!=configuration.accepted_combination_fingerprint:errors.append(CoverageIssue("COMBOS_NOT_ACCEPTED",f"accepted COMBOS output drifted: expected={configuration.accepted_combination_fingerprint}, actual={combos.combinations_audit.output_fingerprint}"))
 if inputs.audit.gate_status!="ready" or inputs.audit.output_fingerprint!=configuration.accepted_input_fingerprint:errors.append(CoverageIssue("INPUTS_NOT_ACCEPTED","accepted 02A output drifted"))
 if tuple(x.definition.combination_id for x in combos.experiments)!=ORDER or tuple(x.combo_id for x in inputs.packages)!=ORDER:errors.append(CoverageIssue("COMBO_ORDER_MISMATCH","VQ,QG,CASHQ required"))
 reports=[]
 if not errors:
  packages={x.combo_id:x for x in inputs.packages}
  for e in combos.experiments:
   p=packages[e.definition.combination_id];a=e.construction_audit;eligible=a.eligible_sample_size;common=p.common_sample_row_count
   if common!=900 or p.evaluation_period_count!=18 or e.comparison.common_sample_fingerprint!=p.common_sample_fingerprint:errors.append(CoverageIssue("COMMON_SAMPLE_DRIFT","common sample must remain frozen",p.combo_id));continue
   members=[]
   expected_members={member for member,_ in p.member_directions}
   for c in a.constituent_coverage:
    if c.factor_id not in expected_members: continue
    original=c.available_observation_count;loss=original-common;members.append(MemberCoverage(c.factor_id,original,original/eligible,common,common/eligible,loss,loss/original if original else 0.0))
   per=p.per_period_row_counts;insufficient=tuple(d for d,n in per if n<30);payload={"combo_id":p.combo_id,"eligible_sample_count":eligible,"common_sample_count":common,"common_sample_coverage_ratio":common/eligible,"member_coverages":[x.to_dict() for x in members],"per_period_common_counts":list(per),"insufficient_sample_periods":list(insufficient),"exclusion_reason_categories":["common_sample_gate_eligibility","all_combo_members_jointly_available"]}
   reports.append(ComboCoverage(p.combo_id,eligible,common,common/eligible,tuple(members),per,insufficient,("common_sample_gate_eligibility","all_combo_members_jointly_available"),_hash("p3_info_gain_04_combo",payload)))
 return _result(tuple(reports),tuple(errors),combos,inputs)
def _result(reports,errors,combos,inputs):
 gate="ready" if not errors and len(reports)==3 else "blocked";out=_hash("p3_info_gain_04_output",[x.to_dict() for x in reports]);payload={"gate_status":gate,"errors":[x.to_dict() for x in errors],"combo_count":len(reports),"member_coverage_count":sum(len(x.member_coverages) for x in reports),"exact_common_samples_verified":gate=="ready","sample_reconstructed":False,"combination_removed_for_coverage":False,"information_gain_assessment_made":False,"input_fingerprint":_hash("p3_info_gain_04_inputs",{"combos":combos.combinations_audit.output_fingerprint,"inputs":inputs.audit.output_fingerprint}),"output_fingerprint":out,"production_status":"not production ready"};return CoverageResult(reports,CoverageAudit(**{**payload,"errors":errors,"content_hash":_hash("p3_info_gain_04_audit",payload)}))
def serialize_coverage_result(result):
 if not isinstance(result,CoverageResult):raise TypeError("result must be CoverageResult")
 return json.dumps(_canon(result.to_dict()),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _canon(v):
 if isinstance(v,Mapping):return {str(k):_canon(x) for k,x in sorted(v.items(),key=lambda x:str(x[0]))}
 if isinstance(v,(list,tuple)):return [_canon(x) for x in v]
 if v is None or isinstance(v,(str,bool,int)):return v
 if isinstance(v,(float,np.floating)):return float(v) if math.isfinite(float(v)) else None
 if isinstance(v,np.integer):return int(v)
 raise TypeError(type(v).__name__)
def _hash(domain,value):return hashlib.sha256(json.dumps({"domain":domain,"value":_canon(value)},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
