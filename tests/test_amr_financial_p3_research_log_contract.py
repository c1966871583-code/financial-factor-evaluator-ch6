import pytest
from backend.amr.financial_p3_research_log_contract import ResearchLogSchema,serialize_research_log_schema,SCHEMA_VERSION
from tests.fixtures.synthetic_financial_p3_research_log_contract_cases import make_schema
def test_frozen_schema_has_all_required_sections_and_statuses():
 s=make_schema();assert s.schema_version==SCHEMA_VERSION and s.section_order==("configuration_snapshot","result_references","failure_references","lineage_references")
 assert {"not_run","not_evaluable","insufficient_data","failed","completed","task_blocked"}<=set(s.status_vocabulary)
def test_schema_serialization_and_hash_are_deterministic():
 a,b=make_schema(),make_schema();assert a.content_hash==b.content_hash and serialize_research_log_schema(a)==serialize_research_log_schema(b)
@pytest.mark.parametrize("field,value",[("schema_version","v2"),("section_order",()),("status_vocabulary",())])
def test_schema_drift_rejected(field,value):
 with pytest.raises(ValueError):make_schema(**{field:value})
def test_type_rejected():
 with pytest.raises(TypeError):serialize_research_log_schema(None)
