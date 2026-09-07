# Two real split-history reproductions

The preregistered HEG and MAZDOCK checks pass against 19 source-verified NSE raw
sessions and five contemporaneous primary PDFs. This validates bounded split
mechanics and timing; it is not a strategy, portfolio or admissibility result.

The [plan](../../config/dated-split-reproduction-v1.json) fixed symbols, windows,
ratios, knowledge convention, tolerances and controls before the first replay.
The two windows contain exactly the expected split in the pinned partition-union
action responses. Those responses establish observed coverage, not an exchange
completeness certificate. [Publication evidence](dated-split-publication-evidence-2026-09-07.md)
records each dated claim and page; no later annual report supplies earlier knowledge.

| Measure | HEG | MAZDOCK |
|---|---:|---:|
| Raw window | 14–25 Oct 2024 | 23 Dec 2024–3 Jan 2025 |
| Sessions / decision cutoffs | 10 | 9 |
| Split ex-session | 18 Oct 2024 | 27 Dec 2024 |
| Conservative all-support known session | 18 Oct 2024 | 27 Dec 2024 |
| New shares per old share | 5 | 2 |
| Raw preceding close | ₹2,570.40 | ₹4,729.75 |
| Preceding close in ex-session units | ₹514.08 | ₹2,364.875 |
| Ex-session raw close | ₹496.35 | ₹2,317.40 |
| Ex-session close-to-close move in coherent units | −3.44888% | −2.00751% |

The normalized MAZDOCK indicator value is not rounded to an execution tick. Actual
fills have a separate dated tick policy. Both raw files retain their previous-close
field in the old units: ₹2,570.40 and ₹4,729.75. These two observations refute using
that field as an unconditional current-unit adjustment oracle. Ratios here come
from documented subdivisions; no price field was used to infer them or repair a bar.

## Checks and evidence

Every daily decision was checked against an independent scalar rational oracle:
275 OHLCV cells for HEG and 225 for MAZDOCK. Full and truncated raw inputs produce
the same history at every cutoff. A deliberately later knowledge date blocks.
Input arrays remain unchanged, including after that rejected call. Dated old/new
ISINs, EQ series and quality flags are required, and each raw receipt must equal
the previously frozen portfolio receipt. Missing or ambiguous identities stop the
run. Historical aliases cannot bypass duplicate-identity detection.

The first run stopped on pandas attribute access for the ISIN column; explicit
column selection and four regressions resolved it. Review also found missing
immutability verification after the rejected knowledge-control call; that is now
checked and regression-tested. No failed attempt is represented as a passing run.
The initial completed artifact was superseded after adding that extra check.

Final artifact:
`data/reports/dated-split-reproduction/5d6e22c9aa696cccd49d8c47b302370bc889a387ea9537aeb1022d906264f47f/report.json`.
Its directory name equals the report SHA-256. Plan SHA-256:
`9f454904cad962faadef6a755fc1d9b9b42366a91b0a037eb0f166d442bd391b`.
The report pins the implementation, parent manifest, contract, transform, action
manifest, lineage, publication note, PDF manifest and individual raw receipts.

Reproduce using the retained local captures:

```sh
.venv/bin/python -m sensei.research.split_reproduction
```

Thirteen focused tests cover the rational oracle, future dependence, knowledge
rejection, mutation on rejection, tolerance bounds, changed inputs and raw identity.
Final Standards and Spec reviews have no remaining findings.

Full suite: **1,070 passed**, 26.91 seconds.

## Remaining scope

Printed document dates with a next-session convention do not prove actual historic
upload timestamps. Capturing documents and raw files now does not recover all
historical revisions. Complete action coverage and historical membership remain
unresolved. The diagnostic stays DATA_BLOCKED, RESEARCH_ONLY and can_trade=false.

These are two splits, not a real bonus reproduction. No full indicator warmup,
daily ranking/correlation, physical share crediting, cash settlement or portfolio
performance was evaluated. The next bounded work is a documented bonus case and
then action-aware indicator/ranking replay with explicit treatment of intervening
dividends and other events. Unknown events must block, not disappear from the input.

The original baseline and hold60 results are unchanged. No Kite calls/credits,
live orders, purchases or automatic overnight-loop resumption occurred.
