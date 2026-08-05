from dataclasses import replace
import pytest
from backend.amr.financial_p3_research_log_gate import evaluate_financial_p3_research_log_gate,serialize_research_log_gate
from tests.fixtures.synthetic_financial_p3_research_log_gate_cases import make_inputs_for_gate
@pytest.fixture(scope="module")
def inputs():return make_inputs_for_gate()
def test_log_gate_accepts_complete_failure_preserving_log(inputs):
 r=evaluate_financial_p3_research_log_gate(*inputs);assert r.gate_status=="accepted" and (r.configuration_entry_count,r.result_entry_count,r.failure_entry_count,r.lineage_entry_count)==(3,4,17,4)
def test_log_gate_is_deterministic(inputs):
 a,b=evaluate_financial_p3_research_log_gate(*inputs),evaluate_financial_p3_research_log_gate(*inputs);assert a.content_hash==b.content_hash and serialize_research_log_gate(a)==serialize_research_log_gate(b)
def test_assembly_or_failure_removal_blocks(inputs):
 log,assembly=inputs;assert evaluate_financial_p3_research_log_gate(log,replace(assembly,output_fingerprint="drift")).gate_status=="blocked"
 bad_log=replace(log,failure_references={**log.failure_references,"entries":log.failure_references["entries"][:-1]});assert evaluate_financial_p3_research_log_gate(bad_log,assembly).gate_status=="blocked"
def test_type_rejected(inputs):
 with pytest.raises(TypeError):evaluate_financial_p3_research_log_gate(None,inputs[1])
