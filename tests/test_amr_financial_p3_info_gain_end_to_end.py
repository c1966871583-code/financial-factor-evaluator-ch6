import json
from pathlib import Path
from backend.amr.financial_p3_info_gain_summary import serialize_financial_p3_info_gain_summary
from backend.amr.financial_p3_info_gain_bad_data_gate import serialize_financial_p3_info_gain_bad_data_gate
from tests.fixtures.synthetic_financial_p3_info_gain_end_to_end_cases import run_pipeline
GOLDEN=Path(__file__).parent/"golden"/"financial_p3_info_gain_end_to_end.json"
def test_end_to_end_frozen_outputs_match_golden():
 summary,gate=run_pipeline();expected=json.loads(GOLDEN.read_text(encoding="utf-8"))
 assert summary.audit.gate_status==expected["summary_status"] and summary.audit.output_fingerprint==expected["summary_output_fingerprint"]
 assert gate.audit.gate_status==expected["bad_data_gate_status"] and gate.audit.output_fingerprint==expected["bad_data_gate_output_fingerprint"]
 assert [x.evidence_status for x in summary.tracks]==expected["track_statuses"]
def test_end_to_end_is_deterministic_and_non_production():
 a,b=run_pipeline(),run_pipeline()
 assert serialize_financial_p3_info_gain_summary(a[0])==serialize_financial_p3_info_gain_summary(b[0])
 assert serialize_financial_p3_info_gain_bad_data_gate(a[1])==serialize_financial_p3_info_gain_bad_data_gate(b[1])
 assert a[0].audit.production_status=="not production ready" and not a[0].audit.aggregate_information_gain_assessment_made
def test_gate_preserves_failures_without_zero_filling():
 _,gate=run_pipeline();assert gate.audit.case_count==15 and gate.audit.passed_case_count==15 and not gate.audit.silent_zero_fill_detected and gate.audit.input_objects_unchanged
 assert {x.actual_behavior for x in gate.reports}>={"record_isolated","period_not_evaluable","track_not_evaluable","task_blocked"}
