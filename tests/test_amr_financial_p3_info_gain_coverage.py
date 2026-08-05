import dataclasses,json,pytest
from backend.amr.financial_p3_info_gain_coverage import *
from tests.fixtures.synthetic_financial_p3_info_gain_coverage_cases import make_inputs,make_configuration
@pytest.fixture(scope="module")
def inputs():return make_inputs()
@pytest.fixture(scope="module")
def result(inputs):return report_financial_p3_info_gain_coverage(*inputs,configuration=make_configuration())
def test_golden(result):
 assert result.audit.gate_status=="ready" and result.audit.combo_count==3 and result.audit.member_coverage_count==11
def test_common_sample_and_periods(result):
 for x in result.combos:assert x.eligible_sample_count==1044 and x.common_sample_count==900 and len(x.per_period_common_counts)==18 and {n for _,n in x.per_period_common_counts}=={50} and not x.insufficient_sample_periods
def test_member_set_excludes_cashq_reference_factor(result):assert {m.member_factor_id for m in result.combos[2].member_coverages}=={"ROA","OCF_SALES","ACCRUALS"}
def test_loss_is_reported_not_used_for_selection(result):
 a=result.audit;assert a.sample_reconstructed is False and a.combination_removed_for_coverage is False and a.information_gain_assessment_made is False
 assert all(m.absolute_coverage_loss>=0 for x in result.combos for m in x.member_coverages)
def test_deterministic(inputs,result):assert serialize_coverage_result(result)==serialize_coverage_result(report_financial_p3_info_gain_coverage(*inputs,configuration=make_configuration()))
@pytest.mark.parametrize(("field","value"),[("run_id",""),("accepted_combination_fingerprint","0"*64),("accepted_input_fingerprint","0"*64),("synthetic_test_only",False)])
def test_config(field,value):
 with pytest.raises(ValueError):make_configuration(**{field:value})
def test_drift_blocks(inputs):
 c,i=inputs;bad=dataclasses.replace(i,audit=dataclasses.replace(i.audit,output_fingerprint="0"*64));assert report_financial_p3_info_gain_coverage(c,bad,configuration=make_configuration()).audit.gate_status=="blocked"
def test_types(inputs):
 with pytest.raises(TypeError):report_financial_p3_info_gain_coverage(object(),inputs[1],configuration=make_configuration())
