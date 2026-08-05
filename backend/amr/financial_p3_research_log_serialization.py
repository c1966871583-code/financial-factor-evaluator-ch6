"""FIN-P3-LOG-06: deterministic assembly serialization and content hash."""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass,replace
from typing import Any
from backend.amr.financial_p3_research_log_contract import ResearchLogSchema
from backend.amr.financial_p3_research_log_config import ResearchLogConfigSnapshot
from backend.amr.financial_p3_research_log_results import ResearchLogResultSnapshot
from backend.amr.financial_p3_research_log_failures import ResearchLogFailureSnapshot
from backend.amr.financial_p3_research_log_lineage import ResearchLogLineageSnapshot
@dataclass(frozen=True)
class FinancialP3ResearchLog:
 schema_version:str;configuration_snapshot:dict[str,Any];result_references:dict[str,Any];failure_references:dict[str,Any];lineage_references:dict[str,Any];content_hash:str
 def to_dict(self):return {"schema_version":self.schema_version,"configuration_snapshot":self.configuration_snapshot,"result_references":self.result_references,"failure_references":self.failure_references,"lineage_references":self.lineage_references,"content_hash":self.content_hash}
def assemble_financial_p3_research_log(schema:ResearchLogSchema,config:ResearchLogConfigSnapshot,results:ResearchLogResultSnapshot,failures:ResearchLogFailureSnapshot,lineage:ResearchLogLineageSnapshot)->FinancialP3ResearchLog:
 if not all(isinstance(x,t) for x,t in ((schema,ResearchLogSchema),(config,ResearchLogConfigSnapshot),(results,ResearchLogResultSnapshot),(failures,ResearchLogFailureSnapshot),(lineage,ResearchLogLineageSnapshot))):raise TypeError("schema and four accepted snapshots required")
 for snapshot,domain in ((config,"p3_research_log_config"),(results,"p3_research_log_results"),(failures,"p3_research_log_failures"),(lineage,"p3_research_log_lineage")):
  if snapshot.content_hash!=_hash(domain,[{"entry_id":k,"payload":v} for k,v in snapshot.entries]):raise ValueError("snapshot content hash mismatch")
 payload={"schema_version":schema.schema_version,"configuration_snapshot":config.to_dict(),"result_references":results.to_dict(),"failure_references":failures.to_dict(),"lineage_references":lineage.to_dict()};return FinancialP3ResearchLog(**{**payload,"content_hash":_hash("p3_research_log",payload)})
def serialize_financial_p3_research_log(log:FinancialP3ResearchLog)->str:
 if not isinstance(log,FinancialP3ResearchLog):raise TypeError("FinancialP3ResearchLog required")
 return json.dumps(log.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":value},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
