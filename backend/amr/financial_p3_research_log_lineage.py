"""FIN-P3-LOG-05: collect immutable lineage and audit references."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from backend.amr.financial_p3_info_gain_bad_data_gate import BadDataGateResult
from backend.amr.financial_p3_info_gain_summary import InfoGainSummaryResult
from backend.amr.financial_p3_info_gain_task_gate import InfoGainTaskGateResult
from backend.amr.financial_p3_research_log_contract import ResearchLogSchema

TASK_FP="719f020d6892e4d04b78aa3ee165954d47696bc466549b93482c6d35cd4a5b6b"
TASK_GATE_READY_STATUSES=frozenset({"accepted","ready"})
@dataclass(frozen=True)
class ResearchLogLineageSnapshot:
 entries:tuple[tuple[str,dict[str,Any]],...];content_hash:str
 def to_dict(self):return {"entries":[{"entry_id":k,"payload":v} for k,v in self.entries],"content_hash":self.content_hash}
def collect_financial_p3_research_log_lineage(schema:ResearchLogSchema,summary:InfoGainSummaryResult,bad:BadDataGateResult,task:InfoGainTaskGateResult,*,repository_head:str,control_sha256:str)->ResearchLogLineageSnapshot:
 if not all(isinstance(x,t) for x,t in ((schema,ResearchLogSchema),(summary,InfoGainSummaryResult),(bad,BadDataGateResult),(task,InfoGainTaskGateResult))):raise TypeError("schema and accepted INFO-GAIN artifacts required")
 if task.gate_status not in TASK_GATE_READY_STATUSES or task.output_fingerprint!=TASK_FP:raise ValueError("task Gate drifted")
 if not isinstance(repository_head,str) or len(repository_head)!=40 or not isinstance(control_sha256,str) or len(control_sha256)!=64:raise ValueError("frozen environment references required")
 entries=(
  ("lineage-schema",{"source_task_id":"FIN-P3-LOG-01","content_hash":schema.content_hash,"schema_version":schema.schema_version}),
  ("lineage-summary",{"source_task_id":"FIN-P3-INFO-GAIN-05","output_fingerprint":summary.audit.output_fingerprint,"content_hash":summary.audit.content_hash,"input_fingerprint":summary.audit.input_fingerprint}),
  ("lineage-bad-data",{"source_task_id":"FIN-P3-INFO-GAIN-05R","output_fingerprint":bad.audit.output_fingerprint,"content_hash":bad.audit.content_hash,"corpus_fingerprint":bad.audit.corpus_fingerprint}),
  ("lineage-task-gate",{"source_task_id":"FIN-P3-INFO-GAIN-07","output_fingerprint":task.output_fingerprint,"content_hash":task.content_hash,"input_fingerprint":task.input_fingerprint,"repository_head":repository_head,"control_sha256":control_sha256}),)
 payload=[{"entry_id":k,"payload":v} for k,v in entries];return ResearchLogLineageSnapshot(entries,_hash("p3_research_log_lineage",payload))
def serialize_research_log_lineage(snapshot:ResearchLogLineageSnapshot)->str:
 if not isinstance(snapshot,ResearchLogLineageSnapshot):raise TypeError("ResearchLogLineageSnapshot required")
 return json.dumps(snapshot.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":value},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
