# Daily research execution contract

Implemented 6 September 2026. Policy:
`daily-fill-relative-open-first-target-capped-v1`.

The legacy daily backtester, Research Examiner simulator and fast portfolio
campaign now share bracket event ordering through
`src/sensei/backtest/daily_execution.py`:

1. A known opening price at/below the stop exits at that opening price.
2. A known opening price at/above the target exits at the target, conservatively
   ignoring favorable gap price improvement.
3. If neither opening condition applies, a daily low touching the stop takes
   precedence over a daily high touching the target. Intrabar chronology is
   unknown, so this remains a pessimistic assumption.
4. A time exit is considered only after bracket exits.

Stops and targets remain relative to the entry fill. Legacy flat-cost defaults
remain available; the new portfolio evaluation explicitly selects current
delivery taxes, per-sale DP charges and entry slippage. This is a current-cost
counterfactual, not historical tax reconstruction.
The portfolio simulation settles opening exits before admission and can reuse
those modeled proceeds for another instrument/strategy. It cannot reuse later
intraday proceeds at that same opening. An instrument or strategy exiting at
the open is blocked from immediate re-entry, matching the existing stop-gap
policy. This is a research cash-availability assumption; broker settlement and
buying-power rules still require separate validation.

Legacy/portfolio stop gaps retain the `stop_gap` label. The examiner continues
grouping all stop exits as `stop` in its existing evidence schema.

## Identity and historical results

New per-symbol statistics, portfolio reports and diagnostic matrices label the
execution policy. Validation campaign fingerprints cover the shared execution
module's source. Research Examiner identity includes the policy and its version
advances from 1.0 to 1.1. Stored reports and locked-access records are not
rewritten. A new implementation identity does not make previously consulted
market history an untouched holdout.

The initial-capital high-water mark is now included in both legacy trade
drawdown and campaign trade-sequence drawdown. These are still trade-sequence
metrics, not substitutes for a daily portfolio or intratrade equity curve.

## Verification

```bash
.venv/bin/python docs/research/probes/backtest_contract_audit.py
.venv/bin/python -m pytest -q tests/test_daily_backtest_parity.py tests/test_backtest.py tests/test_strategy_validation_campaign.py tests/test_research_examiner.py
```

The original three-bar probe now reports +10% before costs in all three daily
research paths. Regression fixtures cover opening targets, opening stops,
exact trigger boundaries, ambiguous intraday bars, target-only bars, fees,
integer quantities, cash reconciliation, and the distinction between opening
and intraday proceeds. Identity tests cover execution-policy/source revisions.

## Expanded remediation

The preliminary audit now delegates to the portfolio simulator. Governed paper
exit decisions also use the common opening/intraday bracket helpers. Production
replay separates prior-session decision data from current-session opening
execution and labels its lagged-volume capacity estimate. After-market paper
settlement uses the completed session's daily bar and preserves its closing
timestamp; it does not require a fresh after-hours quote.

Paper and research share ranking, turnover and correlation mathematics in
`strategy/selection.py`. Historical performance evidence contributes only when
its availability date precedes the decision. Experiment identities cover input
frames, signals, selection, costs, configuration and implementation.

Research CLIs and the governed lab record exposed input dates, including
warmup, in their Operational Journal before evaluation. Confirmation checks
the same journal and the known development interval. Pure simulation APIs do
not mutate journals; custom research runners must call
`record_development_frames` before inspecting inputs and use the same journal
as confirmation. Separate journals or off-platform data inspection cannot be
detected by this ledger. Previously inspected 2024+ local history remains
development data regardless of experiment or vendor name.

## Remaining scope

This is a bounded execution correction, not full strategy or runtime parity.
The frozen TradingView reproduction uses signal-close protection and retains
its registered semantics. Daily research sizing uses initial capital, while
the governed runtime uses current account truth and additional admission rails.
The runtime also models tick rounding, liquidity limits and partial fills;
the fast research simulator does not. Matching bracket and ranking calculations
does not prove complete portfolio parity. A canonical plan type check now
explicitly says that it does not prove behavioral parity.

The local development run is recorded in
`data/reports/stock-remediation-development-20260906.json`. Its data status is
blocked until historical membership, corporate-action treatment, calendar
provenance and a suitable benchmark are established. No live orders were sent.
