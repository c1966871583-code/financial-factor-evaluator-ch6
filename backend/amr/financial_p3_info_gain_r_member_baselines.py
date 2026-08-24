"""INFO-GAIN-02D: formal R-track member-baseline status on frozen samples.

INFO-GAIN-02A does not freeze a PIT risk-label context. This module therefore
returns auditable ``not_run`` records and never manufactures labels, invokes
the R evaluator, or makes a fraud/misstatement conclusion.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.amr.financial_p2_r_evidence import evaluate_financial_p2_r_evidence
from backend.amr.financial_p3_info_gain_contract import INFO_GAIN_COMBO_ORDER
from backend.amr.financial_p3_info_gain_inputs import (
    InfoGainInputPreparationResult,
    compute_info_gain_input_output_fingerprint,
    serialize_info_gain_input_preparation_result,
)

SCHEMA = "FinancialP3InfoGainRMemberBaselines-v1.0"
AUDIT_SCHEMA = "FinancialP3InfoGainRMemberBaselineAudit-v1.0"
POLICY = "FIN-P3-INFO-GAIN-02D-POLICY-v1.0"
HASH_CONTRACT = "FIN-P3-INFO-GAIN-02D-HASH-v1.0"
ACCEPTED_02A = "1599c601f11da9d67adf7d538f80fe75488ac2481c0794678d6660589ea1c48e"
CONTRACT_HASH = "abd60138eaa90418b70d015f701d56690b602abcd9247cd6f78b27e974bf6d55"
R_EVALUATOR_HASH = "f2ad1291b7aa885d77031f4d2feebcdbd620a84039855d145b254bde10dda57e"
R_EVALUATOR_REFERENCE = "backend.amr.financial_p2_r_evidence.evaluate_financial_p2_r_evidence"
INPUT_REASON = "CONTEXT_NOT_FROZEN"
NOT_RUN_REASON = "R_CONTEXT_NOT_FROZEN"
METRICS = ("pr_auc", "roc_auc", "brier_score", "top_k_hit_rate", "expected_calibration_error")
DIRECTIONS = {
    "VQ": (("BP", "positive"), ("EBIT_EV", "positive"), ("ROE", "positive"), ("OCF_NP", "positive")),
    "QG": (("SALES_GROWTH", "positive"), ("PROFIT_GROWTH", "positive"), ("ROE", "positive"), ("OCF_NP", "positive")),
    "CASHQ": (("ROA", "positive"), ("OCF_SALES", "positive"), ("ACCRUALS", "negative")),
}

@dataclass(frozen=True)
class RMemberBaselineConfig:
    run_id: str
    accepted_02a_output_fingerprint: str = ACCEPTED_02A
    accepted_contract_hash: str = CONTRACT_HASH
    expected_evaluator_source_sha256: str = R_EVALUATOR_HASH
    synthetic_test_only: bool = True
    def __post_init__(self):
        if not isinstance(self.run_id, str) or not self.run_id.strip(): raise ValueError("run_id must be a non-empty string")
        if self.accepted_02a_output_fingerprint != ACCEPTED_02A: raise ValueError("accepted INFO-GAIN-02A output fingerprint drifted")
        if self.accepted_contract_hash != CONTRACT_HASH: raise ValueError("INFO-GAIN-01 contract hash drifted")
        if self.expected_evaluator_source_sha256 != R_EVALUATOR_HASH: raise ValueError("accepted R evaluator source hash drifted")
        if self.synthetic_test_only is not True: raise ValueError("INFO-GAIN-02D is authorized for synthetic input only")

@dataclass(frozen=True)
class RMemberBaselineIssue:
    code: str; message: str; combo_id: str | None = None
    def to_dict(self): return {name: getattr(self, name) for name in self.__dataclass_fields__}

@dataclass(frozen=True)
class RMemberBaselineRun:
    combo_id: str; member_factor_id: str; frozen_direction: str; common_sample_reference: str; common_sample_fingerprint: str
    calculation_status: str; not_run_reason: str; evaluator_reference: str; evaluator_source_sha256: str
    metric_statuses: tuple[tuple[str, str], ...]; metric_values: tuple[tuple[str, None], ...]; issue_codes: tuple[str, ...]; content_hash: str
    def to_dict(self):
        return {"combo_id":self.combo_id,"member_factor_id":self.member_factor_id,"frozen_direction":self.frozen_direction,"common_sample_reference":self.common_sample_reference,"common_sample_fingerprint":self.common_sample_fingerprint,"calculation_status":self.calculation_status,"not_run_reason":self.not_run_reason,"evaluator_reference":self.evaluator_reference,"evaluator_source_sha256":self.evaluator_source_sha256,"metric_statuses":dict(self.metric_statuses),"metric_values":dict(self.metric_values),"issue_codes":list(self.issue_codes),"content_hash":self.content_hash}

@dataclass(frozen=True)
class RMemberBaselineBundle:
    combo_id: str; common_sample_reference: str; common_sample_fingerprint: str; member_runs: tuple[RMemberBaselineRun, ...]; calculation_status: str; content_hash: str
    def to_dict(self): return {"combo_id":self.combo_id,"common_sample_reference":self.common_sample_reference,"common_sample_fingerprint":self.common_sample_fingerprint,"member_runs":[x.to_dict() for x in self.member_runs],"calculation_status":self.calculation_status,"content_hash":self.content_hash}

@dataclass(frozen=True)
class RMemberBaselineAudit:
    gate_status: str; errors: tuple[RMemberBaselineIssue, ...]; combo_count: int; member_run_count: int; completed_run_count: int; not_run_count: int
    r_evaluator_call_count: int; m_evaluator_call_count: int; f_evaluator_call_count: int; accepted_input_verified: bool; exact_common_samples_verified: bool; R_context_status: str; existing_R_evaluator_identified: bool; risk_labels_constructed: bool; metrics_calculated: bool; combination_evaluated: bool; strongest_member_selected: bool; information_gain_calculated: bool; input_fingerprint: str; output_fingerprint: str; evaluator_source_sha256: str; production_status: str; conclusion_boundary: str; schema_version: str; audit_schema_version: str; policy_version: str; hash_contract_version: str; content_hash: str
    def to_dict(self):
        return {**{name:getattr(self,name) for name in self.__dataclass_fields__ if name != "errors"},"errors":[x.to_dict() for x in self.errors]}

@dataclass(frozen=True)
class RMemberBaselineResult:
    bundles: tuple[RMemberBaselineBundle, ...]; audit: RMemberBaselineAudit
    def to_dict(self): return {"bundles":[x.to_dict() for x in self.bundles],"audit":self.audit.to_dict()}

def evaluate_financial_p3_info_gain_r_member_baselines(prepared: InfoGainInputPreparationResult, *, configuration: RMemberBaselineConfig) -> RMemberBaselineResult:
    if not isinstance(prepared, InfoGainInputPreparationResult): raise TypeError("prepared must be InfoGainInputPreparationResult")
    if not isinstance(configuration, RMemberBaselineConfig): raise TypeError("configuration must be RMemberBaselineConfig")
    before = serialize_info_gain_input_preparation_result(prepared); evaluator_hash = _evaluator_hash(); errors = _validate(prepared, configuration, evaluator_hash)
    if errors: return _result(prepared, (), tuple(errors), evaluator_hash)
    bundles=[]
    for package in prepared.packages:
        runs=tuple(_run(package, member, direction, evaluator_hash) for member,direction in package.member_directions)
        payload={"combo_id":package.combo_id,"common_sample_reference":package.common_sample_reference,"common_sample_fingerprint":package.common_sample_fingerprint,"member_runs":[x.to_dict() for x in runs],"calculation_status":"not_run"}
        bundles.append(RMemberBaselineBundle(package.combo_id,package.common_sample_reference,package.common_sample_fingerprint,runs,"not_run",_hash("p3_info_gain_02d_bundle",payload)))
    if serialize_info_gain_input_preparation_result(prepared) != before: raise RuntimeError("INFO-GAIN-02A input was mutated")
    return _result(prepared,tuple(bundles),(),evaluator_hash)

def serialize_r_member_baseline_result(result: RMemberBaselineResult) -> str:
    if not isinstance(result,RMemberBaselineResult): raise TypeError("result must be RMemberBaselineResult")
    return json.dumps(_canon(result.to_dict()),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)

def _validate(prepared, configuration, evaluator_hash):
    errors=[]; audit=prepared.audit
    if audit.gate_status != "ready" or audit.errors: errors.append(_issue("INFO_GAIN_02A_NOT_READY","02A input gate must be ready"))
    if audit.output_fingerprint != configuration.accepted_02a_output_fingerprint: errors.append(_issue("INFO_GAIN_02A_FINGERPRINT_MISMATCH",f"02A output fingerprint drifted: expected={configuration.accepted_02a_output_fingerprint} actual={audit.output_fingerprint}"))
    if compute_info_gain_input_output_fingerprint(prepared.packages) != audit.output_fingerprint: errors.append(_issue("INFO_GAIN_02A_CONTENT_MISMATCH","02A packages do not match accepted output"))
    if audit.contract_hash != configuration.accepted_contract_hash: errors.append(_issue("CONTRACT_HASH_MISMATCH","INFO-GAIN-01 contract hash drifted"))
    if evaluator_hash != configuration.expected_evaluator_source_sha256: errors.append(_issue("R_EVALUATOR_HASH_MISMATCH","accepted R evaluator source drifted"))
    if tuple(x.combo_id for x in prepared.packages) != INFO_GAIN_COMBO_ORDER: return errors+[_issue("COMBO_ORDER_MISMATCH","packages must be VQ, QG, CASHQ")]
    for p in prepared.packages:
        if p.member_directions != DIRECTIONS[p.combo_id]: errors.append(_issue("MEMBER_DIRECTION_MISMATCH","member set/order/direction drifted",p.combo_id))
        tracks=tuple(x for x in p.track_inputs if x.track_id == "R")
        if len(tracks) != 1: errors.append(_issue("R_TRACK_INPUT_MISSING","exactly one R track input required",p.combo_id)); continue
        t=tracks[0]
        if t.preparation_status != "not_run" or t.reason_code != INPUT_REASON: errors.append(_issue("R_CONTEXT_STATE_DRIFT","R context must remain formal not_run",p.combo_id))
        if t.evaluation_contexts or t.label_references or t.evaluation_config_reference is not None: errors.append(_issue("R_CONTEXT_REFERENCE_DRIFT","R context must have no unfrozen references",p.combo_id))
    return errors

def _run(p, member, direction, h):
    statuses=tuple((m,"not_run") for m in METRICS); values=tuple((m,None) for m in METRICS)
    payload={"combo_id":p.combo_id,"member_factor_id":member,"frozen_direction":direction,"common_sample_reference":p.common_sample_reference,"common_sample_fingerprint":p.common_sample_fingerprint,"calculation_status":"not_run","not_run_reason":NOT_RUN_REASON,"evaluator_reference":R_EVALUATOR_REFERENCE,"evaluator_source_sha256":h,"metric_statuses":dict(statuses),"metric_values":dict(values),"issue_codes":[NOT_RUN_REASON]}
    return RMemberBaselineRun(p.combo_id,member,direction,p.common_sample_reference,p.common_sample_fingerprint,"not_run",NOT_RUN_REASON,R_EVALUATOR_REFERENCE,h,statuses,values,(NOT_RUN_REASON,),_hash("p3_info_gain_02d_member_run",payload))

def _result(prepared,bundles,errors,h):
    runs=tuple(run for bundle in bundles for run in bundle.member_runs); gate="ready" if not errors and len(runs)==11 else "blocked"; output=_hash("p3_info_gain_02d_output",[x.to_dict() for x in bundles])
    payload={"gate_status":gate,"errors":[x.to_dict() for x in errors],"combo_count":len(bundles),"member_run_count":len(runs),"completed_run_count":0,"not_run_count":len(runs) if not errors else 11,"r_evaluator_call_count":0,"m_evaluator_call_count":0,"f_evaluator_call_count":0,"accepted_input_verified":gate=="ready","exact_common_samples_verified":gate=="ready","R_context_status":"not_run","existing_R_evaluator_identified":True,"risk_labels_constructed":False,"metrics_calculated":False,"combination_evaluated":False,"strongest_member_selected":False,"information_gain_calculated":False,"input_fingerprint":prepared.audit.output_fingerprint,"output_fingerprint":output,"evaluator_source_sha256":h,"production_status":"not production ready","conclusion_boundary":"Formal R-track not_run member-baseline status only; no risk label construction, evaluator call, fraud/misstatement conclusion, combination evaluation, strongest-member selection, information-gain, admission, production, or trading conclusion.","schema_version":SCHEMA,"audit_schema_version":AUDIT_SCHEMA,"policy_version":POLICY,"hash_contract_version":HASH_CONTRACT}
    return RMemberBaselineResult(bundles,RMemberBaselineAudit(**{**payload,"errors":tuple(errors),"content_hash":_hash("p3_info_gain_02d_audit",payload)}))

def _evaluator_hash():
    source=inspect.getsourcefile(evaluate_financial_p2_r_evidence)
    if source is None:return "unavailable"
    normalized=Path(source).read_bytes().replace(b"\r\n",b"\n")
    return hashlib.sha256(normalized).hexdigest()
def _issue(code,message,combo_id=None): return RMemberBaselineIssue(code,message,combo_id)
def _canon(v):
    if isinstance(v,Mapping): return {str(k):_canon(x) for k,x in sorted(v.items(),key=lambda z:str(z[0]))}
    if isinstance(v,(list,tuple)): return [_canon(x) for x in v]
    if v is None or isinstance(v,(str,bool,int)): return v
    if isinstance(v,(float,np.floating)): return float(v) if math.isfinite(float(v)) else None
    if isinstance(v,np.integer): return int(v)
    raise TypeError(f"unsupported canonical type: {type(v).__name__}")
def _hash(domain,value): return hashlib.sha256(json.dumps({"domain":domain,"value":_canon(value)},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
