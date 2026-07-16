# Unattended governed paper scheduler

Status: implementation contract for automated **paper** trading. This contract
does not authorize live or micro-live capital.

## Objective

One restart-safe process owns the normal daily workflow without an operator
having to run the legacy `run-day` and `execute-open` commands. It may automate
research, strategy promotion through `paper`, shadow observation, paper entry
sessions, protective recovery, learning, reporting, and backups.

The scheduler must never manufacture evidence to make progress. Missing
point-in-time data, source provenance, surveillance status, a fresh quote,
operational truth, or a completed shadow sample is a durable waiting or halt
result, not permission to fall back to the legacy scanner.

## Authority boundary

- Machine identities may propose a plan and an independent machine governor
  may promote it through `EXAMINED`, `SHADOW`, and `PAPER` when every exact,
  independently produced dossier passes.
- `CANARY` and `ACTIVE` remain owner-authorized capital stages.
- The scheduler must not mint owner approvals, clear an owner kill-switch, or
  reset a safety latch. A clean reconciliation is necessary but never
  sufficient for reset.
- Only the exact paper gateway is in scope. Network/live broker gateways remain
  rejected by the governed Supervisor boundary.

## Durable scheduling contract

The scheduler is polled repeatedly and derives bounded tasks for the
Asia/Kolkata trading date. Every task has a deterministic identity containing
the task kind, trading date, and policy version. A journal-backed ledger claims
each identity before work, records its terminal outcome, and returns that
outcome on replay. A process crash must not cause the same entry task to submit
again.

Normal task order is:

1. protective recovery and reconciliation;
2. retry-bounded market-data ingestion, universe hygiene, and shadow progression;
3. one bounded governed paper-entry session;
4. post-close outcome/Coach processing and reporting;
5. journal verification and backup.

At most one entry-bearing Desk cycle is dispatched per Supervisor session. A
later poll captures new account and broker truth before evaluating another
candidate.

## Required explicit outcomes

Every poll returns machine-readable status and reason codes. At minimum the
system distinguishes:

- no task is due or the exchange is closed;
- task already completed or currently claimed;
- journal or scheduler-state integrity failure;
- owner kill-switch or durable safety latch;
- legacy exposure awaiting safe adoption/closure;
- missing trusted source claims or immutable plan payload;
- missing/inadmissible point-in-time research data;
- examination, locked confirmation, or shadow sample not ready;
- no plan at `PAPER`, no current signal, stale/missing quote, unknown earnings
  or surveillance status, or risk/committee veto;
- broker/account/health/reconciliation truth unavailable or unhealthy;
- a completed paper session, learning pass, report, or backup.

Unknown exceptions fail the current task closed, are journaled without secret
material, and stop later entry-bearing work in that poll.

Before each EOD shadow observation the scheduler refreshes every configured
universe member with bounded per-symbol retries and records one durable
ingestion manifest. Instruments whose retained history is long stale after all
refresh attempts are explicitly excluded with a reason; their files and prior
history are never deleted. Temporary refresh failures remain in the denominator.
Shadow evaluation proceeds only when the exact-session eligible set meets the
pre-registered `minimum_data_completeness` threshold, and its market snapshot
links the ingestion event, failures and exclusions. No ingestion result grants
lifecycle or trading authority.

## Restart and cutover invariants

- Paper gateway receipts are durable by broker command ID and are written
  before `execute` returns. A new process retrieves the original receipt rather
  than resending the command.
- The immutable Strategy Plan catalog and lifecycle share the operational
  journal. Lifecycle IDs alone are not enough to reconstruct execution.
- Existing legacy paper positions are not silently imported as governed
  exposure. Until a verified adoption/closure workflow accounts for them, new
  governed entries report `LEGACY_EXPOSURE_UNRESOLVED` while legacy protective
  management remains available.
- The old launchd jobs are disabled during cutover; one five-minute governed
  scheduler job becomes the only normal mutating owner.
- NSE holidays and special sessions come from explicit calendar configuration.
  A weekday is not by itself proof of an open exchange session.

## Definition of done

The implementation includes deterministic session scheduling, a durable task
ledger, durable paper command receipts, immutable plan catalog, canonical
legacy-rule conversion, lifecycle automation seams, explicit scheduler CLI and
status output, corrected launchd weekdays, focused replay/crash tests, and an
operator runbook. Production entries remain fail-closed until real provenance,
point-in-time data, current quote, event/surveillance, and truth adapters pass.
