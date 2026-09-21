# First AI investment cycle

Implemented the primary AI research path with analyst, critic and portfolio-manager roles. Frozen momentum v8 remains the parallel benchmark. This is an allocation preview, not a launched paper trial.

A real Claude Code model run completed using the configured `claude-sonnet-4-6` request and invented AAA/BBB evidence. The analyst considered a tentative BBB investment; the critic challenged the contract-renewal risk; the manager chose 100% cash and zero target weights for both symbols. No trades or fills occurred. The run proves model orchestration and saved decision replay, not investment performance.

Local artifact: `data/reports/ai-investment/synthetic-2026-09-21-v1/artifact.json`. Input: `config/examples/ai-investment-synthetic.json`. Replay succeeded without model calls. The actual resolved model identity and monetary cost were not captured by the adapter version used for this run; the requested model is recorded. The later adapter records raw provider responses before parsing for future runs.

The example also showed why schema/citation validation is insufficient: the manager referred to a prior session that was not supplied and described waiting in cash too casually. Prompts now explicitly distinguish colleagues in the same cycle from historical sessions and require acknowledgement of cash opportunity cost. These prompt changes were not rerun against the provider. They reduce ambiguity but do not prove semantic factuality. Independent claim checking and better evidence remain necessary before meaningful forward evaluation.

Review findings were addressed: non-finite input now produces a durable failure record, malformed provider text is saved before parsing, and isolated API requests disable SDK retries. No standards-only maintainability findings remained; spec review identified those three audit/budget issues.

Next delivery is a current, authenticated evidence packet and a governed forward paper-account bridge. Until then, this path neither establishes AI returns nor authorizes live capital. Keep the frozen strategy and Nifty 500 TRI comparisons on the same forward dates once that bridge exists.
