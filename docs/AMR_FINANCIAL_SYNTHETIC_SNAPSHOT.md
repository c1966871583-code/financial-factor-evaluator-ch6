# Financial synthetic snapshot contract test

`financial_synthetic_snapshot.py` is a deterministic, synthetic-only test harness for
`FIN-HO-8-B3A-PRE-01`. Every input row must declare `synthetic_test_only: true`.
It validates the complete PRE-01 field family: PIT dates and revision reference,
sample mask/reason/fingerprint, preprocessing and stale-state policy, source/run/version
identifiers, full row lineage, and deterministic row/dataset/schema/manifest hashes.

The builder sorts rows by the frozen primary key and blocks the whole synthetic snapshot
on any missing field, broken PIT order, duplicate key, invalid mask/reason, missing
lineage, or non-synthetic input. It never silently removes a bad row.

This is implementation evidence only. Its `ready` status is not an authoritative
source snapshot, does not satisfy PRE-01 acceptance, does not unblock B3A, and must
not be used to create P05 or `TASK8_READY`.

The separate synthetic bad-data gate freezes missing run reference, future
disclosure/PIT violation, conflicting primary key, mask/reason conflict, and
broken lineage cases. Every case must return `blocked` with a stable error code
and must leave its input object unchanged.
