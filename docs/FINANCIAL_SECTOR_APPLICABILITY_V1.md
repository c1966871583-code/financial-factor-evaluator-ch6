# Financial sector applicability v1

## PIT sector contract

The internal routing values are `NON_FINANCIAL`, `BANK`, `INSURANCE`,
`SECURITIES`, and `DIVERSIFIED_FINANCIAL`. The classification must be the
evaluation-date PIT result supplied by `ExposureBatch-v1`. Missing and unknown
values fail closed as `SECTOR_CLASSIFICATION_MISSING`; current classifications
must never backfill history.

## MVP applicability matrix

| factor_id | sector_type | applicable | formula_variant | required inputs | denominator policy | not-applicable reason | effective_from | formula_version |
|---|---|---:|---|---|---|---|---|---|
| ROE | all five types | yes | parent net profit TTM / average parent equity | `parent_net_profit_ttm`, `average_parent_equity` | equity must be positive; negative profit with positive equity is valid | — | 2026-08-20 | FIN-MVP-ROE-v1.0 |
| BP | all five types | yes | parent equity / evaluation-date total market cap | `parent_equity`, `market_cap` | market cap and equity must be positive; market-cap as-of must equal evaluation date | — | 2026-08-20 | FIN-MVP-BP-v1.0 |
| OCF_NP | NON_FINANCIAL | yes | operating cash flow TTM / parent net profit TTM | `operating_cash_flow_ttm`, `parent_net_profit_ttm` | absolute profit must exceed the declared materiality floor | — | 2026-08-20 | FIN-MVP-OCFNP-v1.0 |
| OCF_NP | BANK, INSURANCE, SECURITIES, DIVERSIFIED_FINANCIAL | no | — | — | no calculation | operating cash flow is not comparable for financial-sector business models | 2026-08-20 | FIN-MVP-OCFNP-v1.0 |

ROE and BP observations from financial and non-financial companies must enter
separate downstream standardization/evaluation groups. No formula has a
fallback. Bank/insurance/securities-specific metrics require new factor IDs.

## Status and anomaly policy

The structured calculator returns `VALID`, `NOT_APPLICABLE`,
`INVALID_DENOMINATOR`, `MISSING_REQUIRED_INPUT`,
`SECTOR_CLASSIFICATION_MISSING`, `SECTOR_FORMULA_MISMATCH`, or
`NONFINITE_INPUT`. It never adds epsilon to a denominator. A non-applicable or
invalid observation has no numeric value. BP requires explicit
`market_cap_as_of == evaluation_date`; adapters must supply both together.
