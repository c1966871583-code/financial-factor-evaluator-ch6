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

Source worktree: `CH6-G0-worktree-f957d02`

Source HEAD: `f957d02f2f2d97606e2ed40d44f985b05f2ac31a`

Export type: clean artifact export without original Git history.

## Current status

Accepted research artifacts include PIT timing and lineage, sample formation, preprocessing, MVP and Phase 2 evaluation, Phase 3 common-sample/combination/information-gain evidence, Research Log assembly, QA reports, synthetic contract checks, and Chapter 6-side handoff preparation.

The authoritative B3A financial-quarterly input snapshot remains blocked because the authoritative upstream source chain is unavailable. No P05 candidate package has been formed. `TASK8_READY` is false. Production admission and investment conclusions remain out of scope.

## Environment

- Validated source Python version: Python 3.11.9
- Observed source uv version: uv 0.11.32
- Dependency declaration: `requirements-factor-lab.txt`
- Install: `python -m pip install -r requirements-factor-lab.txt`
- Collect tests: `python -m pytest --collect-only -q tests`
- Run tests: `python -m pytest -q tests`

Authoritative Chapter 6 environment files were not exported because their provenance or lock consistency was not confirmed. The source worktree does not contain `pyproject.toml` or `uv.lock`; this repository does not fabricate either file.

## Data statement

This repository contains no real, unsanitized financial data. Tests use synthetic or sanitized fixtures. Formal research runs require an external authoritative data source and must preserve PIT publication/effective-date rules, sample masks, deterministic fingerprints, and row-level lineage.
