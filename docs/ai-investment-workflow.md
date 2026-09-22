# AI investment workflow

The primary investment path now has three model roles: analyst, critic and portfolio manager. The manager selects stocks and target weights or cash. Deterministic validation limits risk and computes a whole-share preview; it does not replace the manager's selection with a strategy ranking.

The first slice is research software, not an active paper trial. No broker orders or paper fills are submitted. Supplied prices are marks, not guaranteed execution prices. Fees use the existing current-cost delivery model; this preview does not model slippage, settlement calendars or corporate actions. Evidence timestamps are checked but their authenticity and the truth of a model's interpretation are not established automatically.

Run the labelled synthetic example:

```sh
SENSEI_LLM_BACKEND=claude-code .venv/bin/python -m sensei.investment \
  config/examples/ai-investment-synthetic.json \
  data/reports/ai-investment/my-new-run
```

Output directories must be new. Each run makes at most three calls. The existing configured provider/model is used, with tools disabled for this workflow. Actual provider cost and resolved model identity are currently unknown in the artifact; no zero-cost claim is made. Use the existing Anthropic API configuration instead by selecting `SENSEI_LLM_BACKEND=api`.

Replay without model calls:

```sh
.venv/bin/python -m sensei.investment --replay data/reports/ai-investment/my-new-run
```

`READY` means a valid allocation preview, not investment approval. `AI_CHOSE_CASH` is an explicit valid decision. `INPUT_BLOCKED`, `MODEL_FAILED` and `RISK_REJECTED` are failures, never substitute cash returns. `STARTED` in an interrupted artifact means incomplete work. The artifact saves prompts and raw outputs plus a digest for accidental-edit detection; this is not a signed audit record. Archive it securely if using private evidence.

Input prices/cash are integer paise, weights integer basis points. Each current holding must be represented, including explicit zero targets for exits. Configure `limits.max_drawdown_bps` in the packet (1500 = 15%): at that drawdown, increases are blocked and reductions remain possible. Available shares constrain sales. Existing cash must fund buys without assuming sale proceeds are immediately reusable. An unaffordable allocation fails as a whole rather than being silently resized. Risk constraints can therefore reject an otherwise plausible AI decision.

The frozen liquid-relative-strength v8 strategy remains a parallel benchmark. This slice merely records its identity; it does not rerun it or claim matched prospective returns. Next: supply authenticated current evidence and account state, then admit decisions through the governed paper runtime with next-session fills. Compare that forward record against the same-date momentum and Nifty 500 TRI paths. Synthetic runs demonstrate plumbing only; historical AI prompts can contain model-training leakage and cannot alone prove alpha.

## Full desk

Use `--full-desk` to run Historian → Reporter → Crowd Reader → Analyst → Critic → Portfolio Manager → Coach (at most seven model calls). Historian analyzes supplied history, Reporter supplied company information, and Crowd Reader supplied regime/sentiment evidence. None fetches data or has tools. The Coach reviews reasoning and evidence gaps; it does not learn from nonexistent fills. Secretary generates a nine-role report with committee detail and explicitly skipped execution.

```sh
.venv/bin/python -m sensei.investment --full-desk \
  config/examples/ai-investment-synthetic.json data/reports/ai-investment/full-desk-example
```

Application integration is `DeskRuntime.run_investment_cycle(packet, output_dir, command_id=...)`. It shares the operational journal with the existing desk, binds the saved artifact to that journal and replays completed commands without model calls. Reusing a command with changed packet/path fails. An interrupted attempt requires inspecting its evidence before issuing a new command. The CLI creates an independent research artifact; use the DeskRuntime method for journal binding.

These are AI research adapters for the desk responsibilities, not new authority for the existing operational role instances. The signed Historian trace, event/surveillance checks, committee and Trader in mechanical `run_cycle` remain unchanged. The AI mode reports `NOT_ADMITTED` even for a valid preview. Current evidence collection and AI-specific governed paper admission remain open; no full paper-integration claim is made.

## Historical portfolio pilot

Run `.venv/bin/python -m sensei.research.ai_backtest NEW_OUTPUT_DIRECTORY` for the registered 30 June–29 August 2025 price-only pilot. It uses local audited data, freezes 20 inception-liquid stocks, makes two full-desk decisions (at most 14 model calls), and simulates next-session fills through the existing raw-price accounting engine. It writes registration, evidence identity, per-role artifacts, AI account history, same-universe momentum control and Nifty 500 TRI comparison. Any model failure stops the AI headline report.

For no-model replay, use `sensei.backtest.ai_portfolio.saved_decisions(previous_ai_directory)` as the `decide` argument to `run_ai_portfolio` with the original inputs/policy/universe. It rejects a changed packet or simulated account rather than reusing an incompatible decision. This API does not reconstruct the raw dataset from the report alone.

Historical archive availability is assumed. No contemporary news/fundamental evidence is supplied, and model-training hindsight remains possible. Returns include configured execution charges/slippage/data overhead but exclude unknown model usage costs. The limited-universe momentum control is not the earlier full-universe v8 headline. Monthly decision scheduling overrides advisory review horizons in this pilot. Resulting-security holdings not representable in the packet stop a later decision rather than silently disappearing.

Command-line replay is also available:

```sh
.venv/bin/python -m sensei.research.ai_backtest NEW_REPLAY_DIRECTORY \
  --replay-from ORIGINAL_PILOT_DIRECTORY
```

This reloads the verified local accounting inputs and uses no model calls. Saved per-date packets must match the regenerated account and evidence exactly.

For an explicitly recorded operational recovery, `--resume-from FAILED_PILOT_DIRECTORY` reuses only exact validated role responses and calls the model for the unfinished remainder. It creates a new run and preserves the failure; it is not an automatic retry loop or a way to change evidence under an old decision. Isolated Claude CLI research calls now request medium reasoning effort to bound latency. Reused responses retain their original provider metadata.

The historical runner uses a target-only manager schema: the AI chooses stock weights and software derives residual cash. It does not change the weights or silently repair contradictory legacy decisions. Resuming across this contract change reuses only upstream research and requests a new manager decision. The general full-desk API retains its legacy schema unless `target_only=True` is selected.

On macOS, wrap a long run with `caffeinate -i` to prevent idle sleep while that command runs. This is temporary and ends with the process; it does not change system sleep settings or prevent lid-triggered sleep. Interrupted provider responses remain failures, with completed role outputs eligible for exact-input resume.
