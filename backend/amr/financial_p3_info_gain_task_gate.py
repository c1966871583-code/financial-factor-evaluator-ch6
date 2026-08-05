"""INFO-GAIN-07: task-level evidence gate, not an investment or production gate."""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Any
from backend.amr.financial_p3_info_gain_summary import InfoGainSummaryResult
from backend.amr.financial_p3_info_gain_bad_data_gate import BadDataGateResult
SUMMARY_FP="206cf303fb83c7037dedec376e5908b216f229fca3c71ae27710f8511cef7ad2";BAD_DATA_FP="a267d8e44bf0ffd4ce3b6632afaf58ee3ebfc9877da65bf8982e14ecce9f29f2"
@dataclass(frozen=True)
class InfoGainTaskGateConfig:
 run_id:str;accepted_summary_fingerprint:str=SUMMARY_FP;accepted_bad_data_gate_fingerprint:str=BAD_DATA_FP
 def __post_init__(self):
  if not isinstance(self.run_id,str) or not self.run_id.strip():raise ValueError("run_id required")
  if (self.accepted_summary_fingerprint,self.accepted_bad_data_gate_fingerprint)!=(SUMMARY_FP,BAD_DATA_FP):raise ValueError("accepted predecessor fingerprint drifted")
@dataclass(frozen=True)
class TaskGateIssue:
 code:str;message:str
 def to_dict(self):return {"code":self.code,"message":self.message}
@dataclass(frozen=True)
class InfoGainTaskGateResult:
 gate_status:str;research_task_status:str;overall_evidence_assessment:str;admission_status:str;production_status:str;errors:tuple[TaskGateIssue,...];summary_fingerprint:str;bad_data_gate_fingerprint:str;input_fingerprint:str;output_fingerprint:str;content_hash:str
 def to_dict(self):return {**{x:getattr(self,x) for x in self.__dataclass_fields__ if x!="errors"},"errors":[x.to_dict() for x in self.errors]}
def evaluate_financial_p3_info_gain_task_gate(summary:InfoGainSummaryResult,bad_data:BadDataGateResult,*,configuration:InfoGainTaskGateConfig)->InfoGainTaskGateResult:
 if not isinstance(summary,InfoGainSummaryResult) or not isinstance(bad_data,BadDataGateResult):raise TypeError("summary and bad-data gate results are required")
 if not isinstance(configuration,InfoGainTaskGateConfig):raise TypeError("configuration must be InfoGainTaskGateConfig")
 errors=[]
 if summary.audit.gate_status!="ready" or summary.audit.output_fingerprint!=configuration.accepted_summary_fingerprint:errors.append(TaskGateIssue("SUMMARY_PREDECESSOR_DRIFT","INFO-GAIN-05 summary is not accepted"))
 if bad_data.audit.gate_status!="ready" or bad_data.audit.output_fingerprint!=configuration.accepted_bad_data_gate_fingerprint:errors.append(TaskGateIssue("BAD_DATA_GATE_DRIFT","bad-data Gate is not accepted"))
 if summary.audit.production_status!="not production ready" or summary.audit.aggregate_information_gain_assessment_made:errors.append(TaskGateIssue("SUMMARY_BOUNDARY_DRIFT","summary must remain non-production and non-aggregate"))
 if bad_data.audit.failed_case_count or bad_data.audit.silent_zero_fill_detected:errors.append(TaskGateIssue("BAD_DATA_GATE_FAILURE","bad-data cases must pass without zero filling"))
 input_fp=_hash("p3_info_gain_07_inputs",{"summary":summary.audit.output_fingerprint,"bad_data":bad_data.audit.output_fingerprint});gate="accepted" if not errors else "blocked";payload={"gate_status":gate,"research_task_status":"ACCEPTED" if not errors else "BLOCKED","overall_evidence_assessment":"insufficient_evidence","admission_status":"not_assessed","production_status":"not production ready","errors":[x.to_dict() for x in errors],"summary_fingerprint":summary.audit.output_fingerprint,"bad_data_gate_fingerprint":bad_data.audit.output_fingerprint,"input_fingerprint":input_fp};out=_hash("p3_info_gain_07_output",payload);return InfoGainTaskGateResult(**{**payload,"errors":tuple(errors),"output_fingerprint":out,"content_hash":_hash("p3_info_gain_07_audit",{**payload,"output_fingerprint":out})})
def serialize_financial_p3_info_gain_task_gate(result:InfoGainTaskGateResult)->str:
 if not isinstance(result,InfoGainTaskGateResult):raise TypeError("result must be InfoGainTaskGateResult")
 return json.dumps(result.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":value},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
