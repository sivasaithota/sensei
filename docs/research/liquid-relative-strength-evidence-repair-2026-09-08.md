# Liquid relative strength: evidence repairs and latest development batch

Research date: 8 September 2026. This supersedes the blocker inventory in the
[first-run note](liquid-relative-strength-first-run-2026-09-08.md), whose original
results remain unchanged. The strategy is implemented and tested. Its main
portfolio comparison is still incomplete; it is not approved for live trading.

## What changed

The [v6 plan](../../config/liquid-relative-strength-v6.json) keeps the same signal,
roster, costs, risk parameters, account inceptions and ten registered account
paths. It adds evidence, not a new strategy variant. The design's original
"not implemented" heading is retained as part of the hashed proposal; current
implementation status is recorded here and in the [run instructions](../operations/liquid-relative-strength.md).

**Security masters:** 48 of the original 50 failed captures now pass the existing
URL, date, compressed-body, schema and identity checks. All four missing formation
dates are restored. Coverage is 411 validated dates out of 413; February 18 and
October 29, 2025 remain unavailable after bounded retries. Missing execution
permission still defers orders. It does not justify a fabricated fill or using a
later master. All twenty monthly formations have 200 ranked stocks.

The first recovery covered the four known formation gaps. Before evaluating the
v5 return, we recorded a uniform retry scope for every remaining failed date;
all five remaining HTTP failures received one second attempt. The original
captures, failed responses, replacement bytes and hashes are retained. This was
56 public NSE metadata requests in total, with no Kite requests. Successful
retrieval does not establish historical publication time: that remains a research
availability convention. The local validation receipts are
[formation repairs](../../data/research/strategy-design/20260908/master-recovered/validation.json)
and [remaining-date repairs](../../data/research/strategy-design/20260908/master-rest-reprobe/validation.json).

**CUPID:** replace only the exact rejected March 9, 2026 event. Its documented
4-for-1 bonus creates five total shares per old share. The March 2 record-date
notice and March 5 NSE admission circular establish the event and the traded
ISIN INE509F01029, despite the action API's stale identity. Additional shares use
March 11 market admission as the availability scenario; that is not proof of an
individual account's credit time. [Company notice](https://archives.nseindia.com/corporate/CUPID_02032026165927_Record_Date_and_Deemed_Allotment_Date_Intimation.pdf),
[NSE admission circular](https://archives.nseindia.com/content/circulars/CML73156.pdf).

**AMIORG:** the April 22 exchange circular establishes the April 25, 2025 2:1 split
and INE00FF01017 → INE00FF01025 transition. The unchanged raw previous-close field
is cross-checked explicitly. Additional-share availability retains the declared
ex+2-session research scenario. NSE's May 27 notice establishes the June 2
AMIORG → ACUTAAS rename; the adapter joins consecutive same-ISIN observations
while retaining actual execution symbols. [Split circular](https://www.msei.in/SX-Content/Circulars/2025/April/Circular-17050.pdf),
[NSE rename notice](https://archives.nseindia.com/content/circulars/CML68201.pdf).

These documents are locally pinned in the plan. A price gap alone does not
establish a ratio. Repairs preserve the original non-dividend signal reset dates
and do not back-adjust ranking windows. The inherited generic ex+2 assumption in
report limitations has the explicit CUPID admission-date exception above.

## Latest results

The batch verdict remains **INCOMPLETE_EVIDENCE**. Nine paths stop before a
complete portfolio valuation; no partial return is reported as completed.

| Account paths | Outcome |
|---|---|
| Monthly candidate, no-trailing control, extended candidate and five stresses | Blocked at VEDL's April 30, 2026 demerger |
| Liquidity control | Blocked at TATAMOTORS' October 14, 2025 demerger |
| Semiannual control | Completed marked research scenario; no demonstrated net edge |

The semiannual control uses the June 30, 2025 formation, first fills on July 1,
and September 3, 2026 endpoint. Its **₹300,000 becomes ₹281,712.81 (−6.10%)**,
versus **−0.33% for Nifty 500 gross TRI** on precisely aligned dates. It trails
by **5.77 percentage points**, with **14.91% maximum drawdown**. Modeled trading
fees are ₹1,572.26 and data overhead ₹7,500. Attribution reconciles within a paisa.

Average gross stock exposure is 15.53%; stopped positions can remain cash until
the next semiannual review. Thus this is the specified slow-cadence-plus-stops
control, not an official momentum-index replication or proof that the entire
momentum family fails. There are five marked terminal holdings and no executed
terminal liquidation. The lower result than v5 follows restored execution
permissions under unchanged rules; the earlier, more favorable result is not
selected as the headline.

- Run ID: `56b4fa5fd0ff79721f4d0114653d7c91c3223328a122cb3256c49e954d595bb3`
- Plan SHA-256: `89bb3c7e029d6e1c74907503161253cb603560051d22f7d7bd26425c99eb922a`
- Report SHA-256: `b181caf118fc58707eb5ba9c2f9ce28778296b36b6494720b761908667969635`
- [Local report](../../data/reports/liquid-relative-strength/56b4fa5fd0ff79721f4d0114653d7c91c3223328a122cb3256c49e954d595bb3/report.json)
- [Manifest](../../data/reports/liquid-relative-strength/56b4fa5fd0ff79721f4d0114653d7c91c3223328a122cb3256c49e954d595bb3/manifest.json)
- [Completed control with fills and attribution](../../data/reports/liquid-relative-strength/56b4fa5fd0ff79721f4d0114653d7c91c3223328a122cb3256c49e954d595bb3/semiannual_control.json)

## What the remaining accounting work requires

A [follow-up investigation](demerger-entitlement-valuation-method-2026-09-08.md)
found an established NSE convention: temporary nonspendable marks from the
parent's special-session price discovery, followed by each child's listed quotes.
The existing raw panel already contains Tata's resulting security and all four
Vedanta children; the latter listed June 15, 2026. This gives the next implementation
a finite valuation contract. It has not yet been added to the strict v6 replay.

A demerger keeps the continuing security and creates claims on different
companies. VEDL distributes four resulting-company entitlements; Tata distributes
one commercial-vehicle entitlement and later renames the continuing security to
TMPV. The [primary-source action investigation](share-action-classification-demergers-2026-09-07.md)
distinguishes ex-dates, identities, ratios and later admission dates. Published
tax cost-allocation percentages cannot be treated as tradable price factors or
additional parent shares.

The next accounting change needs a separate entitlement ledger, documented
parent/child identities and quantities, dated admission and raw-price coverage,
and an explicit valuation convention during any unlisted interval. It must keep
nonspendable entitlements separate from saleable holdings, preserve economic
wealth across the event, and distinguish valuation assumptions from observed
market prices. Freeze that contract before replaying all ten paths. Do not delete
these trades, sell them retrospectively, or tune the selection rules around them.

## Verification and experiment history

The latest full suite passed **1,251 tests in 31.21 seconds**, including **33
focused tests** for this implementation. Compilation and whitespace checks
passed. There is no configured standalone type checker. Standards and spec
reviews verified the earlier fixes and found no material findings in the final
code/evidence adapter review. The v6 change is data/configuration only; all code,
policy and experiment pins match v5, and all 55 direct v6 pins were checked.

| Plan | Purpose | Outcome |
|---|---|---|
| v1 | Unsimulated proposal draft | No performance run |
| v2 | Reviewed implementation | Ten blocked paths; original report retained |
| v3 | Correct control ranking trace labels | Same ten blockers |
| v4 | Enforce actual holding slots and physical daily-volume ceiling | Same ten blockers |
| v5 | Four formation files and documented CUPID/AMIORG repairs | One completed control, nine blocked paths |
| v6 | Uniform recovery of the remaining missing masters | Latest batch above |

Versions v2–v6 contain **50 registered account-path attempts**, including blocked
ones. These are implementation/evidence replays of the same parameter hypothesis,
not independent trials or fresh holdout validation. All dates are previously
exposed development data.

V5's interim semiannual control ended at ₹285,343.91 (−4.89%), versus −0.33% for
the aligned Nifty 500 gross TRI. It remains an immutable historical result;
use the latest uniform-coverage batch above for current interpretation. Controls
with different inception dates must not be compared directly.

Account values are marked wealth, including receivables, rather than terminal
liquidation proceeds. Costs use the current delivery schedule as a historical
counterfactual and ₹500 per started monthly data cycle. Additional hosting/model
costs, verified historical publication timing, circuits, sector constraints and
a costed investable benchmark remain unresolved. The ₹300,000 account model and
100% research drawdown threshold are unchanged. No broker orders, live settings,
credentials, purchases or unrelated runtime/LinkedIn files were changed.
