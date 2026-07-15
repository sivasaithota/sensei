# Fully governed paper cutover

The scheduler may scan or execute a queued paper order only when its exact
canonical Strategy Plan is at lifecycle stage `PAPER`.

The migration command retains the studied-rule bytes in the Provenance Corpus,
records content-addressed claims, converts only backtest-adopted rules, publishes
reproducible examination/conformance/readiness/lock evidence, and advances each
plan no further than `SHADOW`. It also journals the existing paper inventory as
observation-only state requiring reconciliation; it never invents historical
broker fills.

At each EOD session, the scheduler evaluates every `SHADOW` plan over the exact
current universe using the canonical engine. Shadow observations are forward
only and idempotent per market session. A `SHADOW_TRIAL` dossier is published
only after the configured minimum sessions, signals, instruments, completeness,
and zero-error conditions pass. The lifecycle autopilot may then promote the
plan to `PAPER`, after which—and only after which—the legacy paper account
adapter may scan that named strategy or execute one of its queued orders.

This cutover remains paper-only. `CANARY` and `ACTIVE` remain owner-controlled,
and no scheduler path may reset a safety latch.
