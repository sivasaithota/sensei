# Stock loss attribution — 7 September 2026

The saved runs show broadly distributed stop losses and substantial variation
by time period. They do not establish that deleting a few losing stocks or
widening stops would improve future returns. No strategy was changed or rerun.

## Realised P&L by exit year

These are sums of completed-trade net P&L grouped by exit date. They are **not
annual portfolio returns**: holdings may cross year boundaries, while the equity
curve marks them daily. The 2026 period ends on 3 September.

| Run | 2024 | 2025 | 2026 to evaluation end |
|---|---:|---:|---:|
| control | ₹+49,254.26 | ₹+5,409.88 | ₹-60,002.18 |
| hold60 | ₹+49,540.41 | ₹+16,469.70 | ₹-36,156.63 |
| hold60-target20 | ₹+31,988.64 | ₹-30,971.48 | ₹-22,157.47 |
| trend-hold60-target20 | ₹+23,515.32 | ₹-52,075.97 | ₹+7,938.00 |

Baseline 2026 exits produced approximately −₹60,002 net, overcoming gains
realised in the preceding years. The trend-entry package instead suffered its
largest realised loss in 2025. This variation warrants examining the market state
known at entry; it is not evidence for selecting historical dates to omit.

## Stop and gap-stop contribution

| Run | Stop/gap-stop trades | Net P&L from these exits | Share of all losing-trade amounts |
|---|---:|---:|---:|
| control | 308 | ₹-967,823.03 | 99.64% |
| hold60 | 297 | ₹-933,731.97 | 99.80% |
| hold60-target20 | 200 | ₹-609,141.63 | 99.29% |
| trend-hold60-target20 | 187 | ₹-571,341.58 | 99.42% |

These cumulative loss amounts are offset by winning trades and recycle account
capital repeatedly; they are not account drawdowns. A stop exit is a losing
outcome by construction, so its large contribution alone does not diagnose a
bad stop rule. Costs, entry quality, payoff size and opportunity selection all
matter. The unchanged baseline’s maximum drawdown remains 29.451%.

## Fixed pre-entry volatility bins

ATR is the simple mean of 14 true ranges using exactly the last 15 benchmark
sessions strictly before entry. The first bar supplies the preceding close.
Missing bars remain unknown. Stop distance uses the actual entry fill times
the configured 5%; the numerator is known at execution, while ATR uses only
prior bars. This is volatility of the saved adjusted chart, not certified raw
shareholder risk. Bins were declared before this diagnostic was run.

| Run | Stop distance / prior ATR | Trades | Stop/gap-stop rate | Net P&L |
|---|---|---:|---:|---:|
| control | below_1_atr | 118 | 66.95% | ₹+17,036.62 |
| control | 1_to_below_2_atr | 323 | 65.94% | ₹-18,138.32 |
| control | at_least_2_atr | 25 | 60.00% | ₹-1,350.59 |
| control | unknown | 1 | 100.00% | ₹-2,885.75 |
| hold60 | below_1_atr | 115 | 66.09% | ₹+31,252.87 |
| hold60 | 1_to_below_2_atr | 304 | 68.42% | ₹-4,536.42 |
| hold60 | at_least_2_atr | 21 | 57.14% | ₹+6,022.78 |
| hold60 | unknown | 1 | 100.00% | ₹-2,885.75 |
| hold60-target20 | below_1_atr | 73 | 76.71% | ₹+13,213.96 |
| hold60-target20 | 1_to_below_2_atr | 177 | 76.27% | ₹-37,901.39 |
| hold60-target20 | at_least_2_atr | 17 | 47.06% | ₹+6,432.87 |
| hold60-target20 | unknown | 1 | 100.00% | ₹-2,885.75 |
| trend-hold60-target20 | below_1_atr | 60 | 75.00% | ₹+25,034.10 |
| trend-hold60-target20 | 1_to_below_2_atr | 173 | 76.30% | ₹-53,751.83 |
| trend-hold60-target20 | at_least_2_atr | 16 | 56.25% | ₹+10,980.83 |
| trend-hold60-target20 | unknown | 1 | 100.00% | ₹-2,885.75 |

The baseline’s below-1-ATR group was profitable in aggregate despite a 66.95%
stop/gap-stop rate; its 1-to-below-2-ATR group lost money with a similar 65.94%
rate. The at-least-2-ATR group contains only 25 baseline trades. These are
different selected trades, not controlled counterfactuals of the same entries.
Do not infer that widening stops or filtering a bin would improve performance.

All four runs have the same single unknown observation: **FORCEMOT, entered
2024-03-01 and exited 2024-03-04**, net −₹2,885.75. Its preceding 15-session
window reaches before the February 14 resumption of NSE trading. This is
consistent with the [verified inactive interval](kite-security-exceptions-2026-09-07.md).
The diagnostic leaves it unknown and retains the trade; no prices are filled.

## Security concentration

Five lowest and highest total net-P&L security contributors in each complete
run are shown below. These are retrospective labels, not an exclusion list.
All securities and every completed trade remain in the artifacts.

| Run | Five lowest contributors (net P&L) | Five highest contributors (net P&L) |
|---|---|---|
| control | NETWEB: ₹-21,351.81; ACUTAAS: ₹-15,890.20; SHYAMMETL: ₹-10,545.21; SCHNEIDER: ₹-9,407.01; MOTILALOFS: ₹-9,386.99 | TARIL: ₹+24,999.08; WELCORP: ₹+24,582.05; HBLENGINE: ₹+20,938.43; GODFRYPHLP: ₹+18,462.71; PGEL: ₹+17,832.38 |
| hold60 | ACUTAAS: ₹-12,745.23; NETWEB: ₹-12,557.10; NEWGEN: ₹-12,452.73; SHYAMMETL: ₹-10,545.21; SCHNEIDER: ₹-9,407.01 | TARIL: ₹+24,999.08; WELCORP: ₹+24,754.61; GODFRYPHLP: ₹+21,337.43; GRSE: ₹+14,707.55; PGEL: ₹+14,704.90 |
| hold60-target20 | HEG-BE: ₹-14,276.60; WOCKPHARMA: ₹-12,714.92; BSE: ₹-12,183.94; ACUTAAS: ₹-11,992.11; NETWEB: ₹-10,549.08 | TARIL: ₹+35,482.58; GABRIEL: ₹+19,883.34; HINDZINC: ₹+14,259.16; AEGISLOG: ₹+13,445.81; RITES: ₹+11,838.12 |
| trend-hold60-target20 | MOTILALOFS: ₹-12,506.06; NATIONALUM: ₹-11,291.08; ACUTAAS: ₹-10,182.73; AMBER: ₹-9,903.87; REDINGTON: ₹-9,426.27 | TARIL: ₹+23,651.89; ADANIPOWER: ₹+23,250.05; ANANDRATHI: ₹+21,893.17; ATHERENERG: ₹+14,452.23; RITES: ₹+11,838.12 |

The baseline’s five worst net contributors account for **6.85%** of the sum of
all losing-trade amounts. The denominator is absolute net losses across all
losing trades, not the account’s small final net loss. Removing these names
after seeing results would introduce selection bias and would also change the
portfolio’s admission/sizing path.

## Integrity, artifacts and reproduction

Each derivative verifies the original report checksum, manifest-derived run ID,
settings, Kite snapshot provenance, scoped input-frame hashes and benchmark
hash. It binds its source and implementation hashes into a content-addressed
report. Rounded trade P&L reconciles to campaign P&L within an explicit rounding
tolerance. Any open position or material discrepancy blocks attribution.

No new backtest, Kite request, paid data or live action was used. The artifacts
are descriptive reused development, DATA_BLOCKED and can_trade=false.

| Run | Attribution artifact ID |
|---|---|
| control | `6865cf84719d4e2dd9a67eed0ad5b19b6b1913bfab5ad5ad06bc9b07305b5e97` |
| hold60 | `21143ff43d0e7a564e11bfa205663c74887007c66eb756f709306937de6df57a` |
| hold60-target20 | `fb9ec9b4eab7d38721d9d93ab57dc545012dd57ae9192d213414b1a53ccf11e5` |
| trend-hold60-target20 | `7a605fc1faa4a15b5716790787097b9842eb838e8acd9e2c40f09b581a3fd4ec` |

Each artifact is at `data/reports/stock-attribution/<ID>/report.json`, with
complete per-trade records and every group. The ID is the report SHA-256.

```bash
.venv/bin/python -m sensei.research.stock_attribution \
  --report data/reports/stock-development/7e9a282839b09e84f25668c3e20bf60bbfa8e8372079e8c21ae2bbaa2411a579/report.json
```

## Next bounded action

Attribute these same entries to the benchmark trend known at their decision
time, with a fixed, documented market-state definition. Compare exposure and
net outcomes descriptively before proposing a new regime rule. Do not re-run
a parameter grid, remove losing dates/stocks or treat reused observations as
an untouched holdout. The FORCEMOT continuity issue remains explicit evidence
for historical eligibility and indicator-history policy work.

Validation: **903 tests passed**. Standards and Spec implementation reviews
found no remaining issues. Regressions cover prior-only ATR, gaps, fixed bins,
P&L reconciliation, open-position rejection and tampered source artifacts.
