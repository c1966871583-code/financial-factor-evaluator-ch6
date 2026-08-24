import dataclasses
import hashlib
import json

import pytest

import backend.amr.financial_p3_combinations as combinations_subject
from backend.amr.financial_fingerprint import canonicalize_financial_fingerprint
from backend.amr.financial_p3_info_gain_coverage import *
from tests.fixtures.synthetic_financial_p3_info_gain_coverage_cases import (
 make_configuration,
 make_inputs,
)


@pytest.fixture(scope="module")
def inputs():return make_inputs()
@pytest.fixture(scope="module")
def result(inputs):return report_financial_p3_info_gain_coverage(*inputs,configuration=make_configuration())
def test_combination_fingerprint_is_cross_platform(inputs):
 assert inputs[0].combinations_audit.output_fingerprint == COMBO_FP, f"expected={COMBO_FP}, actual={inputs[0].combinations_audit.output_fingerprint}"
def test_combination_first_differing_semantic_component(inputs):
 expected={
  "VQ":{"definition":"51075dc972613c31e243ea4099d3fd47963881f4c98e6ff6b88d19eb2fefcf01","construction_audit":"d5fda31c9351488b9aa2dbd2fc0eaf20f60973c04b4e37dbb7ab3efb7816b94f","comparison":"cdc9427c57b674d7a923c8c5edda33e993842100b7dd4a2ebe0812a82e8a679e","common_sample_audit":"b6b8e1fb71de10d22d4aeee7237b64338742797d62feff4b1cf0944c3a1aea48"},
  "QG":{"definition":"8beec978644bb8dad09e1e91d88ecf588b2cb7a0bfad40d1b1f2ad725f9f31a1","construction_audit":"b87bf99c6567d404b06f3785f75544aa834d043cdefd1e6cf77a361d0fd14234","comparison":"5200fb2047431da6216cd8d16c90dcb2db9acd9cb30fc3285e97fa536b96a44b","common_sample_audit":"b97c491cdbee8799c6a053766f3e7fc485bcf1b0d896995d540527ed34f1a4c0"},
  "CASHQ":{"definition":"0764eb05a82d5dd458277e314f1d3fc68756879f8992c0e7e2f1360a37d7e510","construction_audit":"9abb3b383b0cc8a3b4f101890e42df872763a646242decafc8fb90c1874ed1d3","comparison":"10e7a8206ef43dba33cd264fbe7dc9427177c74d5bbd799a18d731f1f2afc9bd","common_sample_audit":"fb73298c94d40420b57b0468e4fe60661976b76e81a7bad0cc8dc5695e9d0dde"},
 }
 actual={}
 for experiment in inputs[0].experiments:
  combo=experiment.definition.combination_id;actual[combo]={}
  for key,value in experiment.to_dict().items():
   if key=="content_hash":continue
   semantic=combinations_subject._without_nested_content_hashes(value)
   payload=json.dumps(canonicalize_financial_fingerprint(semantic,float_decimals=8),ensure_ascii=False,sort_keys=True,separators=(",",":"))
   actual[combo][key]=hashlib.sha256(payload.encode()).hexdigest()
 assert actual==expected,f"expected={expected}, actual={actual}"
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
