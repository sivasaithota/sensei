# TrueData trial ingestion runbook

Status: private research staging only. The output is not a governed
`MarketDataSnapshot`, cannot authorize a strategy, and must not be connected to
the scheduler or trading kernel.

## What the harness does

`sensei-truedata` creates a credential-free plan, authenticates only when a
network command runs, downloads into an owner-only directory, records one
content-hashed manifest per response, preserves every retrieval revision, resumes
verified usable work, retries error responses, and audits missing, no-data,
error, and data responses separately.

The `run` command executes three phases:

1. download the enabled NSE equity and index symbol masters;
2. discover their symbols, write the expanded immutable plan, and download or
   resume EOD bars, daily Bhavcopies, corporate actions, announcements,
   financial-result lists, and shareholding-pattern lists;
3. discover list-record IDs and retrieve available financial-statement details,
   shareholding details, and announcement attachments.

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

Create and inspect the plan without credentials or network access:

```bash
uv run sensei-truedata plan \
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

## Run and resume

Keep the Mac awake and run the complete two-phase workflow:

```bash
caffeinate -dimsu uv run sensei-truedata run \
  --segments eq in \
  --as-of 2026-08-18 \
  --eod-start 2024-08-18 \
  --corporate-start 2026-05-18 \
  --store "$SENSEI_TRUEDATA_DIR" \
  --plan-output "$SENSEI_TRUEDATA_DIR/trial-plan-expanded.json"
```

The same command is the recovery procedure after a network interruption,
process crash, token expiry, or machine restart. Verified data and explicit
no-data responses are skipped; missing, corrupt, quota, entitlement, proxy, and
other error responses are attempted again. Do not use parallel processes: the
harness intentionally stays within conservative vendor limits.

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
