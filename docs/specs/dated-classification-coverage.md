# Dated classification coverage check

Build a research-only metadata checker over explicit observed symbol/series/ISIN
tuples. Retain every supplied observation. The parser's broad equity label, names,
ISIN prefixes, STK type or board lot must not imply ordinary-stock eligibility.

Caller-transcribed facts carry exact identity tuples, inclusive effective dates,
first-known session, explicit security subtype, board and source SHA-256. The pure
checker validates structure, not source content. Only effective facts known by the
requested as-of date may resolve an observation. Do not forward fill past the
supplied interval or resolve an ISIN mismatch from the symbol alone. Overlapping
known facts or duplicate observed identities reject rather than pick one.

Keep separate statuses for missing dated evidence, unknown subtype, unknown board,
and incomplete observed identity (for example an empty series in a raw debt row),
confirmed main-board ordinary shares, confirmed SME shares and confirmed nonordinary
securities. Later knowledge cannot resolve an earlier gap. Future valid facts must
not change an earlier result. Malformed evidence rejects even when not yet effective.
Output ordering is deterministic. Complete classification coverage alone never
sets admissible or can_trade true: tradability, stable identity, complete universe,
source content/vintage, action accounting and liquidity remain separate obligations.

Apply the checker to all observed tuples in two pinned endpoint bhavcopies,
January 1, 2024 and September 3, 2026, with an explicitly empty classification input.
This produces an honest initial gap report while the historical security-master
sample remains inaccessible. These are end-of-session observation checks, not
opening decisions or a reconstruction of every listed security. Hash-check each
raw receipt against the frozen parent. Do not repeat all-market price diagnostics,
construct a guessed master schema, or output eligibility intervals.
