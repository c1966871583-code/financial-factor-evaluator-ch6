# Full-Market OOS Production Preflight

Status: `BLOCKED_BY_PROVIDER_QUOTA`

## Frozen validation scope

The production validation protocol is now frozen before viewing full-market
results:

- history: January 2016 through December 2025, monthly formation;
- development: 2016–2020;
- validation: 2021–2022;
- locked final OOS: 2023–2025;
- universe: point-in-time A-shares including historical delisted securities;
- factors: `ROE_TTM_ENDING_EQUITY`, `OCF_NP`, and `BP_LF`;
- return horizon: 20 market sessions;
- no post-result direction, sample, period, or policy changes.

The cost policy uses date-effective stamp-duty and transfer-fee transitions,
an explicit 3 bps per-side institutional commission assumption, and 5/10 bps
base/stress slippage scenarios.

## Provider preflight

RQData 3.5.2 initialized successfully in the trusted environment. The first
calendar capability query was rejected with the sanitized exception type
`QuotaExceeded`. A separate 2025-only confirmation produced the same exception.
No universe, factor, price, or historical panel was returned.

The run stopped without retries beyond the diagnostic confirmation. It did not
persist identifiers or values, expose credentials, or generate full-market data
files.

## Gate decision

The protocol and local implementation are ready, but PIT historical-universe
coverage and net-of-cost OOS evidence cannot be evaluated until RQData query
quota is restored or increased. Production status remains
`not production ready`.

Next action: `OPERATOR_RESTORE_OR_INCREASE_RQDATA_QUERY_QUOTA`, then rerun the
same preflight without changing the frozen protocol.
