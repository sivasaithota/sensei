# Governed position operations

Legacy paper positions predate durable gateway command history. The system must
not invent historical orders or receipts for them. Instead it retains each
exact paper-book version as an observation-only adoption event, verifies the
current file against that content hash, and derives a protected broker-shaped
inventory plus reconciled account snapshot from exact cash, quantity, stop,
target and current marks.

Every scheduler paper session refreshes this bridge after any fill, exit or mark
operation. A changed book therefore creates a new linked observation rather
than silently invalidating the initial migration. Missing marks, changed bytes,
invalid protection, or incomplete inventory fail closed. These snapshots carry
`LEGACY_BOOK_RECONCILIATION_ONLY`; they do not claim synthetic broker history
and remain visibly flagged as requiring gateway command history.

The local dashboard reads the append-only operational journal and displays:

- journal integrity and event count;
- the latest scheduler terminal state and halt warning;
- each canonical strategy stage and forward-shadow session count;
- legacy-position adoption and reconciliation status.

The dashboard remains read-only and local-only.
