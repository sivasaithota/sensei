# Held-trade price endpoint screen

Overnight pass 5 compared the saved baseline and hold60 control with verified
local raw NSE bhavcopies. This is descriptive accounting evidence, not a new
strategy run or a certified corporate-action ledger. Both portfolios remain
research-only, DATA_BLOCKED and unable to trade.

## Verified artifact

Final local report:
`data/reports/held-price-screen/8f4ad4a2c8bb26bdc27a1c7ecb7b70e0f7306534584e977ca2733853bd4bb3c7/report.json`.
The directory name and adjacent checksum are the report's SHA-256. It binds
screening code, verified source proofs, snapshot identity and 485 raw-session
receipts. Source report, manifest and price bytes are checked after verification.

| Source | Trades | Matched endpoints | Uncaptured endpoints |
|---|---:|---:|---:|
| Baseline | 467 | 911 | 23 |
| Hold60 | 441 | 859 | 23 |
| Total | 908 | 1,770 | 46 |

Shared trades remain in each supplied run. These are record counts, not counts
of unique executions. Baseline source ID:
`2d2f2ea5243c850bb4758f7dd52b8898dd0beb863cf507127ccd11e3a3734b9a`.
Hold60 source ID:
`281eb8d7f7f8eb29a81f391924149b03b4ad4965ed133db83ff7acd549fc2b99`.

## Findings and limits

Of 1,770 matched endpoints, 1,704 share the current reference ISIN and 66 have
a different ISIN that remains unverified. Neither category proves historical
membership or complete security lineage. The differing identities occur in
MAZDOCK, TATAINVEST, CAMS, MCX, COFORGE, JBMA, PERSISTENT, HEG-BE,
ADANIPOWER, BAJFINANCE and NAVA.

All 46 uncaptured endpoint records fall after the local raw archive ends on
August 14, 2026: August 17–21, 24 and 31, and September 1–3. No missing day was
fetched or filled. No ambiguous or missing candidate rows remain on captured
endpoint dates.

Both endpoints had comparable volume ratios for 880 trade records; none changed
by more than 1%. The remaining 28 trade records lack an endpoint comparison.
This does not rule out intervening actions, dividends or errors. There are 298
matched endpoints where at least one Kite/raw OHLC ratio differs from one by
more than 0.1%, and 190 where the volume ratio differs from one by more than 1%.
Level differences are observations, not repair factors.

Review found that Kite aliases such as HEG-BE were being compared directly with
NSE symbols. Using the frozen canonical exchange symbol recovered four
endpoints while preserving their differing historical ISIN as unverified.
A regression failed before this fix and passed afterward. An earlier ISIN
matching defect caused by pandas attribute access was also fixed and tested.

[Primary dividend research](kite-cash-dividend-conventions-2026-09-07.md) establishes
that vendor-adjusted prices cannot safely be treated as actual trade cash flows
with all dividends independently credited. Exact historical adjustment mechanics
remain unresolved. No price, cash, entitlement, strategy or source trade changed.

Validation: **922 tests passed**. Independent Standards review's canonical-symbol
finding was fixed; Spec implementation review found no issues. Final artifact
counts above were computed from the regenerated report.

Next bounded step: reconcile the observed historical ISIN changes with official
company/exchange split and bonus notices, beginning with MAZDOCK and HEG. Record
effective dates and share ratios without assuming a symbol match proves lineage.
Use that evidence to scope actual-price and entitlement accounting; keep the
failed strategy experiments visible and avoid further parameter tuning meanwhile.
