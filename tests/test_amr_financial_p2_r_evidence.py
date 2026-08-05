"""Acceptance tests for FIN-P2-R risk evidence."""

from __future__ import annotations

import copy

import pytest

from backend.amr.financial_p2_r_evidence import (
    R_LABEL_STATES,
    R_REVIEW_BOUNDARY,
    FinancialP2REvidenceConfig,
    evaluate_financial_p2_r_evidence,
)
from tests.fixtures.synthetic_financial_p2_r_evidence_cases import (
    AS_OF,
    REPORT_PERIODS,
    clone_records,
    company_cohorts,
    configuration,
    expected_split,
    make_golden_records,
    make_record,
)


@pytest.fixture(scope="module")
def records():
    return make_golden_records()


@pytest.fixture(scope="module")
def golden(records):
    return evaluate_financial_p2_r_evidence(
        records, configuration=configuration()
    )


def _codes(result):
    return {item.code for item in result.evidence_audit.errors}


class TestTransparentRiskEvidence:
    def test_golden_case_is_ready(self, golden):
        assert golden.evidence_audit.gate_status == "ready"
        assert golden.evidence_audit.errors == ()
        assert len(golden.screening_rows) == 120
        assert len(golden.review_queue) == 10

    def test_all_four_label_states_are_preserved(self, golden):
        counts = dict(golden.evidence_audit.label_state_counts)
        assert set(counts) == set(R_LABEL_STATES)
        assert counts == dict(
            golden.evidence_audit.effective_label_state_counts
        )
        assert counts["hard_positive"] == 34
        assert counts["confirmed_negative"] == 44
        assert counts["soft_positive"] == 20
        assert counts["unlabeled"] == 22

    def test_unlabeled_is_never_coerced_to_negative(self, golden):
        unknown = [
            row
            for row in golden.screening_rows
            if row.declared_label_state == "unlabeled"
        ]
        assert unknown
        assert {row.effective_label_state for row in unknown} == {
            "unlabeled"
        }
        supervised = golden.supervised_evidence
        assert supervised.train_observation_count == 48
        assert supervised.test_observation_count == 30

    def test_transparent_rule_points_are_exact(self):
        row = make_record(
            "SYNEXACT", REPORT_PERIODS[0], "unlabeled"
        )
        row.update(
            {
                "total_liabilities": 90.0,
                "operating_cash_flow": 0.0,
                "receivables_growth_anomaly": True,
                "inventory_growth_anomaly": True,
                "other_receivables_anomaly": True,
                "non_recurring_or_asset_anomaly": True,
                "audit_opinion": "qualified",
                "restated": True,
            }
        )
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        screened = result.screening_rows[0]
        assert screened.transparent_score == 118
        assert screened.risk_level == "strong_warning"
        assert len(screened.evidence) == 8

    def test_negative_profit_positive_cash_rule(self):
        row = make_record("SYNDIVERGE", REPORT_PERIODS[0], "unlabeled")
        row.update(
            {
                "total_liabilities": 50.0,
                "net_profit": -1.0,
                "operating_cash_flow": 2.0,
                "receivables_growth_anomaly": False,
                "inventory_growth_anomaly": False,
                "other_receivables_anomaly": False,
                "non_recurring_or_asset_anomaly": False,
                "audit_opinion": "standard_unqualified",
                "restated": False,
            }
        )
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        screened = result.screening_rows[0]
        assert screened.transparent_score == 18
        assert screened.risk_level == "review"

    def test_financial_sector_does_not_use_corporate_leverage_rule(self):
        row = make_record("SYNBANK", REPORT_PERIODS[0], "unlabeled")
        row.update(
            {
                "sector_type": "bank",
                "total_liabilities": 99.0,
                "operating_cash_flow": 9.0,
                "receivables_growth_anomaly": False,
                "inventory_growth_anomaly": False,
                "other_receivables_anomaly": False,
                "non_recurring_or_asset_anomaly": False,
                "audit_opinion": "standard_unqualified",
                "restated": False,
            }
        )
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        assert result.screening_rows[0].transparent_score == 0

    def test_missingness_is_preserved_not_zero_filled(self):
        row = make_record("SYNMISS", REPORT_PERIODS[0], "unlabeled")
        row["total_assets"] = None
        row["inventory_growth_anomaly"] = None
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        screened = result.screening_rows[0]
        assert screened.data_quality == "partial"
        assert "total_assets" in screened.missing_fields
        assert "inventory_growth_anomaly" in screened.missing_fields

    def test_review_queue_uses_transparent_order_and_stable_ties(
        self, golden
    ):
        queue = golden.review_queue
        assert [item.rank for item in queue] == list(range(1, 11))
        order = [
            (-item.transparent_score, item.symbol, item.report_period)
            for item in queue
        ]
        assert order == sorted(order)

    def test_output_boundary_is_review_priority_only(self, golden):
        assert golden.evidence_audit.conclusion_boundary == R_REVIEW_BOUNDARY
        assert all(
            item.conclusion_boundary == R_REVIEW_BOUNDARY
            for item in golden.review_queue
        )
        payload = golden.to_dict()
        assert "trade_signal" not in payload
        assert "fraud_determination" not in payload


class TestLabelSafeSupervision:
    def test_supervised_metrics_are_completed(self, golden):
        evidence = golden.supervised_evidence
        assert evidence.status == "completed"
        assert evidence.reason_code is None
        assert evidence.hard_positive_company_count == 17
        assert evidence.train_hard_positive_count == 24
        assert evidence.test_hard_positive_count == 10

    def test_primary_metrics_are_all_explicit(self, golden):
        evidence = golden.supervised_evidence
        assert 0.0 <= evidence.pr_auc <= 1.0
        assert 0.0 <= evidence.roc_auc <= 1.0
        assert 0.0 <= evidence.brier_score <= 1.0
        assert 0.0 <= evidence.top_k_hit_rate <= 1.0
        assert 0.0 <= evidence.expected_calibration_error <= 1.0
        assert len(evidence.calibration) == 5
        assert evidence.negative_control_status == "completed"
        assert 0.0 <= evidence.negative_control_pr_auc <= 1.0
        assert 0.0 <= evidence.negative_control_roc_auc <= 1.0

    def test_company_split_is_disjoint_and_label_independent(
        self, golden
    ):
        by_symbol = {}
        for row in golden.screening_rows:
            by_symbol.setdefault(row.symbol, set()).add(row.split)
            assert row.split == expected_split(row.symbol)
        assert all(len(values) == 1 for values in by_symbol.values())
        train = {
            symbol
            for symbol, values in by_symbol.items()
            if values == {"train"}
        }
        test = set(by_symbol) - train
        assert train.isdisjoint(test)

    def test_soft_positive_is_excluded_from_binary_metrics(
        self, golden
    ):
        evidence = golden.supervised_evidence
        assert evidence.excluded_label_states == (
            "soft_positive",
            "unlabeled",
        )
        assert (
            evidence.train_observation_count
            + evidence.test_observation_count
            == 78
        )

    def test_model_scores_are_descriptive_and_bounded(self, golden):
        assert all(
            row.model_risk_score is not None
            and 0.0 <= row.model_risk_score <= 1.0
            for row in golden.screening_rows
        )

    def test_hard_positive_shortage_is_not_run(self):
        cohort = company_cohorts()
        keep = set(cohort["train_hard"][:3]) | set(
            cohort["test_hard"][:2]
        )
        records = [
            row
            for row in make_golden_records()
            if row["label_state"] != "hard_positive"
            or row["symbol"] in keep
        ]
        result = evaluate_financial_p2_r_evidence(
            records, configuration=configuration()
        )
        evidence = result.supervised_evidence
        assert result.evidence_audit.gate_status == "ready"
        assert evidence.status == "not_run"
        assert evidence.reason_code == "HARD_POSITIVES_INSUFFICIENT"
        assert result.screening_rows
        assert result.review_queue
        assert all(
            row.model_risk_score is None
            for row in result.screening_rows
        )

    def test_late_label_becomes_unlabeled_not_negative(self):
        row = make_record(
            "SYNLATELABEL", REPORT_PERIODS[0], "hard_positive"
        )
        row["label_available_at"] = "2025-05-01"
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        screened = result.screening_rows[0]
        assert screened.declared_label_state == "hard_positive"
        assert screened.effective_label_state == "unlabeled"
        assert "LABEL_NOT_YET_AVAILABLE" in {
            item.code for item in result.evidence_audit.warnings
        }


class TestDeterminismAndAudit:
    def test_repeated_run_is_byte_semantically_equal(self, records, golden):
        repeated = evaluate_financial_p2_r_evidence(
            clone_records(records), configuration=configuration()
        )
        assert repeated.to_dict() == golden.to_dict()

    def test_input_order_does_not_change_result(self, records, golden):
        shuffled = list(reversed(clone_records(records)))
        result = evaluate_financial_p2_r_evidence(
            shuffled, configuration=configuration()
        )
        assert result.to_dict() == golden.to_dict()

    def test_input_is_not_mutated(self, records):
        candidate = clone_records(records)
        before = copy.deepcopy(candidate)
        evaluate_financial_p2_r_evidence(
            candidate, configuration=configuration()
        )
        assert candidate == before

    def test_all_audit_fingerprints_are_sha256(self, golden):
        audit = golden.evidence_audit
        values = (
            audit.configuration_fingerprint,
            audit.input_fingerprint,
            audit.financial_input_fingerprint,
            audit.label_input_fingerprint,
            audit.split_fingerprint,
            audit.output_fingerprint,
            audit.content_hash,
            golden.supervised_evidence.model_fingerprint,
            golden.supervised_evidence.negative_control_fingerprint,
            golden.supervised_evidence.content_hash,
        )
        assert all(len(value) == 64 for value in values)

    def test_lookup_is_strict(self, golden):
        row = golden.screening_rows[0]
        assert (
            golden.get_row(row.symbol, row.report_period).content_hash
            == row.content_hash
        )
        with pytest.raises(LookupError):
            golden.get_row("UNKNOWN", REPORT_PERIODS[0])
        with pytest.raises(ValueError):
            golden.get_row("", REPORT_PERIODS[0])


class TestFailClosedStates:
    def test_future_financial_announcement_blocks(self):
        row = make_record("SYNFUTURE", REPORT_PERIODS[0], "unlabeled")
        row["announced_at"] = "2025-05-01"
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        assert result.screening_rows == ()
        assert "FUTURE_FINANCIAL_ANNOUNCEMENT" in _codes(result)

    def test_duplicate_company_period_blocks(self):
        row = make_record("SYNDUP", REPORT_PERIODS[0], "unlabeled")
        result = evaluate_financial_p2_r_evidence(
            [row, copy.deepcopy(row)], configuration=configuration()
        )
        assert "DUPLICATE_RECORD_KEY" in _codes(result)

    def test_invalid_label_state_blocks(self):
        row = make_record("SYNLABEL", REPORT_PERIODS[0], "unlabeled")
        row["label_state"] = "negative_by_default"
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        assert "INVALID_LABEL_STATE" in _codes(result)

    def test_labeled_record_requires_timing_and_source(self):
        row = make_record("SYNSOURCE", REPORT_PERIODS[0], "hard_positive")
        row["label_source_url"] = None
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        assert "LABEL_METADATA_MISSING" in _codes(result)

    def test_non_synthetic_input_blocks(self):
        row = make_record("SYNREAL", REPORT_PERIODS[0], "unlabeled")
        row["provenance"]["synthetic_test_only"] = False
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        assert "NON_SYNTHETIC_INPUT" in _codes(result)

    def test_invalid_numeric_value_blocks(self):
        row = make_record("SYNNAN", REPORT_PERIODS[0], "unlabeled")
        row["total_assets"] = float("nan")
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        assert "INVALID_NUMERIC_VALUE" in _codes(result)

    def test_invalid_top_level_inputs_block(self):
        result = evaluate_financial_p2_r_evidence(
            None, configuration=configuration()
        )
        assert "INVALID_RECORDS" in _codes(result)
        invalid_config = evaluate_financial_p2_r_evidence(
            [], configuration=None
        )
        assert "INVALID_CONFIGURATION" in _codes(invalid_config)

    def test_empty_input_blocks(self):
        result = evaluate_financial_p2_r_evidence(
            [], configuration=configuration()
        )
        assert "INVALID_RECORDS" in _codes(result)

    def test_non_boolean_rule_flag_blocks(self):
        row = make_record("SYNBOOL", REPORT_PERIODS[0], "unlabeled")
        row["restated"] = "yes"
        result = evaluate_financial_p2_r_evidence(
            [row], configuration=configuration()
        )
        assert "INVALID_RECORD" in _codes(result)

    @pytest.mark.parametrize(
        "kwargs",
        (
            {"top_k": 0},
            {"test_fraction": 1.0},
            {"minimum_hard_positives": 9},
            {"calibration_bins": 1},
            {"synthetic_test_only": False},
        ),
    )
    def test_invalid_configuration_rejected(self, kwargs):
        with pytest.raises((TypeError, ValueError)):
            FinancialP2REvidenceConfig(as_of=AS_OF, **kwargs)
