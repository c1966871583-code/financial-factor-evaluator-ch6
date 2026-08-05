from dataclasses import replace
import pytest
from backend.amr.financial_p3_info_gain_bad_data_gate import BadDataCase,run_financial_p3_info_gain_bad_data_gate,serialize_financial_p3_info_gain_bad_data_gate
from tests.fixtures.synthetic_financial_p3_info_gain_bad_data_cases import make_corpus
def test_frozen_corpus_passes_and_reports_every_case():
 result=run_financial_p3_info_gain_bad_data_gate(make_corpus());assert result.audit.gate_status=="ready" and result.audit.case_count==15 and result.audit.passed_case_count==15
 assert all(x.failure_record_preserved and x.passed for x in result.reports) and not result.audit.silent_zero_fill_detected and result.audit.input_objects_unchanged
def test_required_severity_and_isolation_behaviors():
 result=run_financial_p3_info_gain_bad_data_gate(make_corpus());actual={x.case_id:x.actual_behavior for x in result.reports}
 assert actual["pit_time_violation"]==actual["revision_leakage"]==actual["common_sample_drift"]==actual["contract_conflict"]=="task_blocked"
 assert actual["duplicate_primary_key"]==actual["many_to_many_join"]=="record_isolated" and actual["f_track_not_evaluable"]=="track_not_evaluable"
def test_identical_corpus_is_deterministic():
 a=run_financial_p3_info_gain_bad_data_gate(make_corpus());b=run_financial_p3_info_gain_bad_data_gate(make_corpus());assert a.audit.content_hash==b.audit.content_hash and serialize_financial_p3_info_gain_bad_data_gate(a)==serialize_financial_p3_info_gain_bad_data_gate(b)
def test_unexpected_severe_behavior_fails_gate():
 corpus=list(make_corpus());corpus[5]=replace(corpus[5],expected_behavior="fail_fast");result=run_financial_p3_info_gain_bad_data_gate(tuple(corpus));assert result.audit.gate_status=="blocked" and result.audit.failed_case_count==1
def test_invalid_corpus_rejected():
 with pytest.raises(TypeError):run_financial_p3_info_gain_bad_data_gate(())
 with pytest.raises(ValueError):run_financial_p3_info_gain_bad_data_gate((BadDataCase("a","x","fail_fast","x",{}),BadDataCase("a","x","fail_fast","x",{})))
