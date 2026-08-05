from dataclasses import replace
import pytest
from backend.amr.financial_p3_research_log_serialization import assemble_financial_p3_research_log,serialize_financial_p3_research_log
from tests.fixtures.synthetic_financial_p3_research_log_serialization_cases import make_inputs,make_log
@pytest.fixture(scope="module")
def inputs():return make_inputs()
def test_assembles_all_four_schema_sections(inputs):
 log=assemble_financial_p3_research_log(*inputs);assert log.schema_version.endswith("v1.0") and len(log.failure_references["entries"])==17
def test_serialization_and_hash_are_deterministic(inputs):
 a,b=assemble_financial_p3_research_log(*inputs),assemble_financial_p3_research_log(*inputs);assert a.content_hash==b.content_hash and serialize_financial_p3_research_log(a)==serialize_financial_p3_research_log(b)
def test_snapshot_hash_drift_blocks(inputs):
 values=list(inputs);values[1]=replace(values[1],content_hash="drift")
 with pytest.raises(ValueError):assemble_financial_p3_research_log(*values)
def test_type_rejected(inputs):
 with pytest.raises(TypeError):assemble_financial_p3_research_log(None,*inputs[1:])
