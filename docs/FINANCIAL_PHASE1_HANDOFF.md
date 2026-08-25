# Financial phase 1 handoff

- `financial_mvp_batch.py` now exposes registry v2 metadata and a structured,
  PIT-sector-aware formula evaluator. The float compatibility wrapper remains,
  but now requires explicit `sector_type`; BP also requires matching
  `market_cap_as_of` and `evaluation_date`.
- `financial_evidence_contracts.py` adds strict M/F/R discriminators,
  deterministic per-track hashes, and a gate summary containing references
  only. Existing M/F/R result classes and their metrics remain independent.
- `ExposureBatch-v1` should map its evaluation-date PIT industry result to
  `FinancialSectorType` and pass it as `sector_type`; no RQData reader is added.
- `bp_valuation_adapter.py` is the explicit bridge for the frozen valuation
  package. It maps source-backed `provider_date` to `market_cap_as_of`, requires
  equality with `evaluation_date`, verifies positive finite market cap and
  source hashes, then binds exact `(evaluation_date, code)` coverage to BP
  Path-B records without mutating inputs.
- This is an intentional compatibility change: callers of
  `calculate_registered_mvp_formula` and `to_mvp_path_b_records` must supply PIT
  sector data. Missing classifications fail closed rather than inheriting the
  former non-financial universe assumption.
- The public exposure owner should confirm its missing/unknown code and
  `sector_mapping_version`. The price-volume owner should confirm only the
  later common-sample/neutralization interface; no cross-line deduplication is
  implemented in this phase.
