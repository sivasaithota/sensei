# Lower-turnover swing comparison v1

Predeclared 7 September 2026 before running any of these configurations. The
unchanged baseline lost ₹5,338.04 after ₹68,191.57 in transaction costs. Test
whether fewer forced exits and a larger profit objective reduce costly turnover.
This is reused-history development, not out-of-sample evidence or a search for
parameters that produce a desired return.

## Fixed experiments

Control is `stock-research-demerger-sensitivity.json`: momentum_breakout_55,
5% stop, 12% target, 30-session maximum hold. Three sequential comparisons:

1. `stock-research-lower-turnover-hold60.json`: only extend the maximum hold
   from 30 to 60 sessions. Hypothesis: fewer time exits and subsequent entries.
2. `stock-research-lower-turnover-hold60-target20.json`: retain that 60-session
   limit, raise the target from 12% to 20%, preserve the 5% stop. Hypothesis:
   fewer premature profit exits, potentially offset by larger profit giveback.
3. `stock-research-lower-turnover-trend-hold60-target20.json`: use the existing
   `minervini_breakout_volume` entry conditions with the same 5%/20%/60 bracket.
   This entry package requires close above SMA150 and SMA200, SMA50 above SMA150,
   close above the prior 50-close maximum, and volume above 1.4 times its 50-bar
   mean. It changes several entry conditions together; do not attribute the
   result to any one filter or claim faithful implementation of a book.

Keep all other settings fixed: verified local 499-stock Kite development
snapshot, 252-row warmup, 2024-01-01 through 2026-09-03 evaluation, ₹300,000
capital, position/risk constraints, shared ranking, next-session execution,
current delivery fees, entry slippage, configured 100% research drawdown limit,
Nifty 500 gross TRI and the two-event entry-risk policy. No securities, dates,
stops or costs may be altered after viewing the results. No new strategy is
added to a live playbook. The named entry rule already exists in studied_rules.

## Evaluation and stopping rule

Save all config hashes and UTC declaration time in
`config/stock-lower-turnover-experiment-v1.json` before evaluation. Run each
variant once through the frozen runner. Report all variants, even blocked or
losing ones. Compare final equity, net/excess return, maximum drawdown, completed
trades, total and normalized turnover, transaction costs, utilization, exit
reasons and holding duration. Explain why fewer trades need not mean lower total
rupee costs when prices/equity change. Do not optimize further in this experiment.

Retain the existing bootstrap diagnostic with its exploratory, uncorrected
multiple-testing limitation. A positive number does not restore untouched
history. An unresolved holding crossing a listed demerger must withhold economic
results; do not suppress the guard to obtain a table. Both raw-price accounting
and historical membership remain unresolved. No result authorizes live trading.

Run relevant validation and independent Standards/Spec reviews before committing
the configurations and comparison report. Record exact report identities and
hashes, findings, limitations and the next evidence-based action in the overnight
progress note. Reuse cached data without Kite API calls.

## Demonstrated execution blocker discovered during this pass

Two parallel runs stopped before simulation because the shared exposure stream
advanced between its read and append. Fix this bookkeeping race with bounded
retries on version conflict. Each retry must reread the stream, recheck holdout
overlap/exclusivity, and deduplicate an already recorded identical exposure.
Concurrent identical payloads with different timestamps must not trigger a false
idempotency-integrity error. Preserve journal integrity errors and stop on
persistent contention; do not bypass the ledger or relabel dates as unexposed.
Use deterministic colliding SQLite writers to verify distinct discovery records,
duplicate deduplication and competing confirmation exclusion. Retry the same
frozen configurations after repair; record the interrupted attempts explicitly.
