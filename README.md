# Financial Factor Evaluator Chapter 6

## Project goal

This repository is a clean artifact export of the accepted Chapter 6 financial-factor evaluator. It contains financial-factor construction, PIT-aware preprocessing, M/F/R evaluation, batch evaluation, combinations, information-gain evidence, Research Log assembly, QA evidence, and Chapter 6-side Task 8 handoff preparation.

## Responsibility boundary

This repository does not contain or authorize:

- Task 8 internal factor deduplication;
- Task 8 admission decisions;
- Task 8 ranking or screening;
- downstream production decisions;
- portfolio construction;
- live trading.

The exported handoff modules only preserve Chapter 6-side schemas, numeric semantics, extraction evidence, and fail-closed reconciliation. They do not create a P05 package and do not make the repository TASK8_READY.

## Source

Source worktree: `AMR-FINANCIAL-QUALITY-CI`

Source branch: `agent/financial-factor-quality-ci`

Source HEAD: `9cff5b1` (`Record RQData full-market quota preflight block`)

Export type: scoped Chapter 6 code-and-governance snapshot without real-data artifacts or credentials.

## Current status

Accepted research artifacts include PIT timing and lineage, sample formation, preprocessing, MVP and Phase 2 evaluation, Phase 3 common-sample/combination/information-gain evidence, Research Log assembly, QA reports, synthetic contract checks, and Chapter 6-side handoff preparation.

The controlled real-data acceptance scope covers 30 securities, 3 factors, 3 evaluation dates, and 270 authoritative rows. The accepted factor semantics are `ROE_TTM_ENDING_EQUITY`, `OCF_NP`, and `BP_LF`; BP remains a valuation extension and is not silently reclassified as a quarterly financial-statement P05 field. Financial information becomes effective on the strictly next tradable day after publication, and forward returns follow the frozen 20-session label timeline.

The Chapter 6 final acceptance and BP scope amendment are recorded under `docs/provenance/`. The full-market OOS protocol is frozen for 2016-2025 with a locked 2023-2025 OOS period, date-effective transaction costs, and a PIT-safe universe. Its production preflight is currently blocked by the RQData byte quota, so this repository does not claim production readiness, P05 readiness, or Task 8 readiness.

## Environment

- Validated source Python version: Python 3.11.9
- Observed source uv version: uv 0.11.32
- Dependency declaration: `requirements-factor-lab.txt`
- Install: `python -m pip install -r requirements-factor-lab.txt`
- Current acceptance checks: `python -m pytest -q tests/test_amr_financial_timing.py tests/test_amr_financial_timing_strict_next.py tests/test_amr_forward_returns.py tests/test_amr_financial_factor_registry.py tests/test_amr_production_validation_policy.py tests/test_amr_evaluation_input_contract.py`
- Current acceptance result: 173 passed (2026-08-17)

The remaining historical tests and golden files are retained as an audit archive of the original export. Some of those golden fingerprints encode the superseded same-day timing assumption and are not the acceptance gate for the strict-next-session amendment.

Authoritative Chapter 6 environment files were not exported because their provenance or lock consistency was not confirmed. This repository does not fabricate a lock file.

## Data statement

This repository contains no real, unsanitized financial data. Tests use synthetic or sanitized fixtures. Formal research runs require an external authoritative data source and must preserve PIT publication/effective-date rules, sample masks, deterministic fingerprints, and row-level lineage.
