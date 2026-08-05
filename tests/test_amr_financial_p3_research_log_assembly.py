from dataclasses import replace
import pytest
from backend.amr.financial_p3_research_log_assembly import assemble_financial_p3_research_log_artifact,serialize_research_log_assembly
from tests.fixtures.synthetic_financial_p3_research_log_assembly_cases import make_inputs,make_result
@pytest.fixture(scope="module")
def log():return make_inputs()
def test_assembled_artifact_is_ready_and_complete(log):
 r=assemble_financial_p3_research_log_artifact(log);assert r.gate_status=="ready" and r.section_count==4
def test_assembly_is_deterministic(log):
 a,b=assemble_financial_p3_research_log_artifact(log),assemble_financial_p3_research_log_artifact(log);assert a.content_hash==b.content_hash and serialize_research_log_assembly(a)==serialize_research_log_assembly(b)
def test_log_hash_drift_blocks(log):assert assemble_financial_p3_research_log_artifact(replace(log,content_hash="drift")).gate_status=="blocked"
def test_type_rejected():
 with pytest.raises(TypeError):assemble_financial_p3_research_log_artifact(None)
