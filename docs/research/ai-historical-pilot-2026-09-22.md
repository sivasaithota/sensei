# First historical AI portfolio pilot — 22 September 2026

Completed research simulation: **30 June–29 August 2025**, ₹300,000 starting capital, fixed 20-stock inception-liquidity universe, two monthly AI decisions. This is a price/volume-only operational pilot, not a live strategy or an out-of-sample profitability claim.

| Portfolio | Ending wealth (INR) | Total return | Maximum drawdown |
| --- | ---: | ---: | ---: |
| AI targets | 283,831.60 | -5.3895% | 5.4929% |
| Same-universe momentum control | 285,817.94 | -4.7274% | 4.7864% |
| Nifty 500 gross TRI | 286,224.22 (normalized index) | -4.5919% | Not included in pilot comparison |

The AI lost ₹16,168.40, trailing momentum by 0.6621 percentage points and TRI by 0.7975 points. Average gross stock exposure was 51.20%. Holding substantial cash did not prevent underperformance. Verdict: **NO_DEMONSTRATED_NET_EDGE**.

## What the agents decided

June: BEL 9%, BHARTIARTL 9%, RELIANCE 9%, SBIN 8.5%, HDFCBANK 7%, CDSL 7.5%, INDUSINDBK 7%, M&M 6%, residual cash 37%.

July: ICICIBANK 9.27%, HDFCBANK 9.12%, M&M 7.79%, SBIN 8.58%, BHARTIARTL 8.65%, residual cash 56.59%; exit BEL, CDSL, RELIANCE and INDUSINDBK. These are target weights, not exact realized exposure. Integer shares, prices and execution caps determine actual fills. Rounded target weights also caused one-share trims in SBIN and BHARTIARTL, and additions smaller than quantities mentioned in the Analyst's prose; the Manager's validated weights govern execution.

The largest negative stock contributions, including allocated execution costs, were CDSL ₹3,988.38 and BEL ₹2,752.91. Only M&M contributed positively (₹136.37). The decisions bought recent strength and later reduced exposure following declines. This small sample does not establish that pattern as a general causal explanation or validate a replacement strategy.

## Accounting and verification

- 17 historical fills, next-session execution, raw prices, dated permissions, ticks, slippage, participation caps, T+1 sale settlement and integer shares.
- Execution fees ₹438.40; subscription overhead ₹1,000.00; model usage costs unknown and excluded. Slippage is embedded in fills.
- Six cash-event repairs and one bonus repair are pinned in `config/ai-historical-actions-v1.json`; both portfolios receive identical accounting. Frozen momentum signal rankings remain unchanged, including their earlier treatment of unresolved events. This is not the full-universe v8 headline.
- HDFC's 12 held shares become 24 after the documented bonus; new shares remain unavailable until August 29 admission. Terminal pending bonus shares: zero.
- Ending cash ₹170,721.50, dividend receivables ₹571.50. Dividends remain nonspendable gross entitlements under the frozen research convention; actual payment/tax accounting is not modeled.
- Attribution residual: 0.000000000102 INR. Terminal holdings are marked, not fictitiously liquidated.
- Full suite: **1,369 passed**. Spec and standards reviews found no actionable issues in Coach and overlay changes.
- Saved-decision empirical replay: **exact match**, with zero new model calls. Account reports match apart from artifact-directory paths; all 17 fills, equity rows, actions, terminal positions and attribution match. Decision artifacts are byte-identical; comparison and momentum reports match. Receipt: `data/reports/ai-backtest/pilot-2026-09-22-replay/verification.json`.

## Limitations and next decision

Only 21 prior observations per stock were supplied at each decision. No historical filings, earnings, news, social sentiment, sector or market-wide evidence was supplied. Some model rationales speculated about institutional flows and quarter-end positioning without direct evidence; those explanations are not established facts. The same model serves multiple roles, so agreement is not independent confirmation. Monthly execution ignores advisory shorter review horizons and prose invalidation conditions. Modern-model training may contain future historical knowledge, and the existing source panel has survivorship/selection limitations. Gross TRI excludes investable-product frictions.

Keep this losing pilot as a fixed baseline. The next research milestone is a dated filing/news evidence packet and an explicit decision/review policy, frozen before evaluating an untouched window or forward shadow portfolio. This result does not justify live deployment or tuning prompts against the same two months.

## Artifacts and recovery history

Complete run: `data/reports/ai-backtest/pilot-2026-09-22-accounted/`. See `comparison.json`, `ai/report.json`, per-date `artifact.json`, `inputs.json`, `registration.json` and `usage-audit.json`. Local source PDFs and receipts are retained under `data/research/ai-backtest-actions/20260922/`; primary URLs and evidence qualifications are in the HDFC and cash-action research notes.

Earlier attempts remain preserved: provider timeout; overly restrictive peer-citation validation; manager weights plus cash totaling 103%; provider sleep interruption; Coach using a fictitious portfolio symbol; then an unsupported HDFC dividend. Corrections changed contracts/accounting, not selection based on realized returns. The rejected 103% allocation was never normalized. The successful June manager output was preserved through Coach and accounting recovery. Exact packet/prompt/schema matching and response provenance govern reuse.

Across these attempts, 17 distinct saved provider responses were found, including 1 error response, plus 1 incomplete request without a usage record. CLI-reported estimates total US$5.7327; this is **not an actual subscription invoice** and omits unreported interrupted usage. The pilot used cached Kite history and made no new Kite data requests.
