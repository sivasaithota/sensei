# Nifty 500 membership: evidence coverage and acquisition sequence

Research date: 7 September 2026. Target evaluation: 1 January 2024 through 4 September 2026. This bounded review covers membership evidence only; it does not repeat holding-price checks or evaluate strategies.

## Current verdict

**No complete, versioned membership history for the target period was found in the inspected local research artifacts, configs, or Sensei data store.** The 499-security Kite development selection is a current-matched price universe, not historical Nifty 500 membership. Official public review notices are available, but a dated starting constituent list and a reconciled register of all intervening changes are still missing.

The [point-in-time catalog spec](../specs/point-in-time-market-data.md) requires stable instrument identity, inclusive-start/exclusive-end membership intervals, retained removed constituents, and entry eligibility on the execution session. A complete history cannot be manufactured by assigning today's symbols a 2024 start date.

## Existing local evidence

| Artifact inspected | Observed coverage | Remaining limitation |
|---|---|---|
| `data/research/source-verification/IndexInclExcl.xls` | Earlier recorded inspection: Nifty 500 sheet has 2,495 events, 8 January 1998–14 September 2020. Its saved SHA-256 was reverified against `source-checks-20260906.json`. | Does not cover 2024–2026. Workbook was not redecoded in this pass because this interpreter lacks `xlrd`; the range/count are explicitly the earlier saved inspection. |
| `data/research/source-verification/ind_nifty500list.csv` | Recounted 501 distinct current symbols, including DUMMYHEG; saved hash matches the source-check manifest. | No historical effective-date anchor. Current files can already contain announced future-effective changes. |
| Kite snapshot `111ffe46…b409c/kite_snapshot_manifest.json` | Recounted 499 entries in `identity.selection`; `unmapped_symbols` contains JBCHEPHARM. Selection entries map current symbols, ISINs and tokens. | No membership intervals. A missing broker match is not an index exclusion. |
| `data/research/source-verification/source-checks-20260906.json` | Explicitly inadmissible; preserves initial March 2024 exclusion list and subsequent correction. | A source audit, not a canonical membership CSV. |
| TRI benchmarks, raw bhavcopies, corporate-action captures and split-identity notes | Index levels, exchange trading records and action/identity evidence. | None establishes Nifty 500 membership by itself. |

The official origins of the existing workbook and current list are [NSE inclusion/exclusion archive](https://archives.nseindia.com/content/indices/IndexInclExcl.xls) and [NSE current constituent CSV](https://archives.nseindia.com/content/indices/ind_nifty500list.csv). Both were already captured locally; this pass did not overwrite them. File-name inventory across the local research/config/report directories and `~/.local/share/sensei` found no additional membership/constituent archive. Synthetic catalog fixtures are not market evidence.

## Concrete official sources

The [NSE Indices press-release archive](https://www.niftyindices.com/press-release) is readable through the web reader and exposes dated PDF links. One direct HTTP request to its HTML page timed out; no repeated downloads or bulk collector were attempted. The PDFs below were readable through the web reader. This is a seed list for acquisition, **not a claim that all relevant announcements were enumerated**.

| Review | Effective membership date | Primary document and required treatment |
|---|---|---|
| February 2024 | 28 March 2024, after 27 March close | [28 February announcement](https://www.niftyindices.com/Press_Release/ind_prs28022024.pdf), already inspected in the earlier source review. Must apply [19 March correction](https://www.niftyindices.com/Press_Release/ind_prs19032024.pdf): revoke IREDA inclusion and VGUARD exclusion. |
| August 2024 | 30 September 2024 | [23 August review](https://www.niftyindices.com/Press_Release/ind_prs23082024.pdf). Later September replacement/correction notices must be checked before freezing its final change set. |
| February 2025 | 28 March 2025, after 27 March close | [21 February review](https://www.niftyindices.com/Press_Release/ind_prs21022025.pdf). Later March amendments remain to be enumerated. |
| August 2025 | 30 September 2025, after 29 September close | [22 August review](https://www.niftyindices.com/Press_Release/ind_prs22082025.pdf). Preserve intervening and later corrections separately. |
| February 2026 | 30 March 2026, after 27 March close | [23 February review](https://www.niftyindices.com/Press_Release/ind_prs23022026.pdf). |
| August 2026 | 30 September 2026, after 29 September close | [10 August review](https://www.niftyindices.com/Press_Release/ind_prs10082026.pdf). Announced before the endpoint but **not effective by 4 September**; do not apply to the current research window. |

The [official reconstitution calendar](https://www.niftyindices.com/resources/index-rebalancing-schedule) specifies March/September reviews and permits additional changes for arrangements, suspension and delisting. Read each dated notice's actual effective date; do not derive a historical date from today's calendar alone.

## Ad hoc changes and dummy constituents

These verified examples show why a semiannual-only reconstruction is insufficient:

- **Raymond Lifestyle:** the 13 September 2024 notice references DUMMYRAYMD inclusion from 11 July 2024, listing as RAYMONDLSL on 5 September, and exclusion from Nifty 500 on **17 September 2024**. Acquire and link the original July inclusion and the later removal; a temporary constituent is not an ordinary replacement pair. [Official removal notice](https://www.niftyindices.com/Press_Release/ind_prs13092024.pdf).
- **ITC Hotels:** the 6 February 2025 notice references DUMMYITC inclusion from **6 January 2025**, actual listing on 29 January, and Nifty 500 exclusion from **10 February 2025**. The original December 2024 inclusion notice is another acquisition dependency. [Official removal notice](https://www.niftyindices.com/Press_Release/ind_prs06022025_1.pdf).
- **ABFRL:** DUMMYABFRL was included at zero price in Nifty 500 from **22 May 2025**. Its listing/identifier transition and subsequent removal must also be captured. A zero-price index placeholder must not become an entry-eligible stock. [Official inclusion notice](https://www.niftyindices.com/Press_Release/ind_prs19052025.pdf).
- **Piramal:** PEL was replaced by RELINFRA from **23 September 2025** due to a scheme of amalgamation, a week before the regular review. [Official notice dated 15 September](https://www.niftyindices.com/Press_Release/ind_prs15092025_1.pdf).
- **HEG:** the earlier source review verified DUMMYHEG inclusion effective **7 September 2026**, after the target endpoint. Its presence in the locally downloaded 501-row CSV cannot make it eligible on 4 September. [Official 3 September notice](https://www.niftyindices.com/Press_Release/ind_prs03092026.pdf).

The catalog must distinguish index-accounting membership from actual trading eligibility. Do not enforce a constant 500 rows by deleting temporary demerger lines or inventing compensating removals. The exact number of historical stable instruments remains unknown until the complete event register is reconciled.

## Acquisition sequence and exact gaps

1. **Obtain an independently dated starting list.** For evaluation-only membership, request the list effective at the opening of 1 January 2024, or a confirmed 29 December 2023 closing list with all changes effective at the next open. No such official baseline was located in this bounded pass. If materializing the existing 252-session warm-up request, the prior source review places its history start at **23 December 2022**; the catalog spec then also requires membership overlap evidence for that longer window. Do not silently substitute the 2020 workbook or unanchored current CSV.
2. **Capture the archive register before parsing membership.** Enumerate the relevant equity replacement, corporate-adjustment, exclusion, revision and corrigendum notices over the requested interval, including announcements before its start that become effective inside it. Download exact PDF bytes with source URL, retrieval time and hash. The five in-window scheduled reviews above are necessary, but the ad hoc/correction inventory remains incomplete.
3. **Transcribe and reconcile in effective-date order.** Preserve index name, publication date, effective-open date, prior-close wording, inclusion/exclusion/revocation, historical symbol, stable instrument identifier, and superseded notice. Use exchange/company identity evidence to resolve renames and mergers. Keep unknowns explicit. Preserve removed members' prices and let existing holdings finish after removal; stop new entries when the interval ends.
4. **Reconcile against dated official checkpoints.** Acquire constituent snapshots immediately before/after reviews and at the final as-of date. Confirm membership sets and dummy treatment, not merely counts. A current-list backwards reconstruction is acceptable only after its anchor date and every intervening delta/correction are independently established; neither condition is currently met.
5. **Use the official historical constituent product if public records cannot close the baseline/completeness gap.** NSE Indices explicitly offers ongoing and historical constituent data, including identifiers, weights and prices, with an end-of-day subscription route. Request scope, delivery history, corrections, dummy records and usage terms before choosing it. Availability is advertised, but the required baseline, archive completeness, price and license were not supplied or agreed here. [Official offering](https://www.niftyindices.com/offerings/data-subscription).
6. **Only then pin catalog evidence.** Produce the spec's content-hashed membership CSV, stable-instrument bar artifacts, lineage and adjustment policy; independently pin the canonical manifest and issuer. This note supplies an acquisition plan, not a trusted manifest or a backtest admission decision.

Only this Markdown note was created. No data purchase, external message, broker request, membership fabrication, source-code edit or strategy evaluation was performed.
