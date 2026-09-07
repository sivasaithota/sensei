# Bonus entitlements in the research portfolio

Implement through the existing `run_portfolio_campaign(..., raw_accounting=...)`
interface. No live execution or production authority changes. Legacy and raw runs
without bonus events must retain their economic results and serialized fields,
apart from implementation-dependent experiment identity.

## State and timing

A pre-ex holder owns the additional whole-share entitlement from the ex-session,
including when selling its original shares on that session. A new ex-session buyer
does not receive the entitlement. At the ex-session open, total economic quantity
and entry basis/brackets move into the new units. Original shares remain sellable;
additional bonus shares are a separate non-sellable receivable, marked using the
same security's raw close. No cash or gain is created by a pure unit change.

Availability is an explicitly supplied date, first-known date, source SHA-256 and
basis (`scenario` or `documented_market_admission`). Neither label certifies broker
credit. Release occurs at the open of the first modeled session on or after both
dates. A missing availability date keeps the entitlement pending indefinitely.
Allotment and an expected trading date are not automatically converted into credit.
The BSE May 27, 2025 date is a scenario assumption until stronger evidence exists.

An exit request sells only currently available shares. Remaining pending shares
keep the original exit request and are sold at the first available session's raw
open, with the existing sell-tick/cost policy. A recovery before release does not
erase the queued exit. Entry cost and reserved buy/round-trip costs are allocated
proportionally between exit legs; each actual sale receives its applicable sell
cost. Trade rows represent sale legs, not independent entries. The economic basis
used here is not statutory bonus-share tax accounting.

Pending holdings retain position/risk slots and block reentry into that symbol.
Their marked value contributes to economic exposure/equity but never buying power.
Final-session liquidation cannot sell unavailable shares: residual holdings and
receivables remain visible, with liquidation marked incomplete. No invented
settlement price or forced fraction sale is allowed.

## Scope limits and validation

The first slice handles bonuses yielding whole total shares for the actual held
quantity. Fractional outcomes fail the complete run. Splits, mergers, demergers,
rights, overlapping pending entitlements and another accounting event while a bonus
is pending remain unsupported. Same-symbol simultaneous bonus/mixed events reject.
Mandatory events do not become safe just because the implementation supports a
different event of the same general family.

For a bonus, require an integer positive total-share numerator/denominator greater
than one, known by the ex-session; no dividend amount may accompany it. Reject
partial availability metadata, invalid dates and unknown bases. Availability may
remain unknown or extend beyond the evaluation horizon. A release is a share-state
transfer, not cash, revenue or a second entitlement.

## Worked acceptance examples

- With ₹900 and three shares bought at ₹300, a 2:1 bonus gives nine economic shares
  at a ₹100 basis: three sellable and six pending. At a raw mark of ₹100, equity
  remains ₹900, cash ₹0, invested ₹300 and share receivables ₹600.
- An ex-date time exit sells three at ₹100. Cash becomes ₹300; six pending remain
  worth ₹600. If availability arrives when the raw open is ₹110, the six sell for
  ₹660 and final cash is ₹960. No six-share sale occurs earlier.
- If availability never arrives, final-session liquidation leaves cash ₹300 and
  a visible six-share receivable. A declared later date cannot leak earlier cash.
- Ex-date purchases receive no bonus. Fractional outcomes, duplicate/mixed events
  and incomplete availability metadata reject. Dividends from before the bonus
  reconcile through proportional trade attribution without being counted twice.
- Tests exercise real entry/open/intraday/final phases, costs, deferred exits,
  same-day availability, repeated sessions and economic/strategy-P&L reconciliation.

The output records ex-date accruals, releases, availability assumptions and pending
positions. Existing dividend receivables remain separate and non-reinvested.
Historical membership and source completeness remain independent research gates.
