# Bonus entitlements in portfolio accounting

Implemented the [bounded contract](../specs/bonus-portfolio-entitlements.md) through
the existing research portfolio interface. A pre-ex holder's additional bonus shares
now accrue as a separately marked, non-spendable share receivable. Only available
shares can sell. An exit request remains queued for pending shares until the supplied
availability and knowledge dates are reached. Release creates neither cash nor a
second entitlement. Unknown availability leaves an explicit holding at the end,
even when final liquidation was requested.

Entry basis, brackets, fees and earlier dividend attribution reconcile across the
actual sale legs. Pending shares retain exposure and position slots; their value
cannot fund new entries. The economic basis is not statutory bonus-share tax basis.
Fractional outcomes, simultaneous mixed events and additional accounting events
while shares are pending fail visibly. Other mandatory-action families remain
unsupported in this portfolio slice.

## Captured BSE holding reproduction

This is a forced holding to verify accounting, not a strategy recommendation or a
new portfolio-performance result. Both availability cases were declared before
running. It reuses nine raw sessions, May 20–30, 2025, plus the April 30 tick-reference
receipt. Every receipt is checked against the frozen parent and instrument identity
is verified. The only observed BSE action in that interval is the May 23 bonus.

The April reference close of ₹6,359 implies the documented **₹0.50 May tick**, which
does not divide by three on the bonus date. Eight shares enter May 22 at the raw
₹7,305 open, using the ₹300,000 account, 20% position cap, 2% risk cap and current
delivery-charge counterfactual. The 2:1 bonus gives 24 economic shares: eight
available and sixteen pending. The transformed economic entry basis is ₹2,435.

| Event | Sale quantity and price | Cash after event | Pending bonus shares |
|---|---:|---:|---:|
| May 22 entry | Buy 8 at ₹7,305 | ₹241,490.56 | 0 |
| May 23 time exit | Sell 8 at ₹2,448 | ₹261,038.87 | 16, marked at ₹39,168 |
| May 27, planned-availability scenario | Sell 16 at ₹2,450 open | ₹300,182.83 | 0 |
| May 30, unknown-availability control | No additional sale | ₹261,038.87 | 16, marked at ₹42,784 |

The planned-availability scenario's two sale legs have ₹161.17 total costs and
₹182.83 net economic P&L. The unknown-availability control ends with ₹303,822.87
marked equity, but **₹42,784 is an unsellable receivable**, not cash or a completed
return. Its liquidation remains incomplete. The difference is exposure to later
prices under different assumed availability, not an edge or grounds to prefer one
scenario. Every daily equity component and final strategy attribution reconciles.

May 27 comes from the issuer's advance schedule, **not verified exchange admission
or broker credit**. The [availability investigation](bse-bonus-availability-2026-09-07.md)
records the evidence boundary. The May 26 allotment confirmation is not used to
invent earlier knowledge. Current delivery charges are held fixed, not certified
as the exact historical fee schedule.

## Reproduction and validation

Run `.venv/bin/python -m sensei.research.bonus_portfolio_reproduction` with the frozen
[plan](../../config/bonus-portfolio-reproduction-v1.json). It verifies the contract,
primary PDF bytes, raw/action receipts, availability/tick notes and execution,
fee and selection implementation hashes before evaluating both cases. The runner's
own hash is recorded in the output.

- Final [report](../../data/reports/bonus-portfolio-reproduction/d3bd14d237de126d8fee33f1508af780a55afb0f94506f7a637ee2a9f9457e55/report.json): SHA-256 `d3bd14d237de126d8fee33f1508af780a55afb0f94506f7a637ee2a9f9457e55`.
- Plan SHA-256: `98811bc2c65ec24b996aa6f8272ef0a7bf6fca4b80dff4c5cf3e44944e808706`.
- Runner SHA-256: `4d2d177597b28f0592451d408a2dcd5ae35d8e85e4a0098f11528024d6a34d07`.
- 28 focused portfolio tests pass, covering timing, unknown availability, ex-date
  buyers, gap exits, rational whole-share entitlements, cash constraints, cost and
  dividend attribution, invalid metadata and incomplete liquidation.
- Twelve pre-change versus post-change fixture comparisons preserve all no-bonus
  economic and serialized fields except implementation-dependent experiment IDs.
  This is fixture parity, not a new complete-universe portfolio rerun.
- Full suite: **1,111 passed**, 29.33 seconds.

Independent Standards and Spec reviews found and resolved: a missing modeled
ex-session could skip accrual; a zero-sale pending exit could block unrelated
entries; the runner omitted the transitive fee implementation pin; and its inherited
signal label incorrectly described adjusted history. Regression tests cover the two
accounting failures. Final reviews report no residual findings. The initial report
is retained; the final rerun changed provenance pins/labels, not cases or parameters.

## Remaining portfolio gates

The [daily NSE universe assessment](daily-nse-universe-feasibility-2026-09-07.md)
identifies a viable separately named, lagged liquidity universe that can still be
compared with Nifty 500 gross TRI. It does not need historical index constituents,
but it does need dated ordinary-stock classification and identity coverage. `EQ`
and `STK` alone include ETFs; current instruments cannot be backfilled as historical
eligibility. With the present raw archive, 252-session warmup first supports entry
on January 6, 2025, subject to each instrument's own coverage. Earlier evaluation
requires earlier verified raw history.

Next work is dated classification/identity evidence and an eligibility manifest,
plus the remaining mandatory-action accounting before a complete coherent rerun.
The old raw controls remain −4.401% and +7.916%, against Nifty 500 gross TRI +22.9535%;
this holding diagnostic does not replace them or establish deployable performance.
No Kite calls/credits, purchases, live orders or external messages were used.
The overnight heartbeat remains paused.
