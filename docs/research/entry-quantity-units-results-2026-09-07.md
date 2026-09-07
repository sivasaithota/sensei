# Entry sizing now supports explicit share-unit increments

Pass 7 fixes the demonstrated integer-split sizing defect in an explicit research
mode. A caller can supply dated positive-integer increments and an evidence
artifact hash. Missing dates or unknown values block entry; invalid values,
unmatched instrument universes and malformed evidence dates are rejected.

The delivery solver searches increment-sized orders while preserving allocation
notional, cash including entry fees, and stop risk including both-side fees.
Flat-cost sizing also rounds down to the increment. Existing positions retain
their adjusted quantities when later entry increments change, avoiding a second
split credit. The normalized map and evidence hash are part of campaign identity.

Reports distinguish legacy synthetic integer units from explicit increments and
state the remaining execution/accounting limitations. The simulator binds the
caller-supplied evidence identity; it does not certify that evidence itself.
The full stock runner still uses legacy mode because complete evidence is absent.
Both modes remain research-only and cannot trade.

## Real-case sizing reproduction

The reproduction pins the prior split audit and source screen/proofs, checks
the saved trades, and verifies the full source price-file hashes. It forces
each known entry in isolation on its actual saved bars with the original config
and full initial cash available. It verifies that the legacy sizing and entry
price match the saved trade before checking the new increment. Same-day closure
is only a sizing harness; no portfolio return or exit-outcome claim is made.

| Shared entry | Legacy adjusted units | Corrected adjusted units | Physical shares |
|---|---:|---:|---:|
| HEG, April 16, 2024 | 123 | 120 | 24 |
| MAZDOCK, May 30, 2024 | 35 | 34 | 17 |
| MAZDOCK, June 18, 2024 | 30 | 30 | 15 |
| MAZDOCK, July 5, 2024 | 21 | 20 | 10 |

Each case occurs in both controls, giving eight records, six with corrected
quantities. Reproduction artifact:
`data/reports/quantity-sizing-reproduction/eb4695e2918ec362afa7f8c810ffddb6519a9f30c528c53da744443719404df3/report.json`.
Its directory name is its SHA-256; individual campaign IDs bind the implementation
and entry maps.

## Control parity and checks

Both complete controls were rerun with the new mode omitted. All campaign fields,
including every trade and equity point, reproduce exactly after excluding the
changed experiment ID and added quantity-mode metadata.

| Control | Final equity | Trades | Rerun ID |
|---|---:|---:|---|
| Baseline | ₹294,661.96 | 467 | `aa1201c249e9e3cba71af59c5279e5708b7f2f7942bd3fdda8a2351fb8a98784` |
| Hold60 | ₹329,853.50 | 441 | `10fc1b2134f54c14493920c923c22db075d833efe6346349289df6ca38ec1706` |

Parity record: `data/reports/stock-development/quantity-unit-control-parity-20260907.json`.
These unchanged results do not include the new sizing mode. They remain
DATA_BLOCKED and do not establish a net edge over the benchmark.

Validation: **957 tests passed**. Cash/risk/notional boundaries, unaffordable
increments, unknown evidence, entry-date alignment, mask composition, malformed
inputs, identity changes, control parity and no duplicate quantity credit are
covered. Standards and Spec reviews clear; the Spec reviewer independently
verified all eight reproduction records.

## Next evidence boundary

The current mode deliberately accepts integer increments. It is not a complete
model for rational bonus ratios or demerger entitlements. The held-price screen
contains 27 symbols with non-unit volume scaling; some ratios are nonintegers,
including OIL/TRENT near 1.5 and CUB near 4/3. ABFRL, SIEMENS, TMPV and VEDL also
have noninteger vendor volume factors that must not be labeled share multipliers
from prices alone.

Next classify that finite set using primary action notices, distinguish share
subdivisions/bonuses from vendor demerger adjustments, and measure dated evidence
coverage. Do not convert volume ratios into an automatic unit map or enable a
full-universe corrected run from this two-stock ledger. Actual execution prices,
ticks, dividend receivables and demerger entitlements still require coherent
accounting before portfolio results can be certified.
