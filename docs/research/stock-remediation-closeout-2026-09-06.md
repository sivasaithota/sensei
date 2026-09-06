# Stock backtest remediation closeout

Scope: the stock-bot audit and subsequent “fix all” request. NSE cash equity,
swing first, ₹300,000 account. Preserve the governed architecture.

## Implemented

| Finding | Result |
| --- | --- |
| Conflicting opening-gap/stop behavior | Shared daily opening/intraday decision functions used by legacy, examiner, portfolio and governed paper exits |
| First loss missing from drawdown | Initial capital included in both affected high-water calculations |
| Historical replay filling at prior close | Prior-session decisions separated from current-session open; lagged capacity proxy explicitly labelled |
| Fetch time masquerading as quote time | Provider timestamps retained; stale/future/unknown entry observations rejected; quote snapshots cached across the candidate scan |
| After-market exits require fresh ticks | Separate completed-session paper settlement evidence with retained 15:30 IST timestamp |
| Research/paper ranking mismatch | Shared scoring, turnover, deterministic tie-breaks and correlation; undated/future performance statistics excluded |
| Future-complete universe filtering | Removed from diagnostics; missing held bars block; replay cannot silently skip incomplete dates |
| Single-stock gates treated as portfolio proof | New shared-capital report with benchmarks, costs, exposure, drawdown and block-bootstrap uncertainty; old screen results preserved |
| Experiment identity omits execution/fees | Input, policy, source and charge-schedule identities included |
| Reused history called fresh confirmation | Known history blocked; owner research CLIs and governed lab record input dates including warmup before evaluation; confirmation checks same journal |
| Type conformance described as parity | Evidence explicitly identifies its type-only scope and no portfolio parity proof |
| Stale architecture descriptions | Updated paper composition, durable gateway and scheduler documentation |

The new entry point and its declared assumptions are documented in
[Stock portfolio evaluation](../operations/stock-portfolio-evaluation.md).
The pure simulators remain deterministic and do not write operational state.
Custom research callers must record exposure using the same journal as their
confirmation registry; off-platform inspection is not automatically detectable.

## Dataset audit

The local report `data/reports/stock-remediation-development-20260906.json`
inspected all 500 stored instrument files, retaining every security. It found
58 files with invalid OHLCV relationships after allowing floating-point
rounding tolerance, and 145 with daily price changes above 30% requiring review.
These sets overlap. Large changes are flags, not proof of vendor error.

Examples of structural failures include ABREL on 1996-01-08 (open above high),
ASAHIINDIA on 2008-12-18 (close below low), and AUROPHARMA on 1996-02-06
(open below low). The audit covers all supplied history, including dates older
than the requested 2024–2026 evaluation window. It does not silently rewrite
bars or omit these securities to produce attractive returns.

Because this whole input dataset fails the declared content check, the command
emitted `DATA_BLOCKED` before simulation. No new profitability result was
produced. Historical membership, corporate-action/executable-price treatment,
exchange-calendar provenance and a verified benchmark are still absent from
this evaluation. The AccelPix adapter's existence does not supply those inputs.

**Window-specific follow-up:** classification of the same 500 files found zero
invalid OHLCV rows between 2024-01-01 and 2026-09-04, including each instrument's
preceding 252 stored sessions for indicator warmup. All 58 flagged files have
their structural failures outside that input window. This narrows the initial
whole-history blocker; it does not verify historical membership, corporate
actions, calendar completeness or benchmark alignment. No rows were repaired
and no instruments were removed. Results are in
`data/reports/stock-data-window-diagnosis-20260906.json`.

## Review and validation

The independent Standards review found five substantive issues during the
implementation review; the Spec review found three overlapping issues. They
covered EOD settlement, exposure recording, fee identity, benchmark alignment
and governed exit ordering. These were fixed and regression-tested. A follow-up
review caught an extra benchmark session between the predecessor and first
portfolio session; the final check rejects that mismatch too.

The three-bar probe returns +10% before costs across the three research paths,
and the initial 10% loss now reports 10% drawdown. Synthetic fixtures cover
fees/cash/risk sizing, gap ordering, timestamps, missing bars, benchmark gaps,
exposed dates, and identity changes. Synthetic success is implementation
evidence, not market edge.

Final validation: `python -m pytest -q` — **809 passed in 26.20 seconds**;
the standalone parity probe passed; Python compilation and `git diff --check`
completed without errors.

## Still required for a live decision

1. Validate historical data and the benchmark, then run a frozen portfolio
   protocol and retain all outcomes. Do not optimize until a result looks good.
2. Apply the owner's subsequently confirmed 100% maximum account drawdown to
   the ₹300,000 research account. Complete capital loss is accepted as a
   budget boundary; net-edge requirements and operational controls still apply.
3. Obtain forward paper evidence for the exact strategy and allocation policy.
4. Implement and certify a governed broker gateway, reconciliation and broker
   protection under an explicit canary mandate. The current runtime is paper;
   the legacy OpenAlgo adapter remains sandbox-only.

No live orders, live activation or strategy promotion were performed. This
change improves the reliability of the evidence pipeline; it does not claim
that a strategy is profitable or the bot is ready to deploy with real capital.
