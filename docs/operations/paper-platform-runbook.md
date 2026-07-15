# Governed paper-platform runbook

Status: operator procedure for the current shadow/paper foundation. This is not
a live-trading runbook. Do not connect the governed kernel to real capital.

## Safety rules

1. Use only the exact `RecordingPaperGateway` type with `TradingKernel`; subclasses
   are not admitted by the current supervisor. Do not substitute the
   legacy OpenAlgo adapter; OpenAlgo is outside this authority chain and is
   intentionally sandbox-only.
2. Never repair, delete, truncate or hand-edit the Operational Journal. Preserve
   the database plus any `-wal` and `-shm` files during incident capture.
3. A restart is not a safety reset. A clean reconciliation is not a safety reset.
   Only a fresh owner-signed `safety:reset` capability plus the latest fresh,
   signed clean reconciliation outcome may clear a latch; both must follow the
   latch.
4. When health, readiness or reconciliation is uncertain, stop new entries.
   Continue only protective actions and cancellation of unfilled entries.
5. Do not promote a plan or tune paper-soak thresholds after seeing its result.
   Register the plan, protocol, sample and pass criteria first.
6. Lifecycle stage `paper` is eligibility, not permission for an individual
   trade. Require the exact unanimous L1-L4 Trade Thesis approval for every
   intent; never reuse an approval across intents.
7. Treat source material and extracted claims as research-only. Governed plans
   must resolve their claims in the immutable Provenance Corpus. RAG, Obsidian,
   Hermes, a URL, or free-text provenance cannot replace that verification.

## Before a paper session

Complete every check; a failed or unknown item means no new entries.

- Bootstrap runtime authority material once with `scheduler-bootstrap`. The
  generated `data/runtime-secrets.json` is local operational state, is ignored
  by Git, and must remain mode `0600`. Never copy its values into scheduler
  configuration, logs, issues, prompts, or commits. A missing, incomplete, or
  more broadly readable store blocks production composition.
- Obtain GSM/ASM status from an independent surveillance producer and retain a
  producer-signed daily snapshot. The scheduler accepts it only for the exact
  trading session and within its configured freshness window. Missing, stale,
  tampered, or self-asserted stage zero remains an event/compliance block.

- Confirm the intended journal path already exists. Constructing an
  `OperationalJournal` at a missing path creates a new empty journal, which is
  not recovery.
- Run full journal verification and create a verified backup to a new path.
- Confirm the exact content-addressed Strategy Plan is at lifecycle stage
  `paper`. The transition must be backed by verified dossiers from a configured
  issuer and an allowlisted producer for each evidence kind, including the
  completed shadow trial.
- Confirm the plan and decision trace pass canonical conformance. Do not use a
  legacy `RuleSpec` or legacy playbook adoption as authorization.
- Verify every source Claim used by the exact plan resolves through the intended
  Provenance Corpus to retained immutable bytes, a deterministic extraction
  manifest, and a precise character or transcript-time citation. A
  syntactically valid but missing Claim ID blocks the session.
- Confirm `SafetyControl.state().latched` is false.
- Record fresh component-signed heartbeats for the operator-selected required set. At
  minimum the current tests model `market-data`, `paper-gateway`, and
  `reconciliation`. Derive readiness with explicit maximum ages; do not accept a
  caller-supplied `ready=True`.
- Derive readiness reproducibly and record a monitor-signed operational health
  assessment. It must be durably `HEALTHY`,
  allow new entries, and be within the coordinator's configured maximum age.
- Supply a recent, explicitly reconciled Account Snapshot matching the snapshot
  pinned by the intent. Check marked equity, high-water mark, day/week P&L,
  positions and risk-to-stop values. Its `snapshot_id` must be the identity
  derived from all snapshot content, reservations, reconciliation state and
  capture time; do not accept or copy a caller-selected label. Record that exact
  snapshot through `AccountSnapshotAuthority` using the configured account
  adapter signer, and pass its evidence event ID as session truth. A valid
  content address without valid producer evidence is blocked.
- Confirm the Point-in-Time Market Data snapshot, executable quote and exchange
  session calendar are the intended versions. Missing earnings or surveillance
  status must remain blocked.
- For intraday paper, confirm the explicit trading date and any special-session
  boundaries, receipt-latency budget, feed-age budget and participation cap.

## Verify, back up and restore the journal

There is no operator CLI for these foundations yet. Use the API from the same
environment as the application. Verify that the source path exists before
opening it:

```python
from pathlib import Path

from sensei.operations.journal import OperationalJournal

journal_path = Path("/absolute/path/to/operations.sqlite3")
if not journal_path.is_file():
    raise RuntimeError(f"journal does not exist: {journal_path}")

journal = OperationalJournal(journal_path)
verification = journal.verify()
if not verification.ok:
    raise RuntimeError("; ".join(verification.errors))

backup = journal.backup_to(
    Path("/absolute/path/to/backups/operations-YYYYMMDD-HHMMSS.sqlite3")
)
print(backup.sha256, backup.events, backup.created_at.isoformat())
```

`backup_to` refuses an existing destination, verifies the source first, uses
SQLite's consistent backup operation, and verifies the copy. Store the returned
SHA-256, event count and timestamp in the incident/change record.

Restore only into a new path. First compare the backup file's SHA-256 with the
stored value, then restore and verify:

```python
from pathlib import Path
import hashlib

from sensei.operations.journal import OperationalJournal

backup_path = Path("/absolute/path/to/verified-backup.sqlite3")
expected = "sha256:..."  # copied from the backup inventory
actual = "sha256:" + hashlib.sha256(backup_path.read_bytes()).hexdigest()
if actual != expected:
    raise RuntimeError("backup digest mismatch")

restored = OperationalJournal.restore_from(
    backup_path,
    Path("/absolute/path/to/recovery/operations.sqlite3"),
)
assert restored.verify().ok
```

Never restore over the source. Keep the failed source immutable for analysis,
start from the new verified path, and reconcile all paper broker state before
allowing another entry.

## Normal session flow

Use `GovernedDeskSupervisor.paper_only(...)` as the owner of a bounded paper
session. Its composition must supply the exact `TradingKernel`, `DeskRuntime`,
cycle source, truth source, Account Snapshot verifier, Operations Monitor
verifier and Safety Control that belong to the existing journal. Configure a
small positive request-clock skew bound and use the process's trusted clock;
request timestamps are not freshness authority. The supplied gateway must be
the same exact `RecordingPaperGateway` used by the Kernel, Coordinator, Trader
and Desk path. The supervisor verifies this object-identity chain at startup and
again before dispatch. Do not use it with OpenAlgo or a network-capable adapter.
Treat `compose(...)` as privileged startup code: it executes before the returned
graph can be validated. Do not load strategies, plugins or remote code in that
callback. The public factory rejects subclasses in the side-effecting runtime
chain, but exact-type checks cannot make a hostile composition callback safe.

The supervisor executes the following fail-closed prefix before it polls a
cycle source: acquire the journal lease, verify the journal, enforce kernel
protection/recovery, capture authenticated session truth, reconcile the complete
Broker Snapshot, verify Operational Health and signed Account Snapshot evidence,
check their freshness, and observe the Safety latch. A failed check records a
terminal failed or halted session and suppresses new work. An incomplete prior
session runs kernel recovery and is then halted, including when restart uses a
new command ID; it never reruns agents under the interrupted command. Journal
aliases resolve to one inode-identity lease, so neither a symlink nor a hard
link can create a second owner. One Supervisor object also rejects overlapping
run or shutdown calls; close waits for an active session to leave its protected
lifecycle section.

Before recording `HALTED` or `FAILED`, the Supervisor makes a fresh protective
Kernel enforcement attempt. Replaying either non-completed terminal performs
protective recovery again without polling work or rerunning agents. Production
replay resolves every truth-manifest reference to earlier signed Account,
Health, Broker and reconciliation evidence, verifies the phase sequence, and
requires the final manifest to match the terminal reconciliation.

After that prefix succeeds:

Before every individual queued cycle, the supervisor re-verifies Account
Snapshot evidence, Operational Health, freshness, the Safety latch, the trusted
clock bound and the exact cycle request identity. That identity includes the
command, bars, decision market snapshot, executable quote, Account Snapshot,
health and evaluation inputs. If an earlier cycle degrades health or latches
safety, later cycles are not invoked.

The cycle-level check is not the final entry authority. After Historian,
Reporter, Crowd Reader, Analyst and Committee complete, `TradingKernel.run_once`
first performs protection/cancel recovery and then calls the Supervisor gate
again before any entry reserve, command preparation or gateway call. The gate
uses a new trusted-clock sample, captures authenticated Account, Health and
Broker truth, reconciles it, and records a `DeskSupervisorTruthCaptured`
manifest containing those evidence IDs and the exact cycle request identity.
The gate signs a one-use capability over that manifest, the exact admitted
intent, cycle request and Account Snapshot; the Kernel durably consumes it
before reservation. The Kernel dispatches only the intent named by that cycle. If the gate
rejects it, `TradeIntentQuarantined` records the reason codes and manifest ID;
invalid evidence or any failure before the authorization callback returns is
also quarantined against the best durable evidence available while no entry
command exists. A previously prepared outbox command cannot be quarantined; it
remains incomplete, every retry still requires fresh authorization, and a
rejection is returned without being masked. Unscoped Kernel recovery performs
protection and cancellation only; it cannot dispatch any accepted intent.
After each cycle that does run, the
Supervisor captures and reconciles fresh account/broker/health truth before the
next cycle or terminal session event.

1. Record component-signed heartbeats, derive Operations Readiness, and record a
   monitor-signed Operational Health assessment. These are evidence events, not
   informal log messages.
2. Evaluate the immutable plan to obtain its decision trace and record the
   Historian's signature over that trace and exact market snapshot. The same engine and
   plan must be used for research, shadow and paper; mode-specific strategy
   branches are not allowed.
3. Use the side-effect-free `TradeIntentFactory` with the exact quote and Account
   Snapshot to prepare the candidate derived intent, then prepare its structured
   Trade Thesis. The instrument, long direction, derived quantity, entry zone,
   exact stop, first target and holding horizon must match the plan and intent.
   Its evidence must be nonempty, content-addressed Claims from that exact plan,
   and it must cite the exact plan version.
4. Obtain exactly four approved verdicts, in order: `L1/risk-officer`,
   `L2/devils-advocate`, `L3/compliance`, and `L4/orchestrator`. Each verdict
   needs nonblank reasoning and an aware, non-regressing timestamp. Any veto,
   missing/extra/reordered verdict, identity mismatch or future time means no
   admission. Every role must authenticate its own exact verdict; a freely
   constructed `ApprovalRecord` is not committee evidence.
5. Call `GovernedPaperCoordinator.accept` with that `ApprovalRecord`. It
   validates the exact plan at `paper`, resolves all plan claims in the real
   corpus, checks durable health and safety, re-derives quantity, and requires
   the thesis to match the resulting intent. It durably records
   `TradeCommitteeApproved`, signs an exact kernel-admission capability, starts
   the linked Trade Episode, records the exact
   committee/lifecycle/health evidence, and appends `TradeIntentAccepted`. It
   does not call the gateway.
6. Call the scoped `TradingKernel.run_once` path with the exact accepted intent
   and Supervisor entry-authorizer callback. The kernel recovers fill/protection
   gaps first, obtains the final fresh authorization, atomically reserves
   portfolio capacity, persists a typed command, dispatches it by stable command
   ID, records its receipt, and protects any positive fill before another entry.
   The authorization is signed, exact-intent/cycle bound, and consumed once.
7. Ingest cumulative fills monotonically. Never decrease cumulative quantity or
   replace an average fill price for the same cumulative quantity.
8. Reconcile a complete, content-addressed and gateway-signed `BrokerSnapshot`, including positions, protection and
   every working paper order. Every protective object must match its known
   content-addressed client command on instrument, quantity, stop and target; a
   quantity match with different levels is not clean. The kernel rejects an
   unsigned, stale or future snapshot. A clean result is recorded and signed;
   any unknown, mismatched or under-protected object is
   quarantined and latches safety.
9. Append the linked episode facts through protection, exit and close, then
   append one reconciled cost record and the advisory review. Record outcome
   attribution only against every entry/exit fill and that episode's exact cost
   evidence; planned prices are pinned when the episode starts.
10. Produce daily/weekly Operational Reports. Treat P&L as trusted only when it
   comes from a reconciled `OutcomeAttributed` event. If journal verification
   fails, the report intentionally withholds P&L totals.
11. At session end, verify the journal again, take a new verified backup, and
   retain the readiness, health, reconciliation and report outputs with the soak
   evidence.

Inspect the Desk Head and actual role routing without changing state:

```bash
uv run sensei desk-status --journal /absolute/path/to/operations.sqlite3 --limit 10
```

For intraday paper, feed event time and receipt time separately and preserve
sequence ordering. Reconnect alone never clears a feed halt: the engine must
receive market data strictly after the reconnect receipt, that watermark must
still be fresh, and an explicit authorized feed reset is required. Cached or
pre-disconnect data cannot be reset evidence. The engine continues to emit
flatten/protective directives after entries close or halt.

## Halt and incident response

Halt new entries immediately on any of the following:

- journal verification failure;
- `UNKNOWN`, `HALTED`, stale or otherwise non-entry-capable health;
- failed component readiness;
- a safety latch or portfolio loss/drawdown breaker;
- a missing/unverifiable provenance claim or any absent, vetoed or mismatched
  L1-L4 per-trade approval;
- stale/future/out-of-order market truth or excessive receipt latency;
- feed disconnect, unprotected quantity, unknown broker objects or a failed
  protection command;
- any position, protection or working-order reconciliation mismatch.

Then follow this order:

1. Preserve the journal and record the UTC and exchange-local incident times,
   reason, last known healthy event ID, plan/trace/intent IDs and operator.
2. Stop admission and entry dispatch. Run kernel enforcement protect-first:
   recover completed entry fills and repair every durable protection gap before
   attempting cancellation. Then cancel only the unfilled remainder of an entry
   with a durable completed broker receipt. Never synthesize a broker cancel for
   an accepted-only or merely prepared entry.
3. Capture a complete paper broker snapshot: positions, protections, cumulative
   fills and all working orders with client command IDs.
4. Run kernel reconciliation. Save the returned issues and the resulting
   `QuarantineRaised`, `SafetyLatched` or `ReconciliationClean` event IDs.
5. Resolve every unprotected or unknown object. On protection failure the kernel
   latches safety and prepares cancellation of the unfilled entry remainder.
6. Verify the journal. If verification fails, recover to a new path from the most
   recent digest-verified backup; do not continue on the suspect database.
7. Restart the paper process against the preserved or verified-restored journal.
   Run the kernel recovery path before new admission. It reconstructs a fill from
   a completed entry receipt when a crash occurred before the separate fill
   event. If gateway acceptance preceded a failed completion append, it looks up
   the immutable receipt by command ID without resending the entry. It then
   installs missing protection and handles the confirmed working remainder.
8. Reconcile again from a newer complete snapshot. Keep the latch set until this
   result is clean and all incident actions are documented.

### Incident-specific expectations

| Incident | Required recovery evidence |
| --- | --- |
| Crash or journal failure after gateway receipt | Safety is latched; command-ID receipt lookup recovers the original outcome without resending entry; protection is completed; later broker snapshot reconciles cleanly |
| Protection command failure | Safety remains latched; unfilled entry remainder is cancelled; filled quantity is fully protected or the paper position is flattened under an approved procedure |
| Unknown position/order or quantity mismatch | Full broker inventory captured; unknown object resolved; subsequent reconciliation is clean |
| Feed disconnect or late receipt | Feed reconnect, market data received strictly after that reconnect, fresh watermark, explicit authorized feed reset and fresh health assessment |
| Journal integrity failure | Failed files preserved; backup digest matches inventory; restore to a new path verifies; broker/account truth is reconciled again |
| Daily/weekly loss or drawdown limit | New reservation remains rejected; no journal or account field is edited to bypass the breaker; resume criteria are an explicit owner risk decision backed by fresh account truth |

## Reset and resume

A safety reset is allowed only after the incident cause is closed. The required
sequence is:

1. journal verification succeeds;
2. a complete signed broker snapshot reconciles cleanly after the latest latch,
   and that signed outcome is fresh and still the newest reconciliation outcome;
3. no exposure is unprotected and no broker object is unknown;
4. a fresh owner-signed authorization contains `safety:reset`, follows the
   latch, and is not in the future;
5. `SafetyControl.reset` appends the reset with the clean reconciliation time;
6. required components publish fresh healthy heartbeats;
7. readiness and operational health are reassessed and durably healthy;
8. the next kernel pass completes recovery/protection work before any new entry.

Do not clear a latch by changing configuration, deleting journal events, using a
new empty journal, or restarting the process.

## Paper-soak release gates

Define the soak duration, episode count, regimes and numerical thresholds before
the soak starts. The code intentionally does not invent those business limits.
The soak is eligible for a paper-trial dossier only when all agreed gates pass:

- **Identity and conformance:** every admitted trade resolves to the exact
  immutable source/citation Claims, plan, trace, market snapshot,
  content-addressed account snapshot, intent, unanimous exact L1-L4 committee
  decision and lifecycle evidence; zero legacy-authorized trades.
- **Journal integrity:** every start/end verification passes; backup and restore
  drills reproduce the event history without integrity errors.
- **Risk:** no reservation bypass; held, pending, partial-fill and unreconciled
  exposure agrees with account truth; loss, drawdown, heat and capacity breakers
  behave as preregistered.
- **Order safety:** every positive fill is protected before another entry; every
  protective order reconciles its exact client command, quantity, stop and
  target; zero unresolved unknown orders, exposure mismatches or
  under-protection incidents. Kill-switch drills demonstrate protect-first
  enforcement and cancellation only for broker-confirmed working entries.
- **Operations:** all active-session required components remain within their age
  budgets; every halt, reconnect, reset and special-session boundary is exercised
  and produces the expected durable evidence. A reconnect drill proves that
  pre-disconnect data cannot clear the latch.
- **Recovery:** restart after prepared command, restart after completed receipt,
  protection failure, stale data, disconnect and corrupted-copy restore drills
  all pass without duplicate commands or unprotected continuation.
- **Episodes and accounting:** every closed episode has complete entry/exit and
  reconciled-cost evidence; planned prices, quantity, fill values, fees and
  currency reconcile exactly before report P&L is admitted.
- **Statistical governance:** the preregistered paper sample and pass criteria are
  met without reusing confirmation access or tuning the plan during the test.
  Drift remains review-only and recurrence learning remains research-only.
- **Incident closure:** all quarantines and alerts are explained, remediated and
  independently reviewed; no unexplained safety reset is present.

Passing a soak does not itself enable canary. Issue immutable, plan-pinned
`PAPER_TRIAL`, `RISK_READINESS`, and `OPERATIONS_READINESS` Stage Dossiers from
their supporting journal events. Canary promotion then requires those verified
dossiers and explicit owner approval.

## Conditions still required before canary or live

The following are absent or not yet production-wired, so this runbook must not be
extended to real capital by configuration alone:

- a bounded canary execution adapter and account/envelope separate from paper;
- a governed live `PaperGateway` replacement with broker-native idempotency;
- broker-durable protective-order semantics and verified cancel/replace races;
- continuous broker position, protection, order and exit-fill ingestion;
- continuous reconciled Account Snapshot production and end-of-day truth;
- production scheduling, supervision, alert delivery and operator escalation;
- authenticated service identities, role separation, secrets management and an
  auditable owner-approval mechanism;
- tested backup retention, restore time objectives and disaster/failure drills;
- explicit broker/exchange product constraints, fees, taxes, corporate actions,
  short/auction behavior and applicable compliance controls;
- a predefined canary capital/risk envelope, automatic containment, rollback
  criteria and owner-approved kill procedure.

Only after those capabilities are implemented and independently tested should a
canary trial begin. Active/live promotion additionally requires a completed
canary-trial dossier, fresh risk and operations readiness dossiers, and a new
explicit owner approval.
