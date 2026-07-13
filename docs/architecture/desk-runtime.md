# Governed multi-agent desk runtime

Status: implemented for governed **swing paper trading**. It has no live-capital
gateway and does not turn the intraday replay engine into an MIS executor.

`DeskRuntime.run_cycle(...)` is the Desk Head. It connects the nine roles from
the original PRD to the evidence, risk and execution authorities built in the
platform foundation. Agent prose never becomes an order by itself.

## Which agents are now in use

| PRD role | Runtime implementation | Responsibility in one cycle |
| --- | --- | --- |
| Desk Head | `DeskRuntime` | Orders the workflow, records completed/skipped roles and stops the path on a block, decline or veto |
| Historian | `StrategyHistorian` | Evaluates the immutable Strategy Plan and signs the exact decision trace plus market snapshot |
| Reporter | `EarningsReporter` | Checks the earnings window and verified GSM/ASM status; unknown status fails closed |
| Crowd Reader | `RegimeCrowdReader` | Supplies bounded VIX/breadth regime context; it cannot create a signal |
| Analyst | `GovernedAnalyst` | Writes the thesis around the already-derived quantity, entry, stop, target, horizon and provenance claims; it cannot change them |
| Committee | `ApprovalChainCommittee` | Runs L1 risk, L2 challenge, L3 compliance and L4 sign-off and records a separate signed verdict from every role |
| Trader | `PaperTrader` | Calls governed admission and the durable paper kernel; it cannot accept a raw or unsigned intent |
| Coach | `OutcomeCoach` | Discovers reviewed, reconciled closed episodes from the journal and converts them into scoped, recurrence-gated research hypotheses |
| Secretary | `OperationalSecretary` | Produces read-only daily operational and reconciled-P&L projections |

The existing `ApprovalChain` remains the Committee's decision implementation.
The adapter adds producer authentication around each verdict. The existing
LLM-backed Analyst is not allowed to choose execution numbers; a future LLM
judgment can be injected into `GovernedAnalyst`, but the class always rebuilds
the final thesis from the exact deterministic candidate.

## Runtime path

```mermaid
flowchart LR
    O["Desk Head"] --> H["Historian: signed trace"]
    O --> R["Reporter: event and surveillance brief"]
    O --> C["Crowd Reader: regime context"]
    H --> A["Analyst: exact thesis"]
    R --> A
    C --> A
    A --> K["Committee: signed L1-L4 verdicts"]
    K -->|unanimous only| T["Trader: signed admission + paper kernel"]
    K -->|any veto| X["Trader skipped"]
    T --> L["Coach"]
    X --> L
    L --> S["Secretary"]
    S --> O
```

Every cycle writes `DeskCycleStarted`, one `DeskRoleCompleted` or
`DeskRoleSkipped` event per role, and `DeskCycleCompleted`. The cycle record is
an audit projection, not an execution capability. A completed command replays
from that terminal record without rerunning external roles; its content-addressed
request identity rejects reuse with changed execution facts. Execution still requires all
of these independently verifiable facts:

1. signed decision trace bound to the exact plan and decision-data snapshot;
2. exact plan version at lifecycle stage `paper`;
3. authenticated component heartbeats, reproducible readiness and signed
   operational health;
4. resolvable source claims from the immutable provenance corpus;
5. exact thesis and four independently signed L1-L4 verdicts;
6. signed paper-kernel admission for the exact content-addressed intent;
7. fresh reconciled account truth and a successful atomic risk reservation.

## Operator visibility

Inspect the most recent cycles without mutating the journal:

```bash
uv run sensei desk-status --journal /absolute/path/to/operations.sqlite3 --limit 10
```

The command refuses a missing journal rather than silently creating an empty
one. Its JSON output shows the result, intent identity, completed roles and
skipped roles for each cycle.

## Safety boundaries

- The runtime is paper-only. `PaperTrader` only accepts `TradingKernel` and the
  kernel package still exposes no live broker gateway.
- A Committee veto never invokes the Trader. Reporter blocks and Analyst
  declines also record downstream roles as skipped.
- The Coach can only create `RESEARCH_ONLY` hypotheses. It cannot veto the next
  trade or edit a Strategy Plan. It automatically discovers only episodes that
  contain close, reconciled attribution and review evidence; incomplete or
  already-learned episodes are skipped and command replay is idempotent.
- Reporter and Crowd Reader context cannot bypass deterministic plan semantics,
  portfolio risk, safety, lifecycle or kernel admission.
- Broker reconciliation requires a content-addressed gateway-signed snapshot.
  Safety reset requires the latest signed clean reconciliation plus a fresh
  owner-signed `safety:reset` authorization.
- RAG, Obsidian and Hermes remain excluded. They are optional future research
  projections and have no place in the authority chain.

## Deployment boundary still open

The Python runtime and its production role adapters are implemented and tested,
but this repository does not yet contain a continuously running, secrets-backed
desk service that provisions every issuer key, point-in-time data feed,
surveillance feed and lifecycle policy. The old launchd jobs still call the
contained legacy commands; they are not silently redirected into this governed
runtime. Production scheduling should be added only with explicit issuer-key
provisioning, fresh broker/account adapters, alert delivery and paper-soak
operations. Live and micro-live remain out of scope.
