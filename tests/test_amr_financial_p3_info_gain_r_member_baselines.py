"""Contract tests for INFO-GAIN-02D formal R-track not_run baselines."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

import backend.amr.financial_p3_info_gain_r_member_baselines as subject
from backend.amr.financial_p3_info_gain_r_member_baselines import *
from tests.fixtures.synthetic_financial_p3_info_gain_r_member_baseline_cases import (
    make_configuration,
    make_prepared_inputs,
)


@pytest.fixture(scope="module")
def prepared(): return make_prepared_inputs()
@pytest.fixture(scope="module")
def result(prepared): return evaluate_financial_p3_info_gain_r_member_baselines(prepared,configuration=make_configuration())

def test_golden_formal_not_run(result):
    assert result.audit.gate_status == "ready"
    assert result.audit.input_fingerprint == ACCEPTED_02A
    assert result.audit.output_fingerprint == "91ead71b3767a31ad0fb23cdff91c9c6372a8d77bbd68d552b23ebc4cf7a2e2e"
    assert result.audit.content_hash == "f2d07280cb347378b5cbf180de5f55fdb39a472d9dbc5a65ac7c927cadec4a23"
    assert (result.audit.member_run_count,result.audit.completed_run_count,result.audit.not_run_count)==(11,0,11)

def test_every_member_has_explicit_non_numeric_r_metrics(result):
    assert tuple(x.combo_id for x in result.bundles)==("VQ","QG","CASHQ")
    for bundle in result.bundles:
        assert bundle.calculation_status == "not_run"
        assert tuple((x.member_factor_id,x.frozen_direction) for x in bundle.member_runs)==DIRECTIONS[bundle.combo_id]
        for run in bundle.member_runs:
            assert run.calculation_status == "not_run" and run.not_run_reason == NOT_RUN_REASON
            assert dict(run.metric_statuses)=={m:"not_run" for m in METRICS}
            assert dict(run.metric_values)=={m:None for m in METRICS}

def test_no_risk_label_evaluator_or_conclusion_work(result):
    a=result.audit
    assert (a.r_evaluator_call_count,a.m_evaluator_call_count,a.f_evaluator_call_count)==(0,0,0)
    assert a.risk_labels_constructed is False and a.metrics_calculated is False
    assert a.combination_evaluated is False and a.strongest_member_selected is False and a.information_gain_calculated is False
    assert "fraud/misstatement conclusion" in a.conclusion_boundary

def test_r_evaluator_hash_pinned(result):
    assert result.audit.evaluator_source_sha256 == R_EVALUATOR_HASH
    assert subject._evaluator_hash() == R_EVALUATOR_HASH

def test_input_immutable_and_serialization_deterministic(prepared,result):
    before=prepared.to_dict(); repeated=evaluate_financial_p3_info_gain_r_member_baselines(prepared,configuration=make_configuration())
    assert prepared.to_dict()==before
    text=serialize_r_member_baseline_result(result)
    assert text==serialize_r_member_baseline_result(repeated)
    assert json.loads(text)["audit"]["gate_status"]=="ready" and "NaN" not in text

@pytest.mark.parametrize(("field","value"),[("run_id",""),("accepted_02a_output_fingerprint","0"*64),("accepted_contract_hash","0"*64),("expected_evaluator_source_sha256","0"*64),("synthetic_test_only",False)])
def test_config_drift_rejected(field,value):
    with pytest.raises(ValueError): make_configuration(**{field:value})

def test_input_fingerprint_drift_blocks(prepared):
    drifted=dataclasses.replace(prepared,audit=dataclasses.replace(prepared.audit,output_fingerprint="0"*64))
    r=evaluate_financial_p3_info_gain_r_member_baselines(drifted,configuration=make_configuration())
    assert r.audit.gate_status=="blocked" and "INFO_GAIN_02A_FINGERPRINT_MISMATCH" in {x.code for x in r.audit.errors}

def test_r_context_ready_drift_blocks_not_evaluates(prepared):
    p=prepared.packages[0]; old=next(x for x in p.track_inputs if x.track_id=="R")
    changed=dataclasses.replace(old,preparation_status="ready",evaluation_contexts=("R",),label_references=("forbidden",),evaluation_config_reference="forbidden")
    p2=dataclasses.replace(p,track_inputs=tuple(changed if x.track_id=="R" else x for x in p.track_inputs))
    r=evaluate_financial_p3_info_gain_r_member_baselines(dataclasses.replace(prepared,packages=(p2,*prepared.packages[1:])),configuration=make_configuration())
    assert r.audit.gate_status=="blocked" and r.audit.r_evaluator_call_count==0 and "R_CONTEXT_STATE_DRIFT" in {x.code for x in r.audit.errors}

def test_evaluator_hash_drift_blocks(prepared,monkeypatch):
    monkeypatch.setattr(subject,"_evaluator_hash",lambda:"0"*64)
    r=evaluate_financial_p3_info_gain_r_member_baselines(prepared,configuration=make_configuration())
    assert r.audit.gate_status=="blocked" and "R_EVALUATOR_HASH_MISMATCH" in {x.code for x in r.audit.errors}

def test_r_evaluator_never_called(prepared,monkeypatch):
    monkeypatch.setattr(subject,"evaluate_financial_p2_r_evidence",lambda *a,**k:(_ for _ in ()).throw(AssertionError("must not call")))
    monkeypatch.setattr(subject,"_evaluator_hash",lambda:R_EVALUATOR_HASH)
    assert evaluate_financial_p3_info_gain_r_member_baselines(prepared,configuration=make_configuration()).audit.gate_status=="ready"

def test_no_risk_batch_or_classifier_is_constructed():
    src=Path(subject.__file__).read_text(encoding="utf-8")
    assert "FinancialP2REvidenceConfig" not in src and "FinancialRisk" not in src and "evaluate_financial_p2_r_evidence(" not in src

def test_type_checks_and_frozen_config(prepared):
    with pytest.raises(TypeError): evaluate_financial_p3_info_gain_r_member_baselines(object(),configuration=make_configuration())
    with pytest.raises(TypeError): serialize_r_member_baseline_result(object())
    c=RMemberBaselineConfig(run_id="frozen")
    with pytest.raises(dataclasses.FrozenInstanceError): c.run_id="x"
