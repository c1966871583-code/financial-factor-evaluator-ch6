# Chapter 6 BP Scope Extension Review

Status: `CHAPTER_6_BP_SCOPE_EXTENSION_ACCEPTED`

Chapter 6 is now complete for the controlled real-data research scope containing
`ROE_TTM_ENDING_EQUITY`, `OCF_NP`, and `BP_LF`: 270 rows, 30 securities, and
3 evaluation dates from authoritative run
`rqdata-authoritative-20260812T023240Z-16b9b5eba2`.

## Contract boundary

This is a non-destructive, multi-contract extension. The existing quarterly
financial P05 remains frozen at 180 rows for ROE and OCF/NP. BP remains a
separate 90-row `valuation_numeric_dedup_v1` package with
`evaluation_date_snapshot` frequency. BP was not assigned artificial report,
publication, or effective dates and was not coerced into `FinancialBatch`.

## BP definition

The accepted semantic name is `BP_LF`. RQData field
`book_to_market_ratio_lf` is used directly and independently checked against
`1 / pb_ratio_lf` when PB is positive. Missing, non-finite, or non-positive PB
fails closed; no absolute-value substitution is permitted.

## Validation

- Independent scope checks: 11 passed, 0 failed.
- Main repository: 691 passed, 4 skipped, 0 failed.
- Task8 repository: 657 passed, 4 skipped, 0 failed.
- No authoritative snapshot, quarterly P05, prior Chapter 6 acceptance, timing
  policy, or forward-return policy was modified.
- No new RQData query was performed.

## Governance conclusion

The expanded controlled scope is **research usable**. It is not production
ready: full-market historical-universe coverage and net-of-cost out-of-sample
significance remain untested. Any such expansion requires separate operator
authorization.
