# Integrated stock research replay — 7 September 2026

All four frozen strategies now complete the 413-session research replay. All
four lose money and trail Nifty 500 gross TRI. None is a live deployment
candidate. The integrated data/accounting pass is complete for these four
scenarios; the remaining source assumptions are still explicitly unresolved.

The owner requested the remaining work together. This pass connects historical
raw prices, dated security metadata, corporate-action accounting, strategy signals
and benchmark evaluation in one reproducible command. It does not authorize live
trading. The four existing strategy hypotheses are frozen before their results.

## Scope and acquisition

The raw panel contains 1,566,840 unique valid EQ/BE observations across 3,224
historically observed symbols and 665 exchange sessions, January 2024 through
September 3, 2026. This replaces selection from today's constituents with a
historical observed superset. It is not a certified historical Nifty 500 universe.

The evaluation window is January 6, 2025 through September 3, 2026. A preceding
master is required for every entry date: 413 source dates, January 3, 2025 through
September 2, 2026. Acquisition made 382 new public NSE requests and reused 31
captures. There were **zero Kite calls or credits consumed**. All source bodies,
receipts and failed responses are retained. Fifty responses were HTTP 404; no
older master is carried across a missing source date.

The entry proxy requires prior-session EQ broad-equity metadata, the normal-market
marker, permitted eligible nonsuspended status, no deletion and a one-share lot.
It also requires 252 consecutive prior raw observations in the same symbol/ISIN
identity. Gaps, identity changes and non-dividend accounting events restart that
history. Signals, ranking and correlation use only the current history segment.
The current execution row must separately match the preceding master identity.

## Accounting and reproducibility

Prices and quantities use raw exchange observations and physical shares. Cash
dividends become receivables, not spendable cash. Split/bonus ratios are parsed
with a bounded grammar. The replay assumes share availability two exchange
sessions after the ex-date; this is an explicit research scenario, not evidence of
broker credit. Fractional entitlements, unsupported held actions, unexplained
identity/restatement events and missing held prices stop a simulation.

Review fixed two accounting defects before evaluation: a dividend could otherwise
waive an unrelated ISIN/share-unit discontinuity, and an unproved symbol-only
match could otherwise credit a dividend. Both now create unsupported events.
Regressions also verify compatible cash adjustments and documented split ratios.

The frozen hypotheses are momentum breakout with 30- and 60-session holding
limits, the existing 50-DMA pullback, and RSI(2) reversion. All use ₹300,000,
current delivery costs, ₹15.34 DP per simulated sale, 10 bps entry slippage and
five positions. Stops, targets and ranking policy are unchanged. The configured
100% drawdown threshold is a reported acceptance threshold, not a promised cap.

V1 was interrupted during action mapping, before any strategy evaluation, to
strengthen cache provenance. V2 additionally pins both the raw-panel receipt and
Parquet bytes. All strategy parameters remain identical. V2 completed RSI(2) and stopped the other hypotheses at old/new ISIN split
transitions. V3 adds exact NSE-documented TFCILTD/NUVAMA bridges and explicitly
validates notice dates, source/prior/ex series and old/new identities. Strategy
parameters stay unchanged. Original source and contract copies are saved under
`data/research/stock-closure/20260907/sources-v1/`, with v3/v4 copies alongside. V4 adds MBAPL and five later verified split
transitions in one batch: KRISHANA, MWL, JLHL, NARMADA and TEMBO. Its notice must
strictly predate the ex-session; the new regression rejects a same-day notice.
POCL/TDPOWERSYS retain stale API identity conflicts, KIRLPNU lacks a captured
new-ISIN notice, and CORDELIA lacks a notice preceding the ex-session. None is
authorized through a ticker-only fallback.

Reproduce with:

```sh
.venv/bin/python -m sensei.research.stock_closure --plan config/stock-closure-v4.json
```

The command verifies code and evidence hashes before evaluating and writes a
content-addressed manifest and report under `data/reports/stock-closure/`. Its
manifest includes runtime versions, every instrument/history-mask hash, raw and
metadata receipts, accounting evidence and the aligned benchmark. The report
retains every hypothesis, including explicit simulation failures. All inspected
history is recorded as development data, not fresh holdout evidence.

## Interpretation of the completed development tests

These results are not an isolated before/after estimate of the accounting fixes.
The older reports used a current-constituent sample, adjusted signal histories and
a January 2024 start. This replay uses the historical observed metadata proxy,
stable raw-price signal segments and a January 2025 start. Compare each reported
strategy to its own aligned Nifty 500 TRI window, not to a benchmark percentage
from a different report.

In v3, both momentum variants and RSI(2) completed with no open positions. All
three lost money even before the separately reported realized fees. Lowering
fees alone therefore would not create a demonstrated edge. The pullback run was
still blocked on a later MBAPL split; no return was attributed to that stopped
run. Its official notice is handled with the same exact bridge rule.

## Final v4 results

January 6, 2025–September 3, 2026; starting equity ₹300,000. Nifty 500 gross
TRI returned **+4.2248%** over the same 413 sessions, including the required
preceding-session reference close.

| Hypothesis | Final equity ₹ | Net return | Maximum drawdown | Trades | Realized fees ₹ |
|---|---:|---:|---:|---:|---:|
| momentum_raw_hold30 | 130,787.42 | -56.404% | 59.218% | 419 | 43,888.84 |
| momentum_raw_hold60 | 142,280.50 | -52.573% | 59.288% | 413 | 43,327.50 |
| pullback_raw | 229,903.53 | -23.365% | 40.284% | 366 | 41,640.49 |
| rsi2_raw | 177,367.21 | -40.878% | 46.274% | 616 | 68,315.35 |

Every run reports `NO_CLEAR_NET_EDGE`, zero open positions, research-only authority
and `can_trade=false`. Equity includes accrued, unpaid cash-dividend receivables;
it is not all spendable cash. All four lose money even before the separately
reported realized fees. Neither choosing the least-bad variant nor lowering fees
alone establishes an edge.

All 3,224 history hashes and entry-mask hashes are identical between v3 and v4.
The three previously completed controls also have exactly identical trades and
equity curves. The evidence additions repaired accounting links without changing
signal history, admission rules or strategy parameters. Of the 413 master dates,
363 validated and 50 were blocked HTTP 404 responses. There were 1,882 instruments
with at least one eligible entry date and zero final execution-identity mismatches.
The report's entry-gate counters cover the whole raw panel, including warmup;
therefore its missing-master row count is not a count of missing evaluation days.

[Final report](../../data/reports/stock-closure/f761e7e8e9e21c9b81069cf2d5d85292c50cc3286c71ca1eb064a80a0c72fb86/report.json),
SHA-256 `c23c855ed750dcbd1d8355077939135c23122707cca98c85c0b29b8616b27e2c`.
[Final manifest](../../data/reports/stock-closure/f761e7e8e9e21c9b81069cf2d5d85292c50cc3286c71ca1eb064a80a0c72fb86/manifest.json),
SHA-256 `f761e7e8e9e21c9b81069cf2d5d85292c50cc3286c71ca1eb064a80a0c72fb86`.

Validation: **1,218 tests passed in 30.83 seconds**. Standards and Spec review
findings were fixed and rechecked. The final review verified source hashes,
notice transcriptions, all eight admitted bridges, four unresolved cases and
unchanged strategy/portfolio parameters. No live activation, order, purchase,
external message or automation-state change occurred. Unrelated runtime JSON and
LinkedIn documents remain outside the change.

## Remaining evidence limits

Historical pre-open publication time and exhaustive ordinary-share classification
are not certified. The dated MII circular resolves the non-SME normal-market
marker from June 16, 2025; it does not prove the broader missing claims. MII field 9
is the tick field, while field 58 is filler; the captured MII definitions do not
explicitly certify its units. Execution therefore retains the existing dated tick
reconstruction policy and its limitation.

The action API's previously documented partition/whole-year discrepancy remains.
Share availability, dividend payment timing, settlement cash reuse and current-cost
counterfactuals are not account-level historical reconstruction. A completed
research scenario is still inadmissible for live trading. An interrupted or
unliquidated simulation is not a valid performance result. No strategy is promoted
without independent forward evidence and a demonstrated net edge.
