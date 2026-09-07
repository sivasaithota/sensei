# Full raw-price portfolio comparison

Both frozen strategies still fail to establish an edge against Nifty 500 gross
TRI after raw-price accounting. The baseline loses 4.401%; hold60 gains 7.916%,
versus the benchmark's 22.9535%. This closes the requested accounting comparison
for these holdings; it does not qualify either strategy for live trading.

## Frozen scope and results

Evaluation: 1 January 2024 through 3 September 2026, 665 sessions, ₹300,000 initial
capital, the same 499-stock development snapshot and original entry exclusions.
Signals, ranking, correlation, strategy parameters, costs, benchmark and runtime
are checked against the content identities of the saved controls. No parameter
search or additional entry exclusion was introduced.

| Measure | Baseline | Hold60 | Nifty 500 gross TRI |
|---|---:|---:|---:|
| Final economic equity | ₹286,796.32 | ₹323,748.95 | — |
| Total return | −4.401% | +7.916% | +22.9535% |
| Annualized return | −1.6912% | +2.9291% | +8.1452% |
| Maximum account drawdown | 29.660% | 24.126% | — |
| Completed trades | 467 | 441 | — |
| Modeled transaction costs | ₹67,751.25 | ₹64,506.54 | — |
| Gross dividend entitlements | ₹5,481.00 | ₹6,026.25 | Reinvested in TRI |
| Final strategy buying-power cash | ₹281,315.32 | ₹317,722.70 | — |
| Return shortfall to TRI | 27.3545 pp | 15.0375 pp | — |

Both verdicts are `NO_CLEAR_NET_EDGE`. The exploratory 90% moving-block intervals
for annualized mean daily excess return are [−29.0360%, +11.8155%] and
[−23.3068%, +14.7978%]. These are reused development histories, not untouched
holdouts or corrected multiple-testing claims.

Economic equity includes gross dividends outside buying power. They are accrued
on the ex date for prior holders and remain non-reinvested throughout this model.
No actual payment date, tax withholding or settled bank balance is claimed.
For every session, cash + marked shares + dividend entitlements reconciles to
equity within displayed rounding. Both portfolios finish without open positions;
trade P&L and strategy attribution reconcile to the account change.

## Coverage and accounting

Captured only the 14 missing sessions from 17 August through 3 September 2026.
All 665 benchmark sessions now have verified raw NSE ZIP/CSV/Parquet receipts.
Across the full retained universe, 315,950 observed rows pass dated identity
checks. Another 15,885 symbol/session cells are missing or ambiguous, and are
not filled or called verified. An actual required entry/holding with such a gap
fails the run instead of dropping the security.

All **908 source trades** and **908 independently simulated raw trades** have
complete raw/tick checks across their held sessions: 3,267 baseline and 3,271
hold60 trade-sessions. Both source and new holding audits report zero issues.
Raw executions use integer physical shares; adjusted prices are used only for
the frozen signals, ranking and correlation. Dated tick rules use circulars and
prior-month raw closes, including the April 2025 rule transition. This is rule
reconstruction, not an archived daily security-master certificate.

The NSE action history has three whole-period captures and six partition checks.
The whole 2024 response omits COASTCORP's 20 September dividend; its half-year
partition includes it. Use the partition union, preserving that discrepancy.
2025 and 2026 whole-period arrays agree with their partition unions. The provider
offers no total-count or completeness certificate, so these captures establish
observed coverage, not guaranteed absence of every possible exchange omission.

Held action overlaps are 14 dividends and one elective buyback in the baseline;
15 dividends, the same buyback and an AGM in hold60. Meeting-only records have no
accounting entry. The ZYDUSLIFE February 2024 tender is explicitly voluntary;
the portfolio does not participate. There are no held split, bonus or demerger
crossings in either completed run. Unsupported mandatory crossings still stop
the entire simulation. A purchase on an ex date receives no prior-holder claim.

Added PGEL and 21 further dated split identity transitions. The ledgers determine
ISIN only; their ratios are not applied to holdings. Combined split/bonus actions
and VBL's rational split ratio therefore cannot silently credit incorrect shares.
See the [accounting policy](raw-portfolio-accounting-policy-2026-09-07.md),
[PGEL evidence](pgel-split-identity-2026-09-07.md), and
[remaining identities](remaining-split-identities-2026-09-07.md).

## Why the corrected returns differ

The legacy controls finish at ₹294,661.96 and ₹329,853.50. Raw accounting changes
those by −₹7,865.64 and −₹6,104.55, despite including gross dividends. This is not
just a dividend addition or a sum of isolated trade corrections: cash, exits and
subsequent portfolio admissions are simulated again.

A concrete example is GODFRYPHLP on 9 September 2024. The adjusted bar's low is
₹2,255, below its synthetic stop, so the legacy position closes that day. The raw
entry is ₹7,122.15 and the tick-rounded stop ₹6,766.00; the raw low is ₹6,766.30,
so that stop is not reached until the following session. The resulting admission
path replaces the legacy JUBLPHARMA entry on 10 September with PPLPHARMA on
11 September in both controls. That demonstrates why adjusted daily rounding
can materially alter a portfolio, even without an action inside the holding.
The observed raw bars are retained; no tolerance or exit rule was changed to
recover the better legacy outcome.

## Artifacts and validation

Final comparison:
`data/reports/raw-portfolio/0b195544a232eb526769ddbb47a74ff25d098070513cc39a59718a37ab351fb2/report.json`

- Report SHA-256: `0ee2965a7d665359a0068e50711eb2fd825286ebc26ab22a1a82130a1ac5fc3a`
- Manifest SHA-256: `49d77c27d99d168510ba78b58251dc56b6c43dcf298958557f8fd483768b12fa`
- Action manifest: `data/reports/portfolio-action-evidence/manifest.json`, SHA-256
  `579c006e24b9e61f87c251ee6601b654123d7b1acc2ceb87548e39b2ed127d03`.
- Source controls: `config/raw-portfolio-source-controls-v1.json`.
- Legacy parity: `data/reports/raw-portfolio/legacy-control-parity-20260907.json`.
  Both full controls rerun with exact campaign parity except experiment identity;
  their new run IDs are `f16e61ecd6c9ce1faa46672b393c09d7da5c38669056891392bbad16dddca3e9`
  and `746103d1bdb16c9770d61b692e38df4ce7200ba850180492cff5fb12bb9bec5e`.

The initial PGEL-blocked result and intermediate comparisons remain retained.
Only the final ID above includes every integrity fix and expanded identity input.
Raw captures and detailed reports remain in the local research archive rather
than adding the market-data archive to Git.

Validation: **1,013 tests passed** (28.26 seconds), including 35 new checks for
physical sizing, raw-only execution, dividend timing/non-reinvestment, unsupported
actions, missing or ambiguous evidence, dated ticks, frozen-input mutations and
conflicting duplicate raw rows. Independent Standards and Spec reviews have no
outstanding actionable findings. Review fixes bind the current inputs to the
original content identities and preserve distinct conflicting raw rows.

Reproduce with the saved local archives:

```sh
.venv/bin/python -m sensei.research.raw_portfolio \
  --config config/stock-research-demerger-sensitivity.json \
  --config config/stock-research-lower-turnover-hold60.json
```

## Decision and next work

Do not promote this strategy family to live trading. Preserve this raw accounting
comparison as the reference for future work; stop adjusting its filters to seek
a favorable reused-history result.

The next data question is causal signal construction: frozen vendor-adjusted
history may encode later actions, and the current constituent universe still
has survivorship bias. Test prefix invariance and document which dated inputs
are needed before claiming point-in-time strategy evidence. New strategy work
should use a small preregistered set of economically distinct hypotheses and
evaluation rules, followed by genuinely later paper-trading observations.
The present model also retains the original immediate sale-proceeds reuse,
current-cost counterfactual, daily-bar fill assumptions and unreinvested gross
dividends. All outputs remain `DATA_BLOCKED`, `RESEARCH_ONLY`, `can_trade=false`.

This pass made no Kite requests, used no additional Kite credits, and placed no
orders. It used cached Kite history and bounded public NSE/MSEI evidence retrieval.
