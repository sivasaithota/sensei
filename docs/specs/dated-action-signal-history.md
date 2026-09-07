# Dated corporate-action signal history

Status: bounded research contract, written before its synthetic acceptance run.
This extends the requirements of [the market-data catalog](point-in-time-market-data.md)
without changing catalog admissibility or the frozen portfolio inputs.

## Scope and interface

One pure research function, `signal_history(raw, actions, as_of)`, returns a copy
of a single stable instrument's raw daily OHLCV history through a decision session,
in that session's share units. An action contains an identity, ex-session,
first-known session, kind and exact positive rational new-shares/old-shares ratio.
Only splits and bonuses are supported. This function exercises transform
mechanics; caller-provided dates/ratios are not verified corporate-action evidence.
No production catalog, strategy, order, portfolio or cash path calls it.

The first slice uses end-of-session knowledge. Date-only announcement evidence is
usable no earlier than the following exchange session unless a pinned publication
timestamp proves availability before the decision. The caller must map publication
timestamps to that conservative first-known session before constructing an action.
Session mapping, historical identity and complete source coverage remain required
upstream evidence. A symbol match or this diagnostic passing cannot satisfy them.

For an event with ratio r effective at e, a decision at d >= e applies OHLC / r
and volume * r only to rows before e. Rows on e already use new units. Multiple
events compose in chronological order. Events after d never alter the returned
history, even when announced earlier. A completed event whose first-known session
is after d blocks the result: do not smooth an unexplained past discontinuity using
future information, or silently return raw mixed units. Missing/unknown events
cannot be detected by this function; coverage certification stays outside it.

All other columns remain unchanged, including supplied currency turnover. The
transform must preserve raw input, retain genuine price movement, avoid rounding
indicator values to exchange ticks, reject duplicate action identities and
conflicting same-session actions, reject nonfinite/invalid OHLCV and reject unknown
action kinds when effective by the decision. No synthetic rows or prices are added.
Input dates are unique, ordered, timezone-naive midnight session labels; action
dates and the decision use the same representation. Future raw rows are discarded.

## Three separate economic treatments

1. Signal history: split/bonus unit normalization only in this slice. A cash
   dividend does not change share count. A future separately named total-return
   signal policy would need its own formula, dated inputs and experiment identity;
   it must never be silently substituted here.
2. Holdings: physical entitlement processing remains a different implementation.
   For a split/bonus, quantity, entry-cost basis per share and price brackets would
   transform coherently, with no gain created by the unit change. Fractional
   entitlements, allotment/credit timing and tradability require explicit evidence;
   the signal ratio alone cannot authorize sellable shares. Existing raw accounting
   still rejects unsupported mandatory events held across their ex-session.
3. Dividends: existing results accrue gross receivables on the modeled ex-session
   and exclude them from buying power throughout. An actual cash-payment model
   would move a verified receivable into cash once, on its evidenced availability
   date, without increasing total equity a second time. Payment timing, tax and
   reinvestment are not implemented by this signal transform.

Rights, demergers, mergers, capital reductions, fractional settlements, simultaneous
mixed actions and missing lineage remain blocked. Do not derive a demerger factor
from a later listing price. This module deliberately rejects even cash dividends
in its action input; a broader price-only policy must explicitly classify them
before integration, rather than having this first slice silently ignore events.

## Acceptance examples fixed before implementation

- Split 5-for-1: prior OHLC 100/110/90/100 and volume 10 become
  20/22/18/20 and 50 on/after the ex-session; ex-session raw prices remain unchanged.
- Bonus 1-for-1: ratio 2, not 1. Prior price 100 becomes 50 and volume 10 becomes 20.
- Split ratio 5 followed by bonus ratio 2 yields a cumulative factor 10 for rows
  before both, factor 2 between events, and factor 1 after both.
- Before effectiveness, an announced split changes no past row. Before knowledge,
  an already-effective event blocks instead of leaking the later announcement.
- Adding arbitrary future raw rows or future effective events changes no earlier
  decision history. Recomputing an old decision never reuses a later decision's
  transformed array. This is distinct from fixed-vintage signal prefix invariance.
- Pure unit changes preserve price-times-volume; an actual ex-session price rise
  remains a rise after normalization. Raw input and extra columns are unchanged.
- Invalid ratios, dates, OHLCV, duplicates, unknown effective actions and malformed
  schemas reject; no malformed result is usable as a partial success.

## Evidence needed before integration

A production adapter must pin raw bytes, stable identity intervals, a complete
event register over warmup and evaluation, dated revisions/supersessions, ratio
orientation, session conventions and this policy/version. Revisions must preserve
the originally knowable vintage rather than rewrite earlier decisions. Evidence
must distinguish an explicitly empty action interval from missing coverage.
Raw sources revised after the decision remain a separate vintage limitation.

Integration requires independent real split/bonus reproductions and daily decision
replay through ranking/correlation, plus physical entitlement and tick tests for
held positions. It must retain removed constituents and refuse incomplete historical
membership. Synthetic acceptance alone leaves `DATA_BLOCKED`, `RESEARCH_ONLY` and
`can_trade=false`. No new performance claim follows from this module.
