"""FIN-P3-LOG-07: final immutable Research Log assembly audit."""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Any
from backend.amr.financial_p3_research_log_serialization import FinancialP3ResearchLog
LOG_HASH="ca3bc2b4987b28be0af63c9a24cd86a12f835fd0d05f2c41d8422df0976cec5a"
@dataclass(frozen=True)
class ResearchLogAssemblyResult:
 gate_status:str;section_count:int;research_log_content_hash:str;output_fingerprint:str;content_hash:str
 def to_dict(self):return {x:getattr(self,x) for x in self.__dataclass_fields__}
def assemble_financial_p3_research_log_artifact(log:FinancialP3ResearchLog)->ResearchLogAssemblyResult:
 if not isinstance(log,FinancialP3ResearchLog):raise TypeError("FinancialP3ResearchLog required")
 payload={"schema_version":log.schema_version,"configuration_snapshot":log.configuration_snapshot,"result_references":log.result_references,"failure_references":log.failure_references,"lineage_references":log.lineage_references}
 valid=log.content_hash==LOG_HASH and log.content_hash==_hash("p3_research_log",payload) and all(payload[x].get("content_hash") for x in ("configuration_snapshot","result_references","failure_references","lineage_references"))
 gate="ready" if valid else "blocked";out=_hash("p3_research_log_assembly",{"gate_status":gate,"log_hash":log.content_hash});audit={"gate_status":gate,"section_count":4 if valid else 0,"research_log_content_hash":log.content_hash,"output_fingerprint":out};return ResearchLogAssemblyResult(**{**audit,"content_hash":_hash("p3_research_log_assembly_audit",audit)})
def serialize_research_log_assembly(result:ResearchLogAssemblyResult)->str:
 if not isinstance(result,ResearchLogAssemblyResult):raise TypeError("ResearchLogAssemblyResult required")
 return json.dumps(result.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":value},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
