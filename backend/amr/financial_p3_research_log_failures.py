"""FIN-P3-LOG-04: preserve bad-data and unfinished-track references."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from backend.amr.financial_p3_info_gain_bad_data_gate import BadDataGateResult
from backend.amr.financial_p3_info_gain_summary import InfoGainSummaryResult

BAD_FP="a267d8e44bf0ffd4ce3b6632afaf58ee3ebfc9877da65bf8982e14ecce9f29f2"
SUMMARY_READY_STATUSES=frozenset({"ready","accepted"})
@dataclass(frozen=True)
class ResearchLogFailureSnapshot:
 entries:tuple[tuple[str,dict[str,Any]],...];content_hash:str
 def to_dict(self):return {"entries":[{"entry_id":k,"payload":v} for k,v in self.entries],"content_hash":self.content_hash}
def collect_financial_p3_research_log_failures(bad_data:BadDataGateResult,summary:InfoGainSummaryResult)->ResearchLogFailureSnapshot:
 if not isinstance(bad_data,BadDataGateResult) or not isinstance(summary,InfoGainSummaryResult):raise TypeError("bad-data and summary results required")
 if bad_data.audit.gate_status!="ready" or bad_data.audit.output_fingerprint!=BAD_FP:raise ValueError("accepted bad-data Gate drifted")
 if summary.audit.gate_status not in SUMMARY_READY_STATUSES:raise ValueError("accepted summary required")
 bad=tuple((f"failure-bad-data-{x.case_id}",{"source_task_id":"FIN-P3-INFO-GAIN-05R","source_output_fingerprint":bad_data.audit.output_fingerprint,"status":"completed","input_problem":x.input_problem,"error_code":x.error_code,"expected_behavior":x.expected_behavior,"actual_behavior":x.actual_behavior,"failure_record_preserved":x.failure_record_preserved,"passed":x.passed}) for x in bad_data.reports)
 unfinished=tuple((f"unfinished-track-{x.track_id.lower()}",{"source_task_id":"FIN-P3-INFO-GAIN-05","source_output_fingerprint":x.source_output_fingerprint,"status":"not_evaluable","track_id":x.track_id,"evidence_status":x.evidence_status,"not_evaluable_count":x.not_evaluable_count,"reason":"evaluation_context_not_frozen"}) for x in summary.tracks if x.track_id in ("F","R"))
 entries=bad+unfinished;payload=[{"entry_id":k,"payload":v} for k,v in entries];return ResearchLogFailureSnapshot(entries,_hash("p3_research_log_failures",payload))
def serialize_research_log_failures(snapshot:ResearchLogFailureSnapshot)->str:
 if not isinstance(snapshot,ResearchLogFailureSnapshot):raise TypeError("ResearchLogFailureSnapshot required")
 return json.dumps(snapshot.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":value},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
