# NSE master schema drift: September 2026 sample

Research date: 7 September 2026. **Two header changes are confirmed in the captured samples; their authoritative definitions and effective dates remain unresolved.** Keep the September 2026 file outside the accepted older-schema audit. Equal field counts do not justify silently renaming either field.

## Observed evidence

Both captures contain 120 columns. After verifying their compressed payload hashes against the acquisition receipts, a direct comparison found these differences:

| One-based field | 1 April 2025 header | 3 September 2026 header |
|---|---|---|
| 24 | `ElgbltyRETDBTMkt` | `ElgbltyClsgAuctnSsn` |
| 59 | `Rsvd01` | `XchgExclsv` |

Sources are the official NSE reports endpoint responses retained in the [1 April capture receipt](../../data/research/nse-master-batch/v1/2025-04-01/capture.json) and [3 September capture receipt](../../data/research/nse-master-batch/v1/2026-09-03/capture.json). Each receipt records the exact requested URL, NSE-only descriptor, dated filename, retrieval clock and compressed-body hash. The payload hashes are respectively `00d3dccf5dea1b10be7ba43a07db911685a0c6f026f1f0ebe5f85aac712cc214` and `02d3df3cb15410588ca77a8f77f633ed84b0433d305335515dd7182b7dc2833e`.

The older names are consistent with the previously captured [MSD55276](https://nsearchives.nseindia.com/content/circulars/MSD55276.zip) and [CMTR61813](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip) schema packages. The new names suggest closing-auction eligibility and exchange exclusivity, respectively, but those are **inferences from labels**, not verified value dictionaries or activation dates. A schema can be deployed before a related trading facility becomes effective.

The separately verified [MSD67344 circular](https://nsearchives.nseindia.com/content/circulars/MSD67344.pdf) changes `PrtdToTrad` at field 17 from 1 April 2025. It does not establish either observed change at fields 24 or 59. Do not transfer that effective date or its permission-value dictionary to `XchgExclsv`.

## Bounded search result

Four official-domain queries were attempted: each exact new tag, closing auction/security/2026, and exchange exclusive/security master. Neither exact tag nor the exchange-exclusive query returned an applicable result. The closing-auction query returned a company's annual-report discussion of a consultation, which cannot establish NSE's operative field definitions. No new circular was downloaded and no authoritative effective date was identified. The [investigation record](../../data/research/nse-master-schema-change/20260907/investigation.json) preserves the queries, receipt hashes and header differences.

This result means the bounded search did not resolve the change; it does not prove that the exchange has published no documentation. A follow-up should identify the relevant NSE circular and schema attachment, pin their definitions and applicability dates, and only then add a separate schema version with tests. Additional dated master samples could narrow the first observed header change, but could not by themselves certify its effective date or historical public availability.

No code, pinned universe-rule note, historical classifications or trading authority changed. This follow-up made no Kite calls or purchases.
