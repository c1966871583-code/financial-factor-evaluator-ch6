from dataclasses import replace

import pytest

from backend.amr.financial_p3_research_log_failures import (
 collect_financial_p3_research_log_failures,
 serialize_research_log_failures,
)
from tests.fixtures.synthetic_financial_p3_research_log_failure_cases import (
 make_inputs_for_log,
 make_snapshot,
)


def test_preserves_every_bad_data_case_and_unfinished_track():
 s=make_snapshot();assert len(s.entries)==17 and sum(x[0].startswith("failure-bad-data-") for x in s.entries)==15
 assert [x[0] for x in s.entries[-2:]]==["unfinished-track-f","unfinished-track-r"] and all(x[1]["status"]=="not_evaluable" for x in s.entries[-2:])
def test_failure_snapshot_is_deterministic():
 a,b=make_snapshot(),make_snapshot();assert a.content_hash==b.content_hash and serialize_research_log_failures(a)==serialize_research_log_failures(b)
def test_accepted_summary_alias_is_accepted():
 bad,summary=make_inputs_for_log();summary=replace(summary,audit=replace(summary.audit,gate_status="accepted"))
 assert collect_financial_p3_research_log_failures(bad,summary).entries
def test_bad_data_drift_rejected():
 bad,summary=make_inputs_for_log()
 with pytest.raises(ValueError):collect_financial_p3_research_log_failures(replace(bad,audit=replace(bad.audit,output_fingerprint="drift")),summary)
def test_type_rejected():
 with pytest.raises(TypeError):collect_financial_p3_research_log_failures(None,make_inputs_for_log()[1])
