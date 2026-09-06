# Adjustment repair evidence — 6 September 2026

**A fresh Yahoo download does not recover the four missing exchange sessions for TCS.** Four bounded history calls and four direct chart responses all succeeded, but none contained the target date. Consequently this probe supplies **zero directly observed adjustment factors for those dates**. Existing prices were not overwritten and no adjusted bars were manufactured.

## Provider probe

One symbol, `TCS.NS`, was requested in four nine-calendar-day windows. Installed yfinance version: `1.5.1`. Settings: `auto_adjust=False`, `actions=True`, `repair=False`; end dates are exclusive. The responses retain `Close`, `Adj Close`, OHLC, volume, dividends and splits. Four additional requests to the same [Yahoo chart data endpoint](https://query1.finance.yahoo.com/v8/finance/chart/TCS.NS) preserved original JSON with timestamps and event payloads. Every direct response returned HTTP 200.

| Missing NSE session | Request start | End exclusive | Returned bars | Target present |
|---|---|---|---:|---|
| 2024-01-20 | 2024-01-16 | 2024-01-25 | 6 | No |
| 2024-03-02 | 2024-02-27 | 2024-03-07 | 7 | No |
| 2024-05-18 | 2024-05-14 | 2024-05-23 | 6 | No |
| 2026-02-01 | 2026-01-28 | 2026-02-06 | 7 | No |

Files are under `data/research/adjustment-checks/`: four decoded CSVs, four original chart JSON responses, `yahoo-probe-manifest.json`, `yahoo-chart-manifest.json` and `tcs-neighbor-factors.json`. Manifests preserve request parameters, retrieval time and SHA-256 hashes. This is eight bounded requests for one stock, not a bulk replacement feed.

Because the direct JSON itself omits these dates, the missing TCS rows in this probe are not caused solely by a local dataframe-cleaning step. The probe cannot establish the same provider behavior for every other symbol.

## What neighboring factors do and do not establish

The installed yfinance `auto_adjust` implementation multiplies open/high/low by `Adj Close / Close` and uses adjusted close as close. It does not invent a missing session. Source inspected locally: `.venv/lib/python3.12/site-packages/yfinance/utils.py`, function `auto_adjust`, lines 497–514.

For TCS, immediately neighboring observed factors differ by less than 0.11 parts per million:

| Missing session | Prior observed session | Next observed session | Prior factor | Next factor |
|---|---|---|---:|---:|
| 2024-01-20 | 2024-01-19 | 2024-01-23 | 0.9202194724 | 0.9202195326 |
| 2024-03-02 | 2024-03-01 | 2024-03-04 | 0.9202194716 | 0.9202194352 |
| 2024-05-18 | 2024-05-17 | 2024-05-21 | 0.9269077716 | 0.9269076754 |
| 2026-02-01 | 2026-01-30 | 2026-02-02 | 0.9812422248 | 0.9812422426 |

These are diagnostic consistency observations, not directly observed factors on the missing dates. They do not prove a complete corporate-action history, absence of offsetting events, correct volume adjustment or stable security identity. No target-date factor was approved from this comparison.

The repository already has integrity-verified, quarantined raw NSE bhavcopies for all four missing dates. Those are usable repair inputs once the adjustment convention and dated factors are established. See `source-verification/calendar-checks-20260906.json` and the [calendar diagnosis](stock-data-admissibility-next-actions-2026-09-06.md).

## Corporate-action evidence

The original Yahoo JSON exposes a TCS dividend of ₹27 on January 19, 2024 and ₹28 on May 16, 2024 in the sampled windows. TCS's own dividend history lists January 19 record-date components of ₹9 interim and ₹18 special, and a ₹28 final dividend with May 16 record date. This corroborates those nearby amounts and dates; record date must still be distinguished from exchange ex-date. [TCS dividend history](https://www.tcs.com/investor-relations/dividend-payment-details).

The TCS issuer dividend list does not identify a dividend record date on any of the four missing sessions. This narrow observation does **not** establish that all 500 stocks had no ex-date action on those days. Likewise, an empty Yahoo event object for a sampled window cannot certify an exchange-wide absence of corporate actions.

A date-filtered attempt to read the NSE corporate-actions API for January 20 through the web tool was unavailable. Earlier direct bulk API attempts timed out. No complete official date-filtered action export was retrieved for the four sessions, so the action-coverage status remains **unverified**, not “zero actions.” The relevant official interface is [NSE Corporate Actions](https://www.nseindia.com/companies-listing/corporate-filings-actions?tabIndex=equity).

## Concrete next repair boundary

1. Keep the four verified holiday exclusions separate from this adjustment problem; holiday removal needs no guessed price.
2. For each missing stock/session, establish identity and an effective-dated price/volume adjustment factor from a source that covers that exact session, or reconstruct it from a complete verified corporate-action chain under a declared convention.
3. Apply those factors to the existing verified raw bars in a new versioned snapshot, recording input hashes and repair provenance. Validate OHLC coherence, raw-volume lineage and continuity with surrounding adjusted bars.
4. Until that evidence exists, preserve the missing-session failure. Do not forward-fill prices, multiply raw bars by an unapproved neighbor factor, or drop real exchange sessions from the benchmark to force a result.

This probe rules out one simple repair route for TCS: repeating the same Yahoo daily download with adjustment disabled does not produce the missing bars. It does not authorize a new historical performance verdict.
