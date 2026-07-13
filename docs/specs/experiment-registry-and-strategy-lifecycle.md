# Experiment Registry and Strategy Lifecycle

Status: implemented foundation slice. This specification does not authorize live
execution.

## Purpose

The Experiment Registry prevents a promising result from silently becoming a
tradable strategy. It records every declared variant in a Research Campaign,
separates discovery data from a server-selected opaque confirmation holdout, and
applies campaign-level multiple-testing correction. The Strategy Lifecycle then
requires explicit, audited evidence at every promotion stage.

## Experiment registration

`ExperimentRegistry.preregister` records one immutable declaration containing:

- campaign and variant identity;
- exact Strategy Plan Version identity and SHA-256 content identity;
- exact Examination Protocol and data-policy identities;
- discovery or confirmation phase;
- either a pinned discovery snapshot or an opaque confirmation holdout policy;
- campaign family-wise alpha;
- minimum effect size and minimum confidence lower bound.

Every unique declaration is a campaign trial. Repeating the exact declaration is
idempotent and does not create another trial. A confirmation declaration cannot
contain a caller-selected snapshot. The first confirmation-access event seals the
campaign against later variants.

## Locked confirmation

The public confirmation request contains only campaign identity, registration
identity, expected revision, command identity, and time. Snapshot resolution and
examination are dependencies owned by the registry; the caller cannot pass market
data to the confirmation call.

The registry commits `ConfirmationAccessConsumed` before asking the resolver to
materialize the holdout. A resolver or examiner crash therefore consumes the
one-use opportunity. Retrying that registration fails closed. Successful evidence
must name an accepted dependence-aware uncertainty method (purged walk-forward
folds, moving-block bootstrap, or cluster-robust inference), its independent unit
count, point effect size, and confidence lower bound. It passes only when all of
the following are true:

- the examination protocol passes;
- the effect meets the preregistered minimum effect size;
- the confidence lower bound meets its preregistered minimum; and
- the p-value is at or below:

```text
campaign family-wise alpha / total registered campaign trials
```

The campaign is sealed before this denominator is used, so a later variant cannot
make an earlier correction stale. Interleaved confirmations may append events while
an examiner runs; result recording advances over those immutable events without
re-accessing the holdout.

After successful completion, retrying the exact same `ConfirmationRequest` returns
the immutable recorded result without resolving or examining the holdout again. A
different command for that registration remains rejected as consumed. A matching
command whose content changed is an integrity error. A burn followed by resolver or
examiner failure remains consumed because there is no completed result to recover.

## Strategy lifecycle

The only normal progression is:

```text
proposed -> examined -> shadow -> paper -> canary -> active
```

No stage may be skipped. Each transition records the exact plan version, previous
and target stages, typed evidence references, actor authority, approval reference,
expected lineage revision, and immutable journal event identity.

An `Authority` carried by a request is a claim, not a credential. Every new
transition, including `proposed`, must resolve the actor and claimed role through a
trusted actor-to-roles configuration supplied by the composition root. Missing
configuration, an unknown actor, or caller-side role relabeling fails closed. The
actor recorded on the first `proposed` event is the durable proposer for that exact
plan version and cannot authorize any later promotion of the same plan, even when
the trusted configuration grants that actor another role.

Typed references are only routing keys. Except for `proposed`, every transition
with required evidence must pass a `StageDossierRegistry` verifier. A lifecycle
constructed without a verifier fails closed at `examined`, and therefore cannot
reach shadow, paper, canary, or active. Safety and terminal transitions with
required evidence are verified by the same boundary.

Required stage evidence is:

| Target | Required evidence |
| --- | --- |
| examined | examination dossier |
| shadow | readiness, plan-conformance dossier, locked-confirmation dossier |
| paper | completed shadow trial |
| canary | completed paper trial, risk readiness, operations readiness |
| active | completed canary trial, risk readiness, operations readiness |

Canary and active transitions additionally require an explicit owner approval
reference; an agent or research governor cannot supply that authority. A missing
verifier, a false result, or a verifier error fails closed before the event is
appended. Only one plan version per strategy lineage may be active. An existing
active version must be retired or rolled back before another version can become
active.

Lifecycle eligibility is not per-trade approval. Even at stage `paper`, every
individual governed paper intent requires a separate, content-addressed Trade
Thesis decision from the exact unanimous L1-L4 committee. That committee binds
the plan, trace, corpus-backed claims, derived quantity, entry, stop, target and
horizon to one intent and has only `TRADE_ADMISSION_ONLY` authority. See
`per-trade-committee.md`.

## Stage dossiers

A Stage Dossier is an immutable, content-addressed attestation for one evidence
kind. Its identity pins:

- exact strategy lineage and Strategy Plan Version;
- exact `EvidenceKind`;
- one or more content-addressed supporting Operational Journal event IDs;
- issuer and producer identities;
- issue time and `passed`, `failed`, or `inconclusive` outcome;
- dossier schema version.

Issuance first verifies the complete journal hash chains and confirms every support
event exists. Existence alone is insufficient: each support must be a
`StageEvidenceProduced` event with the exact schema and fields for lineage, plan
version, evidence kind, producer, outcome, and a SHA-256 artifact content identity.
Every field must match the dossier, and the event timestamp and journal sequence
must precede issuance. The dossier is then appended on its own stream; exact retries
return the same immutable dossier.

The registry requires an independently configured issuer allowlist and an
explicit producer allowlist for each `EvidenceKind`; missing configuration and
unknown identities fail closed. Issuer and producer allowlists must be disjoint,
so a caller cannot gain authority by relabelling the same actor. The dossier
issuer and evidence producer must also be different identities. During a
transition, the producer must differ from the transition authority. Together,
these checks prevent invented identities or self-attestation from promoting a
plan.

`StageDossierRegistry.verify_transition` returns true only when every required kind
is present, every reference resolves to a valid content-addressed dossier, all
dossiers pin the request's exact lineage and plan version, all outcomes passed, all
supporting events still exist, and journal integrity remains clean. A wrong-plan,
wrong-kind, wrong-producer, wrong-outcome, missing, failed, duplicate, malformed,
or tampered dossier or supporting event makes the complete transition untrusted.
This is the durable path into paper and remains an additional gate beneath owner
authority for canary and active.

`quarantined`, `rejected`, `retired`, and `rolled_back` are terminal in this
foundation. Quarantine and rollback require safety/owner authority plus an exact
safety or rollback evidence reference. A terminal version cannot be revived; a
replacement must be a new immutable Strategy Plan Version and traverse the full
path.

## Persistence and side effects

Both modules write only append-only facts to the shared Operational Journal. Views
are rebuilt from those facts after restart. Optimistic expected revisions prevent
concurrent decisions from overwriting one another, and command identities make
exact retries idempotent.

Neither module places orders, calls a broker, or exposes a live-execution adapter.
Lifecycle state is governance evidence only; a later Trading Kernel must still
enforce risk, reservations, runtime mode, and broker reconciliation.
