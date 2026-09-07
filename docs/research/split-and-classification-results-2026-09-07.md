# Split accounting and dated classification coverage

Completed the next research integration after `14bb914`: physical share subdivision
accounting and a metadata coverage checker. Neither turns on live trading or
replaces the earlier full-portfolio comparison with Nifty 500 gross TRI.

## Split inventory and availability

The [split contract](../specs/split-portfolio-entitlements.md) extends the public
research portfolio interface. Every old share is replaced by the resulting split
shares on the ex-session. All resulting shares remain pending until both supplied
availability and knowledge dates are reached. A bonus still leaves original shares
sellable; a split does not. Basis and brackets move to the new units without
creating cash, profit, fees or dividend income. Dated tick rounding follows.

Exit requests survive while shares are pending. Unknown availability prevents any
sale, including final liquidation. Same-session market admission can release the
entire replacement quantity before the opening exit, under that explicit research
availability input. Market admission is not evidence of actual account credit.
Reverse splits, fractions and other unresolved mandatory actions still reject.

### Captured HEG reproduction

The fixed forced holding uses the saved HEG old/new ISIN chain, October 14–25, 2024
raw sessions and September 30 tick reference: eleven hash-verified receipts.
[NSE CML64528](https://nsearchives.nseindia.com/content/circulars/CML64528.pdf)
establishes new-ISIN trading from October 18. The all-support knowledge convention
is October 18, after the October 17 clearing notice. This is date-level knowledge,
not verified historical upload or receipt time. See the
[source evidence](dated-split-publication-evidence-2026-09-07.md).

The predeclared holding buys **24 shares at ₹2,483.50** on October 17. The 5/1 split
creates **120 resulting shares**, with economic entry basis **₹496.70** and no cash
flow from the subdivision. With documented market admission used as availability,
all 120 sell at the October 18 close of ₹496.35 on the fixed time exit. Gross P&L
is −₹42, current-schedule transaction costs ₹148.01, and final cash ₹299,809.99.

The unknown-availability control sells **zero** shares. On October 25 it retains
120 shares worth ₹49,728, cash ₹240,325.17 and economic equity ₹290,053.17, with
liquidation explicitly incomplete. These are different availability assumptions,
not competing strategies; the prices are not a parameter-selection criterion.
Neither case certifies actual account credit, historical charges or settlement.

- Run: `.venv/bin/python -m sensei.research.split_portfolio_reproduction`.
- [Frozen plan](../../config/split-portfolio-reproduction-v1.json), SHA-256 `46f5e03de95211184aebf99221ff10a219b45dc3d8c71b7c4082982daf7a88d2`.
- [Final report](../../data/reports/split-portfolio-reproduction/a040f9f54c93c5318783e7eeceb6baf4578f24d045e4fc8d1eeda0580eb2c130/report.json), SHA-256 `a040f9f54c93c5318783e7eeceb6baf4578f24d045e4fc8d1eeda0580eb2c130`.
- Runner SHA-256 `5303fb301d51ad8760743890167ff30c5f95335f9984b6d90fdd644cfb274a71`.

The first artifact is retained. Review found that the general portfolio experiment
identity omitted `_Position`, which now owns entitlement mechanics. A controlled
altered implementation changed synthetic equity from ₹990 to ₹960 without changing
the old ID. Inventory implementation is now included, and the behavioral regression
requires different IDs. The final rerun updated that implementation pin, not the
forced holding's dates or parameters. Earlier frozen plans were not rewritten.

## Classification input and coverage

The [source investigation](dated-stock-classification-sources-2026-09-07.md) identified
NSE's daily MII security master and its separate NSE-only/interoperability variants.
The [official report selector](https://www.nseindia.com/all-reports/) lists both.
Historical sample downloads and direct-page requests did not succeed. A follow-up
read through the web reader confirmed the report listing; direct HTTP/2 failed and
a bounded HTTP/1.1 page request timed out. No dated master was captured. Neither
the candidate archive URLs nor historical file absence was established.

Implemented the [classification coverage contract](../specs/dated-classification-coverage.md)
without guessing the unavailable master schema. Explicit dated, caller-transcribed
facts can resolve exact observed symbol/series/ISIN tuples. Known-from dates and
effective intervals prevent later evidence or indefinite forward fill. Unknown
subtype, unknown board, missing evidence and incomplete raw identity are distinct
from positively documented exclusions. Overlaps reject. Every result remains
research-only, non-admissible and unable to trade, even if all supplied facts match.
Hashes identify sources; this pure checker does not certify their contents.

The initial run deliberately supplies **no classification facts** and retains every
tuple from the two saved endpoint bhavcopies:

| Observed session | Total observations | Missing dated classification | Incomplete identity |
|---|---:|---:|---:|
| January 1, 2024 | 2,683 | 2,678 | 5 |
| September 3, 2026 | 3,635 | 3,630 | 5 |

The ten incomplete identities have empty raw series; they remain visible. No row
is promoted using an EQ/STK flag, board lot, name or ISIN prefix. The output is an
initial evidence-gap report, not a count of eligible stocks, a listed-universe
register, or coverage of intervening sessions. It does not ingest a historical
security master or generate entry-eligibility intervals.

- Run: `.venv/bin/python -m sensei.research.classification_coverage`.
- [Frozen plan](../../config/classification-coverage-sample-v1.json), SHA-256 `8858277814f0bdd0358d9131423544f6af6fb352f394b4712137071013801fb7`.
- [Report](../../data/reports/classification-coverage/a7333d8cb367a0d53714ef7d344718e098015ae2055d7391b4430e8794421186/report.json), SHA-256 `a7333d8cb367a0d53714ef7d344718e098015ae2055d7391b4430e8794421186`.
- Implementation SHA-256 `048e6eff37536d1b53bfd539fc26bfc53e19b4518ea61b70f9b114e8c78b921c`.

## Verification and remaining work

Fifteen split tests, fifteen classification tests and the earlier twenty-eight
bonus tests pass. Twelve no-action/dividend fixture comparisons and eight bonus
fixture comparisons preserve all economic and serialized fields except experiment
IDs. Real split sale quantities, daily equity components and strategy attribution
reconcile. Final independent Standards and Spec reviews have no residual findings.
Full suite: **1,141 passed**, 30.22 seconds.

The next data dependency is one successfully captured historical NSE-only master
with applicable schema documentation and dated subtype/board evidence. That should
feed this coverage check before expanding to more sessions and deriving a separately
named liquidity universe. A master code that groups ETFs with equities will require
additional dated evidence; it cannot be treated as solved by the download alone.
Complete action coverage, identity transitions and signal/accounting integration
remain prerequisites to the coherent portfolio rerun. The existing strategy family
has not earned deployment and was not retuned in this pass.

No Kite requests/credits, purchases, orders, external messages or live activation.
The overnight heartbeat remains paused. Unrelated runtime JSON and LinkedIn files
are outside this change.
