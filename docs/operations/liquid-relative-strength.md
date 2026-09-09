# Liquid relative-strength development batch

This isolated research runner implements the [strategy specification](../specs/liquid-relative-strength-v1.md).
It does not add an active playbook strategy, access Kite credentials, place orders
or change the live drawdown configuration.

Run from the repository root:

```bash
.venv/bin/python -m sensei.research.relative_strength_run \
  --plan config/liquid-relative-strength-v8.json
```

The runner verifies closure-v4 source/code pins, the new specification and code
pins, raw panel cache, security-master captures, corporate-action records and TRI
data. It prepares calendar-month rankings separately from session-level execution
permissions. It writes a content-addressed manifest before simulation and an
individual registration before each account path. Results live under
`data/reports/liquid-relative-strength/<run-id>/`; the exposure ledger records all
history as development. No downloads are performed. Add `--preflight-only` to
produce the complete potential-ownership input audit without registering economic
account paths. A blocked preflight produces no portfolio returns; inspect all
gaps in `preflight.json` before another batch.

Plan v1 is retained as the unsimulated pre-review draft. Plan v2 pins the reviewed
implementation; v3 corrects rank labels in control traces. V4 additionally enforces
the ten-holding limit while partial exits remain and the physical daily-volume
fill ceiling. V5 adds documented CUPID/AMIORG share actions, AMIORG's rename and
four recovered formation masters. V6 adds 44 further validated masters after a
uniform retry of every remaining failed date. Signal and risk parameters are
unchanged. V7 adds the demerger ledger and full preflight; it was used only for an
input audit. V8 includes review corrections and the documented SML rename. Old
plans/results remain historical artifacts; replay them from their matching source
commits. See the [closure scorecard](../research/liquid-relative-strength-closure-2026-09-09.md)
and [accounting contract](../specs/demerger-accounting-closure-v1.md).

The batch has four policies initialized independently with ₹300,000 at the June
30, 2025 formation, an additional January 31 candidate inception, and five fixed
stresses. One additional accounting diagnostic excludes unlisted value from sizing
equity while retaining it in marked NAV. Reports must not compare the extended inception directly with a June
control. The inherited delivery schedule is a current-cost counterfactual; daily
opens with slippage are modeled fills. Neither is historical broker reconciliation.

`SIMULATION_BLOCKED` means there is no complete portfolio return for that attempt.
Missing formation metadata, an unsupported held action or a missing held bar may
cause it. An execution permission gap instead defers the order; buys expire and
exits persist under their registered rules. Never replace a missing snapshot with
today's universe or silently omit an unsuccessful formation. The last incomplete
calendar month in the source is not a scheduled month-end review.

`COMPLETED_MARKED_RESEARCH_SCENARIO` describes marked equity including nonspendable
dividends and share entitlements. It is not a liquidated bank balance. Terminal
liquidation remains unavailable if there are no subsequent verified execution
sessions; the report states that explicitly. Unverified circuits, sectors, source
publication timing and production overhead remain limitations. The runner cannot
produce a live-admissible verdict even if its gross-TRI comparison is positive.

When correcting implementation or evidence, retain the old plan and result bytes.
Create a newly pinned plan version and record the reason before rerunning. Do not
change signal or risk parameters to rescue a result. A source repair must apply to
all controls and stresses. Compare like-for-like accounting versions and disclose
all prior attempts.

Focused checks:

```bash
.venv/bin/python -m pytest tests/test_relative_strength.py \
  tests/test_relative_strength_portfolio.py tests/test_relative_strength_run.py \
  tests/test_relative_strength_evidence.py tests/test_relative_strength_preflight.py \
  tests/test_demerger_portfolio.py -q
```

These cover calendar lookbacks/future invariance, liquidity and history exclusions,
model-roster retention, frozen quantities, next-session stops, settlement delays,
dividend receivables, split/bonus availability, partial exits, current-equity
rebalancing, expiry, stress timing, control rank traces, physical holding/volume
limits, aligned benchmark dates, pinned metadata recovery, exact rejected-action
replacement and documented same-ISIN symbol continuity. Closure tests additionally
cover demerger wealth conservation, zero-valued legal entitlements, listing marks,
child dividends/disposal/settlement, conservative sizing, cash-repair-to-ranking
continuity and collecting multiple input gaps in one preflight.
