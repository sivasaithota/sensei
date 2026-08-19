# TrueData trial ingestion runbook

Status: private research staging only. The output is not a governed
`MarketDataSnapshot`, cannot authorize a strategy, and must not be connected to
the scheduler or trading kernel.

## What the harness does

`sensei-truedata` creates a credential-free capability-specific plan, authenticates only when a
network command runs, downloads into an owner-only directory, records one
content-hashed manifest per response, preserves every retrieval revision, resumes
verified usable work, retries error responses, and audits missing, no-data,
error, and data responses separately.

The separate `record-announcements` command connects to the confirmed corporate
WebSocket, validates each JSON object, deduplicates replays by announcement ID
and content hash, preserves changed revisions, and reconnects with bounded
backoff. Its credential-bearing connection URL exists only in process memory;
stored manifests contain only `wss://corp.truedata.in:9092`.

The activation dated 2026-08-18 explicitly confirms only Corporate/Fundamental
data. Therefore `plan` and `run` default to `--capabilities corporate`. Market
history and symbol-master traffic remains disabled unless its bounded entitlement
probe succeeds and those capabilities are selected explicitly.

For a fully entitled run, the command executes three phases:

1. download the enabled NSE equity and index symbol masters and symbol-change history;
2. discover their symbols, write the expanded immutable plan, and download or
   resume EOD bars, daily Bhavcopies, corporate actions,
   financial-result lists, and shareholding-pattern lists;
3. discover list-record IDs and retrieve available financial-statement details,
   shareholding details, and announcement attachments.

For financial results and shareholding, the capture uses the vendor's
comprehensive `All...ById` endpoints. It does not repeat the same record through
every convenience projection (P&L, balance-sheet, summary and detail), which
would multiply the trial by roughly five without adding source items.

The plan follows the vendor's trial limits: two years of EOD requests and one
quarter of corporate requests by default. API responses remain quarantined even
when their hashes verify because historical index membership and final
adjustment lineage are not supplied by the trial.

## Before trial activation

Prepare an owner-only store outside Git:

```bash
mkdir -p "$HOME/.local/share/sensei/truedata"
chmod 700 "$HOME/.local/share/sensei/truedata"
```

Create and inspect the confirmed corporate-only plan without credentials or network access:

```bash
uv run sensei-truedata plan \
  --capabilities corporate \
  --segments eq in \
  --as-of 2026-08-18 \
  --eod-start 2024-08-18 \
  --corporate-start 2026-05-18 \
  --output "$HOME/.local/share/sensei/truedata/trial-plan-bootstrap.json"
```

Never place credentials in a command, configuration file, Git, shell history,
or support ticket. Export them only into the terminal session that runs the
trial:

```bash
export TRUEDATA_USERNAME='provided-user-id'
read -s "TRUEDATA_PASSWORD?TrueData password: "
echo
export TRUEDATA_PASSWORD
export SENSEI_TRUEDATA_DIR="$HOME/.local/share/sensei/truedata"
```

Ask the vendor to activate the trial only after the plan command and local tests
pass. Then test authentication without downloading market data:

```bash
uv run sensei-truedata probe
```

Then run bounded, non-persistent entitlement probes. `no_data` still proves that
the endpoint is accessible; quota, subscription, authentication and malformed
responses do not:

```bash
uv run sensei-truedata entitlements \
  --as-of 2026-08-18 \
  --required corporate
```

## Run and resume

Keep the Mac awake and run the complete two-phase workflow:

```bash
caffeinate -dimsu uv run sensei-truedata run \
  --capabilities corporate \
  --segments eq in \
  --as-of 2026-08-18 \
  --eod-start 2024-08-18 \
  --corporate-start 2026-05-18 \
  --store "$SENSEI_TRUEDATA_DIR" \
  --plan-output "$SENSEI_TRUEDATA_DIR/trial-plan-expanded.json"
```

The `run` command repeats the entitlement probe before downloading and refuses
to start if any selected capability is unavailable. The same command is the
recovery procedure after a network interruption,
process crash, token expiry, or machine restart. Verified data and explicit
no-data responses are skipped; missing, corrupt, quota, entitlement, proxy, and
other error responses are attempted again. Do not use parallel processes: the
harness intentionally stays within conservative vendor limits.

Run the real-time announcement recorder in a second terminal for the trial
window. It does not consume the REST request quota:

```bash
caffeinate -dimsu uv run sensei-truedata record-announcements \
  --store "$SENSEI_TRUEDATA_DIR" \
  --duration-seconds 259200
```

The recorder is safe to restart. Identical replayed messages are skipped and a
changed payload for an existing announcement ID is retained as a new revision.
Connection failures are counted rather than printed because vendor exceptions
may reproduce the credential-bearing WebSocket URL.

Audit locally without credentials or network access:

```bash
uv run sensei-truedata audit \
  --plan "$SENSEI_TRUEDATA_DIR/trial-plan-expanded.json" \
  --store "$SENSEI_TRUEDATA_DIR"
```

Only `VERIFIED_DATA` exits successfully. `INCOMPLETE`, `ERROR_RESPONSES`, and
`COVERAGE_GAPS` are fail-closed outcomes. Inspect the separate `missing`,
`no_data`, and `error` counts. The audit also reports EOD request/data counts,
row totals, earliest/latest observed dates, and duplicate dates. Delisted
instruments may legitimately return no data outside their listing period;
entitlement and quota responses are errors and must not count as coverage.

These diagnostics describe what the trial actually returned; they do not infer
exchange holidays, historical index membership, symbol-effective dates, or
corporate-action correctness. Those remain promotion blockers, not assumptions.

## Confidentiality and promotion boundary

- Keep the store, manifests, plans, vendor documentation, and credentials private.
- Do not include raw vendor rows in public UI, logs, reports, issues, or PRs.
- Never commit downloaded responses, even though this repository is private;
  the external store prevents accidental history growth and later exposure.
- Preserve the vendor's written permission for local download and retention.
- A separate materializer must add stable identity, effective-dated universe
  membership, corporate-action lineage, licensed provenance, and catalog trust
pins before any artifact can participate in governed research.

## Optional market-history run

Only if `entitlements` reports both `history` and `master` accessible, use:

```bash
caffeinate -dimsu uv run sensei-truedata run \
  --capabilities corporate history master \
  --segments eq in \
  --as-of 2026-08-18 \
  --eod-start 2024-08-18 \
  --corporate-start 2026-05-18 \
  --store "$SENSEI_TRUEDATA_DIR" \
  --plan-output "$SENSEI_TRUEDATA_DIR/trial-plan-full.json"
```

Do not infer market access from WebSocket port `9092`: that port is the corporate
announcement feed. Market-price WebSocket access uses a separately entitled
`push.truedata.in` port and is outside this bulk REST capture workflow.

The legacy historical announcement-range endpoint returned HTTP 404 for every
trial date and is absent from the latest official Postman collection, so it is
not part of the default REST plan. The `record-announcements` command captures
new announcements from the confirmed corporate WebSocket feed; it does not
manufacture historical coverage for announcements emitted before it started.

## Vendor and harness hazards observed in the 2026-08-19 capture

### `getMarketCap` fails a whole batch for one unknown symbol

`getMarketCap` rejects the **entire** request when any single symbol is unknown to
TrueData, and reports it as:

```
"IP Address mismatch. Need to request data from same IP where token was generated"
```

The message is misleading. It is **not** an IP/auth problem and **not** a
batch-size limit — larger batches simply had a higher chance of containing one
bad symbol, which makes it look size-dependent. Bisecting a failing batch to
single symbols identifies the culprits.

Consequence: 39 symbols are permanently unresolvable in this vendor scope, and
they block 30 otherwise-valid batch requests. Those requests are unfillable, not
transient, and must not be retried. The set is recorded privately in
`marketcap-unresolvable.json` in the artifact store. Exclude those symbols and
batches succeed.

### Vendor content types are unreliable

TrueData serves CSV payloads with `Content-Type: text/html`, and returns some
errors as a bare JSON **string**. `_response_class` therefore cannot trust the
declared type: it sniffs content, treats a bare JSON scalar as an error, and
classifies a header-only CSV as `no_data` rather than `error`.

### Misclassification is sticky, and the audit will look green

The store never revisits an artifact once written, so a wrong `response_class`
persists: an error body stored as `data` is skipped by every later run while the
audit reports `error: 0`. Fixing the classifier does **not** heal already-stored
artifacts — they must be purged by content scan and re-fetched. Before this store
feeds anything downstream, stored classifications should be re-validated rather
than trusted on first write.

### Only `corporate` is entitled

Bounded probes on 2026-08-19 confirmed `corporate` accessible; `history` (price
REST) and `master` (symbol master) both inaccessible. `getCorpAction`,
`getCorpActionRange`, `getSymbolNameChange`, `getCorporateInfo`,
`getQuarterlyReports` and `getAnnoucementsForCompanies` return HTTP 404 under
this trial. Announcement PDFs are available from TrueData via
`getAnnouncementFile?id=`; the `ATTACHMENTURL` field points at bseindia.com and
should not be scraped.
