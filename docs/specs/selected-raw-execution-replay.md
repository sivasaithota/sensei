# Selected raw-price execution replay

Pass 9 replays the four distinct MAZDOCK/HEG entries established by the original
split audit, preserving their eight source records across the two controls.
This is a forced-entry development diagnostic, not a complete strategy or portfolio
rerun. Use the original selected entry, strategy exits, costs, capital and sizing
limits; full initial cash is available in each isolated case.

Use verified raw NSE sessions for every benchmark session from the predecessor
through the saved exit date, with exact canonical symbol, old ISIN and EQ series.
Missing/ambiguous/invalid rows or unresolved action coverage block that case and
remain in the report. Require a separately documented source review of in-interval
actions; do not infer absence of dividends/bonuses from a stable ISIN alone.

The saved adjusted-data decision fixes the entry signal. Actual raw prices drive
entry, brackets, exits and marks; use whole physical shares. Stop at the saved
exit date, labeling any forced final closure as horizon-censored instead of
asserting that the strategy would really exit then. Report raw/adjusted outcomes
as isolated-case results, never combine them into a portfolio performance claim.

Add optional constant tick rounding to the research simulator for these explicitly
bounded intervals: hypothetical single entry fills round up after buy slippage,
stop levels round down, target levels round up. Compute rounding with decimal
arithmetic and size from the rounded stop, retaining cash and fee-inclusive risk
constraints. Omitted mode must preserve existing numerical behavior. Bind the
tick configuration and implementation into campaign identity. Caller evidence
must establish the constant historical tick; no inference from today's price,
adjusted price or same-day price. This is not a general historical tick engine.

Pin source reports/proofs, raw-session receipts, source action/tick notes and
the replay implementation. Retain DATA_BLOCKED and can_trade=false. Test exact
tick boundaries, conservative directions, sizing after rounding, omitted-mode
parity and blocking missing raw/action coverage. Run actual cases, independent
Standards/Spec reviews and the full suite; document limits and commit/push.

NSE's complete returned 2024 symbol-filtered action responses must also be captured
and hashed, with request scope retained. Check every returned ex-date against
each holding interval; any in-interval action blocks the replay. Empty, malformed
or wrong-symbol responses cannot certify absence. This establishes scoped
absence within the exchange response, not a universal action-history certificate.
