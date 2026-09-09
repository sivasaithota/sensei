# Liquid relative strength: accounting closure and decision

9 September 2026. Frozen plan v8, following the user's instruction to complete the
accounting and economic evaluation together. The original signal, position/risk
parameters, ten cases and inception dates are unchanged. No live configuration,
orders, credentials or unrelated runtime/LinkedIn files were changed.

**Closure complete: all eleven account paths finish and reconcile.** The input
audit is clear across 83 potential securities, including the resulting companies.
No unsupported events, raw-price gaps, formation failures or rule errors remain
within this declared conservative scope. This is not a certification of all NSE securities.

**Decision: retain the frozen candidate for forward research; do not deploy live.**
It passes the original development criterion: positive net return and benchmark
excess for both the candidate and doubled-slippage run. The verdict is
`POSITIVE_DEVELOPMENT_SCENARIO_ONLY`. No parameters are changed after this result.

Common comparison: June 30, 2025 formation, first fills July 1, endpoint September
3, 2026. Returns below are total-period returns, not annualized. Earlier-start
candidate: January 31, 2025 formation, first eligible fills February 1; its TRI
comparison uses that separate window.

| Case | Final marked equity | Net return | Aligned TRI | Excess (pp) | Max drawdown |
|---|---:|---:|---:|---:|---:|
| Monthly candidate | ₹319,652.97 | +6.55% | -0.33% | +6.88 | 10.51% |
| Liquidity selection control | ₹269,808.40 | -10.06% | -0.33% | -9.74 | 11.85% |
| No trailing exit control | ₹318,347.34 | +6.12% | -0.33% | +6.44 | 14.21% |
| Semiannual control | ₹281,712.81 | -6.10% | -0.33% | -5.77 | 14.91% |
| Earlier-start candidate | ₹327,631.40 | +9.21% | +9.58% | -0.37 | 10.55% |
| 20 bps slippage per side | ₹316,493.39 | +5.50% | -0.33% | +5.82 | 10.66% |
| 40 bps slippage per side | ₹310,794.06 | +3.60% | -0.33% | +3.92 | 11.03% |
| One-session execution delay | ₹326,591.10 | +8.86% | -0.33% | +9.19 | 7.70% |
| Half capacity | ₹319,652.97 | +6.55% | -0.33% | +6.88 | 10.51% |
| Three-session exit delay | ₹328,541.45 | +9.51% | -0.33% | +9.84 | 8.34% |
| Exclude unlisted value from sizing | ₹318,592.90 | +6.20% | -0.33% | +6.52 | 10.51% |

Candidate costs: **₹3,909.28 trading charges** and **₹7,500 data overhead**.
The resulting profit is **₹19,652.97 before unknown additional production costs**.
Average gross exposure is 43.47%; maximum single-security weight is 11.55%.
Half-capacity produces identical economics at this account size; that cap was not
binding in this path. Delayed executions happen to improve the result here; this
does not justify adopting the favorable delay.

The conservative accounting diagnostic returns +6.20%, versus +6.55% for base:
a ₹1,060.07 reduction. Thus the sign does not depend on sizing against unlisted
marks in this sample. It still shares the same assumed valuation and available data.

**Counterevidence matters.** The earlier-start candidate returns +9.21% against
+9.58% TRI, trailing by 0.37 percentage points. CUPID contributes ₹17,132.98 to
base account P&L, about 87% of its ₹19,652.97 net profit after overhead. This is
contribution arithmetic, not a rerun excluding CUPID; allocations would change.
WELCORP and MTARTECH also supply large positive contributions. This record does
not establish a persistent or broadly diversified edge. The trailing control
comparison is +6.55%/10.51% drawdown versus +6.12%/14.21% without trailing exits;
it is one observed policy comparison, not an independent causal estimate.

### Entitlement closure

Base owns **26 shares of each Vedanta child** at the endpoint. They were unlisted
for 30 exchange sessions and then listed-but-unsold for 58 sessions. Their combined
endpoint value is **₹14,137.50**; no unlisted mark remains at the endpoint. The
unlisted share of base NAV peaked at **4.20%**. The common cause of pending disposal
is unavailable 60-session capacity, explicitly reported for every child.

The liquidity control receives 38 TMCV shares and disposes of them on **February
6, 2026**, after the original capacity and permission rules permit it. They remain
outstanding for 80 exchange sessions in total (19 unlisted, 61 listed including
the disposal session). Disposal cash settles the following exchange session.

Every account reconciles cash, receivables, listed holdings, resulting securities,
fees and attribution within one paisa. Ending values remain marked wealth; no
fabricated terminal liquidation is included.

### Frozen artifacts

- Run: `01cb9b460a2186d3841219501497429f2e5e0aa5480fdff823eaa6ca87840475`
- Plan SHA-256: `83debbf6389d6e8f8167f28b7d9a910ad6ab2aee17b9899291c724a0af4cef94`
- Report SHA-256: `feea85821617565033c764c6103b2c08b2b12201d7193b7e8e9ef7343eed7ff3`
- [Report](../../data/reports/liquid-relative-strength/01cb9b460a2186d3841219501497429f2e5e0aa5480fdff823eaa6ca87840475/report.json)
- [Manifest](../../data/reports/liquid-relative-strength/01cb9b460a2186d3841219501497429f2e5e0aa5480fdff823eaa6ca87840475/manifest.json)
- [Complete input audit](../../data/reports/liquid-relative-strength/01cb9b460a2186d3841219501497429f2e5e0aa5480fdff823eaa6ca87840475/preflight.json)
- [Candidate fills, curve, contributions and entitlement lifecycles](../../data/reports/liquid-relative-strength/01cb9b460a2186d3841219501497429f2e5e0aa5480fdff823eaa6ca87840475/candidate.json)
- [Frozen plan v8](../../config/liquid-relative-strength-v8.json)

## Accounting and evidence now covered

The [accounting contract](../specs/demerger-accounting-closure-v1.md) separates
parent holdings, resulting securities, spendable cash, unsettled sales and gross
cash-dividend receivables. The ledger conserves total internal book basis and
reconciles all contributions to marked account wealth. Book-basis allocation is
not tax reporting.

Tata's one resulting-company share and Vedanta's four resulting-company shares
are recorded separately. Before listing, their marks use the declared NSE
price-discovery convention. From listing, each uses its own raw market quotes.
Initial unlisted marks are nonspendable; admission-based account availability is
explicitly assumed, not certified broker credit. The original EQ permissions,
60-session turnover cap, ticks, fees, settlement delay and execution stresses
apply to disposal. Compulsory securities occupy account slots and gross exposure.
They may therefore block further purchases even though they were not selected.

The VEDL children have only 58 observed sessions through September 3. Under the
unchanged 60-session rule they cannot yet be liquidated in this snapshot. Their
listed market values are legitimate marked inputs to this scenario, but are not
cash proceeds. Per-child records report both unlisted and listed outstanding
durations, remaining quantities and the latest disposal blocker.

Source-backed adapters join TATAMOTORS → TMPV and SMLISUZU → SMLMAH, retaining
actual execution symbols and verifying consecutive ISINs. The exact TCS January
16, 2026 event accrues ₹11 interim plus ₹46 special dividend. Its resolved
cash-only reset is removed from signal exclusions only after independent raw
identity/previous-close checks. Share-action and unrelated reset dates remain.

Primary evidence: [demerger source dossier](demerger-closure-sources-2026-09-09.md),
[TCS dividend notice](tcs-combined-dividend-source-2026-09-09.md),
[SML rename notice](sml-rename-source-2026-09-09.md). The existing 411/413 metadata
coverage and all twenty formation dates are retained. Two unavailable daily
masters still defer affected executions under the frozen rules.

## Verification and prior attempts

The full suite passed **1,263 tests in 30.04 seconds**, including **45 focused
checks** for ranking, execution, source repair, preflight and entitlement behavior.
Compilation and whitespace checks passed; no standalone type checker is configured.

Standards review identified the stale cash-event reset; it was corrected and
verified. Spec review identified that reset and incomplete child-disposal duration
reporting; both were corrected and verified. There are no unresolved findings in
the final reviewed implementation. Tests exercise repair-to-ranking behavior,
wealth conservation, listing transitions, nonspendable dividends, delayed disposal,
zero-mark legal ownership, future-price invariance and attribution reconciliation.

Versions v2–v6 retain their fifty registered account attempts, including blocked
paths. V7 ran an input audit only and produced no economic account attempts. Its
complete audit found the remaining SML symbol gap; review then corrected the TCS
signal reset and completed reporting. V8 incorporates those corrections before
performance evaluation. The [earlier v6 result](liquid-relative-strength-evidence-repair-2026-09-08.md)
is preserved and must not be substituted for this version.
V8 adds eleven registered account paths, bringing this relative-strength family
to 61 recorded economic attempts across versions, including earlier blocked runs.
These are evidence/implementation replays and declared diagnostics, not 61
independent confirmations. Older strategy families remain in the exposure ledger.

## Limits and next action

All inspected history is development data, not an untouched holdout. The source
window is short. The current-cost fee schedule is a historical counterfactual;
₹500 per started monthly data cycle is charged, but unknown production hosting and
model costs remain additional. Gross Nifty 500 TRI is an aligned diagnostic, not
a costed investable fund. Historical source publication timing, exact circuits,
account credits and receipt of dividends remain assumptions. The 100% research
drawdown threshold is unchanged and does not set a live loss budget.

The strict v6 accounting result remains blocked alongside this explicitly assumed
valuation scenario. This release closes the declared research calculation; it
does not certify every historical fill or authorize live trading. A positive
historical scenario would still need a separately frozen forward evaluation and
live risk mandate. A rejected scenario should not be rescued by repeated tuning
of the same history.
