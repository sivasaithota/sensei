# Integrated stock research closure

The owner requests the remaining fixes together. Build one reproducible research
pipeline from frozen raw NSE observations to entry eligibility, coherent raw-price
signals, physical-share accounting and Nifty 500 TRI comparison. Preserve the
existing architecture, earlier evidence and unrelated runtime/user files. No live
activation, orders, purchases or claims of guaranteed performance.

## Frozen acquisition and period

Evaluation is 6 January 2025 through 3 September 2026, with saved raw observations
from 1 January 2024 for warmup. Capture each immediately preceding exchange-session
master needed in that period, 413 dates from 3 January 2025 through 2 September
2026. The acquisition scope is frozen before requests. Use existing bounded
six-date capture partitions, sequential spacing, 15-second timeouts, one request
per uncached date, retained failures and verified reuse. This larger scope replaces
the earlier diagnostic limit of 40 for this expressly authorized integration only.
Do not refetch failures or fill missing masters with older/current snapshots.

## Decisions and universe

Use a separately named research proxy: prior-session MII broad equity type 0,
EQ, normal-market marker 1, listed permission 0, eligible nonsuspended status,
raw deletion flag N and lot 1. Preserve the prior master identity and source date.
Historical pre-open publication and exhaustive ordinary-share subtype remain
assumptions/blockers unless primary evidence resolves them. Never label this
proxy a certified historical Nifty 500 universe or allow it into live execution.

Build the instrument superset from all historically observed unique EQ/BE rows,
not today's constituents. Entry decisions use only preceding-session metadata
and prior price history. Same-day raw identity is an execution check, not an
admission-ranking feature. Missing/ambiguous metadata, identity conflicts, raw
gaps, invalid prices and insufficient history block new entries explicitly.
Missing entry metadata never removes held positions or waives held-price checks.

Require 252 consecutive prior observations in one stable symbol/ISIN identity,
resetting after identity changes, raw-session gaps and non-dividend accounting
events. This deliberately conservative research policy avoids inventing unit
adjustments across uncertain events. Signals and ranking use raw prices inside
that stable window. No future events may reset or suppress earlier history.

## Accounting and evaluation

Reuse physical-share execution, dated ticks, cash dividend receivables, fees,
slippage, position limits and bracket semantics. Whole-share splits/bonuses may
use explicitly labelled research availability scenarios; document ratios, sources
and the availability convention. Never present scenario availability as verified
broker credit. Unsupported held actions, identity breaks or missing held prices
must stop the affected simulation with an explicit blocker, not vanish or generate
synthetic fills. Fractional entitlements and simultaneous unsupported actions are
not silently rounded or ignored.

Freeze four existing hypotheses before evaluation: momentum breakout with 30/60
session holds, 50-DMA pullback and RSI(2) reversion. Keep their existing stop/target
settings and use the same ₹300,000 capital, current delivery costs, 10 bps entry
slippage and portfolio limits. No parameter search or after-the-fact winner tuning.
The configured drawdown threshold remains a reported acceptance threshold; do
not imply it guarantees a maximum realized drawdown.

Pin inputs, source receipts, policies, code and benchmark before evaluating.
Report dates, coverage, blocked-entry reasons, executed trades, accounting
limitations, net return, drawdown, costs and aligned Nifty 500 gross TRI. A stopped
simulation gets no valid performance claim. Completed research results still
remain inadmissible for live trading while classification/availability assumptions
or required validation remain unresolved. Mark previously inspected history as
development data, never fresh holdout evidence.

## Documented split identity transitions

An old-ISIN corporate-action row may be linked to the new raw identity only with
an explicitly pinned, dated exchange notice naming the new ISIN and matching the
split ratio and ex-date. Require the immediately preceding raw observation to
match the source old ISIN. A valid bridge can accept NSE's unadjusted yesterday
close on the ex-row, as well as a ratio-adjusted previous close. The notice must predate the ex-session: a same-day date cannot establish
availability before the opening. Missing or later notice dates, wrong identities,
ratios or dates never authorize the transition.
This bridge applies only to split accounting; history still resets, dividends
cannot borrow it, and market admission does not establish broker share credit.
