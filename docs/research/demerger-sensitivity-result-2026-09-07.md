# Demerger entry-risk sensitivity: unchanged baseline result

The two-event entry exclusion produced **exactly the same 467 trades and daily
equity curve** as the original momentum baseline. ABFRL and VEDL's demerger
discontinuities therefore do not explain this baseline's underperformance via
the selected trades tested here. This does not certify the other corporate
actions, historical universe, or entitlement-inclusive returns.

## Cause established, accounting still unresolved

Kite's preceding closes closely match raw exchange closes multiplied by the
companies' retained tax cost allocations: 75.68% for ABFRL and 52.34% for VEDL.
Zerodha documents this chart convention and that gaps may remain. Tax cost
allocation is not the market value of all shares a shareholder receives. No
price was rescaled and no missing entitlement was represented as cash. See the
[primary-source investigation](demerger-adjustment-conventions-2026-09-07.md)
for exact letters, dates, raw observations, arithmetic and limitations.

## Frozen comparison

Both runs use the same 499-stock current-matched development snapshot, 252-row
warmup, 2024-01-01 through 2026-09-03 evaluation, momentum-breakout rule, position
sizing, stop/target, holding period, fees, slippage, drawdown setting and Nifty
500 gross TRI benchmark. The sensitivity only adds the policy in
`config/stock-demerger-risk.json` and changes the campaign name. Configurations
were saved before these runs; the policy was not adjusted after seeing results.

The policy blocks new entries from the day after the dated event announcement
until 252 post-event observations exist strictly before the entry session. This
period covers the current shared ranking's longest lookback. Sources for the
early announcements establish the event; the later tax-allocation letters are
not treated as information known before publication.

- ABFRL: notice 2025-05-12, available 2025-05-13, ex-date 2025-05-22;
  259 evaluation sessions blocked for new entries.
- VEDL: notice 2026-04-20, available 2026-04-21, ex-date 2026-04-30;
  95 evaluation sessions blocked for new entries.
- No simulated holding crossed either listed ex-date. All stocks and prices
  remain in the input; OFSS and ZEEL's documented market moves remain intact.

| Metric | Original/control | Entry-risk sensitivity |
|---|---:|---:|
| Initial equity | ₹300,000 | ₹300,000 |
| Final equity | ₹294,661.96 | ₹294,661.96 |
| Net P&L | −₹5,338.04 | −₹5,338.04 |
| Total return | −1.779% | −1.779% |
| Maximum drawdown | 29.451% | 29.451% |
| Completed trades | 467 | 467 |
| Realised transaction costs | ₹68,191.57 | ₹68,191.57 |
| Nifty 500 gross TRI | +22.9535% | +22.9535% |
| Economic diagnostic | NO_CLEAR_NET_EDGE | NO_CLEAR_NET_EDGE |
| Overall decision | DATA_BLOCKED | DATA_BLOCKED |

The rerun control's complete campaign equals the saved original campaign. The
sensitivity campaign differs only in its experiment identifier: every trade,
daily equity mark and reported metric matches. Different identifiers record
different code/policy exposure, not a new holdout. This is a post-hoc, reused
development-history sensitivity selected after investigating flagged events.

Realised gross P&L was ₹62,853.53 and realised transaction costs ₹68,191.57.
That arithmetic explains the net loss. It is not a simulated cost-free account
return: removing costs would also change sizing and subsequent equity. The next
strategy experiment should predeclare a small lower-turnover comparison, assess
net excess returns and drawdown, and preserve these observations as development
data. This result provides no basis to promote the current strategy to live.

## Safeguards and remaining evidence

Policy bytes, parsed events and implementation enter the frozen run identity.
Unknown symbols, invalid dates, duplicate event IDs, inadequate post-event
history thresholds, and missing configured policy files fail explicitly. Entry
eligibility is checked on the prospective entry session. Its unobserved bar
does not count as completed history.

The policy does not sell existing holdings. If a position opened before an
unresolved ex-date exits on or after it, the runner reports the affected holding
and withholds the economic verdict and campaign metrics. End liquidation is
required so remaining holdings are included in that audit. Coverage is explicitly
limited to listed events. Neither this guard nor an unchanged sensitivity
certifies shareholder returns.

Still needed: raw-price and entitlement accounting (including credit dates,
tradability, ordinary dividends and unlisted-share valuation), historical
membership and lifecycle evidence, resolution of other price exceptions and
the 145 rejected full-archive request windows. No full-archive normalization,
news/social trading signal, or live order authority was introduced. These runs
reuse local files and make no Kite API requests.

## Reproduction and artifacts

```bash
.venv/bin/python -m sensei.research.stock_evaluation \
  --config config/stock-research-kite-development.json
.venv/bin/python -m sensei.research.stock_evaluation \
  --config config/stock-research-demerger-sensitivity.json
```

Artifacts under `data/reports/stock-development/`:

- Original: `04b7b8d2757564fe492bd293e8cce58c6f0b2da8d195123fc387f120d7a5e88b/report.json`.
- Control: `870a09cb4075f9997a16b1492d91fd7aed1f766cebe69da56a8787ffd09b7bed/report.json`.
- Sensitivity: `7e9a282839b09e84f25668c3e20bf60bbfa8e8372079e8c21ae2bbaa2411a579/report.json`.
- Comparison: `demerger-comparison-20260907.json`, with verified report hashes
  and equality checks. Reports and source data remain local ignored artifacts.

Control report SHA-256:
`cd98648c54276f548e3241a8e1c88840eeb7e445146c012c58f285af083f8e2e`.
Sensitivity report SHA-256:
`9f974fb974bbdcb8dd5907754659a881bfb3039350ec7dcb78e2d0a53f57568c`.

Validation: **889 tests passed**. Standards and Spec code reviews found no
remaining issues. Tests cover announcement timing, the 252-observation boundary,
entry blocking, changed/missing policies, and held-position economic blocking.
