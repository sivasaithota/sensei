# Recommendation: liquid relative-strength swing trading

Research completed 2026-09-07 for the ₹300,000 NSE cash-equity account.

**Build and evaluate one slower, liquid-stock momentum candidate next.** Rank by
six- and twelve-month volatility-adjusted strength, hold up to ten stocks, review
monthly with a retention buffer, and allow winners to run for months. Use current
equity for sizing, hard capacity limits, and a volatility-based trailing exit.
This is a proposed replacement, not a profitable strategy demonstrated by our
backtest. The [candidate specification](../specs/liquid-relative-strength-v1.md)
fixes the proposed rules and comparison runs before seeing their returns.

## Why this candidate

The official Nifty200 Momentum 30 methodology gives us a transparent six/twelve-
month volatility-adjusted signal. It uses thirty stocks and semiannual reviews;
our ten-stock, monthly, risk-managed version is a substantial adaptation, not
index replication. [NSE methodology](https://www.niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf)

There is positive evidence after the index's August 2020 launch: the five-year
TRI CAGR ending February 27, 2026 was **18.15%, versus 14.42% for Nifty 200**.
That is an index calculation, before our account's costs. Counterevidence matters:
the momentum index lost **4.57% in 2025**, trailing its parent by **14.13 percentage
points**. Its reported historical maximum drawdown was **67.7%**, with pre-launch
backfill in the history. More frequent review is not established as better: the
paper's quarterly alternative beat semiannual in only six of twenty calendar
years and traded more. We therefore include a slow-cadence control rather than
claiming monthly review improves the published strategy.
[NSE study, April 2026 cover, data through February 27](https://www.niftyindices.com/docs/default-source/indices/nifty500-momentum-50/momentum-strategy-whitepaper_2026.pdf?sfvrsn=4f4d6335_6)

Independent Indian research covering 3,956 BSE stocks during 2000–2021 finds
medium-term momentum and stronger evidence among liquid stocks. The accessible
abstract and introduction support the direction and holding horizon; they do not
provide verified net returns for our long-only NSE implementation.
[Chui et al., 2023](https://researcher.manipal.edu/en/publications/momentum-reversals-and-liquidity-indian-evidence/)

The practical change is from repeatedly predicting tomorrow's reversal or
breakout to owning sustained relative winners with fewer decisions. It remains
exposed to reversals, correlated holdings and large market declines. No reliable
monthly income or superior future performance is implied.

## What the local trade diagnosis found

The completed [closure run](stock-closure-results-2026-09-07.md) lost money in all
four variants, including before separately reported fees. I inspected its trades
against their preceding raw bars; I did not simulate alternative stops or a new
strategy during this research.

| Existing strategy | Median holding sessions | Nominal initial stop below prior ATR20 | Entries in stocks below ₹5 crore median daily turnover | Largest entry / prior closing equity |
|---|---:|---:|---:|---:|
| Momentum hold30 | 2 | 41.77% | 46.54% | 46.07% |
| Momentum hold60 | 2 | 43.34% | 47.22% | 43.64% |
| Pullback | 3 | 57.38% | 20.77% | 32.85% |
| RSI2 | 2 | 78.73% | 29.87% | 36.74% |

ATR20 here is the mean of the preceding twenty true ranges. Stop distance uses
entry fill times the nominal stop percentage, not the exact tick-rounded stop.
Turnover is the preceding sixty-session median. Entry concentration uses prior
closing equity, not equity revalued at that day's opening prices.

- **The hold60 label did not mean long holding periods.** Its median trade lasted
  two sessions; 304 of 413 trades exited through stops or gap stops. Extending the
  maximum holding period alone barely changed the dominant exit mechanism.
- **Liquidity scoring admitted unrealistic capacity.** One DCMFINSERV entry on
  March 16, 2026 was ₹59,996.70 against preceding median daily turnover of only
  ₹77,556.04: **77.36% of a typical whole day's traded value**. A generic slippage
  assumption cannot certify that execution.
- **Initial-capital sizing amplified concentration after losses.** A ₹59,973.50
  JINDWORLD entry on August 4, 2026 was 46.07% of prior closing equity. This followed
  the configured budgeting rule; it is an economic design weakness, not evidence
  of an arithmetic bug.
- **Costs magnified an already negative gross edge.** Reported fees alone consumed
  approximately 13.9–22.8% of starting capital across the four runs.

These observations justify testing capacity limits, current-equity sizing and
slower exits. They do **not** prove that wider stops or liquidity filters would
have made the old trades profitable. The new strategy needs its own evaluation.

Diagnostic artifacts are local, under
`data/research/strategy-design/20260907/diagnostics/`. The summary pins:

| Artifact | SHA-256 |
|---|---|
| Closure report | `c23c855ed750dcbd1d8355077939135c23122707cca98c85c0b29b8616b27e2c` |
| Raw panel | `b6564c244ad3fb31e407146b9ea3fcf49ffb36a1bed74739387d1c2e5d821b29` |
| Diagnostic script | `a81f3d31c40bffe487e68716f8c7d803f4d31d31b1e43bba956f2ec9cc0b2ee1` |
| Trade diagnostics parquet | `d4af2a13d213ae5b9cbf975461d553fa4d186d73520bd8e1052690b4180227bc` |

## Why defer the alternatives

**Quality plus momentum** is a reasonable later challenger, but current financial
ratios cannot be backdated. The reviewed index evidence is mostly backfilled and
does not isolate quality's contribution over momentum. **Earnings drift** has a
clearer hypothesis than generic sentiment, but needs archived earnings releases,
first-seen timestamps and historical expectations. **Short-term reversal** needs
particularly credible spread, impact and circuit handling. These data demands
would expand uncertainty before resolving the current portfolio's weaknesses.
See the [five-source empirical review](stock-strategy-empirical-evidence-2026-09-07.md).

News and social data should initially be timestamped research inputs and event
context. Do not let an agent's present-day interpretation of old news change a
historical trade, or add sentiment to v1 after seeing a disappointing result.

## Economics and the next deliverable

Kite Connect is currently **₹500 per app per month**. Twelve billed months cost
₹6,000, or **2% of the initial ₹300,000**, before other overhead. Include that
recurring cost, charges, slippage and any hosting/model costs in the account's
economic comparison. Monthly subscription charges are distinct from how many
requests we make. [Zerodha pricing](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis)

Next engineering deliverable: implement the isolated candidate and its controls
inside the existing architecture, pin the input/config/code manifests, then run
the complete registered development batch against aligned Nifty 500 TRI. Report
whether momentum selection adds value, whether the trailing exit helps, whether
monthly review earns its turnover, and whether any net advantage survives cost
and execution stresses. Do not pick whichever control wins and call it validated.

January 2024–September 2026 raw history supplies few independent medium-term
cycles. All inspected dates remain development data. Additional verified history
and a frozen forward paper record are needed before any deployment claim; the
seven million vendor bars alone do not establish corporate-action-safe coverage
of the dotcom crash, 2008 or COVID. Preserve the configurable drawdown mechanism
and existing 100% research setting; this research does not change live risk limits.

Methodology details: [official rules and replication limits](momentum-methodology-research-2026-09-07.md).
Validation principles: [research protocol](stock-strategy-validation-design-2026-09-07.md).
No new candidate backtest, broker call or live action occurred in this research.
