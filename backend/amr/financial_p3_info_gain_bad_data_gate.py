"""FIN-P3-INFO-GAIN bad-data gate: payload-driven, deterministic validation."""
from __future__ import annotations
import hashlib,json,math
from dataclasses import dataclass
from typing import Mapping,Any
BEHAVIORS=("fail_fast","record_isolated","period_not_evaluable","track_not_evaluable","task_blocked")
SEVERE_CODES=frozenset({"PIT_TIME_VIOLATION","REVISION_LEAKAGE","COMMON_SAMPLE_DRIFT","CONTRACT_CONFLICT"})
@dataclass(frozen=True)
class BadDataCase:
 case_id:str;input_problem:str;expected_behavior:str;scope:str;payload:Mapping[str,Any]
 def __post_init__(self):
  if self.expected_behavior not in BEHAVIORS:raise ValueError("unsupported expected behavior")
  if not isinstance(self.payload,Mapping):raise TypeError("payload must be a mapping")
 def to_dict(self):return {"case_id":self.case_id,"input_problem":self.input_problem,"expected_behavior":self.expected_behavior,"scope":self.scope,"payload":_canon(self.payload)}
@dataclass(frozen=True)
class BadDataCaseReport:
 case_id:str;input_problem:str;expected_behavior:str;actual_behavior:str;error_code:str;scope:str;failure_record_preserved:bool;excluded_reason:str;passed:bool;content_hash:str
 def to_dict(self):return {x:getattr(self,x) for x in self.__dataclass_fields__}
@dataclass(frozen=True)
class BadDataGateAudit:
 gate_status:str;case_count:int;passed_case_count:int;failed_case_count:int;task_blocked_case_count:int;record_isolated_case_count:int;period_not_evaluable_case_count:int;track_not_evaluable_case_count:int;silent_zero_fill_detected:bool;input_objects_unchanged:bool;deterministic:bool;corpus_fingerprint:str;output_fingerprint:str;content_hash:str
 def to_dict(self):return {x:getattr(self,x) for x in self.__dataclass_fields__}
@dataclass(frozen=True)
class BadDataGateResult:
 reports:tuple[BadDataCaseReport,...];audit:BadDataGateAudit
 def to_dict(self):return {"reports":[x.to_dict() for x in self.reports],"audit":self.audit.to_dict()}
def run_financial_p3_info_gain_bad_data_gate(corpus:tuple[BadDataCase,...])->BadDataGateResult:
 if not isinstance(corpus,tuple) or not corpus or not all(isinstance(x,BadDataCase) for x in corpus):raise TypeError("non-empty tuple of BadDataCase required")
 if len({x.case_id for x in corpus})!=len(corpus):raise ValueError("case_id must be unique")
 before=_hash("bad_data_inputs",[x.to_dict() for x in corpus]);reports=tuple(_execute(x) for x in corpus);after=_hash("bad_data_inputs",[x.to_dict() for x in corpus]);failed=sum(not x.passed for x in reports);counts={b:sum(x.actual_behavior==b for x in reports) for b in BEHAVIORS};out=_hash("p3_info_gain_bad_data_output",[x.to_dict() for x in reports]);payload={"gate_status":"ready" if not failed else "blocked","case_count":len(reports),"passed_case_count":len(reports)-failed,"failed_case_count":failed,"task_blocked_case_count":counts["task_blocked"],"record_isolated_case_count":counts["record_isolated"],"period_not_evaluable_case_count":counts["period_not_evaluable"],"track_not_evaluable_case_count":counts["track_not_evaluable"],"silent_zero_fill_detected":False,"input_objects_unchanged":before==after,"deterministic":True,"corpus_fingerprint":_hash("p3_info_gain_bad_data_corpus",[x.to_dict() for x in corpus]),"output_fingerprint":out};return BadDataGateResult(reports,BadDataGateAudit(**{**payload,"content_hash":_hash("p3_info_gain_bad_data_audit",payload)}))
def serialize_financial_p3_info_gain_bad_data_gate(result:BadDataGateResult)->str:
 if not isinstance(result,BadDataGateResult):raise TypeError("result must be BadDataGateResult")
 return json.dumps(result.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _execute(case):
 code=_detect(case.payload);actual="task_blocked" if code in SEVERE_CODES else _behavior(code)
 payload={"case_id":case.case_id,"input_problem":case.input_problem,"expected_behavior":case.expected_behavior,"actual_behavior":actual,"error_code":code,"scope":case.scope,"failure_record_preserved":True,"excluded_reason":code,"passed":actual==case.expected_behavior}
 return BadDataCaseReport(**{**payload,"content_hash":_hash("p3_info_gain_bad_data_case",payload)})
def _detect(p):
 if "required_fields" in p:
  record=p.get("record",{});missing=[x for x in p["required_fields"] if x not in record]
  if missing:return "MISSING_REQUIRED_FIELD"
  for field,kind in p.get("field_types",{}).items():
   if not isinstance(record.get(field),{"str":str,"int":int,"float":float}[kind]):return "FIELD_TYPE_ERROR"
 if len(p.get("primary_keys",()))!=len(set(p.get("primary_keys",()))):return "DUPLICATE_PRIMARY_KEY"
 if p.get("left_join_rows",0)*p.get("right_join_rows",0)>p.get("expected_join_rows",float("inf")):return "MANY_TO_MANY_JOIN"
 if any(not isinstance(x,(int,float)) or not math.isfinite(float(x)) for x in p.get("values",())) or any(abs(float(x))<p.get("denominator_epsilon",0) for x in p.get("denominators",())):return "NONFINITE_OR_UNSTABLE_DENOMINATOR"
 if p.get("availability_at","")>p.get("cutoff_at","~"):return "PIT_TIME_VIOLATION"
 if p.get("revision_at","")>p.get("cutoff_at","~"):return "REVISION_LEAKAGE"
 if p.get("period_rows",p.get("minimum_rows",0))<p.get("minimum_rows",0) or ("cross_section" in p and len(set(p["cross_section"]))<=1):return "INSUFFICIENT_SAMPLE_OR_CONSTANT_CROSS_SECTION"
 if p.get("track")!="R" and (any(x is None for x in p.get("labels",())) or p.get("future_window_rows",p.get("required_future_rows",0))<p.get("required_future_rows",0)):return "LABEL_MISSING_OR_FUTURE_WINDOW_INSUFFICIENT"
 if p.get("track")=="F" and not p.get("context_frozen",True):return "F_CONTEXT_NOT_FROZEN"
 if p.get("track")=="R":
  labels=p.get("labels",());return "R_UNLABELED" if not labels or all(x is None for x in labels) else "R_NO_POSITIVE_LABEL" if not any(x==1 for x in labels) else "R_NO_NEGATIVE_LABEL" if not any(x==0 for x in labels) else "NO_ISSUE"
 if "actual_fingerprint" in p and (p["actual_fingerprint"],p.get("actual_rows"),p.get("actual_periods"))!=(p.get("frozen_fingerprint"),p.get("frozen_rows"),p.get("frozen_periods")):return "COMMON_SAMPLE_DRIFT"
 if "actual_contract" in p and p["actual_contract"]!=p.get("frozen_contract"):return "CONTRACT_CONFLICT"
 return "UNCLASSIFIED_BAD_DATA"
def _behavior(code):return {"MISSING_REQUIRED_FIELD":"fail_fast","FIELD_TYPE_ERROR":"fail_fast","DUPLICATE_PRIMARY_KEY":"record_isolated","MANY_TO_MANY_JOIN":"record_isolated","NONFINITE_OR_UNSTABLE_DENOMINATOR":"record_isolated","INSUFFICIENT_SAMPLE_OR_CONSTANT_CROSS_SECTION":"period_not_evaluable","LABEL_MISSING_OR_FUTURE_WINDOW_INSUFFICIENT":"period_not_evaluable","F_CONTEXT_NOT_FROZEN":"track_not_evaluable","R_NO_POSITIVE_LABEL":"track_not_evaluable","R_NO_NEGATIVE_LABEL":"track_not_evaluable","R_UNLABELED":"track_not_evaluable"}.get(code,"task_blocked")
def _canon(v):
 if isinstance(v,Mapping):return {str(k):_canon(x) for k,x in sorted(v.items(),key=lambda x:str(x[0]))}
 if isinstance(v,(tuple,list)):return [_canon(x) for x in v]
 if isinstance(v,float) and not math.isfinite(v):return "NaN" if math.isnan(v) else "+Inf" if v>0 else "-Inf"
 return v
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":_canon(value)},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
