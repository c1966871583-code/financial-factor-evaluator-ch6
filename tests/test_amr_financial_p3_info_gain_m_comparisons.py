from __future__ import annotations
import dataclasses,json
import pytest
from backend.amr.financial_p3_info_gain_m_comparisons import *
from tests.fixtures.synthetic_financial_p3_info_gain_m_comparison_cases import make_inputs,make_configuration

@pytest.fixture(scope="module")
def inputs(): return make_inputs()
@pytest.fixture(scope="module")
def result(inputs): return compare_financial_p3_info_gain_m(*inputs,configuration=make_configuration())
def test_golden_pairwise_result(result):
 assert result.audit.gate_status=="ready";assert (result.audit.combo_count,result.audit.member_count,result.audit.comparison_count)==(3,11,143)
 assert (result.audit.completed_comparison_count,result.audit.not_evaluable_count)==(66,77)
 assert result.audit.output_fingerprint=="6a9f764b450431582b5e5955e04dcc0e05978e543648e65d980e40b188ab0c64"
 assert result.audit.content_hash=="571175f58ca1678d9c2081c9916d1c5563077ebfcf3450493bcb678140994161"
def test_only_common_metrics_have_increments(result):
 rows=[r for c in result.combinations for r in c.member_comparisons]
 for r in rows:
  if r.metric_id in COMMON: assert r.calculation_status=="completed"
  else: assert r.calculation_status=="not_evaluable" and r.reason_code=="METRIC_NOT_AVAILABLE_ON_BOTH_SIDES"
def test_pairwise_not_strongest_selection(result):
 a=result.audit;assert a.strongest_member_selected is False and a.information_gain_assessment_made is False
 assert a.combo_results_recomputed is False and a.member_results_recomputed is False
 assert all("strongest" not in x.to_dict() for x in result.combinations)
def test_same_frozen_samples_and_metric_direction(result):
 for c in result.combinations:
  assert c.common_sample_fingerprint
  x=next(r for r in c.member_comparisons if r.metric_id=="rank_ic_mean")
  assert x.absolute_increment==pytest.approx(x.combo_metric_value-x.member_metric_value)
def test_serialization_deterministic(inputs,result):
 r=compare_financial_p3_info_gain_m(*inputs,configuration=make_configuration()); assert serialize_m_info_gain_result(result)==serialize_m_info_gain_result(r);assert json.loads(serialize_m_info_gain_result(r))["audit"]["gate_status"]=="ready"
@pytest.mark.parametrize(("field","value"),[("run_id",""),("accepted_combination_fingerprint","0"*64),("accepted_member_fingerprint","0"*64),("accepted_contract_hash","0"*64),("synthetic_test_only",False)])
def test_config_drift_rejected(field,value):
 with pytest.raises(ValueError):make_configuration(**{field:value})
def test_combo_or_member_drift_blocks(inputs):
 combos,members=inputs
 bad=dataclasses.replace(combos,combinations_audit=dataclasses.replace(combos.combinations_audit,output_fingerprint="0"*64))
 assert compare_financial_p3_info_gain_m(bad,members,configuration=make_configuration()).audit.gate_status=="blocked"
 badm=dataclasses.replace(members,audit=dataclasses.replace(members.audit,output_fingerprint="0"*64))
 assert compare_financial_p3_info_gain_m(combos,badm,configuration=make_configuration()).audit.gate_status=="blocked"
def test_type_checks(inputs):
 with pytest.raises(TypeError):compare_financial_p3_info_gain_m(object(),inputs[1],configuration=make_configuration())
 with pytest.raises(TypeError):serialize_m_info_gain_result(object())
