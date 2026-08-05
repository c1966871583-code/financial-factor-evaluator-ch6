from dataclasses import replace
import pytest
from backend.amr.financial_p3_info_gain_task_gate import evaluate_financial_p3_info_gain_task_gate,serialize_financial_p3_info_gain_task_gate
from tests.fixtures.synthetic_financial_p3_info_gain_task_gate_cases import make_inputs,make_configuration
@pytest.fixture(scope="module")
def inputs():return make_inputs()
def test_task_gate_accepts_research_but_not_production(inputs):
 out=evaluate_financial_p3_info_gain_task_gate(*inputs,configuration=make_configuration());assert out.gate_status=="accepted" and out.research_task_status=="ACCEPTED"
 assert out.overall_evidence_assessment=="insufficient_evidence" and out.admission_status=="not_assessed" and out.production_status=="not production ready"
def test_deterministic_serialization(inputs):
 a=evaluate_financial_p3_info_gain_task_gate(*inputs,configuration=make_configuration());b=evaluate_financial_p3_info_gain_task_gate(*inputs,configuration=make_configuration());assert serialize_financial_p3_info_gain_task_gate(a)==serialize_financial_p3_info_gain_task_gate(b)
@pytest.mark.parametrize("index",range(2))
def test_predecessor_drift_blocks(inputs,index):
 values=list(inputs);item=values[index];values[index]=replace(item,audit=replace(item.audit,output_fingerprint="drift"));assert evaluate_financial_p3_info_gain_task_gate(*values,configuration=make_configuration()).gate_status=="blocked"
def test_config_and_type_rejected(inputs):
 with pytest.raises(ValueError):make_configuration(accepted_summary_fingerprint="drift")
 with pytest.raises(TypeError):evaluate_financial_p3_info_gain_task_gate(None,inputs[1],configuration=make_configuration())
