from dataclasses import replace

import pytest

from backend.amr.financial_p3_research_log_results import (
 collect_financial_p3_research_log_results,
 serialize_research_log_results,
)
from tests.fixtures.synthetic_financial_p3_research_log_result_cases import (
 make_inputs_for_log,
 make_snapshot,
)


def test_collects_track_and_overall_references_only():
 s=make_snapshot();assert [x[0] for x in s.entries]==["result-track-m","result-track-f","result-track-r","result-overall"]
 assert s.entries[-1][1]["overall_evidence_assessment"]=="insufficient_evidence" and s.entries[-1][1]["production_status"]=="not production ready"
def test_result_snapshot_is_deterministic():
 a,b=make_snapshot(),make_snapshot();assert a.content_hash==b.content_hash and serialize_research_log_results(a)==serialize_research_log_results(b)
def test_ready_task_and_accepted_summary_aliases_are_accepted():
 summary,gate=make_inputs_for_log();summary=replace(summary,audit=replace(summary.audit,gate_status="accepted"));gate=replace(gate,gate_status="ready")
 assert collect_financial_p3_research_log_results(summary,gate).entries[-1][0]=="result-overall"
def test_task_gate_drift_rejected():
 summary,gate=make_inputs_for_log()
 with pytest.raises(ValueError):collect_financial_p3_research_log_results(summary,replace(gate,output_fingerprint="drift"))
def test_type_rejected():
 with pytest.raises(TypeError):collect_financial_p3_research_log_results(None,make_inputs_for_log()[1])
