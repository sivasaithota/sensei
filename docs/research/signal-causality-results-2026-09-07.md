# Frozen breakout signal causality audit

The current `momentum_breakout_55` implementation passes the complete fixed-data
prefix audit. Adding later rows does not change its earlier signals in the saved
499-stock research snapshot. This is an algorithm result, not proof that those
historical input prices or universe members were available at the time.

## Predeclared checks and outcomes

The plan is `config/signal-causality-audit-v1.json`, written before evaluation.
It pins the completed raw-portfolio report and manifest. The runner additionally
checks the original control's frame hashes, signal implementation, ranking policy,
runtime and settings. It uses the same 252-row warmup and 1 January 2024 through
3 September 2026 evaluation window. No strategy or portfolio parameter changed.

| Check | Observed result |
|---|---:|
| Instruments retained | 499 |
| Available evaluation-date prefixes | 315,950 |
| Prefixes with later rows in the full frame | 315,451 |
| Boolean cells compared, including earlier warmup cells | 175,403,081 |
| Changed Boolean cells | **0** |
| Deliberately leaking future-mean control | **2 differences detected** |
| Causal control | 0 differences |
| Signal changes under uniform multipliers 3 and 5 | **0** |
| Final-date ranking comparisons outside 1e−12 tolerance | **0** |
| Maximum ranking-component absolute difference | 7.216449660063518e−16 |

At each available cutoff, the runner recomputes the signal from the truncated
frame and compares **the entire Boolean prefix** with the corresponding full-run
outputs. It therefore detects earlier changed cells as well as a changed last
cell. The intentionally noncausal control demonstrates that this diagnostic can
fail; a zero mismatch count is not merely successful program execution.

The separate unit test multiplies every OHLC value by 3 or 5 and divides volume
by the same number, without explicit rounding. Currency turnover, where supplied,
stays unchanged. This tests mathematical unit invariance. Ranking is checked only
at each instrument's final frame date, across every score component; the diagnostic
does not test every historical ranking decision, correlation, or portfolio path.

## What remains unresolved

Truncating a September 2026 snapshot cannot recover its January 2024 data vintage.
An algorithm can pass the prefix audit on two separately revised histories while
generating different historical decisions between them; a regression test
demonstrates this distinction. The previous GODFRYPHLP raw/adjusted rounding
example is already evidence that exact series choice can change an execution
path. Do not interpret uniform scaling invariance as immunity to rounding,
cash-dividend conventions, nonuniform changes across actions, or demerger factors.

Static inspection of the frozen portfolio call site shows that ranking and
correlation receive histories ending at the preceding session. The shared scorer
also caps its frame at `as_of`, but currency turnover is a caller-supplied argument;
the inspected portfolio caller computes it from that already-truncated history.
This audit makes no general guarantee about every caller of the ranking API.

The [membership review](nifty500-membership-coverage-2026-09-07.md) separately
establishes the next concrete gaps: no verified starting constituent set, no
complete reconciled review/ad hoc/correction register, and no sufficient dated
checkpoints. It lists official source documents and distinguishes temporary index
placeholders from tradable securities. The current Kite 499 selection has no
historical membership intervals. No fabricated intervals or substitute universe
was introduced.

## Evidence and validation

Artifact:
`data/reports/signal-causality/6ebe81508a87e8253669d9146c649bd04d436be66c019df3c217545557835970/report.json`

- Report SHA-256: `3923b351e965168d938bdedb6a5ddb12a78ece27e18f2d10a48c12ac7f570f0e`
- Manifest SHA-256: `c9474b9b7151e73b9f5994e2beffd5a8446fa7ae8d673deb571211a3da34eddd`
- Full suite: **1,020 passed**, 27.93 seconds; seven new diagnostic tests.
- Independent Standards and Spec reviews: no actionable findings.

Reproduce using existing local captures:

```sh
.venv/bin/python -m sensei.research.signal_causality
```

No production strategy, execution, cash accounting or governance behavior changed.
The previous portfolio results remain the reference; they were not rerun for this
diagnostic. No Kite calls, additional credits, purchases, orders or external
messages were made. Outputs remain `DATA_BLOCKED`, `RESEARCH_ONLY`, `can_trade=false`.

Next, acquire and pin the finite official membership notices identified in the
coverage note, preserving exact effective dates and corrections. Continue looking
for an independently dated starting list and checkpoints. An incomplete ledger
must stay explicitly incomplete. For causal adjusted indicators, establish a
dated corporate-action transformation contract and its source coverage before
using it to claim point-in-time strategy evidence. Do not repeat this completed
prefix audit or resume tuning the rejected filter family.
