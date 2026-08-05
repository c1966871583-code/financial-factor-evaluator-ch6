"""FIN-R1A tests: announcement timing, effective date, and source adapter."""

import ast
import copy
import json
import runpy
from pathlib import Path

import pytest

from backend.amr.evaluation_input_contract import FinancialBatch
from backend.amr.financial_source_adapter import adapt_financial_source_records
from backend.amr.financial_timing import (
    ANNOUNCEMENT_TIMESTAMP_INVALID,
    ANNOUNCEMENT_TIMEZONE_UNVERIFIED,
    EFFECTIVE_DATE_BEFORE_PUBLICATION,
    EFFECTIVE_DATE_POLICY_MISMATCH,
    REVISION_EFFECTIVE_DATE_INVALID,
    RETURN_START_BEFORE_EFFECTIVE_DATE,
    TRADING_CALENDAR_UNAVAILABLE,
    FinancialTimingObservation,
    FinancialTimingPolicy,
    evaluate_financial_timing,
)


_FIXTURES = runpy.run_path(
    str(
        Path(__file__).resolve().parent
        / "fixtures"
        / "synthetic_financial_timing_cases.py"
    )
)
SYNTHETIC_TRADING_DAYS = _FIXTURES["SYNTHETIC_TRADING_DAYS"]
SYNTHETIC_TIMING_CASES = _FIXTURES["SYNTHETIC_TIMING_CASES"]
SYNTHETIC_SOURCE_RECORDS = _FIXTURES["SYNTHETIC_SOURCE_RECORDS"]


@pytest.fixture
def policy():
    return FinancialTimingPolicy(
        trading_days=SYNTHETIC_TRADING_DAYS,
        trading_calendar_version="synthetic-sse-szse-2024-v1",
    )


def _observation(**overrides):
    values = {
        "code": "SYN001",
        "publish_date": "2024-01-08",
        "announcement_timestamp": "2024-01-08T10:00:00+08:00",
        "announcement_timezone": "Asia/Shanghai",
        "statement_version": "original",
        "source_record_id": "synthetic-observation-1",
    }
    values.update(overrides)
    return FinancialTimingObservation(**values)


def _adapt(records, policy):
    return adapt_financial_source_records(
        records,
        factor_id="synthetic-financial-factor",
        version="v1",
        source="synthetic-fixture",
        policy=policy,
    )


class TestConservativeTimingPolicy:
    @pytest.mark.parametrize(
        "case",
        SYNTHETIC_TIMING_CASES,
        ids=[case["case_id"] for case in SYNTHETIC_TIMING_CASES],
    )
    def test_synthetic_timing_matrix(self, policy, case):
        audit = evaluate_financial_timing(
            _observation(
                publish_date=case["publish_date"],
                announcement_timestamp=case["announcement_timestamp"],
                announcement_timezone=case["announcement_timezone"],
            ),
            policy,
        )
        assert audit.overall_status == "passed"
        assert audit.market_session_classification == case["expected_session"]
        assert audit.derived_effective_date == case["expected_effective_date"]
        assert audit.timezone == "Asia/Shanghai"
        assert audit.timing_policy_version == "FIN-R1A-CONSERVATIVE-v1.0"

    def test_pre_market_is_not_same_day(self, policy):
        audit = evaluate_financial_timing(
            _observation(
                announcement_timestamp="2024-01-08T08:00:00+08:00"
            ),
            policy,
        )
        assert audit.market_session_classification == "pre_market"
        assert audit.derived_effective_date == "2024-01-09"
        assert audit.decision_reason_code == (
            "CONSERVATIVE_NEXT_TRADING_DAY_PRE_MARKET"
        )

    def test_policy_cannot_enable_same_day_without_new_gate(self):
        with pytest.raises(ValueError, match="not authorized"):
            FinancialTimingPolicy(
                trading_days=("2024-01-08", "2024-01-09"),
                trading_calendar_version="v1",
                pre_market_same_day_allowed=True,
            )

    def test_market_open_is_in_session(self, policy):
        audit = evaluate_financial_timing(
            _observation(
                announcement_timestamp="2024-01-08T09:30:00+08:00"
            ),
            policy,
        )
        assert audit.market_session_classification == "in_session"

    def test_market_close_is_post_market(self, policy):
        audit = evaluate_financial_timing(
            _observation(
                announcement_timestamp="2024-01-08T15:00:00+08:00"
            ),
            policy,
        )
        assert audit.market_session_classification == "post_market"

    def test_calendar_is_canonical_and_order_independent(self):
        policy = FinancialTimingPolicy(
            trading_days=("2024-01-09", "2024-01-08"),
            trading_calendar_version="v1",
        )
        assert policy.trading_days == ("2024-01-08", "2024-01-09")

    def test_duplicate_calendar_day_rejected(self):
        with pytest.raises(ValueError, match="duplicates"):
            FinancialTimingPolicy(
                trading_days=("2024-01-08", "2024-01-08"),
                trading_calendar_version="v1",
            )


class TestTimingFailures:
    def test_missing_future_calendar_blocks(self):
        policy = FinancialTimingPolicy(
            trading_days=(),
            trading_calendar_version="synthetic-empty-v1",
        )
        audit = evaluate_financial_timing(_observation(), policy)
        assert audit.overall_status == "blocked"
        assert audit.decision_reason_code == TRADING_CALENDAR_UNAVAILABLE

    def test_invalid_timestamp_blocks(self, policy):
        audit = evaluate_financial_timing(
            _observation(announcement_timestamp="not-a-timestamp"),
            policy,
        )
        assert audit.overall_status == "blocked"
        assert audit.decision_reason_code == ANNOUNCEMENT_TIMESTAMP_INVALID

    def test_timestamp_date_mismatch_blocks(self, policy):
        audit = evaluate_financial_timing(
            _observation(announcement_timestamp="2024-01-09T08:00:00+08:00"),
            policy,
        )
        assert audit.decision_reason_code == ANNOUNCEMENT_TIMESTAMP_INVALID

    def test_missing_declared_timezone_blocks(self, policy):
        audit = evaluate_financial_timing(
            _observation(announcement_timezone=None),
            policy,
        )
        assert audit.decision_reason_code == ANNOUNCEMENT_TIMEZONE_UNVERIFIED

    def test_wrong_offset_blocks(self, policy):
        audit = evaluate_financial_timing(
            _observation(announcement_timestamp="2024-01-08T02:00:00+00:00"),
            policy,
        )
        assert audit.decision_reason_code == ANNOUNCEMENT_TIMEZONE_UNVERIFIED

    def test_invalid_publish_date_fails_closed(self, policy):
        audit = evaluate_financial_timing(
            _observation(publish_date="2024-02-30"),
            policy,
        )
        assert audit.overall_status == "blocked"
        assert audit.derived_effective_date is None

    def test_provided_effective_before_publication_blocks(self, policy):
        audit = evaluate_financial_timing(
            _observation(provided_effective_date="2024-01-07"),
            policy,
        )
        assert audit.decision_reason_code == EFFECTIVE_DATE_BEFORE_PUBLICATION

    def test_provided_effective_mismatch_blocks(self, policy):
        audit = evaluate_financial_timing(
            _observation(provided_effective_date="2024-01-10"),
            policy,
        )
        assert audit.decision_reason_code == EFFECTIVE_DATE_POLICY_MISMATCH
        assert audit.effective_date_validation_status == "mismatch"

    def test_provided_effective_match_passes(self, policy):
        audit = evaluate_financial_timing(
            _observation(provided_effective_date="2024-01-09"),
            policy,
        )
        assert audit.overall_status == "passed"
        assert audit.effective_date_validation_status == "matched"

    def test_return_start_before_effective_blocks(self, policy):
        audit = evaluate_financial_timing(
            _observation(return_start_date="2024-01-08"),
            policy,
        )
        assert audit.decision_reason_code == RETURN_START_BEFORE_EFFECTIVE_DATE
        assert audit.return_start_validation_status == "blocked"

    def test_return_start_equal_effective_passes(self, policy):
        audit = evaluate_financial_timing(
            _observation(return_start_date="2024-01-09"),
            policy,
        )
        assert audit.overall_status == "passed"
        assert audit.return_start_validation_status == "passed"

    def test_audit_is_json_serializable(self, policy):
        audit = evaluate_financial_timing(_observation(), policy)
        json.dumps(audit.to_dict(), ensure_ascii=False, sort_keys=True)


class TestFinancialSourceAdapter:
    def test_builds_public_financial_batch(self, policy):
        result = _adapt(SYNTHETIC_SOURCE_RECORDS, policy)
        assert result.gate_result.overall_status == "ready"
        assert isinstance(result.batch, FinancialBatch)
        frame = result.batch.get_frame()
        assert list(frame.columns) == [
            "code",
            "report_period",
            "publish_date",
            "effective_date",
            "factor_value",
        ]
        assert frame["effective_date"].tolist() == ["2024-01-08", "2024-01-09"]

    def test_batch_provenance_contains_timing_versions(self, policy):
        result = _adapt(SYNTHETIC_SOURCE_RECORDS, policy)
        provenance = result.batch.provenance
        assert provenance["timing_policy_version"] == (
            "FIN-R1A-CONSERVATIVE-v1.0"
        )
        assert provenance["trading_calendar_version"] == (
            "synthetic-sse-szse-2024-v1"
        )
        assert provenance["synthetic_test_only"] is True

    def test_input_not_mutated(self, policy):
        records = copy.deepcopy(list(SYNTHETIC_SOURCE_RECORDS))
        original = copy.deepcopy(records)
        _adapt(records, policy)
        assert records == original

    def test_row_order_does_not_change_outputs_or_hashes(self, policy):
        forward = _adapt(SYNTHETIC_SOURCE_RECORDS, policy)
        reverse = _adapt(tuple(reversed(SYNTHETIC_SOURCE_RECORDS)), policy)
        assert forward.batch.get_frame().equals(reverse.batch.get_frame())
        assert forward.input_fingerprint == reverse.input_fingerprint
        assert forward.timing_audit_fingerprint == (
            reverse.timing_audit_fingerprint
        )
        assert forward.output_fingerprint == reverse.output_fingerprint

    def test_revision_keeps_both_versions(self, policy):
        original = dict(SYNTHETIC_SOURCE_RECORDS[0])
        revision = dict(original)
        revision.update(
            {
                "publish_date": "2024-01-08",
                "announcement_timestamp": "2024-01-08T16:00:00+08:00",
                "statement_version": "revision-1",
                "source_record_id": "synthetic-record-001-revision-1",
                "factor_value": 1.5,
            }
        )
        result = _adapt([revision, original], policy)
        frame = result.batch.get_frame()
        assert result.gate_result.overall_status == "ready"
        assert len(frame) == 2
        assert frame["effective_date"].tolist() == ["2024-01-08", "2024-01-09"]
        assert frame["factor_value"].tolist() == [1.25, 1.5]

    def test_same_day_revision_conflict_blocks(self, policy):
        original = dict(SYNTHETIC_SOURCE_RECORDS[0])
        revision = dict(original)
        revision.update(
            {
                "statement_version": "revision-1",
                "source_record_id": "synthetic-record-001-revision-1",
                "factor_value": 1.5,
            }
        )
        result = _adapt([original, revision], policy)
        assert result.batch is None
        error_codes = {
            issue.code for issue in result.gate_result.errors
        }
        assert REVISION_EFFECTIVE_DATE_INVALID in error_codes
        assert "DUPLICATE_FINANCIAL_TIMING_KEY" in error_codes

    def test_different_securities_do_not_cross_contaminate(self, policy):
        result = _adapt(SYNTHETIC_SOURCE_RECORDS, policy)
        frame = result.batch.get_frame()
        assert dict(zip(frame["code"], frame["factor_value"])) == {
            "SYN001": 1.25,
            "SYN002": -0.5,
        }

    def test_duplicate_source_record_id_blocks(self, policy):
        duplicate = dict(SYNTHETIC_SOURCE_RECORDS[1])
        duplicate["source_record_id"] = SYNTHETIC_SOURCE_RECORDS[0][
            "source_record_id"
        ]
        result = _adapt([SYNTHETIC_SOURCE_RECORDS[0], duplicate], policy)
        assert result.batch is None
        assert "DUPLICATE_SOURCE_RECORD_ID" in {
            issue.code for issue in result.gate_result.errors
        }

    def test_dynamic_formula_blocks_without_execution(self, policy):
        record = dict(SYNTHETIC_SOURCE_RECORDS[0])
        record["formula"] = "__import__('os').system('should-not-run')"
        result = _adapt([record], policy)
        assert result.batch is None
        assert result.gate_result.errors[0].code == "DYNAMIC_FORMULA_NOT_ALLOWED"

    def test_non_synthetic_input_blocks(self, policy):
        record = dict(SYNTHETIC_SOURCE_RECORDS[0])
        record["synthetic_test_only"] = False
        result = _adapt([record], policy)
        assert result.batch is None
        assert result.gate_result.errors[0].code == (
            "NON_SYNTHETIC_INPUT_NOT_AUTHORIZED"
        )

    def test_timing_failure_preserves_audit(self, policy):
        record = dict(SYNTHETIC_SOURCE_RECORDS[0])
        record["announcement_timezone"] = "UTC"
        result = _adapt([record], policy)
        assert result.batch is None
        assert len(result.timing_audits) == 1
        assert result.timing_audits[0].overall_status == "blocked"
        assert result.gate_result.overall_status == "blocked"

    @pytest.mark.parametrize("bad_value", ["abc", float("inf"), True])
    def test_non_finite_or_non_numeric_factor_value_blocks(
        self, policy, bad_value
    ):
        record = dict(SYNTHETIC_SOURCE_RECORDS[0])
        record["factor_value"] = bad_value
        result = _adapt([record], policy)
        assert result.batch is None
        assert result.gate_result.errors[0].code == "NON_NUMERIC_VALUE"

    def test_report_period_after_publication_blocks_at_contract(self, policy):
        record = dict(SYNTHETIC_SOURCE_RECORDS[0])
        record["report_period"] = "2025-01-01"
        result = _adapt([record], policy)
        assert result.batch is None
        assert "INVALID_DATE_ORDER" in {
            issue.code for issue in result.gate_result.errors
        }

    def test_empty_records_block(self, policy):
        result = _adapt([], policy)
        assert result.batch is None
        assert result.gate_result.errors[0].code == "EMPTY_SOURCE_RECORDS"

    def test_result_is_json_serializable(self, policy):
        result = _adapt(SYNTHETIC_SOURCE_RECORDS, policy)
        json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)

    def test_no_network_supabase_or_dynamic_execution_imports(self):
        root = Path(__file__).resolve().parents[1]
        imported_roots = set()
        for relative in (
            "backend/amr/financial_timing.py",
            "backend/amr/financial_source_adapter.py",
        ):
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_roots.update(
                        alias.name.split(".", 1)[0] for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module.split(".", 1)[0])
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in {"eval", "exec", "compile"}

        forbidden = {"requests", "httpx", "urllib", "socket", "supabase"}
        assert imported_roots.isdisjoint(forbidden)
