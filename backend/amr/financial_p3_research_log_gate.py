"""FIN-P3-LOG-08: task-level completeness gate for assembled Research Log."""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Any
from backend.amr.financial_p3_research_log_assembly import ResearchLogAssemblyResult
from backend.amr.financial_p3_research_log_serialization import FinancialP3ResearchLog
ASSEMBLY_FP="66e0fca3dcb14187ebaaf7da17c31f5f72744cb22a05dab0840c2460a1e5e863"
@dataclass(frozen=True)
class ResearchLogGateResult:
 gate_status:str;configuration_entry_count:int;result_entry_count:int;failure_entry_count:int;lineage_entry_count:int;research_log_content_hash:str;output_fingerprint:str;content_hash:str
 def to_dict(self):return {x:getattr(self,x) for x in self.__dataclass_fields__}
def evaluate_financial_p3_research_log_gate(log:FinancialP3ResearchLog,assembly:ResearchLogAssemblyResult)->ResearchLogGateResult:
 if not isinstance(log,FinancialP3ResearchLog) or not isinstance(assembly,ResearchLogAssemblyResult):raise TypeError("log and assembly audit required")
 counts=(len(log.configuration_snapshot["entries"]),len(log.result_references["entries"]),len(log.failure_references["entries"]),len(log.lineage_references["entries"]))
 failures=log.failure_references["entries"];has_bad=sum(x["entry_id"].startswith("failure-bad-data-") for x in failures)==15;has_unfinished={x["entry_id"] for x in failures}>={"unfinished-track-f","unfinished-track-r"}
 valid=assembly.gate_status=="ready" and assembly.output_fingerprint==ASSEMBLY_FP and counts==(3,4,17,4) and has_bad and has_unfinished
 gate="accepted" if valid else "blocked";payload={"gate_status":gate,"configuration_entry_count":counts[0],"result_entry_count":counts[1],"failure_entry_count":counts[2],"lineage_entry_count":counts[3],"research_log_content_hash":log.content_hash};out=_hash("p3_research_log_gate",payload);return ResearchLogGateResult(**{**payload,"output_fingerprint":out,"content_hash":_hash("p3_research_log_gate_audit",{**payload,"output_fingerprint":out})})
def serialize_research_log_gate(result:ResearchLogGateResult)->str:
 if not isinstance(result,ResearchLogGateResult):raise TypeError("ResearchLogGateResult required")
 return json.dumps(result.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":value},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
