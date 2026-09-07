# Dated signal-history acceptance results

The [contract](../specs/dated-action-signal-history.md) was written before the
synthetic run. Its pure research implementation lives in
`src/sensei/research/action_history.py`; no production caller uses it.

Twenty focused acceptance tests pass. A 5-for-1 split changes earlier prices by
1/5 and volume by 5 while preserving the ex-session raw bar. A subsequent 1-for-1
bonus applies another factor of 2. In the composed example, closes become
10, 10, 11, preserving the genuine 10% move. The raw input and supplied currency
turnover remain unchanged. Ratios may be rational; physical fractional-share
availability is not inferred from this mathematical operation.

Future rows and announced future actions do not change an earlier decision's
history. Already-effective events whose knowledge date is later than the decision
block the result. Unsupported effective events, duplicate/simultaneous actions,
invalid prices, ratios and session labels are rejected. The Spec review identified
future-event ratio validation occurring too late; it now runs before future
events are skipped, with three added regression cases. Final Standards and Spec
reviews have no remaining findings.

Final full suite: **1,057 passed**, 27.26 seconds.

Reproduce the focused checks with:

```sh
.venv/bin/python -m pytest tests/test_action_history.py -q
```

This tests synthetic arithmetic and timing only. It does not verify a real event's
first-known session, complete action coverage, historical raw-price vintage or
stable instrument identity. The caller still needs that independently pinned
evidence. It does not handle rights, demergers, mergers, reverse splits, dividends,
fractional settlements or physical share crediting. All broader research remains
DATA_BLOCKED, RESEARCH_ONLY and unable to trade.

The frozen portfolio uses its existing adjusted signal files and raw execution
inputs. No signal file, simulation parameter or return result changed. There were
no Kite calls, purchases, orders or external messages in this pass.

Next, preregister a small real split/bonus reproduction against existing official
captures. Establish publication-to-session mapping, exact raw identity and action
coverage before running it. Keep its result separate from portfolio performance;
integration additionally needs daily ranking/correlation replay, held-action
accounting and complete historical universe evidence.
