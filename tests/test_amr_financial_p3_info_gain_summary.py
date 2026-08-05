from dataclasses import replace
import pytest
from backend.amr.financial_p3_info_gain_summary import summarize_financial_p3_info_gain,serialize_financial_p3_info_gain_summary
from tests.fixtures.synthetic_financial_p3_info_gain_summary_cases import make_inputs,make_configuration
@pytest.fixture(scope="module")
def inputs():return make_inputs()
@pytest.fixture
def result(inputs):return summarize_financial_p3_info_gain(*inputs,configuration=make_configuration())
def test_golden_status_summary(result):
 assert result.audit.gate_status=="ready" and [x.track_id for x in result.tracks]==["M","F","R"]
 assert [(x.completed_comparison_count,x.not_evaluable_count) for x in result.tracks]==[(66,77),(0,55),(0,55)]
def test_no_aggregate_conclusion(result):
 assert result.coverage_status=="reported_without_acceptance_threshold"
 assert not result.audit.aggregate_information_gain_assessment_made and not result.audit.cross_track_composite_calculated and not result.audit.strongest_member_selected
def test_serialization_is_deterministic(inputs,result):assert serialize_financial_p3_info_gain_summary(result)==serialize_financial_p3_info_gain_summary(summarize_financial_p3_info_gain(*inputs,configuration=make_configuration()))
@pytest.mark.parametrize("field,value",[("accepted_m_fingerprint","x"),("synthetic_test_only",False),("run_id","")])
def test_config_drift_rejected(field,value):
 with pytest.raises(ValueError):make_configuration(**{field:value})
@pytest.mark.parametrize("index",range(4))
def test_predecessor_drift_blocks(inputs,index):
 values=list(inputs);item=values[index];values[index]=replace(item,audit=replace(item.audit,output_fingerprint="drift"));out=summarize_financial_p3_info_gain(*values,configuration=make_configuration());assert out.audit.gate_status=="blocked"
def test_type_checks(inputs):
 with pytest.raises(TypeError):summarize_financial_p3_info_gain(None,*inputs[1:],configuration=make_configuration())
 with pytest.raises(TypeError):serialize_financial_p3_info_gain_summary(None)
