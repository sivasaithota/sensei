# Calendar repair results — 6 September 2026

The first repair is complete: **1,917 verified holiday placeholders were
removed in a separate 500-instrument snapshot**. No missing price was inserted.
The frozen baseline still stops before simulation because four real exchange
sessions remain absent. AccelPix access is pending, as confirmed by the owner.

## Snapshot and exclusions

Snapshot: `data/research/stock-repairs/c707298d8f2f7e0db5b69945f71fdb2db3566da4cf761eef8bd2aba6196f82ef/`.
`snapshot_manifest.json` records original file hashes, output hashes, every
excluded row, official holiday sources and unresolved data requirements.

| Confirmed holiday | Rows removed |
|---|---:|
| 2026-01-15 | 457 |
| 2026-05-01 | 463 |
| 2026-05-28 | 498 |
| 2026-06-26 | 499 |
| Total | 1,917 |

All removed rows have flat positive OHLC, zero volume and zero turnover.
The January date is supported by [NSE circular CMTR72260](https://nsearchives.nseindia.com/content/circulars/CMTR72260.pdf);
the other dates by [NSE circular CMTR71775](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf).
Original files are preserved. Retained rows and every instrument remain in
the new snapshot. This operation does not repair older OHLC defects or certify
historical membership and corporate-action treatment.

## Missing-session audit

`adjustment_audit.json` records 2,000 stock/session checks: 500 supplied stocks
across 2024-01-20, 2024-03-02, 2024-05-18 and 2026-02-01. The audit uses the
verified raw NSE archive for each target and its immediately adjacent sessions
on the official benchmark calendar. Current ISIN matching is a diagnostic,
not a historical identity certificate.

| Status | Checks |
|---|---:|
| Neighboring price and volume factors agree; exact-date factor unverified | 1,749 |
| Target outside the stock's observed history | 158 |
| Identity or raw bar unresolved | 89 |
| Neighboring factors disagree | 4 |

The four disagreements all concern 2026-02-01: BALKRISIND, BPCL and LTFOODS
have differing neighboring price factors; IDEA has differing volume ratios.
The audit identifies discrepancies without claiming their cause. A relative
tolerance of 0.00001 is used for comparison, not insertion approval.

**Exact-date factors verified: 0. Rows inserted: 0.** The
[fresh Yahoo probe](stock-adjustment-repair-evidence-2026-09-06.md) also omits
all four target dates for TCS. Agreement between neighboring values cannot
substitute for a dated factor or a complete verified corporate-action chain.

## Frozen rerun

Configuration: `config/stock-research-calendar-clean.json`. It retains the
original dates, strategy parameters, ₹300,000 capital, costs and configurable
100% research drawdown limit; only the input directory changes.

Run ID: `3170b8a013cca73ef1697b82319b8a7c5dc07f71399b573777bcd394b7cb0845`.
Artifacts: `data/reports/stock-development/<run ID>/report.json`,
`manifest.json` and `report.sha256`.

The snapshot manifest is verified and bound into the frozen run identity.
The result is `DATA_BLOCKED`, `can_trade=false`: the portfolio calendar has
661 sessions against 665 benchmark sessions, no extra dates and the same four
missing sessions. Simulation did not run; there are no new return, Sharpe or
drawdown estimates to interpret.

## Remaining data dependency

Complete the adjustment repair only after a provider supplies those sessions
with adequate price/volume adjustment evidence, or a complete verified action
chain supports reconstruction. Pending AccelPix access is a possible route,
not proof its trial will supply the required history. Historical constituent
coverage, identity changes and the action ledger still need validation after
these calendar gaps are repaired. Runtime risk settings and live authority
are unaffected by this research snapshot.

## Validation

All **841 tests passed** in 27.52 seconds. The focused repair/run tests cover
unexpected holiday activity, preservation of non-holiday rows, source and
output integrity, altered exclusion records, neighbor agreement without
insertion authority, and propagation of verified lineage into blocked runs.
Compilation and diff checks passed. A separate comparison verified all 500
original file hashes and equality of every retained row in the final snapshot.
Standards and spec reviews have no remaining findings; their initial evidence
integrity finding was fixed before the final snapshot was generated.
