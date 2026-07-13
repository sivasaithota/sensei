# Intraday session and deterministic replay

Status: shadow/paper foundation only. There is no live or MIS execution path.

## Scope and authority

The intraday engine owns exchange-session time, feed health latching, bar-level
entry participation, and deterministic directives. It does not own portfolio
risk, capital reservations, broker lifecycle, accounting, or strategy
promotion. Its only modes are `SHADOW` and `PAPER`.

Every input retains both `occurred_at` (exchange/event time) and `received_at`
(the time the engine could act). Session cutoffs and freshness use receipt time;
the difference must remain inside `maximum_event_latency`. The optional
`received_at=None` constructor behavior maps receipt to event time solely for
compatibility with pre-foundation fixtures. New producers must always provide
both timestamps.

## Calendar and auctions

`trading_dates` is an explicit exchange calendar. Standard boundaries include
an optional opening auction start, continuous `session_open`, last-entry time,
mandatory flatten time, optional closing auction start, and session close.
`special_sessions` maps a trading date to a complete `SessionBoundaries` value;
the engine never guesses shortened or evening-session clocks.

Opening and closing auctions are distinct states. Entering either produces a
deterministic audit directive. No entry is accepted during an auction. If event
receipt jumps directly into a closing auction, the flatten directive is emitted
before the closing-auction directive.

## Feed latch and reset

A disconnect immediately latches new entries. Reconnect changes connectivity
state but does not clear the latch. Even fresh market data after reconnect leaves
the engine halted. `FeedResetEvent` must be explicit, carry an authorization
reference, arrive within the latency budget, and follow a fresh watermark before
the latch can clear. For a reconnect, that watermark must come from a market-data
event whose `received_at` is strictly later than the reconnect's `received_at`;
a cached or pre-disconnect watermark is never reset evidence. Protective exits
and session flattening remain available while entries are halted.

Missing, stale, or over-latency data also latches entry admission. Invalid
state-dependent feed commands are rejected before their sequence is consumed,
so replay cannot inherit partial mutations from a failed event.

## Participation and replay

An `ENTER_LONG` signal must carry a positive share quantity and cite a market
watermark whose bar volume has been observed. The accepted quantity is capped at
`floor(bar_volume * maximum_participation_rate)`. The engine rejects absent
volume, absent quantity, zero capacity, or excess participation and includes the
calculated maximum in its directive.

`IntradayReplayHarness` creates a fresh engine on every run. The same ordered
events, event times, receipt times, calendar, and configuration produce equal
transitions, equal directive IDs, and the same content-derived replay ID. This
is the conformance boundary for historical replay and forward shadow/paper
operation.
