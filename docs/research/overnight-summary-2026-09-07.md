# Stock research overnight checkpoint — 7 September 2026

The full requested raw-price accounting comparison is complete. Both frozen
strategies underperform Nifty 500 TRI. The work improved the credibility of the
measurement; it did not establish a profitable strategy or authorize live trading.

## Portfolio results

Evaluation: 1 January 2024 through 3 September 2026, initial capital ₹300,000.

| Control | Final equity | Net return | Maximum drawdown | Trades | Modeled costs |
|---|---:|---:|---:|---:|---:|
| Baseline | ₹286,796.32 | −4.401% | 29.660% | 467 | ₹67,751.25 |
| Hold60 | ₹323,748.95 | +7.916% | 24.126% | 441 | ₹64,506.54 |
| Nifty 500 TRI | — | +22.9535% | — | — | — |

Final equity includes gross dividend receivables of ₹5,481 and ₹6,026.25,
respectively. They never become buying power in this model. Costs are material,
but neither lower fees nor another holding-period choice should be assumed to
create an edge. All 499 frozen instruments were retained. Both the 908 saved
trades and 908 rerun trades passed held raw-price/tick coverage checks, covering
6,538 trade-sessions per comparison pair. No mandatory split/bonus/demerger was
held across its event in these controls; that accounting remains unsupported.

[Full accounting evidence and limitations](raw-portfolio-results-2026-09-07.md).

## What was resolved

- Raw session coverage reached all 665 evaluation sessions, with missing recent
  sessions captured once. Fills and marks use verified raw prices, whole physical
  shares and dated ticks. Dividends accrue separately from spendable cash.
- The fixed-vintage signal audit compared 175,403,081 Boolean cells across
  315,950 cutoffs and found no changes to earlier signals. A deliberately leaking
  control failed as expected. This does not certify historical data vintages.
- Twelve official Nifty 500 notice PDFs were pinned and transcribed. The register
  preserves 342 rows, including two revoked originals, two revocations and 55
  future-effective rows. It cannot reconstruct a complete historical universe.
- The new research-only split/bonus transform passes 20 synthetic acceptance
  tests for dated unit conversion, knowledge timing and malformed input rejection.
  It is deliberately separate from the frozen portfolio and production catalog.

Final validation: **1,057 tests passed**. Independent Standards and Spec reviews
have no remaining findings in the final implementation slice.

## What still prevents an admissible strategy comparison

1. An independently dated complete starting membership list, complete reconciled
   changes/checkpoints and stable identity/dummy lineage are still missing. The
   current-universe selection creates survivorship limitations.
2. Real dated action evidence must satisfy the new contract, including publication
   timing and source revisions. Synthetic arithmetic cannot certify that evidence.
3. Physical share entitlements, credit timing, fractions and other mandatory
   actions need explicit implementation and validation before a portfolio may
   hold through them. Unknown cash-payment dates cannot fund reinvestment.
4. A new strategy needs a preregistered hypothesis and evaluation protocol. This
   heavily reused development history is not an untouched holdout. Do not resume
   parameter sweeps on the rejected momentum-filter family.

The next bounded technical action is a source-pinned real split/bonus reproduction,
then daily decision replay through ranking and correlation. In parallel, obtain
the missing dated universe evidence if an independently archived official source
is available; no purchase or vendor commitment has been made. Only after those
data gates should a new strategy comparison support promotion decisions.

The ₹300,000 model and configurable drawdown controls remain in place. No live
orders, strategy activation, additional Kite requests/credits, subscriptions,
usage-reset credits or messages to other people occurred in the final passes.
