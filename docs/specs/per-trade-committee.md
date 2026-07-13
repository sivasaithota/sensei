# Per-trade Trade Thesis committee

Status: implemented governed-paper foundation. This gate authorizes neither live
execution nor strategy lifecycle promotion.

## Purpose and separation of authority

Lifecycle stage `paper` means that one exact Strategy Plan Version is eligible
for a paper trial. It does not approve any individual trade. Every governed paper
intent must separately pass `TradeCommitteeGate` with a structured
`ApprovalRecord` for that exact intent. There is no default approval, committee
bypass, or fallback to prose, a lifecycle event, a playbook label, or an LLM
summary.

The gate binds the existing specialized decision roles; it does not replace or
reconfigure the project's background subagents. Its required committee is
exactly, and in this order:

1. `L1` / `risk-officer` — checks capital and trade risk;
2. `L2` / `devils-advocate` — challenges the setup and failure case;
3. `L3` / `compliance` — checks policy and compliance constraints; and
4. `L4` / `orchestrator` — confirms the complete chain.

All four verdicts must approve. A veto, missing level, extra verdict, changed
agent identity, reordered verdict, blank reasoning, naive timestamp, future
timestamp, or time-regressing chain fails closed.

## Exact Trade Thesis binding

The Trade Thesis is data, not narrative authority. The gate verifies that it:

- follows the observed signal and precedes the admission decision;
- names the exact intent instrument and long `BUY` direction;
- uses the quantity derived by `TradeIntentFactory`;
- contains the derived entry price inside its approved entry zone;
- matches the intent's exact stop and first target;
- matches the Strategy Plan's maximum holding sessions;
- cites the exact content-addressed Strategy Plan Version;
- contains nonempty, unique, content-addressed evidence Claim IDs drawn only
  from that plan; and
- carries finite out-of-sample statistics and a positive trade count for every
  playbook citation.

Before the gate runs, governed admission resolves every plan Claim ID through
the immutable Provenance Corpus. A syntactically valid but absent claim, a claim
from another plan, raw source text, or a RAG/Obsidian/Hermes result cannot support
approval.

## Durable decision

A successful decision appends one content-addressed
`TradeCommitteeApproved` event. Its identity covers the exact lineage, intent,
plan and trace identities, thesis, ordered verdicts, allowed Claim IDs, holding
horizon and signal time. An exact retry returns the same approval; a different
decision for an already-approved intent fails closed.

The event's authority is `TRADE_ADMISSION_ONLY`. It may be cited by the linked
Trade Episode and governed paper acceptance, but it cannot:

- promote or mutate a Strategy Plan;
- manufacture provenance;
- choose or alter quantity;
- reserve portfolio capacity;
- reset a safety latch; or
- dispatch a broker command.

Portfolio Risk and the paper-only Trading Kernel remain independent downstream
authorities.
