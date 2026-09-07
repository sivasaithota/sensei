# Split-unit audit of saved trades

Pass 6 investigates a demonstrated execution representation issue: integer
quantities bought on backward split-adjusted prices may represent fractional
physical shares. It does not rerun or optimize the strategy.

Use the complete saved held-price screen and a bounded, manually transcribed
primary-evidence ledger for MAZDOCK and HEG. Preserve every source trade,
including duplicates between portfolios. Pin the screen checksum, its source
proofs, the ledger bytes, cited local research note and audit implementation.
Retain research-only, DATA_BLOCKED and can_trade=false.

For a single evidenced split with an old/new ISIN transition, require entry and
exit before its effective date, and the split on or before the frozen capture's
scope end. Require the canonical exchange symbol, raw old ISIN and reference
new ISIN to agree with the ledger. Both endpoints must exist and their volume
scaling must agree with the documented integer share multiplier. Require each
adjusted OHLC field to agree with raw divided by the multiplier within ₹0.05
in adjusted-price units, an explicit diagnostic rounding envelope. This does
not establish exchange-valid tick prices or complete intervening action coverage.

Only then calculate exact physical-share equivalent using rational arithmetic,
flag fractional quantities, and report the largest whole-share quantity no
larger than the saved entry quantity, represented in both physical and adjusted
units. No price, position, cash, P&L or fill dates change. Do not call these a
corrected portfolio or claim that integral quantities certify a trade.

Keep outside-ledger, post-event, crossing-event, missing, identity-mismatch and
scaling-mismatch records explicitly unevaluated. Multiple applicable events
must be ambiguous rather than silently compounded. Reject malformed dates,
nonpositive quantities and invalid/noninteger split multipliers.

Test fractional versus integral quantities, event boundaries, missing and
conflicting evidence, input corruption and complete record preservation. Compare
the real baseline and hold60 artifacts, run required checks and independent
Standards/Spec reviews, document findings and the next implementation step.
