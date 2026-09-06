# Kite stock-history acquisition

Owner-funded Connect data access is used through official read-only APIs.
The archive is separate from trading state and the existing Yahoo price files.
Data remains quarantined until calendar, adjustments and historical membership
are independently validated.

## Local authentication

Configure the developer app redirect as `http://127.0.0.1:8000`. Run locally:

```bash
.venv/bin/python -m sensei.data.kite_auth configure
.venv/bin/python -m sensei.data.kite_auth login
```

The first command accepts hidden API key/secret input and writes macOS Keychain
items named `sensei-kite-api-key` and `sensei-kite-api-secret`, account `sensei`.
It passes secrets to the Keychain command over stdin rather than arguments.
The second opens the normal Kite login page, receives a state-checked loopback
callback and stores `sensei-kite-access-token`. No order operation is implemented.
The setup runs on the Mac where the browser completes login. Port 8000 must be
available. Access tokens expire separately from the paid subscription; use
`login` again when authentication expires. [Kite authentication](https://kite.trade/docs/connect/v3/user/).

## Capture and resume

```bash
.venv/bin/python -m sensei.data.kite_history capture \
  --start 1996-01-01 --end 2026-09-04
```

The default private store is `~/.local/share/sensei/kite`. The current capture
uses the two reference CSVs and hash receipts saved under `reference/` on
6 September: `20260906-EQUITY_L.csv` and `20260906-SME_EQUITY_L.csv`.
They were retrieved from the official downloads linked on
[NSE securities available for trading](https://www.nseindia.com/static/market-data/securities-available-for-trading).
Future captures can supply different verified files using `--equity-reference`
and `--sme-reference`; the command does not scrape these pages automatically.

The frozen plan includes the vendor master hash, reference bytes/hashes,
symbol/series matches, unmatched exchange names, excluded master records and
exact date windows. EQ, BE, BZ, SM and ST aliases are considered during matching;
that acquisition mapping is not proof of historical identifier continuity.
Current equity and SME membership is never presented as historical membership.

The command prints its exact plan path before acquisition. Nine cached or newly
captured probes check the four missing sessions, BSE's bonus date and the four
February discrepancy symbols. Passing means date coverage only. Every bulk
entry path repeats these checks against the same verified master.

One process holds the store lock. Requests are spaced at least 0.55 seconds
apart, below Kite's 3 historical requests/second. Windows contain no more than
2,000 calendar dates. The 2022+ window comes first, with existing research
symbols prioritized; older windows follow. Timeouts and 5xx get bounded retries;
authentication/entitlement failures and 429 stop the capture.

If interrupted, resume with the printed plan path:

```bash
.venv/bin/python -m sensei.data.kite_history download --plan /absolute/path/to/plan.json
.venv/bin/python -m sensei.data.kite_history audit --plan /absolute/path/to/plan.json
.venv/bin/python -m sensei.data.kite_history normalize --plan /absolute/path/to/plan.json
```

Do not recreate the plan from a new day's master to resume an old acquisition.
Raw bytes and manifests publish atomically; completed responses are hash- and
schema-verified before reuse, including empty windows. A verified empty response
means the provider returned no data for that window, not that no earlier history
exists. A corrupted artifact stops the run for inspection.

Normalization writes per-instrument-token Parquet files plus symbol mappings,
raw-input hashes, first/last dates and special-session gaps under
`normalized/<plan ID>/`. It requires every planned request. Tokens are output
filenames, not permanent security identifiers. Do not point the existing
symbol-filename research runner at this directory without an explicit mapping.

API access, file completeness, calendar coverage, adjustment accuracy and
economic strategy readiness are distinct results. No capture or normalization
grants live authority. Ordinary cash dividends and complex actions need explicit
accounting; Kite-adjusted prices must not be silently mixed with Yahoo's series.
See the [capture contract](../research/kite-capture-contract-2026-09-06.md).
