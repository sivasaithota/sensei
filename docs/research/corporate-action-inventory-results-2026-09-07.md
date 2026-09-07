# Corporate-action classes and remaining execution gaps

Pass 8 classifies all 27 symbols with non-unit volume scaling in the saved
held-price screen. The registry binds primary research notes; the inventory
retains all 908 trade records across 244 traded symbols, including 1,770 matched
and 46 uncaptured endpoint records. Shared trades are counted in each portfolio.

| Documented action class | Flagged symbols | Non-unit endpoint records |
|---|---:|---:|
| Pure split | 10 | 62 |
| Bonus issue | 12 | 106 |
| Combined split and bonus | 1 | 4 |
| Demerger | 4 | 18 |
| Total | 27 | 190 |

This is classification of documented events, not verification of every vendor
adjustment or every held interval. The other 217 traded symbols remain
unclassified; unit volume ratios do not certify absence of actions. Registry:
`config/stock-action-classification-v1.json`.

Final inventory:
`data/reports/corporate-action-inventory/192465b51e1b66822b7bfba5ebcd6a1be5e0ed2a55c7585d2b35faababe763d8/report.json`.
Its directory name equals its SHA-256. Source screen/proofs, registry, source
notes and implementation are pinned. No portfolio, price, quantity or cash
result changed.

## What the primary evidence changes

- [Split research](share-action-classification-splits-2026-09-07.md) verifies
  eight additional pure splits. Bajaj Finance is a separate combined action:
  a 2× split followed by a 5× total-share bonus transformation, explicitly
  composed as 10× by company/exchange evidence.
- [Bonus research](share-action-classification-bonuses-2026-09-07.md) establishes
  twelve bonus entitlements. CUB's total-share ratio is 4/3; OIL and TRENT are
  3/2. These cannot simply enter an integer-only quantity map. BSE and TRENT
  exchange ex dates are confirmed; ten other bonus ex dates remain unresolved
  in this bounded pass. Record, allotment and tradability dates remain separate.
  TRENT's initial May 29, 2026 record date was formally revised to June 4.
- [Demergers](share-action-classification-demergers-2026-09-07.md) explain why
  ABFRL, SIEMENS, TMPV and VEDL need a separate accounting path. Their observed
  factors approximately correspond to reciprocals of parent tax cost allocations
  of 75.68%, 76.18%, 68.85% and 52.34%. Those are not additional parent shares.
  Resulting securities can become tradable well after the ex-date; the company
  tax-allocation letters can also postdate that date.

## Additional strict split-unit audit

The new ledger `config/stock-split-evidence-additional-v1.json` covers ADANIPOWER,
CAMS, COFORGE, JBMA, MCX, NAVA, PERSISTENT and TATAINVEST. It excludes Bajaj
Finance's combined action and leaves the original MAZDOCK/HEG ledger intact.
The existing audit rules, including the ₹0.05 adjusted-price diagnostic envelope,
were applied unchanged.

Among all 908 retained records, **nine have fractional physical-share equivalents**,
two are integral, 12 fail the price-scaling check, seven are outside pre-split
scope and 878 outside this ledger. The fractional cases occur in JBMA,
ADANIPOWER, CAMS and NAVA. The mismatches occur in TATAINVEST, MCX and COFORGE;
they remain unevaluated rather than having their tolerance enlarged to pass.

Examples: JBMA 63 adjusted units imply 31.5 physical shares (floor 31); ADANIPOWER
343 imply 68.6 (floor 68); CAMS 64 imply 12.8 (floor 12); NAVA 93 imply 46.5
(floor 46). These are diagnostic floors, not rerun portfolio results.

Additional audit:
`data/reports/share-unit-audit/cd83195df2866c3c68f9685641545e6750d596b32afccfc5e6ae4f7100d12212/report.json`.
The failed price comparisons show mixed-sign deviations from raw divided by the
documented split, reaching ₹0.50 in adjusted units at sampled endpoints. This
does not establish whether the cause is tick rounding, vendor methodology or
another data difference. No cause or correction factor is inferred from that
observation alone.

Validation: **961 tests passed**. Standards and Spec reviews clear; the reviewer
independently reconciled all inventory and additional-audit counts and hashes.
No Kite requests, new spending or live orders were made.

## Next bounded step

Investigate dated NSE equity tick-size rules and compare raw versus Kite OHLC
for the unresolved split cases, preserving both directions of the differences.
Do not widen tolerances from the observed failures. In parallel, prepare a
bounded actual-price execution reproduction for already selected pre-action
trades, separating adjusted signal data from raw execution prices and physical
whole-share sizing. Require verified raw-session coverage and reject intervals
with unmodeled actions. This is the next step toward a coherent execution ledger;
the full portfolio remains DATA_BLOCKED pending wider evidence and entitlements.
