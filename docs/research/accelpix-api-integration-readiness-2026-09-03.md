# AccelPix API integration readiness

**Research date:** 2026-09-03
**Scope:** AccelPix Market Data API, specifically NSE cash-equity master data and historical daily/EOD OHLCV for internal research.
**Source policy:** Only public, first-party AccelPix pages and its official support knowledge base were used. No credentials were accessed and no authenticated request was made.

## Executive verdict

AccelPix publishes enough information to scaffold an isolated REST downloader before access is provisioned:

- history is exposed over REST as one ticker plus a start and end date;
- dates use `yyyyMMdd`;
- EOD responses are JSON arrays containing ticker, timestamp, OHLC, volume, open interest and an EOD flag;
- a symbol/instrument master is available; and
- NSE cash equities use NSE-style ticker names, with series such as EQ/BE/BZ auto-mapped.

The downloader must **not be treated as production-ready or its output as governed evidence yet**. AccelPix's public documentation does not specify rate limits, maximum date span or response size, pagination, complete error semantics, historical delisted coverage, point-in-time symbol membership, or the actual corporate-action adjustment formula. The signed agreement must also explicitly settle local retention after trial/subscription expiry. These are activation gates, not implementation details.

For the initial five-year NSE equity capture, use the REST API rather than the Python streaming SDK. REST has a simpler historical request contract and avoids binding bulk ingestion to the SDK's connection lifecycle. The Python SDK remains useful later for streaming/live integration.

## First-party sources

1. [AccelPix REST API guide](https://support.accelpix.com/portal/en/kb/articles/pix-apis-realtime-and-historical-data-in-rest)
2. [AccelPix Python API guide](https://support.accelpix.com/portal/en/kb/articles/pix-apis-realtime-and-historical-data-in-python)
3. [AccelPix API symbol format](https://support.accelpix.com/portal/en/kb/articles/symbols-format-for-realtime-data-apis)
4. [AccelPix Pix APIs product page](https://accelpix.com/products/pix-api/)
5. [AccelPix terms and policies](https://accelpix.com/legal/)

## Documented API contract

### Authentication

The REST guide says every request uses an API token supplied as the `api_token` query parameter. The Python SDK guide initializes its client with an API key and host, and requires initialization to complete before other calls are made.

Security implications for Sensei:

- obtain the token only from the OS keychain or an injected environment variable;
- never write it to configuration, manifests, logs, exceptions, URLs in reports, or tests;
- construct requests with a query-parameter API rather than string interpolation;
- redact query strings at the HTTP logging boundary; and
- do not send a credential until AccelPix confirms an HTTPS historical endpoint. The REST guide's examples use `http://`, while its public master URLs use `https://`. Sending a bearer-like token over plain HTTP is unacceptable.

**Unknown:** token lifetime, rotation/revocation procedure, IP binding, simultaneous-session rules, authorization error body/status, and whether the supplied host differs between trial and paid access.

### Host and transport

The public guides identify `apidata.accelpix.in` as the normal host. The documented REST base path is:

```text
/api/fda/rest
```

The documented public master paths are:

```text
/api/hsd/Masters/2?fmt=json   # without lot size
/api/hsd/Masters/3?fmt=json   # with lot size
```

The product page describes REST as historical/reference/backfill over HTTP and JSON, and WebSocket as the live push channel. It says REST and WebSocket read the same underlying archive.

**Unknown:** REST timeout expectations, compression support, HTTP/2 support, regional/failover hosts, ports, service-level availability, and whether HTTPS is supported for every authenticated path.

### Instrument master

The REST API exposes `GET /api/fda/rest/master?api_token=...`; the guides also advertise the separate large master downloads above. A master row is documented with:

| Field | Meaning in official documentation |
|---|---|
| `xid` | segment ID; examples use `1` for equity and `2` for F&O |
| `tkr` | ticker used to communicate with the server |
| `atkr` | alternate/display ticker |
| `ctkr` | contract/current ticker mapping |
| `exp` | contract expiry; a Unix-epoch-like default is shown for non-expiring instruments |
| `utkr` | underlying ticker |
| `inst` | instrument type such as `EQUITY`, `FUTSTK`, `FUTIDX`, `OPTSTK`, `OPTIDX` |
| `a3tkr` | another alternate ticker |
| `sp` | strike price |
| `tk` | exchange-defined token |
| `lot` | lot size, when using the lot-size master |

For the requested initial capture, select `xid == 1` and `inst == "EQUITY"`, but retain the complete raw master response for auditability.

**Unknown:** master publication cadence, effective/as-of timestamp, inactive/delisted inclusion, stable security identifier (ISIN is not shown), historical versions, symbol-change lineage, series field, listing/delisting dates, and whether `tk` remains stable through name changes.

### NSE cash-equity symbol format

The symbol-format guide states that NSE equities and indices use NSE symbol format, and that cash-equity series EQ, BE and BZ are auto-mapped. For example, the API master and quotes examples use `TCS` directly. Symbols must be taken from the current master rather than manufactured from company names.

The guide documents derivative conventions too, but they are outside the initial NSE cash-equity scope.

**Unknown:** how a caller explicitly distinguishes two instruments with the same ticker across historical series; handling of punctuation, ampersands and renamed symbols; and how to request an inactive ticker after it disappears from the current master.

### Historical EOD request

The REST guide documents this shape:

```http
GET https://{confirmed-host}/api/fda/rest/{url-encoded-ticker}/{start:yyyyMMdd}/{end:yyyyMMdd}
    ?api_token={redacted}
```

The Python SDK equivalent is asynchronous:

```python
await api.get_eod(ticker, start_date_yyyymmdd, end_date_yyyymmdd)
```

The API is documented per ticker; no multi-symbol historical endpoint is published. The REST guide does not document pagination or a cursor.

**Unknown:** inclusivity of start/end dates, maximum range, maximum rows/bytes, empty-series behavior, holiday behavior, ordering guarantee, duplicate policy, split adjustment boundary, caching behavior, concurrency and permitted parallelism.

### EOD response schema

The REST guide shows a JSON array of records:

| Field | Observed documented meaning |
|---|---|
| `tkr` | ticker |
| `td` | bar timestamp/date as a string |
| `op` | open |
| `hp` | high |
| `lp` | low |
| `cp` | close |
| `vol` | volume |
| `oi` | open interest |
| `eod` | `true` for EOD bars |

The Python guide's EOD sample omits `tkr` and `eod`, so the normalizer must accept both documented shapes but require the requested ticker and EOD mode as capture metadata. Cash-equity `oi` should not be assumed meaningful.

The product page says timestamps are always IST and are not re-stamped on replay. The REST samples show midnight without an explicit offset, while Python samples use an ISO-like value without an offset. Treat `td` as an exchange-session date for daily bars and retain the original string.

**Unknown:** formal JSON schema, nullability, numeric bounds/types, timezone encoding, whether timestamps can include `Z` or offsets, and backward-compatibility/versioning policy.

### Adjustments and archive behavior

The product page makes these public claims:

- historical EOD is adjusted;
- corporate actions are applied across tick, one-minute and EOD resolutions;
- closed candles do not change later;
- archive gaps are backfilled; and
- for continuous derivatives, price and open interest are adjusted together.

These claims are promising, but the REST/Python guides do not identify adjustment fields or methodology. For equities, Sensei still needs written confirmation covering splits, bonuses, dividends, rights, mergers/demergers, which fields are adjusted, whether volume is adjusted, ex-date timing, rounding, revision handling, and whether both raw and adjusted series are available.

**Unknown:** the complete corporate-action adjustment algorithm and event ledger. Therefore an EOD response cannot yet be certified as reproducible adjustment evidence solely from the public documentation.

### Live connection and reconnect behavior

The Python guide describes `pix-apidata`, installed with:

```text
pip install pix-apidata
```

It uses an asynchronous API and exposes connection-started and connection-stopped callbacks. The guide says the stopped callback can fire after an automatic retry or network problem, and that the caller must manually re-establish the connection. It also warns that requesting segment snapshots can transfer enough data to disconnect a slow consumer, recommending buffering before processing.

The official change log says version 1.3.4 removed the `scheme` argument from `initialize`; the quick-start correctly shows `initialize(apiKey, apiHost)`, but the longer sample on the same page still passes a third `scheme` argument. Pin and test the provisioned SDK version rather than copying the stale long sample verbatim.

**Unknown:** reconnect attempt count, retry intervals, heartbeat behavior, resume cursor, replay gap semantics, message ordering/deduplication, backpressure limits, WebSocket port, and subscription-symbol limits.

For these reasons, streaming should not be part of the initial historical trial capture.

### REST errors and limits

The public REST guide does not publish:

- status-code semantics;
- error response schema;
- rate-limit headers or calls per second/day;
- retry-after behavior;
- concurrency limits;
- maximum symbols or date range;
- pagination/cursors; or
- idempotency/retry guidance.

Do not infer these values. During activation, make one harmless master request and one small EOD request, capture only status/headers/schema (never the token), and calibrate the downloader before launching a full capture.

## Licensing, storage and use

The API product page says personal/non-commercial use is the default; commercial use or redistribution requires a different licence. AccelPix's published Terms of Use grant a limited, non-exclusive, non-transferable and revocable licence for personal or internal-business use during the subscription term. They prohibit redistribution, retransmission, resale, sublicensing, sharing credentials, and scraping or automation outside documented APIs. They also describe the service as provided “as is” without accuracy, completeness, timeliness or uninterrupted-service warranties.

The public terms do **not clearly grant retention of downloaded historical market data after the trial/subscription ends**. They also contain broad language against copying while the product page expressly markets REST for seeding databases and research pipelines. The signed API agreement and written vendor response must resolve this apparent tension before bulk capture.

Required written confirmations:

1. Downloaded EOD data may be stored locally in an owner-only private research store.
2. It may be retained and used for the owner's internal research/backtesting after trial or subscription expiry.
3. Derived private statistics/models may be retained.
4. A private source repository will contain only code and manifests—not raw vendor data or credentials.
5. Personal automated trading using derived signals is permitted.
6. No deletion obligation applies at termination, or its exact scope/timing if one does.

Until confirmed, captured artifacts must remain private, uncommitted, unshared and quarantined from governed research/trading.

## Prepared downloader contract

The following can be implemented safely before credentials arrive.

### Capture layout

Use an owner-only store outside the repository, for example:

```text
~/.local/share/sensei/accelpix/
  raw/master/{retrieved_at}.json
  raw/eod/{ticker}/{start}_{end}.json
  manifests/requests.jsonl
  normalized/eod/year=YYYY/part-*.parquet
  reports/coverage.json
```

The repo must ignore all vendor artifacts. Directory mode should be `0700`; files should be `0600`.

### Capture sequence

1. Load a token from Keychain/environment without printing it.
2. Refuse non-HTTPS authenticated URLs unless the owner explicitly stops for vendor clarification; do not downgrade automatically.
3. Fetch and hash the master once.
4. Select NSE cash equities from recorded master fields; do not silently substitute today's Nifty membership.
5. Probe one liquid equity for five sessions and validate the schema.
6. Determine actual range/rate limits empirically with bounded probes only after access starts.
7. Generate a deterministic, resumable request plan by ticker and date chunk.
8. Save the raw response atomically before normalization.
9. Record request identity, retrieval time, HTTP status, response hash, classification and row count—never the query token.
10. Normalize to Parquet only after raw hash verification.
11. Produce coverage, first/last date, gaps, duplicates, OHLC validity and cross-source comparison reports.
12. Keep all output stamped `PRELIMINARY_VENDOR_TRIAL — NOT admissible` until lineage, licence and quality gates pass.

### Required validations

- requested ticker matches every returned `tkr` when present;
- `eod` is true when present;
- dates are parseable, unique, ascending after normalization and inside the requested range;
- `low <= min(open, close) <= max(open, close) <= high`;
- prices are positive and finite;
- volume is a non-negative integer-like value;
- no duplicate `(ticker, session_date)` rows;
- raw response hash and byte count are stable after write;
- empty arrays, JSON error objects, HTML bodies and authorization pages classify separately from valid data;
- suspicious corporate-action jumps are compared with existing bhavcopy and TrueData event evidence; and
- no result is promoted automatically into a governed catalog.

### Conservative retry policy until documented

- retry network timeouts and HTTP 5xx with exponential backoff and jitter;
- honor `Retry-After` if present;
- treat 401/403 as terminal authorization failures;
- treat 400/404 as terminal for that request pending classification;
- pause on 429 rather than increasing concurrency;
- cap attempts and persist terminal status for resumability;
- do not retry a valid empty response endlessly.

This is an internal safety policy, not a claim about AccelPix's server behavior.

## Trial activation gates

Do not ask AccelPix to start the short trial until all of these are satisfied:

- [ ] signed agreement reviewed for retention/deletion, automation, personal use and confidentiality;
- [ ] HTTPS authenticated history endpoint confirmed;
- [ ] exact trial start/end timestamps and timezone confirmed;
- [ ] NSE Equity Cash and EOD entitlements confirmed;
- [ ] five-year entitlement and maximum symbol count confirmed;
- [ ] whether the 250-symbol Pix Connect limit also applies to API history confirmed;
- [ ] rate, concurrency, date-range and response-size limits confirmed;
- [ ] inactive/delisted/renamed availability confirmed;
- [ ] corporate-action adjustment methodology supplied;
- [ ] token stored in Keychain, never shell history or repo;
- [ ] resumable plan, raw artifact store and audit command tested with fixtures;
- [ ] monitoring distinguishes data, no-data, throttling and authorization failures;
- [ ] enough disk space available, plus a private backup allowed by the agreement;
- [ ] a final immutable audit is scheduled before trial expiry.

## Questions for the API specialist

Send these as one concise technical checklist rather than discovering them during the trial:

1. What is the HTTPS base URL for authenticated REST history?
2. What are calls/second, calls/day, concurrent-request, maximum-date-range and maximum-response-size limits?
3. Is there pagination or must long ranges be date-chunked?
4. Does the five-year EOD trial cover all NSE cash-equity symbols, or only 250? Can the allowed symbol set rotate?
5. Does the master/history include inactive, delisted, renamed, merged, suspended and BE/BZ-series instruments?
6. Is there an ISIN/stable-ID and historical symbol-lineage endpoint?
7. Are returned EOD OHLC and volume adjusted? Supply the split/bonus/dividend/rights/merger/demerger methodology and revision policy.
8. Are raw and adjusted series both available?
9. What do 401, 403, 404, 429 and valid no-data responses look like?
10. May trial data be retained locally after expiry for personal internal backtesting, with no redistribution?
11. Are private backups and private derived Parquet datasets allowed?
12. Is personal automated trading from derived signals within the licence?

## Go/no-go rule

**Go for a quarantined trial capture** only after secure transport, local retention and the requested history entitlement are confirmed in writing. **No-go for paid purchase or governed backtest certification** until a coverage probe demonstrates full-universe behavior, inactive/delisted access, stable identity/lineage, and auditable corporate-action adjustments. Five years of adjusted survivor-only bars would improve convenience but would not solve Sensei's survivorship-bias requirement.
