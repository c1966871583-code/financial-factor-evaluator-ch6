from dataclasses import replace

import pytest

from backend.amr.financial_p3_research_log_lineage import (
 collect_financial_p3_research_log_lineage,
 serialize_research_log_lineage,
)
from tests.fixtures.synthetic_financial_p3_research_log_lineage_cases import (
 CONTROL,
 HEAD,
 make_inputs_for_log,
 make_snapshot,
)


def test_collects_four_frozen_lineage_references():
 s=make_snapshot();assert [x[0] for x in s.entries]==["lineage-schema","lineage-summary","lineage-bad-data","lineage-task-gate"]
 assert s.entries[-1][1]["repository_head"]==HEAD and s.entries[-1][1]["control_sha256"]==CONTROL
def test_lineage_snapshot_is_deterministic():
 a,b=make_snapshot(),make_snapshot();assert a.content_hash==b.content_hash and serialize_research_log_lineage(a)==serialize_research_log_lineage(b)
def test_ready_task_gate_alias_is_accepted():
 values=list(make_inputs_for_log());values[-1]=replace(values[-1],gate_status="ready")
 assert collect_financial_p3_research_log_lineage(*values,repository_head=HEAD,control_sha256=CONTROL).entries[-1][0]=="lineage-task-gate"
def test_task_gate_or_environment_drift_rejected():
 values=list(make_inputs_for_log());values[-1]=replace(values[-1],output_fingerprint="drift")
 with pytest.raises(ValueError):collect_financial_p3_research_log_lineage(*values,repository_head=HEAD,control_sha256=CONTROL)
 with pytest.raises(ValueError):collect_financial_p3_research_log_lineage(*make_inputs_for_log(),repository_head="bad",control_sha256=CONTROL)
