"""FIN-P3-LOG-03: collect accepted research-result references without recomputation."""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Any
from backend.amr.financial_p3_info_gain_summary import InfoGainSummaryResult
from backend.amr.financial_p3_info_gain_task_gate import InfoGainTaskGateResult
TASK_FP="719f020d6892e4d04b78aa3ee165954d47696bc466549b93482c6d35cd4a5b6b"
@dataclass(frozen=True)
class ResearchLogResultSnapshot:
 entries:tuple[tuple[str,dict[str,Any]],...];content_hash:str
 def to_dict(self):return {"entries":[{"entry_id":k,"payload":v} for k,v in self.entries],"content_hash":self.content_hash}
def collect_financial_p3_research_log_results(summary:InfoGainSummaryResult,task_gate:InfoGainTaskGateResult)->ResearchLogResultSnapshot:
 if not isinstance(summary,InfoGainSummaryResult) or not isinstance(task_gate,InfoGainTaskGateResult):raise TypeError("summary and task Gate required")
 if summary.audit.gate_status!="ready" or task_gate.gate_status!="accepted" or task_gate.output_fingerprint!=TASK_FP:raise ValueError("accepted INFO-GAIN predecessors required")
 if summary.audit.aggregate_information_gain_assessment_made or summary.audit.production_status!="not production ready":raise ValueError("research boundary drifted")
 entries=tuple((f"result-track-{x.track_id.lower()}",{"source_task_id":"FIN-P3-INFO-GAIN-05","source_output_fingerprint":x.source_output_fingerprint,"track_id":x.track_id,"evidence_status":x.evidence_status,"comparison_count":x.comparison_count,"completed_comparison_count":x.completed_comparison_count,"not_evaluable_count":x.not_evaluable_count,"status":"completed"}) for x in summary.tracks)+( ("result-overall",{"source_task_id":"FIN-P3-INFO-GAIN-07","source_output_fingerprint":task_gate.output_fingerprint,"coverage_status":summary.coverage_status,"overall_evidence_assessment":task_gate.overall_evidence_assessment,"admission_status":task_gate.admission_status,"production_status":task_gate.production_status,"status":"completed"}), )
 payload=[{"entry_id":k,"payload":v} for k,v in entries];return ResearchLogResultSnapshot(entries,_hash("p3_research_log_results",payload))
def serialize_research_log_results(snapshot:ResearchLogResultSnapshot)->str:
 if not isinstance(snapshot,ResearchLogResultSnapshot):raise TypeError("ResearchLogResultSnapshot required")
 return json.dumps(snapshot.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":value},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
