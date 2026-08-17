# ROE Registry Semantics Unification

Status: `ROE_REGISTRY_SEMANTICS_UNIFIED`

The governed ROE definition now has one registry identity:

- machine factor ID: `ROE`
- canonical semantic name: `ROE_TTM_ENDING_EQUITY`
- formula ID: `FORMULA_ROE_TTM_ENDING_EQUITY`
- formula version: `1`
- formula reference: `FORMULA_ROE_TTM_ENDING_EQUITY_V1`
- formula: `np_parent_company_ownersTTM / equity_parent_company`

The numerator is TTM net profit attributable to parent-company owners. The
denominator is parent-company equity at the report-period end. This is not a
weighted-average-equity ROE.

## Version boundary

`AUTHORITATIVE_FINANCIAL_FACTORS_V1`, retained in frozen rows as
`factor_version`, is the dataset/package contract version. It is not the ROE
formula version. Formula identity and evolution are governed separately by the
registry's `formula_id`, `formula_version`, and `formula_reference`.

## Compatibility and fail-closed behavior

`ROE` and `ROE_TTM_PARENT_ENDING_EQUITY` resolve to the canonical semantic
definition. Provider fields `return_on_equity_ttm`,
`return_on_equity_weighted_average`, and `roe_diluted` are explicitly not
treated as equivalent aliases.

## Validation

- Registry and frozen real-data checks: 11 passed, 0 failed.
- Frozen authoritative ROE rows checked: 90.
- Full repository suite: 699 passed, 4 skipped, 0 failed.
- Existing Chapter 6 validation: 15/15 passed.
- BP scope-extension validation: 11/11 passed.
- No RQData query, frozen-data rewrite, P05 rewrite, or historical acceptance
  rewrite was performed.

Conclusion: `research usable`; production readiness remains unchanged.
