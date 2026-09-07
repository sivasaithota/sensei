# BSE bonus and dated indicator replay

Preregistered research contract; no portfolio run, strategy selection or promotion.
The existing 2:1 BSE bonus classification fixes total new/old shares at 3/1.
No ratio or window is selected using replay returns or scores.

## Fixed scope

- Symbols: BSE and HEG. BSE exercises a real bonus; HEG exercises the previously
  verified split within a longer indicator history and supplies a correlation peer.
- BSE ex-session: 23 May 2025. Required pre-ex evidence: company 12 May notice
  and NSE 14 May circular. Conservative first-known session: 15 May. The later
  26 May allotment notice may corroborate terms but never establish earlier knowledge.
- HEG split: 18 October 2024, ratio 5/1, conservative all-support knowledge 18 October,
  using the existing pinned October listing/clearing notices.
- History: 252 observations through the first decision, then all available history
  through each subsequent decision. Eleven decisions run from five exchange sessions
  before BSE's ex-session through five after. The calendar is the frozen raw portfolio
  receipt calendar; gaps, ambiguous identities or changed receipts block the run.
- Each history must have a unique EQ row matching the expected dated ISIN. BSE uses
  INE118H01025 throughout, verified against each raw row and the pre-ex notice. This
  does not independently certify all historical identity transitions or membership.

## Explicit indicator convention

`share-unit-price-only-v1` normalizes only documented splits/bonuses. All observed
actions over the entire warmup and decision window must be matched by source ID to
the predeclared treatment list. Unknown, missing, extra or changed events block.
Three expected cash-dividend rows (including an AGM/dividend row) remain raw price
moves. Their monetary amounts do not transform indicator history or fund simulated
cash. This is an explicit price-only convention, not total-return adjustment and
not an omission from action coverage. There are no holdings or entitlements in this
diagnostic. The underlying action API still provides observed, not certified complete,
coverage. No general production action policy changes.

Reported raw currency turnover stays unchanged; ranking liquidity uses its trailing
60-session mean. This input choice is fixed for all comparisons here and does not
silently replace the frozen portfolio's liquidity inputs. Share-unit-normalized
volume is appropriate for this declared relative-volume indicator convention; it
is not an assertion that historical traded share counts changed.

## Checks fixed before replay

For each decision and both stocks:

1. Build fresh dated history with `signal_history`, applying only already-effective,
   already-known share events to earlier rows. Never reuse the final vintage for an
   earlier decision.
2. Compare each OHLCV cell with an independent rational-factor oracle, with maximum
   rtol 1e-12 and atol 1e-10. Compare raw turnover unchanged. Verify raw inputs remain
   unchanged, and full future input versus truncated input yields identical history.
3. Evaluate the existing momentum_breakout_55 signal and every SignalRankingPolicy
   component on actual and oracle histories. Stop/target inputs are fixed at 5%/12%,
   with no performance evidence. At least 252 observations precede or include each
   decision. Scores are descriptive checks, not simulated trades.
4. Compare the existing return_correlation output with oracle inputs, using the
   policy's 60-session lookback and its existing exclusion of the latest return.
   Record score order for both stocks and signal-eligible order separately.
5. Record the same calculations on raw unnormalized inputs as a diagnostic contrast.
   Differences are neither alpha nor a pass criterion; preserve all differences.
6. A deliberately omitted bonus factor must fail the oracle check. An effective
   bonus assigned knowledge after the decision must block. Synthetic regression
   tests also inject future dependence and verify rejection.

The BSE ex-session close is compared with the previous raw close divided by three.
No exchange tick rounding, fractional bonus credit or post-ex allotment tradability
is inferred. A successful output must still be RESEARCH_ONLY, DATA_BLOCKED and
can_trade=false. It does not establish a historically complete universe, vintage
availability, successful portfolio or executable bonus-entitlement accounting.
