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
