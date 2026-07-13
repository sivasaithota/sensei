# Read-only legacy migration and operational reporting

Status: implemented compatibility boundary. Imported history has no lifecycle,
risk, or trading authority.

## Migration contract

`LegacyImporter` accepts only a caller-supplied `LegacyImportManifest`. There is
no default path to the live `data/` directory. Each source is read once as bytes;
the importer never opens, rewrites, renames, or annotates a legacy file.

Every source and record receives a SHA-256 fingerprint. When a complete thesis
object is present, the canonical thesis content receives its own fingerprint.
The old thesis ID is retained only as a legacy label: two different thesis
objects that reuse an ID remain two different facts. References that contain an
ID but no thesis body are explicitly marked as missing thesis content rather
than being joined by ID.

The importer understands audit JSONL, standalone submissions, pending approval
records, paper position snapshots, paper closed-trade JSONL, and legacy mistake
ledger JSONL. Missing, empty, and unparseable sources become explicit facts;
they are not silently discarded. Every `LegacyFactImported` event declares:

- `authority: HISTORICAL_FACT_ONLY`
- `can_authorize_lifecycle: false`
- `can_authorize_trading: false`
- evidence status and the exact missing evidence categories

The content-derived idempotency key makes repeated imports no-ops even when the
second import happens later. A changed source produces new historical facts and
does not overwrite the first capture.

## Operational report contract

`OperationalReporter.daily` and `.weekly` use caller-selected local calendar
boundaries and event occurrence time. Weekly reports cover Monday 00:00 through
the following Monday 00:00. The projection includes:

- episodes started;
- lifecycle transitions;
- risk events;
- operational/safety/drift alerts;
- hypotheses proposed or registered;
- durable kernel commands prepared;
- a full event-type breakdown; and
- whole-journal hash-chain verification.

P&L is deliberately narrower than general event reporting. Only an explicit
`OutcomeAttributed` event with a finite decimal `realized_net_pnl`, currency,
episode identity, evidence references, and `reconciles: true` contributes to a
total. A P&L-looking field in a legacy fact, episode closure, broker receipt, or
arbitrary event is ignored. Currencies are never combined. If journal integrity
fails, accounting totals are withheld while diagnostic counts and integrity
errors remain visible.
