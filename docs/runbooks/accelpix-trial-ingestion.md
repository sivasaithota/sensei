# AccelPix EOD trial ingestion

This runbook captures AccelPix NSE cash-equity EOD history into an owner-only,
quarantined store. It never makes the data admissible for strategy governance
or real-capital decisions.

## Before activation

Obtain written confirmation of:

- the authenticated HTTPS REST host;
- exact trial start/end timestamps and timezone;
- NSE Equity (Cash), EOD, five-year history and permitted symbol count;
- request, concurrency, date-range and response-size limits;
- whether inactive, delisted and renamed instruments are available;
- the corporate-action adjustment methodology; and
- permission to retain downloaded data privately after access expires.

The public guide documents `apidata.accelpix.in`, but its historical examples
mix HTTP and HTTPS. Sensei deliberately permits HTTPS only.

## Secret and private store

Save the token in macOS Keychain under service `sensei-accelpix`. Do not paste
it into source code, a committed `.env`, chat, logs or shell history.

For each terminal session, load it without printing it:

```bash
export ACCELPIX_API_TOKEN="$(security find-generic-password \
  -a "$USER" -s sensei-accelpix -w)"
export SENSEI_ACCELPIX_DIR="$HOME/.local/share/sensei/accelpix"
export ACCELPIX_REQUEST_INTERVAL_SECONDS="1.0"
```

The default store is already outside the repository. Directories are mode
`0700`; artifacts, manifests, plans and Parquet files are mode `0600`.

## Prepare the symbol selection before access

The repository universe currently contains 500 symbols. If AccelPix confirms a
250-symbol historical limit, provide a reviewed CSV or newline file containing
exactly the chosen 250; do not select the first 250 alphabetically. If the
250-symbol limit applies only to live subscriptions, use the confirmed EOD
limit instead.

Prepare the reviewed symbol file now. The exact plan is generated immediately
after `capture-master`, because every selection must be checked against the
hash-verified vendor master. Plan creation itself makes no network request.

## Activation sequence

Run these steps only after the API team confirms access.

1. Probe one master request without storing vendor content:

   ```bash
   uv run sensei-accelpix probe
   ```

2. Capture and hash the full instrument master:

   ```bash
   uv run sensei-accelpix capture-master
   ```

3. Create the exact, credential-free plan:

   ```bash
   mkdir -p "$SENSEI_ACCELPIX_DIR/plans"

   uv run sensei-accelpix plan \
     --symbols /absolute/path/to/reviewed-symbols.csv \
     --master-store "$SENSEI_ACCELPIX_DIR" \
     --start 2021-09-01 \
     --end 2026-09-01 \
     --maximum-symbols 250 \
     --output "$SENSEI_ACCELPIX_DIR/plans/nse-equity-eod.json"
   ```

4. Probe one liquid equity over five sessions to verify the EOD schema:

   ```bash
   uv run sensei-accelpix probe-eod \
     --ticker TCS --start 2026-08-24 --end 2026-08-28
   ```

   Then create the exact plan as shown above. Confirm actual request limits
   before launching it.

5. Run or safely resume the reviewed full plan:

   ```bash
   uv run sensei-accelpix download \
     --plan "$SENSEI_ACCELPIX_DIR/plans/nse-equity-eod.json"
   ```

6. Verify every artifact offline:

   ```bash
   uv run sensei-accelpix audit \
     --plan "$SENSEI_ACCELPIX_DIR/plans/nse-equity-eod.json" \
     --store "$SENSEI_ACCELPIX_DIR"
   ```

7. Only after the audit reports `missing: 0`, normalize to private Parquet:

   ```bash
   uv run sensei-accelpix normalize \
     --plan "$SENSEI_ACCELPIX_DIR/plans/nse-equity-eod.json" \
     --store "$SENSEI_ACCELPIX_DIR" \
     --output "$SENSEI_ACCELPIX_DIR/normalized/nse-equity-eod.parquet"
   ```

Commands output status, counts and probe session dates only. Raw payloads and API tokens are
never printed.

## Targeted stock-repair probe

Access was still pending on 6 September 2026. These commands are prepared for
activation; they have not been run against AccelPix. After the activation
checks above, test the four sessions missing from the current stock corpus:

```bash
uv run sensei-accelpix probe-eod --ticker TCS \
  --start 2024-01-19 --end 2024-01-23 --required-session 2024-01-20
uv run sensei-accelpix probe-eod --ticker TCS \
  --start 2024-03-01 --end 2024-03-04 --required-session 2024-03-02
uv run sensei-accelpix probe-eod --ticker TCS \
  --start 2024-05-17 --end 2024-05-21 --required-session 2024-05-18
uv run sensei-accelpix probe-eod --ticker TCS \
  --start 2026-01-30 --end 2026-02-02 --required-session 2026-02-01
```

A valid response containing only neighbors returns
`REQUIRED_SESSIONS_MISSING`, names the missing dates and exits with code 2.
`REQUIRED_SESSIONS_PRESENT` establishes date coverage for that probe only;
`adjustment_factors_verified` and `admissible` remain false. Repeat
`--required-session` to require multiple dates in one bounded window.

The [repair audit](../research/stock-calendar-repair-results-2026-09-06.md)
also found neighboring factor discrepancies for BALKRISIND, BPCL, IDEA and
LTFOODS around 2026-02-01. Check these exact tickers against the captured
vendor master, then use the February command above for each confirmed ticker.
Probe responses are not stored; capture approved responses through the normal
plan/download flow before using them as repair evidence. Reconcile adjustment
methodology and dated factors against verified raw NSE bars before insertion.

Once the dataset passes the existing audits, rerun the frozen ₹300,000 swing
baseline and report its benchmark-relative outcome. The next strategy campaign
is the bounded relative-strength comparison in the
[strategy evidence review](../research/stock-strategy-evidence-2026-09-06.md),
with its rules frozen before evaluating returns. No new performance test or
live activation follows merely from a successful provider probe.

## Fail-closed behavior

- HTTP authentication failures are terminal, not endlessly retried.
- Only transient throttling/server failures receive bounded retries.
- Terminal failures are checkpointed without response bodies; audits report
  their count separately from missing and verified requests.
- HTTP 200 HTML pages and JSON error objects are rejected rather than stored as
  valid data.
- Existing payloads are skipped only after their SHA-256 hashes verify.
- Normalization rejects mismatched symbols, non-EOD rows, dates outside the
  request, duplicate sessions, invalid OHLC and negative volume/open interest.
- Raw data, normalized Parquet and manifests remain stamped
  `PRELIMINARY_ACCELPIX_VENDOR_DATA` and are never promoted automatically.

## Post-capture acceptance

Before using the dataset even for preliminary research, produce a coverage
report for first/last date, missing sessions, duplicates and per-symbol row
counts; compare overlapping closes with NSE bhavcopy; measure inactive/delisted
coverage; and reconcile large jumps with a corporate-action ledger. A clean
download alone does not prove survivorship-safe or adjustment-reproducible
history.

The detailed documentation review is in
`docs/research/accelpix-api-integration-readiness-2026-09-03.md`.
