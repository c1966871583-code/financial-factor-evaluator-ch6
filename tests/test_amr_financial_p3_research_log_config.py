from dataclasses import replace
import pytest
from backend.amr.financial_p3_research_log_config import collect_financial_p3_research_log_config,serialize_research_log_config
from tests.fixtures.synthetic_financial_p3_research_log_config_cases import make_inputs_for_log,make_snapshot
def test_collects_only_three_configuration_entries():
 s=make_snapshot();assert [x[0] for x in s.entries]==["config-schema","config-info-gain","config-task-gate"]
 assert all("result" not in x[0] and "failure" not in x[0] for x in s.entries)
def test_config_snapshot_is_deterministic():
 a,b=make_snapshot(),make_snapshot();assert a.content_hash==b.content_hash and serialize_research_log_config(a)==serialize_research_log_config(b)
def test_task_gate_drift_rejected():
 values=list(make_inputs_for_log());values[-1]=replace(values[-1],output_fingerprint="drift")
 with pytest.raises(ValueError):collect_financial_p3_research_log_config(*values)
def test_type_rejected():
 with pytest.raises(TypeError):collect_financial_p3_research_log_config(None,*make_inputs_for_log()[1:])
