# Liquid relative strength: implementation and first registered batch

Completed 2026-09-08. **The implementation is tested; the first batch is blocked
by accounting and metadata evidence. There is no complete strategy return yet.**

The [reviewed plan](../../config/liquid-relative-strength-v2.json) retains the
specified four policies, five base account paths and five fixed stresses. It
preserves all selection/risk parameters from the research proposal. The earlier
v1 plan is retained as an unsimulated draft; v2 incorporates pre-performance code
review corrections. [Run instructions](../operations/liquid-relative-strength.md).

## Implementation and verification

- Six/twelve-calendar-month volatility-adjusted ranking; hard ₹5 crore liquidity
  threshold; top-200 universe; independent calendar-year observed-history check.
- Monthly buffered model roster, kept independent of actual stopped holdings;
  purchases in current ranking order. Semiannual and liquidity controls are separate
  policies, not official index replications.
- Formation-frozen whole-share buy ceilings, current-equity execution limits,
  5% cash reserve, 0.1% daily capacity cap, expiry and persistent partial exits.
- Daily-close ATR trailing exits with next-session execution, no fixed profit
  target, and no intraday stop inferred from the day's later high/low.
- Separate spendable cash, unsettled sales, nonspendable dividends and unavailable
  split/bonus shares; fees and monthly data overhead; stock attribution reconciles
  to account equity.
- Immutable input manifest and per-attempt registrations before simulation;
  missing formation evidence or unsupported held accounting prevents a complete
  return. Existing live code/configuration is unchanged.

The full suite passed: **1,240 tests in 30.21 seconds**, including 22 new focused
tests. Compilation checks passed; no standalone type-checker is configured in this
repository. `git diff --check` passed. Input/code/spec hashes still match the run.

**Standards review:** no hard documented-standard violations or material style
findings. One reproduced correctness issue—applying an initial-stop guard to an
existing holding—was fixed and regression tested. Reviewer verified the correction.

**Spec review:** two findings—purchase priority within buffered membership and
calendar-year age separate from month-end endpoints—were fixed and regression
tested. Reviewer verified both corrections. Report timestamp serialization was
also checked with a JSON round-trip before the first run.

## Actual run outcomes

| Attempts | First blocker |
|---|---|
| Candidate, no-trailing control, 20/40 bps slippage, execution delay, half capacity, three-session exit delay | CUPID bonus on March 9, 2026: source action identity differs from raw traded identity |
| Liquidity control | TATAMOTORS demerger on October 14, 2025: separate resulting-share accounting is unsupported |
| Semiannual control | Missing June 30, 2026 formation security master |
| Earlier-start candidate | AMIORG split on April 25, 2025: identity transition plus unrevised previous-close field is unresolved by the current adapter |

All **ten** attempts are `SIMULATION_BLOCKED`; batch verdict is
`INCOMPLETE_EVIDENCE`. No partial return is presented as a completed result, and
there is no valid Nifty 500 TRI strategy comparison from this batch. A blocked
run neither accepts nor rejects the momentum hypothesis.

The full formation audit also identifies missing masters for **March 30, April 30,
June 30 and July 31, 2026**. Sixteen other completed month-end formations each
produced a 200-stock ranked universe. The partial September source month was not
mistaken for a scheduled review. Underlying prior-master capture counts remain
363 validated and 50 blocked out of 413.

## Exact evidence repair scope

1. **CUPID:** source action ID
   `1019a0ab856d1d2383d144f9aa9d69ddf3b295987d6c832647e08dd87fc824e9`
   names `INE509F01011` for the 4:1 bonus. Immediate prior and ex-date raw rows
   instead use `INE509F01029`; the ex-date previous-close field remains ₹402.20.
   Establish a dated identity link, bonus terms and availability, and explicitly
   reconcile that unrevised previous-close convention. A large price change alone
   cannot authorize a fivefold quantity adjustment. A January 2026
   [NSE issuer filing](https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_139103_30012026161342_iXBRL_WEB.html)
   supports the proposed 4:1 bonus; proposal approval alone is not the full ex-date
   and sellability evidence. This source lead has not been admitted to the runner.
2. **AMIORG:** April 24 raw close ₹2,202.50; April 25 open ₹1,118.00, with
   `INE00FF01017 → INE00FF01025` but the raw previous-close field still ₹2,202.50.
   Existing [identity research](remaining-split-identities-2026-09-07.md) already
   cites the documented 2:1 split and subsequent June 2 AMIORG→ACUTAAS rename.
   Connect both events to held-position accounting; repairing the split alone
   would leave the later symbol-continuity problem.
3. **TATAMOTORS:** preserve the continuing holding and separately account for the
   resulting company's entitlement, valuation and later availability, including
   the October 24 TMPV rename. Existing
   [demerger research](share-action-classification-demergers-2026-09-07.md)
   records the relevant source chain. A tax cost-allocation percentage is not an
   executable price adjustment or additional parent shares.
4. **Four formation masters:** obtain admissible dated metadata or leave these
   formations blocked. Do not reuse a prior universe or skip the review to improve
   the strategy's record.

Apply evidence/accounting corrections to every policy and stress under a new
registration. Keep v2 intact. Do not change the strategy parameters, remove the
affected trades or declare a winning control during this repair.

## Artifacts

- Run ID: `abfd6b3bcc933518e397f834c08100839330db35d7f1e1a1a813f2c331b06e66`
- Report SHA-256: `e3108e3a6501f6cdb06cca2006ffaa4dd17928ee0682593f3ce972fc89d34ce8`
- Plan SHA-256: `05180d00e5bc7d93b1c9ed1ce75fda50f974312596b0d131351badcb4cd4a770`
- Local report:
  [report.json](../../data/reports/liquid-relative-strength/abfd6b3bcc933518e397f834c08100839330db35d7f1e1a1a813f2c331b06e66/report.json)
- Local source and implementation manifest:
  [manifest.json](../../data/reports/liquid-relative-strength/abfd6b3bcc933518e397f834c08100839330db35d7f1e1a1a813f2c331b06e66/manifest.json)

No Kite requests, purchases, orders, live activation or drawdown-setting changes
occurred. Additional production overhead, executable passive-product comparison,
sector coverage and terminal liquidation evidence remain explicitly unresolved.
