# Stock data verification — 6 September 2026

The current 500 Yahoo files are **not yet an admissible historical Nifty 500 universe**. Official evidence confirms a concrete coverage problem, while one corporate-action check passes. This is a data-readiness finding, not a strategy-performance verdict.

The requested evaluation period is 2024-01-01 through 2026-09-04 with 252 prior sessions. The separately retrieved official Nifty 500 TRI calendar puts that warmup boundary at **2022-12-23**. Local stock files end on **2026-09-03 for 499 symbols**, and **2026-07-23 for JBCHEPHARM**. Therefore a development run ending September 3 still needs an explicit missing-bar policy; it must not silently discard JBCHEPHARM.

## Evidence actually retrieved

Raw downloads and computed checks are in `data/research/source-verification/`. The JSON includes file hashes, exact source URLs, counts, symbol lists and the corporate-action comparison. No prices or universe files were changed.

| Artifact | Observed contents | What it establishes |
|---|---|---|
| `IndexInclExcl.xls` | 820,736 bytes; Nifty 500 sheet has 2,495 dated events, 1998-01-08 through 2020-09-14 | A real official archive exists, but this particular file does not cover the required period. |
| `ind_nifty500list.csv` | 501 unique symbols, including DUMMYHEG | A current download, not an effective-dated historical baseline. |
| `source-checks-20260906.json` | Local coverage comparison and a hash-verified BSE bonus spot-check | Reproducible observations; explicitly `admissible: false`. |

The workbook and CSV were downloaded successfully from the official [NSE inclusion/exclusion archive](https://archives.nseindia.com/content/indices/IndexInclExcl.xls) and [NSE constituent CSV](https://archives.nseindia.com/content/indices/ind_nifty500list.csv). Direct downloads from the Nifty Indices host and the bulk NSE corporate-actions endpoint timed out in this session. Relevant official PDFs remained readable through the web tool; they were inspected but not downloaded as local binaries.

## Historical membership: specific missing evidence

The February 28, 2024 announcement initially listed 34 Nifty 500 exclusions effective March 28. **32 of those historical symbols have no same-symbol local price file**; only PFIZER and ZYDUSWELL are present. Missing examples include AARTIDRUGS, BCG, DELTACORP, GRINFRA, GALAXYSURF, RAIN and VGUARD. The full list is in the JSON. This comparison is at symbol level: renames and mergers require security-identity mapping before asserting entity-level absence. [Official February announcement, Nifty 500 section, pages 2–4](https://www.niftyindices.com/Press_Release/ind_prs28022024.pdf).

A subsequent March 19 announcement **revoked IREDA's inclusion and VGUARD's exclusion**. Consequently, the initial 34-name announcement must not be loaded as the final effective change list. This is a concrete reason to preserve publication date, effective date and correction precedence. [Official correction](https://www.niftyindices.com/Press_Release/ind_prs19032024.pdf).

The new CSV differs from local files: PFOCUS and DUMMYHEG are absent locally, while JBCHEPHARM is local-only. DUMMYHEG is officially a zero-price demerger placeholder for HEG Graphite, effective **September 7, 2026, after the September 4 close**. It must not become a tradable stock or historical September 3 member merely because it appears in a file downloaded today. [Official HEG adjustment](https://www.niftyindices.com/Press_Release/ind_prs03092026.pdf).

The published reconstitution calendar provides March/September reviews and allows additional changes for events such as delistings and schemes of arrangement. Two semiannual snapshots alone therefore do not prove daily membership. [Official calendar](https://www.niftyindices.com/resources/index-rebalancing-schedule).

## Corporate action: BSE bonus check

BSE's filing confirms a **2:1 bonus**, with May 23, 2025 as record date. The exchange corporate-action listing identifies May 23 as ex-date. [BSE filing on NSE](https://nsearchives.nseindia.com/corporate/BSE1_26052025095238_NSEintimation.pdf), [NSE action listing](https://www.nseindia.com/companies-listing/corporate-filings-actions?symbol=BSE&tabIndex=equity).

Existing raw NSE bhavcopies for May 22 and 23 passed the repository's ZIP/CSV/parquet/manifest integrity checks through `QuarantinedRawBhavcopy.verified_session`. Those checks verify the local artifact chain, not independent external authenticity or admission for trading.

| Session | Raw NSE close | Local adjusted close | Raw volume | Local volume |
|---|---:|---:|---:|---:|
| 2025-05-22 | 6,996.50 | 2,326.038818 | 5,026,831 | 15,080,493 |
| 2025-05-23 | 2,448.00 | 2,441.567627 | 16,556,320 | 16,556,320 |

The adjusted/raw price factor changes by **2.99999979**, and pre-event volume is exactly three times raw volume. This is consistent with the bonus transformation across this event. The remaining non-unit price factor is not independently explained by this check; the full dividend-adjustment chain remains unverified. Source bhavcopy URLs and hashes are retained in the JSON.

Do not infer full corporate-action correctness from this sample. Each security still needs dated split/bonus/dividend events, demerger distributions, symbol/ISIN lineage and comparable raw-price evidence. The current store retains adjusted OHLCV and synthesized turnover, not a complete action ledger or raw/adjusted pair.

## Next admissibility work

1. Acquire a dated baseline at or before 2022-12-23 and all effective membership changes through the chosen end date, including ad hoc changes and superseding announcements. Map symbols to stable security identities; obtain price history for former members. A reconstructed ledger must reconcile against independently dated official snapshots.
2. Reconcile corporate actions against raw bars, initially covering every held security and then the complete candidate universe. Define treatment of cash dividends, demerger entitlements, suspensions and delistings in the portfolio ledger before certifying results.
3. Record each missing session and stale symbol explicitly. A September 3 endpoint is a declared development scope, not permission to silently remove missing stocks.
4. Keep current results marked development-only until membership and adjustments pass. This research history has already been inspected and cannot be relabeled untouched holdout data.

NSE Indices explicitly offers historical security/index information and end-of-day constituent subscriptions. If the public archive cannot establish completeness, request the dated baseline, full change history, ISIN mapping and corporate-action coverage from the official supplier or a licensed vendor. No subscription was purchased and no message was sent. [Official data subscription offering](https://www.niftyindices.com/offerings/data-subscription).

## Calendar mismatch found by the frozen run

The first benchmark-aligned run exposed four genuine exchange sessions missing from **all 500 adjusted stock files**, plus rows on four official trading holidays. These are data defects, not a reason to change the benchmark calendar. `calendar-checks-20260906.json` records counts, TCS samples, source URLs and verified raw-artifact references.

All four missing days **already exist in the quarantined NSE bhavcopy corpus**. Each passed the repository's full local integrity check; no replacement download or price-file write was needed.

| Missing session | Clean equity rows in verified raw snapshot | TCS raw close | TCS volume | Official session evidence |
|---|---:|---:|---:|---|
| 2024-01-20 | 2,114 | 3,860.65 | 516,477 | [MSD60340](https://nsearchives.nseindia.com/content/circulars/MSD60340.pdf) |
| 2024-03-02 | 2,129 | 4,107.10 | 65,057 | [MSD60677](https://nsearchives.nseindia.com/content/circulars/MSD60677.pdf) |
| 2024-05-18 | 2,155 | 3,851.45 | 91,066 | [MSD61893](https://nsearchives.nseindia.com/content/circulars/MSD61893.pdf) |
| 2026-02-01 | 2,541 | 3,186.90 | 3,012,937 | [CMTR72349](https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf) |

January 20 ultimately used regular market timings: the January 19 circular withdrew earlier disaster-recovery-session instructions. March 2 and May 18 were live sessions with a switch to the disaster-recovery site. February 1, 2026 was the Sunday Union Budget trading session. A weekday-only calendar therefore cannot represent these sessions. These exchange circulars establish trading status; settlement holidays are a separate concept.

The four extra dates are trading holidays: January 15 was added for municipal elections by [CMTR72260](https://nsearchives.nseindia.com/content/circulars/CMTR72260.pdf); May 1, May 28 and June 26 appear in the original [2026 Capital Market holiday circular](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf).

| Holiday | Local files containing a row | Zero-volume rows | Flat OHLC rows |
|---|---:|---:|---:|
| 2026-01-15 | 457 | 457 | 457 |
| 2026-05-01 | 463 | 463 | 463 |
| 2026-05-28 | 498 | 498 | 498 |
| 2026-06-26 | 499 | 499 | 499 |

The next repair can remove these specifically verified non-trading dates from a **new versioned research snapshot**, retaining the original files and an exclusion manifest. Filling the four missing sessions requires converting real raw bars into the same verified adjustment convention as the surrounding history, with valid identity and corporate-action factors. Do not insert raw prices directly into adjusted series, estimate bars, forward-fill missing sessions, or discard those dates from the benchmark. The verified raw snapshots provide repair inputs; they do not by themselves complete the adjustment work.
