# AI investment decisions, first executable slice

The AI workflow is the primary investment research path. Frozen liquid-relative-strength v8 remains a parallel benchmark; its ranks and trade decisions are not inputs to the AI.

## Scope

A caller supplies a timestamped evidence packet, allowed NSE cash symbols, marks, paper holdings, available cash and configurable portfolio limits. Three sequential model calls produce an analyst proposal, a critic review, and the portfolio manager's final target weights. The manager can select stocks, retain/reduce/sell existing holdings or explicitly choose cash. Deterministic checks constrain risk and arithmetic, not stock selection. Every existing holding must be addressed explicitly, including zero targets for exits.

Only supplied evidence available by the decision cutoff is allowed. Inputs and model outputs receive strict validation; symbol-specific decisions require symbol-specific citations. Evidence is untrusted content, never instructions. Publication and availability timestamps must be timezone-aware and no later than the cutoff. Supplied provenance is not independently authenticated by this slice.

Persist each attempt, the input packet, prompts, raw role outputs, requested backend/model, and validated result. Failures remain failures; never replace them with a cash decision. One call per role, no optimization/retry loop. Calls use no filesystem, network or execution tools. Replay uses saved outputs without another model call and verifies the artifact digest. Costs are unknown unless measured, never assumed zero.

The result is a whole-share allocation preview using supplied marks and estimated delivery charges, not fills, an order authorization or a backtest. A cash shortfall blocks the entire preview rather than silently changing the manager's choices. Sale proceeds cannot fund purchases in this same-cycle preview. Held shares cannot be sold beyond the supplied available quantity. Marks must meet a configurable freshness bound. A configurable drawdown limit blocks exposure increases at or beyond the limit, while reductions remain possible.

CLI accepts a JSON packet and a new output directory. Existing output directories cannot be overwritten. The synthetic example is explicitly labelled and proves plumbing only. Existing trading admission, runtime state and frozen benchmark implementation remain unchanged.

## Acceptance

Tests exercise genuine selection freedom through injected role outputs, intentional cash, malformed/future/stale inputs, invalid citations/weights, explicit holding coverage, model failures, risk limits, affordable whole-share accounting, unavailable shares, no reuse of sale proceeds, durable failure artifacts and replay integrity. A real-model synthetic smoke run, if authentication is available, is separate from tests and is not investment-performance evidence.

## Remaining integration

An authenticated current evidence collector, incremental account state and next-session fills, exchange calendars/corporate actions, and admission through the governed paper runtime are future work. This slice does not activate a paper trial or live trading. Compare prospective AI results with the frozen benchmark and Nifty 500 TRI only after the same-date forward account paths exist. Modern models may know historical outcomes; historical prompt replays alone cannot establish out-of-sample AI alpha.
