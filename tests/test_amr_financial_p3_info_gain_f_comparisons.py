import dataclasses

import pytest

from backend.amr.financial_p3_info_gain_f_comparisons import *
from tests.fixtures.synthetic_financial_p3_info_gain_f_comparison_cases import (
 make_configuration,
 make_inputs,
)


@pytest.fixture(scope="module")
def inputs():return make_inputs()
@pytest.fixture(scope="module")
def result(inputs):return compare_financial_p3_info_gain_f(*inputs,configuration=make_configuration())
def test_golden(result):
 assert result.audit.gate_status=="ready" and result.audit.comparison_count==result.audit.not_evaluable_count==55
 assert result.audit.output_fingerprint=="04998ae6e9bfda4fa0182b24d902d556879b438169438beacf67055997f77825"
 assert result.audit.content_hash=="a907eeb569860bf386cc6cbb903f74756d09a42a5fa00472d6241c178005671c"
def test_all_rows_are_formal_not_evaluable(result):
 assert {x.calculation_status for x in result.comparisons}=={"not_evaluable"};assert {x.reason_code for x in result.comparisons}=={"F_COMBO_AND_MEMBER_CONTEXT_NOT_FROZEN"};assert all(x.combo_metric_value is None and x.member_metric_value is None for x in result.comparisons)
def test_no_f_evaluator_or_selection(result):
 a=result.audit;assert a.F_evaluator_called is False and a.combo_results_recomputed is False and a.member_results_recomputed is False and a.strongest_member_selected is False and a.information_gain_assessment_made is False
def test_deterministic(inputs,result):assert serialize_f_info_gain_result(result)==serialize_f_info_gain_result(compare_financial_p3_info_gain_f(*inputs,configuration=make_configuration()))
@pytest.mark.parametrize(("field","value"),[("run_id",""),("accepted_combination_fingerprint","0"*64),("accepted_member_fingerprint","0"*64),("accepted_contract_hash","0"*64),("synthetic_test_only",False)])
def test_config_rejects_drift(field,value):
 with pytest.raises(ValueError):make_configuration(**{field:value})
def test_predecessor_drift_blocks(inputs):
 c,m=inputs;bad=dataclasses.replace(m,audit=dataclasses.replace(m.audit,output_fingerprint="0"*64));assert compare_financial_p3_info_gain_f(c,bad,configuration=make_configuration()).audit.gate_status=="blocked"
def test_type_checks(inputs):
 with pytest.raises(TypeError):compare_financial_p3_info_gain_f(object(),inputs[1],configuration=make_configuration())
 with pytest.raises(TypeError):serialize_f_info_gain_result(object())
