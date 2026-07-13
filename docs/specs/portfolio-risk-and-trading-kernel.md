# Portfolio Risk and Trading Kernel

Status: implemented paper-only foundation. This specification does not authorize
live execution and is not wired into the existing daily loop or OpenAlgo adapter.

## Purpose

This slice separates strategy intent from capital authority and broker side
effects. A conformant Strategy Plan may produce a decision, but only Portfolio
Risk can reserve account capacity and only the Trading Kernel can prepare a typed
paper command. Both write to the shared append-only Operational Journal.

## Trade intents and money

`TradeIntent` is immutable and content-addressed. Its identity covers the exact
plan, decision trace, executable market snapshot, reconciled account snapshot,
instrument, quantity, entry, stop, target, timestamp, side, and product. Portfolio
reservation rejects an account snapshot that does not match the intent's pinned
account input. The foundation accepts only long `BUY` delivery intents. Money is
integer paise throughout; floats, non-finite values, booleans, zero, and negative
values fail at the boundary.

## Portfolio reservations

`PortfolioRisk.reserve` requires a recent, explicitly reconciled account snapshot.
It checks a new intent together with broker-held exposure and every durable pending
or not-yet-reconciled reservation. The checks cover:

- available cash;
- marked equity and its high-water mark;
- total portfolio notional;
- per-instrument notional;
- per-trade stop risk; and
- total portfolio heat to protective stops; and
- occupied position slots.

Each held position supplies integer-paise risk to its current protective stop.
Total heat adds those marked held risks to pending-entry risk and any filled risk
not yet incorporated by the reconciled snapshot. Partial fills use their actual
average fill price against the immutable stop; unfilled quantities use the intent's
limit-to-stop risk. No sector or correlation adjustment is invented without
explicit portfolio data.

The reconciled snapshot also carries integer-paise day and week P&L. New admission
fails closed when daily loss, weekly loss, or high-water-mark drawdown reaches its
configured threshold. Drawdown thresholds are integer basis points, avoiding
binary floating-point comparisons. Strategy sizing uses marked equity rather than
reconstructing equity from cash and position notional.

The account snapshot identity is also a SHA-256 content address, not a caller
label. It covers every cash, equity, P&L, position quantity/notional/stop-risk,
included-reservation, reconciliation, and capture-time field. Position and
reservation collections are canonically ordered. Changing any material value
therefore produces a new snapshot identity and invalidates an intent pinned to the
old truth.

Admission and reservation are one journal append guarded by the risk stream's
expected version. Concurrent writers therefore cannot both consume the same view
of capacity. Exact intent retries return the same reservation. Reusing a journal
idempotency identity with different content fails closed.

Fill quantity is cumulative and may only increase. A partial fill keeps the
unfilled amount reserved. Releasing the remainder after a partial fill leaves the
filled exposure encumbered until a later reconciled broker snapshot explicitly
includes that reservation. This prevents a lagging snapshot from silently freeing
capital or a position slot.

Reservation release cannot be requested with a reservation ID and timestamp
alone. It requires the exact Operational Journal event for a completed typed
`CANCEL_ENTRY`. Portfolio Risk verifies that the command was durably prepared
first, accepted, causally linked, belongs to the same intent, and covers the
outstanding remainder. The evidence identity is retained on `RiskReleased`.

## Latched safety control

Safety latches are durable and independent of strategy logic. A latch blocks every
new entry but never blocks protective orders or entry cancellation. Reset requires
an authenticated owner authorization with the `safety:reset` scope and a clean
reconciliation observed no earlier than the latch. Reset, latch reasons, and the
authorizing owner are journaled.

## Durable paper command flow

Intent acceptance only appends `TradeIntentAccepted`; it does not reserve cash or
call a gateway. `run_once` performs the side-effecting sequence:

```text
reserve capacity
  -> append typed BrokerCommandPrepared (durable outbox)
  -> execute by stable command_id at paper gateway
  -> append BrokerCommandCompleted
```

Commands are content-addressed and limited to entry, protection, and cancel-entry.
A completed command is not sent again after kernel restart. A command whose call
succeeded but whose completion append was interrupted can be retried safely only
because the gateway protocol requires idempotency by `command_id`; this is an
explicit prerequisite for any future adapter.

A positive partial fill is journaled before downstream accounting. The kernel then
installs protection for the cumulative filled quantity before it may dispatch the
next entry, and only afterward advances reservation accounting. On protection
failure, safety latches, the unfilled entry remainder is cancelled with a typed
command, and later entries remain blocked. Recovery replays any journaled
fill/protection gap first. A completed entry-command receipt also carries the
cumulative fill: if the process stops after that completion append but before the
separate fill event, restart reconstructs the fill from the receipt and installs
protection before continuing.

`TradingKernel.enforce` is the non-admission safety path and runs at the beginning
of every kernel cycle. It protects all durable fills first. When safety is latched,
it then cancels every unfilled remainder whose entry has a durable completed broker
receipt. Accepted-only or merely prepared entries are not claimed to exist at the
broker and never receive synthetic cancellation commands.

## Reconciliation and quarantine

Broker reconciliation compares held quantities to kernel-observed fills,
broker-native protective quantities, and every working broker order to a known
content-addressed client command. Unknown exposure, unknown working orders, order
content mismatches, position quantity mismatch, or under-protection appends a
quarantine fact and latches safety. Broker protections and working protective
orders include their actual stop and target prices; quantity alone is not accepted
as proof of protection, and either level differing from the typed protection
command is quarantined. A clean snapshot is also recorded, but does not
automatically reset a prior latch.

## Deliberate limits

Only `RecordingPaperGateway` is provided. There is no live gateway, broker import,
intraday leverage product, short-selling path, runtime wiring, or mutation of
legacy order/position files. Before live-capital work, broker-native idempotency,
durable protective-order semantics, exit-fill ingestion, reconciliation polling,
operations readiness, canary lifecycle evidence, and explicit owner approval must
all be implemented and verified.
