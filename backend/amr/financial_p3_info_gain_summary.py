"""INFO-GAIN-05: deterministic three-track status summary, without a decision."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from backend.amr.financial_p3_info_gain_coverage import CoverageResult
from backend.amr.financial_p3_info_gain_f_comparisons import FInfoGainResult
from backend.amr.financial_p3_info_gain_m_comparisons import MInfoGainResult
from backend.amr.financial_p3_info_gain_r_comparisons import RInfoGainResult

M_FP="aa32f025ae82886060f1c7dae45e6140a96ff2c8d984bda6db8b40c325b1784a";F_FP="04998ae6e9bfda4fa0182b24d902d556879b438169438beacf67055997f77825";R_FP="effd4f7028d98ced2b98fc2131a69d4f80975bde1be0a393d725141fb1cd5e95";COVERAGE_FP="2f5ec56afef1cbe87805c6e04747d2048065808447b07a0ea91782b3b5809be3"
@dataclass(frozen=True)
class InfoGainSummaryConfig:
 run_id:str;accepted_m_fingerprint:str=M_FP;accepted_f_fingerprint:str=F_FP;accepted_r_fingerprint:str=R_FP;accepted_coverage_fingerprint:str=COVERAGE_FP;synthetic_test_only:bool=True
 def __post_init__(self):
  if not isinstance(self.run_id,str) or not self.run_id.strip():raise ValueError("run_id required")
  if (self.accepted_m_fingerprint,self.accepted_f_fingerprint,self.accepted_r_fingerprint,self.accepted_coverage_fingerprint)!=(M_FP,F_FP,R_FP,COVERAGE_FP):raise ValueError("accepted predecessor fingerprint drifted")
  if self.synthetic_test_only is not True:raise ValueError("synthetic input only")
@dataclass(frozen=True)
class SummaryIssue:
 code:str;message:str
 def to_dict(self):return {"code":self.code,"message":self.message}
@dataclass(frozen=True)
class TrackSummary:
 track_id:str;evidence_status:str;comparison_count:int;completed_comparison_count:int;not_evaluable_count:int;source_output_fingerprint:str
 def to_dict(self):return {x:getattr(self,x) for x in self.__dataclass_fields__}
@dataclass(frozen=True)
class InfoGainSummaryAudit:
 gate_status:str;errors:tuple[SummaryIssue,...];track_count:int;coverage_combo_count:int;formal_member_coverage_count:int;M_evidence_included:bool;F_evidence_included:bool;R_evidence_included:bool;aggregate_information_gain_assessment_made:bool;cross_track_composite_calculated:bool;strongest_member_selected:bool;production_status:str;input_fingerprint:str;output_fingerprint:str;content_hash:str
 def to_dict(self):return {**{x:getattr(self,x) for x in self.__dataclass_fields__ if x!="errors"},"errors":[x.to_dict() for x in self.errors]}
@dataclass(frozen=True)
class InfoGainSummaryResult:
 tracks:tuple[TrackSummary,...];coverage_status:str;conclusion_boundary:str;audit:InfoGainSummaryAudit
 def to_dict(self):return {"tracks":[x.to_dict() for x in self.tracks],"coverage_status":self.coverage_status,"conclusion_boundary":self.conclusion_boundary,"audit":self.audit.to_dict()}
def summarize_financial_p3_info_gain(m:MInfoGainResult,f:FInfoGainResult,r:RInfoGainResult,coverage:CoverageResult,*,configuration:InfoGainSummaryConfig)->InfoGainSummaryResult:
 if not isinstance(m,MInfoGainResult) or not isinstance(f,FInfoGainResult) or not isinstance(r,RInfoGainResult) or not isinstance(coverage,CoverageResult):raise TypeError("M, F, R, and coverage results are required")
 if not isinstance(configuration,InfoGainSummaryConfig):raise TypeError("configuration must be InfoGainSummaryConfig")
 errors=[]
 for label,result,expected in (("M",m,M_FP),("F",f,F_FP),("R",r,R_FP),("COVERAGE",coverage,COVERAGE_FP)):
  if result.audit.gate_status!="ready" or result.audit.output_fingerprint!=expected:errors.append(SummaryIssue(f"{label}_PREDECESSOR_DRIFT",f"accepted {label} predecessor is not ready or drifted"))
 if coverage.audit.combo_count!=3 or coverage.audit.member_coverage_count!=11:errors.append(SummaryIssue("COVERAGE_SCOPE_INVALID","coverage must report three combinations and eleven formal members"))
 tracks=(TrackSummary("M","pairwise_metrics_available",m.audit.comparison_count,m.audit.completed_comparison_count,m.audit.not_evaluable_count,m.audit.output_fingerprint),TrackSummary("F","not_evaluable_context_not_frozen",f.audit.comparison_count,0,f.audit.not_evaluable_count,f.audit.output_fingerprint),TrackSummary("R","not_evaluable_context_not_frozen",r.audit.comparison_count,0,r.audit.not_evaluable_count,r.audit.output_fingerprint))
 return _result(tracks,coverage,errors,m,f,r)
def _result(tracks,coverage,errors,m,f,r):
 gate="ready" if not errors else "blocked";boundary="Three-track status summary only: M contains accepted pairwise common-sample metric increments; F and R remain not_evaluable because their contexts are not frozen. Coverage cost is reported separately. No aggregate information-gain assessment, cross-track composite, strongest-member selection, admission, production, fraud, or trading conclusion is made."
 input_fp=_hash("p3_info_gain_05_inputs",{"M":m.audit.output_fingerprint,"F":f.audit.output_fingerprint,"R":r.audit.output_fingerprint,"coverage":coverage.audit.output_fingerprint});output_fp=_hash("p3_info_gain_05_output",[x.to_dict() for x in tracks]);payload={"gate_status":gate,"errors":[x.to_dict() for x in errors],"track_count":len(tracks),"coverage_combo_count":coverage.audit.combo_count,"formal_member_coverage_count":coverage.audit.member_coverage_count,"M_evidence_included":True,"F_evidence_included":True,"R_evidence_included":True,"aggregate_information_gain_assessment_made":False,"cross_track_composite_calculated":False,"strongest_member_selected":False,"production_status":"not production ready","input_fingerprint":input_fp,"output_fingerprint":output_fp};return InfoGainSummaryResult(tracks,"reported_without_acceptance_threshold",boundary,InfoGainSummaryAudit(**{**payload,"errors":tuple(errors),"content_hash":_hash("p3_info_gain_05_audit",payload)}))
def serialize_financial_p3_info_gain_summary(result:InfoGainSummaryResult)->str:
 if not isinstance(result,InfoGainSummaryResult):raise TypeError("result must be InfoGainSummaryResult")
 return json.dumps(_canon(result.to_dict()),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _canon(v):
 if isinstance(v,Mapping):return {str(k):_canon(x) for k,x in sorted(v.items(),key=lambda x:str(x[0]))}
 if isinstance(v,(list,tuple)):return [_canon(x) for x in v]
 if v is None or isinstance(v,(str,bool,int)):return v
 if isinstance(v,(float,np.floating)):return float(v) if math.isfinite(float(v)) else None
 if isinstance(v,np.integer):return int(v)
 raise TypeError(type(v).__name__)
def _hash(domain,value):return hashlib.sha256(json.dumps({"domain":domain,"value":_canon(value)},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
