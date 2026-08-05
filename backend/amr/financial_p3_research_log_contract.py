"""FIN-P3-LOG-01: frozen Research Log schema contract only."""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Any,Mapping
SCHEMA_VERSION="FIN-P3-RESEARCH-LOG-SCHEMA-v1.0";SECTIONS=("configuration_snapshot","result_references","failure_references","lineage_references");STATUSES=("not_run","not_evaluable","insufficient_data","failed","completed","task_blocked")
@dataclass(frozen=True)
class ResearchLogSchema:
 schema_version:str=SCHEMA_VERSION;section_order:tuple[str,...]=SECTIONS;status_vocabulary:tuple[str,...]=STATUSES;content_hash:str=""
 def __post_init__(self):
  if self.schema_version!=SCHEMA_VERSION or self.section_order!=SECTIONS or self.status_vocabulary!=STATUSES:raise ValueError("frozen Research Log schema drifted")
  expected=_hash("p3_research_log_schema",self._payload())
  if self.content_hash and self.content_hash!=expected:raise ValueError("content_hash drifted")
  object.__setattr__(self,"content_hash",expected)
 def _payload(self):return {"schema_version":self.schema_version,"section_order":list(self.section_order),"status_vocabulary":list(self.status_vocabulary),"required_entry_fields":["entry_id","source_task_id","source_output_fingerprint","source_content_hash","status","payload"],"forbidden_actions":["recalculate_metrics","modify_upstream_results","persist_external_data"]}
 def to_dict(self):return {**self._payload(),"content_hash":self.content_hash}
def serialize_research_log_schema(schema:ResearchLogSchema)->str:
 if not isinstance(schema,ResearchLogSchema):raise TypeError("ResearchLogSchema required")
 return json.dumps(schema.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(domain:str,value:Any)->str:return hashlib.sha256(json.dumps({"domain":domain,"value":value},ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
