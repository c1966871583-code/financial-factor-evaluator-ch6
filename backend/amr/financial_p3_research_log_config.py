"""FIN-P3-LOG-02: deterministic configuration snapshot collection."""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Any
from backend.amr.financial_p3_research_log_contract import ResearchLogSchema
from backend.amr.financial_p3_info_gain_summary import InfoGainSummaryResult
from backend.amr.financial_p3_info_gain_bad_data_gate import BadDataGateResult
from backend.amr.financial_p3_info_gain_task_gate import InfoGainTaskGateResult
TASK_FP="719f020d6892e4d04b78aa3ee165954d47696bc466549b93482c6d35cd4a5b6b"
@dataclass(frozen=True)
class ResearchLogConfigSnapshot:
 entries:tuple[tuple[str,dict[str,Any]],...];content_hash:str
 def to_dict(self):return {"entries":[{"entry_id":k,"payload":v} for k,v in self.entries],"content_hash":self.content_hash}
def collect_financial_p3_research_log_config(schema:ResearchLogSchema,summary:InfoGainSummaryResult,bad_data:BadDataGateResult,task_gate:InfoGainTaskGateResult)->ResearchLogConfigSnapshot:
 if not all(isinstance(x,t) for x,t in ((schema,ResearchLogSchema),(summary,InfoGainSummaryResult),(bad_data,BadDataGateResult),(task_gate,InfoGainTaskGateResult))):raise TypeError("accepted schema and INFO-GAIN outputs required")
 if task_gate.gate_status!="accepted" or task_gate.output_fingerprint!=TASK_FP:raise ValueError("INFO-GAIN task Gate drifted")
 entries=(
  ("config-schema",{"source_task_id":"FIN-P3-LOG-01","schema_version":schema.schema_version,"source_content_hash":schema.content_hash,"status":"completed"}),
  ("config-info-gain",{"source_task_id":"FIN-P3-INFO-GAIN-05","summary_fingerprint":summary.audit.output_fingerprint,"bad_data_gate_fingerprint":bad_data.audit.output_fingerprint,"production_status":summary.audit.production_status,"status":"completed"}),
  ("config-task-gate",{"source_task_id":"FIN-P3-INFO-GAIN-07","source_output_fingerprint":task_gate.output_fingerprint,"overall_evidence_assessment":task_gate.overall_evidence_assessment,"admission_status":task_gate.admission_status,"production_status":task_gate.production_status,"status":"completed"}),)
 payload=[{"entry_id":k,"payload":v} for k,v in entries];return ResearchLogConfigSnapshot(entries,_hash("p3_research_log_config",payload))
def serialize_research_log_config(snapshot:ResearchLogConfigSnapshot)->str:
 if not isinstance(snapshot,ResearchLogConfigSnapshot):raise TypeError("ResearchLogConfigSnapshot required")
 return json.dumps(snapshot.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":value},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
