# Demerger accounting closure: frozen research contract

9 September 2026. Implements the user's accounting-and-evaluation closure release.
This extends the [unchanged momentum strategy](liquid-relative-strength-v1.md).
No new alpha, parameter search, live configuration or orders. Review baseline:
`6f2d346`. Public test seams: portfolio replay, source repair and batch input audit.

## Source and valuation convention

Use the pinned [primary source research](../research/demerger-closure-sources-2026-09-09.md)
and [valuation investigation](../research/demerger-entitlement-valuation-method-2026-09-08.md).
Replace only the two exact rejected demerger events identified in the plan.
Parent and children remain separate instruments; the Tata parent rename preserves
its ISIN and actual observed execution symbol. The split/bonus-only RawAccounting
contract and original closure source artifacts remain unchanged.

At the ex-session, before any executions, distribute the legal quantity for all
parent shares held at the prior close. This retains the existing T+1 delivery
assumption; entry on the ex-session cannot earn entitlements. If parent shares
remain unavailable from a prior action, fail for unresolved eligibility. Ratios
must yield whole shares. No fractional entitlement or tax allocation shortcut.

Aggregate mark per old parent share is max(0, previous raw close minus ex-session
raw open), with the explicit `NSE_SPOS_RULE_PLUS_RAW_OPEN` inference. Dated SPOS
notices and the NSE opening-price definition support it; no independent numeric
auction bulletin is claimed. Equal economic value is assigned to each resulting
company, divided by its legal share quantity, with full precision. Zero valuation
does not remove legal ownership. Multi-child methodology revision predates VEDL.

Until each child's listing, retain its initial nonspendable mark. From listing
use that child's contemporaneous raw open/close, including observed BE quotes for
valuation. Never backfill listed prices. Missing/changed child prices or identities
block the accounting result. Later reference prices only validate source inference.

Transfer aggregate internal book basis in proportion to the initial distribution
value divided by the parent's discovered price plus distribution value. Divide
transferred basis equally between children, preserving total parent/child basis.
This is P&L attribution, not tax cost-basis reporting. No value is created by the
book transfer; future market gains, dividends and realized fees reconcile to NAV.

## Parent state and child disposal

Cancel pending parent buys and trims on the ex-date. Keep persistent full exits
and their remaining parent quantities. Subtract aggregate distribution per parent
share from its stop and high-water close; retain original entry ATR. Apply the
normal close-trigger rule afterward. This is the same cash-distribution distance
convention already used for dividends, not an additional signal filter.

Resulting securities are compulsory holdings with persistent disposal instructions,
not new selected entries. Their first eligible sale is after the first listing
close and after the dated listing notice is known, with market admission used as
an explicitly assumed account-availability date. Execution/exit stress delays apply.
Individual broker credit timestamps are not established. No automatic sale at an
index deletion price, listing open, tax factor or unlisted mark.

Retain existing dated EQ eligibility, observed identity/token checks, one-share
lots, reconstructed ticks, whole-day activity checks, prior **60-session** median
turnover cap, fees and following-session cash settlement. Do not relax these
requirements to liquidate new listings sooner. In particular, VEDL children have
58 observed sessions through September 3; their terminal holdings may remain
unsold. That is a complete marked scenario, not completed liquidation.

Compulsory child holdings can push account security count above ten at distribution;
they occupy slots and gross exposure, blocking further purchases until room exists.
Do not buy a security already held as an entitlement. Children cannot overlap an
existing selected position when granted. This bounded model rejects overlapping
or fractional grants and subsequent child non-cash actions; preflight inventories
these before any economic run. Ordinary listed-child cash dividends accrue as
nonspendable receivables under the existing contract. Unlisted-child distributions
require explicit reconciliation, not an unadjusted constant mark plus extra cash.

## Batch and completion gate

Keep all ten existing registered cases, dates, costs and strategy parameters.
Add one explicitly registered accounting diagnostic: common-inception candidate
with unlisted value excluded from sizing equity. NAV and its cash reserve remain
unchanged; target/gross budgets use the reduced sizing equity. Child assets never
supply spendable cash in either case. The diagnostic is not another alpha candidate.

Before simulation, derive the union of scheduled rosters under every registered
policy from its inception, plus all resulting children. Inventory every unsupported
action, missing/invalid raw price, invalid configured rule and failed formation in
that conservative potential-ownership scope. Keep the full report and block the
batch if any gap remains. No position exclusion, dropped month or iterative first-
error-only performance report. Dated execution permission/capacity gaps defer orders.

Report all eleven registered cases, aligned TRI, fees/data overhead, marked NAV,
return/drawdown, exposure, contributions, nonspendable entitlements and their days
outstanding, and terminal holdings/disposal status. Retain all previous plans and
runs. All examined dates remain development data.

Apply the original development rejection criterion unchanged: candidate and doubled
slippage must each have positive net return and positive aligned Nifty 500 TRI
excess. Otherwise reject this version on this sample. A positive result remains
provisional research, not a paper/live promotion. The conservative accounting
scenario is disclosed alongside the base; material dependence on it must be stated.

Completion means a full, reconciled comparison and an explicit decision. Additional
production overhead, certified cash/credit timing, sector labels, executable passive
comparison and future confirmation are disclosed limitations, not excuses to keep
tuning this batch. No implementation or evidence change can overwrite an earlier run.
