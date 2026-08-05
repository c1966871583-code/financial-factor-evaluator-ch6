import dataclasses,json,pytest
from backend.amr.financial_p3_info_gain_r_comparisons import *
from tests.fixtures.synthetic_financial_p3_info_gain_r_comparison_cases import make_inputs,make_configuration
@pytest.fixture(scope="module")
def inputs():return make_inputs()
@pytest.fixture(scope="module")
def result(inputs):return compare_financial_p3_info_gain_r(*inputs,configuration=make_configuration())
def test_golden(result):
 assert result.audit.gate_status=="ready" and result.audit.comparison_count==result.audit.not_evaluable_count==55
def test_statuses(result):assert {x.reason_code for x in result.comparisons}=={"R_COMBO_AND_MEMBER_CONTEXT_NOT_FROZEN"} and all(x.combo_metric_value is None and x.member_metric_value is None for x in result.comparisons)
def test_no_risk_work(result):
 a=result.audit;assert a.R_evaluator_called is False and a.risk_labels_constructed is False and a.strongest_member_selected is False and a.information_gain_assessment_made is False
def test_deterministic(inputs,result):assert serialize_r_info_gain_result(result)==serialize_r_info_gain_result(compare_financial_p3_info_gain_r(*inputs,configuration=make_configuration()))
@pytest.mark.parametrize(("field","value"),[("run_id",""),("accepted_combination_fingerprint","0"*64),("accepted_member_fingerprint","0"*64),("accepted_contract_hash","0"*64),("synthetic_test_only",False)])
def test_config(field,value):
 with pytest.raises(ValueError):make_configuration(**{field:value})
def test_drift_blocks(inputs):
 c,m=inputs;bad=dataclasses.replace(m,audit=dataclasses.replace(m.audit,output_fingerprint="0"*64));assert compare_financial_p3_info_gain_r(c,bad,configuration=make_configuration()).audit.gate_status=="blocked"
def test_types(inputs):
 with pytest.raises(TypeError):compare_financial_p3_info_gain_r(object(),inputs[1],configuration=make_configuration())
