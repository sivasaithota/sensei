# First configured stock development run

**Outcome: DATA_BLOCKED before portfolio simulation.** No return, CAGR or
strategy verdict was generated from the mismatched calendar.

Configuration: `config/stock-research.json` — ₹300,000, momentum_breakout_55,
5% stop, 12% target, 30-session time exit, at most five positions of at most
20% each, 2% risk-to-stop budget, current delivery costs, ₹15.34 DP per modeled
sale, 10 bps entry slippage. Research maximum drawdown is configurable, currently
100%. This is a frozen development baseline, not an optimized winner.

Evaluation dates are 2024-01-01 through 2026-09-03, with 252 preceding stored
sessions per instrument. All 500 local instruments are retained. The actual
official benchmark capture has 934 observations from 2022-12-01 through
2026-09-04. It uses gross total return, not the separate net total-return field
in the source response. Raw response and Parquet hashes are retained locally.

Final run identifier:
`18549150e3def890a037bd2c9fc22991c315a5fa5dbe2fc8f81865d5b3e3e920`.
Its settings/input/code manifest and report are under
`data/reports/stock-development/<run-id>/`. Earlier diagnostic attempts are
retained under their own implementation identities. No attempt is relabelled
an untouched holdout.

The local stock union and benchmark each contain 665 evaluation dates, but
they are **different dates**. A count-only completeness check would miss this:

| Missing actual exchange sessions | Extra holiday rows in stock data |
| --- | --- |
| 2024-01-20 | 2026-01-15 |
| 2024-03-02 | 2026-05-01 |
| 2024-05-18 | 2026-05-28 |
| 2026-02-01 | 2026-06-26 |

All 1,917 stock rows on the four holidays have zero volume and flat OHLC.
All four missing sessions already have integrity-verified raw NSE snapshots.
The [source verification report](stock-data-admissibility-next-actions-2026-09-06.md)
contains official exchange circulars and per-session counts. It also records
the concrete former-member coverage gap and the passing BSE bonus spot-check.

The next data repair must create a new snapshot with a recorded exclusion list
for the confirmed holidays, reconcile raw-to-adjusted factors for the four
missing sessions, and preserve original files. Raw bars must not be inserted
directly into adjusted history. Full historical universe membership and the
corporate-action ledger remain separate requirements; a clean calendar alone
will not remove those blockers.

Validation: **831 tests passed in 27.17 seconds**. Independent Standards and
Spec reviews found two overlapping cache-identity defects during implementation;
both were corrected and regression-tested. The final reviews have no remaining
findings within this scope. No strategy promotion or live orders occurred.
