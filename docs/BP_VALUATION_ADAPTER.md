# BP valuation adapter

## Purpose

`backend.amr.bp_valuation_adapter` is the explicit boundary between a frozen
evaluation-date valuation package and the financial Path-B BP formula. It does
not query RQData, infer a date, copy `evaluation_date` into a missing source
date, or substitute provider BP for the registered formula.

## Source mapping

| Frozen valuation field | Financial formula field | Rule |
|---|---|---|
| `provider_date` | `market_cap_as_of` | Required and must equal `evaluation_date` |
| `evaluation_date` | `evaluation_date` | ISO date; part of the binding key |
| `market_cap` | `formula_inputs.market_cap` | Finite, positive, and exactly equal to the prepared input |
| `code` | `code` | Part of the binding key |
| `source_record_reference` | `valuation_source_reference` | Required lineage reference |
| `source_input_hash` | `valuation_input_hash` | Lowercase SHA-256 |
| `valuation_policy_version` | same | Required policy identity |

The adapter also freezes `provider`, `provider_endpoint`, and `provider_field`.
The default accepted identity is
`RQData / rqdatac.get_factor / book_to_market_ratio_lf`.

## Integration sequence

```python
import pandas as pd

from backend.amr.bp_valuation_adapter import (
    adapt_bp_valuation_rows,
    bind_bp_valuation_to_path_b_records,
)

valuation_rows = pd.read_parquet(
    "artifacts/bp_valuation_handoff/bp_valuation_rows.parquet"
)
valuation = adapt_bp_valuation_rows(valuation_rows)
if valuation.status != "READY":
    raise RuntimeError(valuation.to_dict())

prepared_records = preprocessing_result.to_mvp_path_b_records(
    sector_types=pit_sector_types,
    source_snapshot_fingerprints=snapshot_fingerprints,
)
bound_records = bind_bp_valuation_to_path_b_records(
    prepared_records,
    valuation,
)

result = build_mvp_financial_batches(
    bound_records,
    lineage_references=lineage_references,
    sample_references=sample_references,
    configuration=batch_configuration,
)
```

The valuation observation keys and prepared BP keys must have exact one-to-one
coverage. Existing but different `formula_inputs.market_cap` values block the
binding rather than being overwritten silently. Input frames and records are
defensively copied.

## Local readiness evidence

The frozen local package under
`AMR-FINANCIAL-QUALITY-CI/artifacts/bp_valuation_handoff` contains 90 BP rows,
30 securities, and three evaluation dates. A read-only adapter rehearsal on
2026-08-20 produced 90 observations, zero issues, exact binding coverage, and
90 valid registered BP formula results. This is controlled research evidence,
not a production-readiness determination.

Parquet loading requires the optional dependency group:

```text
uv sync --extra bp-valuation
```

The core adapter itself accepts a DataFrame and therefore remains independent
of the storage/connector implementation.
