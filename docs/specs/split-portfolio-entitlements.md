# Share subdivisions in the research portfolio

Extend the existing `run_portfolio_campaign(..., raw_accounting=...)` seam to
explicit `split` actions. This supersedes only the earlier bonus contract's
unsupported-split restriction. Preserve no-action, dividend and bonus economics
and output fields apart from implementation-dependent experiment identity.

A subdivision replaces every held old share. On its ex-session, multiply economic
quantity by the supplied total-share ratio and divide economic entry basis and
brackets by that ratio before dated tick rounding. No cash, revenue or extra fee
arises from the subdivision itself. Earlier dividend entitlements remain unchanged.
New ex-session buyers purchase resulting shares and receive no prior-holder action.

Unlike a bonus, **all resulting split shares are pending** until the explicit
availability date and first-known date are both reached. Never leave the old
quantity sellable in new units. Same-session availability may release all resulting
shares before the opening exit. Unknown availability leaves all resulting shares
pending, valued separately from cash. Availability metadata uses the existing
`scenario` or `documented_market_admission` basis; neither proves account credit.

Preserve the first exit request while pending and sell at the first available raw
open. Pending holdings occupy position/risk slots, block symbol reentry and cannot
fund other purchases. A zero-share exit cannot block unrelated strategy entries.
Final liquidation cannot manufacture availability. Share ledgers identify splits
explicitly; mixed portfolios report the combined split/bonus policy accurately.

Only share-increasing subdivisions with positive integer ratio terms and whole
resulting shares are supported. Reverse splits, fractions, rights, mergers,
demergers, simultaneous mixed actions and accounting actions while shares are
pending remain unsupported. Reject missing in-window ex-sessions, knowledge after
ex-date and partial/invalid availability evidence. Scope validation also applies
to actions with no held position. Identity and action completeness are caller
evidence obligations, not inferred from raw price ratios.

Acceptance: three shares at ₹300, split 3/1, raw mark ₹100: nine economic shares,
₹900 equity and no change in cash. If availability is unknown, all nine are pending.
If a time exit is requested on the ex-date and release later occurs at ₹110, all
nine sell for ₹990 then. If availability is documented for the ex-date, nine can
sell that day. A bonus under the same ratio still leaves three originals sellable.

Use the captured HEG split, old/new ISIN lineage and NSE new-ISIN trading notice for
a fixed forced-holding reproduction with documented market admission and unknown
availability controls. Retain explicit account-credit and date-level knowledge
limitations. This verifies accounting, not strategy effectiveness or a historical
universe. Do not alter frozen earlier plans or reselect parameters after returns.
