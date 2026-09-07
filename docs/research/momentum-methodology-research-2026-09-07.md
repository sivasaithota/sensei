# Nifty200 Momentum 30: implementable rules and replication limits

Research date: 2026-09-07. Scope: methodology research only; no strategy implementation, backtest, broker access, or orders.

The defensible next hypothesis is slower cross-sectional momentum with explicit turnover control. The index supplies a concrete signal definition, but does not establish that a smaller, faster retail portfolio will make money. A ₹300,000 cash portfolio can use the idea; it must not claim index replication when it changes the universe, weighting, timing, or exit rules.

## Evidence captured

All source files and SHA256 checksums are recorded in [the manifest](../../data/research/strategy-design/20260907/methodology/manifest.json).

| Source | Captured version | Relevant printed pages |
|---|---|---|
| [Official February 2023 methodology](https://archives.nseindia.com/content/indices/Method_Nifty50_Value_20.pdf) | Original PDF, 195 pages; 20230222 | 110–113 |
| [Official archive methodology](https://archives.nseindia.com/content/indices/Method_NIFTY_Equity_Indices.pdf) | Original PDF, 317 pages; June 2026 cover, 20260325 footer | 165–168, 262–263, 297–302 |
| [Current official methodology](https://www.niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf) | August 2026, 20260821; selected web-tool text extracts, **not original PDF bytes** | 180–183, 281–282, 318–323 |

Direct PDF retrieval from niftyindices.com timed out. The web tool read the August document; its selected text response is preserved and hashed. The archive URL returned June, so those files are deliberately distinguished. These snapshots do not establish every rule change or every historical constituent between 2024 and 2026.

## Signal specification

Let `M` be the rebalance month; `P(m)` is the final trading-day price in calendar month `m`; `U` is the eligible cross-section. The following numerical specification is in February 2023, pp.111–112, and was checked against August 2026, pp.181–182. [Official formula source](https://archives.nseindia.com/content/indices/Method_Nifty50_Value_20.pdf)

```text
R12_i = P_i(M−1) / P_i(M−13) − 1
R6_i  = P_i(M−1) / P_i(M−7)  − 1
sigma_i = annualized standard deviation of one year's daily log returns
MRh_i = Rh_i / sigma_i                         h ∈ {6,12}
Zh_i  = (MRh_i − mean_U(MRh)) / stdev_U(MRh)
A_i   = 0.5*Z6_i + 0.5*Z12_i
S_i   = 1+A_i          if A_i >= 0
        1/(1−A_i)      otherwise
Initial portfolio = 30 highest S_i
```

For June 2026 this means May 2026 / May 2025 and May 2026 / November 2025. **May is included.** An additional exclusion of May would change the formula. June's final trading-day implementation creates a lag after the May signal cutoff; it is not the academic 12-minus-1 return window ending April.

The same one-year volatility measure divides both horizons. Annualization multiplier, sample-versus-population standard deviation, missing-session conventions, and zero-volatility handling are unspecified here. Neither clipping nor winsorization appears in this momentum section. Treat `sqrt(252)`, sample standard deviation, and any data completeness threshold as explicit implementation choices. The return numerator is price return, not a dividend-reinvested return. [Current specification, pp.181–182](https://www.niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf)

## Membership, weights, and timing

| Component | Published rule |
|---|---|
| Eligibility | Current/incoming Nifty200 member; ≥1-year listing; F&O availability on effective date; qualifying restructuring requires twelve post-ex calendar months |
| Buffer | Ranks ≤15 must enter; existing ranks >45 must leave |
| Base weight | Free-float market capitalization × `S_i`, normalized |
| Cap | `min(5%, 5 × stock's free-float-only weight within the index)` |
| Review | June/December; ordinary Nifty200 departures removed at review |
| Exceptions | Corporate-action/suspension removals can trigger additional reviews; quarterly concentration compliance checks |

[Current methodology, pp.180–183](https://www.niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf)

Scheduled changes apply at the **beginning of the final trading day** in the applicable month. General capping calculations use `T−3` closing prices. Shares/IWF updates are quarterly. Strategy-specific capping is semiannual; do not interpret the generic quarterly calendar as quarterly momentum reranking. The general notice period for these indices is ≥5 working days, with exceptions. [June methodology, pp.167–168, 262–263](https://archives.nseindia.com/content/indices/Method_NIFTY_Equity_Indices.pdf)

The buffer text does not fully specify tie-breaking or how all remaining vacancies/overflow resolve. A reasonable adaptation is: force top 15; preserve the best eligible incumbents through rank 45 up to capacity; fill remaining places by rank. This is an inferred completion, not a verbatim NSE algorithm. Likewise, proportional iterative redistribution after capping should be declared, and exact official weights require validation against published weights. The cap wording refers to the index's free-float-only portfolio; do not silently substitute the parent Nifty200's weights.

## Corporate actions

The general rules adjust splits/bonuses through price and shares; rights/special dividends involve divisor changes. Actions apply on ex-dates. Mergers remove the transferor on ex-date. SPOS demergers may retain parent plus a temporary dummy/new entity; treatment depends on listing and circuit conditions. [June methodology, pp.297–302](https://archives.nseindia.com/content/indices/Method_NIFTY_Equity_Indices.pdf)

This is **index accounting**, not a complete stock-history adjustment recipe. The momentum section does not specify every adjustment to its historical `Price` inputs. Do not claim an arbitrary vendor's adjusted close reproduces NSE. A research implementation needs documented split/bonus/rights/special-dividend policies, event identities, effective dates, and treatment of holdings/receivables through mergers and demergers. A genuine demerger return cannot be erased by substituting a split ratio. The August general demerger text also contains detailed conditional provisions; reproducing it requires event-level review and announcements, not one universal liquidation rule.

## What the retail experiment can honestly claim

For ₹300,000, the official 30-position structure has ₹10,000 average notional before weighting. A 5% cap is ₹15,000. These are arithmetic, not recommended order sizes. Integer shares, transaction costs, and cash residuals create tracking differences. Reducing to ten names while retaining a 5% cap can invest at most 50%; a fully invested ten-name design necessarily changes that risk structure.

Price/volume history alone can support the momentum calculations, after adjustment verification. It cannot establish historical Nifty200 membership, point-in-time F&O eligibility, free-float shares/IWF, historical incumbent lists, and announcement timing. Without those records, label the research **NSE cash cross-sectional momentum adaptation**, and define its own point-in-time universe. Current members applied backwards create survivorship bias. Current market caps applied historically introduce future information.

An equal-weight or volatility-weight portfolio avoids the need for historical free-float weighting data but is a new weighting hypothesis. A volume-based universe is a new universe hypothesis. A monthly review, top-10 selection, index trend filter, cash exit, stop loss, sector cap, or minimum-positive-return screen is a separate design choice. None should be presented as part of this official momentum index. F&O eligibility here is a stock selection condition: it does not require using derivatives in the retail account.

Because these signals need a full calendar year's history, raw data beginning January 2024 cannot evaluate a June 2024 portfolio using the stated formula. June 2025 is the first regular June/December review with the required May-to-May endpoint history, subject to complete stock coverage. December 2024 also lacks the November 2023 endpoint. Extending history is necessary to avoid consuming much of the available sample as warm-up; treating warm-up as invested performance would misstate the experiment.

The useful research question is whether a preregistered, slower momentum portfolio survives realistic costs and unseen periods better than the failed daily variants. Nothing in this document establishes profitability, suitable drawdown, or an execution-ready strategy. Keep the clean official comparator separate from each retail modification so any improvement has an attributable cause.
