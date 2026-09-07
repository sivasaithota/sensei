# NSE MII security-master schema: August 2026 revision

Research date: 7 September 2026. **Both September header changes now have authoritative documentation.** A separately versioned parser can accept the revised header from 3 August 2026, while preserving the older schema for earlier sessions. This resolves the schema uncertainty recorded in the earlier investigation; it does not itself certify any historical universe or trading decision.

## Operative change

NSE circular **CMTR73845**, issued 22 April 2026, changes the capital-market security masters for the Closing Auction Session. The circular expressly makes the change effective **3 August 2026**, identifies field 59 as a filler whose ISO tag changes, and says other fields and the file structure remain unchanged apart from the attached changes. Its single PDF page was visually inspected. [Official circular and attachment package](https://nsearchives.nseindia.com/content/circulars/CMTR73845.zip).

The package's `Annexure A.xlsx`, `Sheet1`, rows 4–6 defines the MII-file changes:

| One-based field | Earlier ISO tag | Revised tag | Meaning from 3 August 2026 |
|---|---|---|---|
| 23 | `SctyStsRETDBTMkt` | No replacement tag supplied | Now filler. Preserve the observed header and raw contents; do not interpret them as the former RETDBT market status. |
| 24 | `ElgbltyRETDBTMkt` | `ElgbltyClsgAuctnSsn` | Closing-auction eligibility: `0` ineligible, `1` eligible. |
| 59 | `Rsvd01` | `XchgExclsv` | Remains filler; the attachment provides no exclusivity dictionary. |

The new name `XchgExclsv` therefore **does not authorize an exchange-exclusivity inference**. A CAS eligibility flag also does not classify ordinary equity or establish main-board membership. [Official Annexure A source](https://nsearchives.nseindia.com/content/circulars/CMTR73845.zip).

## Complete header bridge and observed values

The later-issued capital-market consolidated package **CMTR73927**, dated 28 April 2026, contains `PART-D.xlsx`. Its `Annexure 10`, rows 11–130, supplies the 120-field pre-CAS MII header. After stripping the same incidental surrounding spreadsheet whitespace used in the existing schema extraction, it exactly equals the frozen January 2025 header. Apply the two expressly revised ISO tags to that header; the result exactly equals all 120 fields in the saved **3 September 2026** response. Field 23 retains its original header in that actual response. No field-count heuristic or generic alias was required. [Official consolidated package](https://nsearchives.nseindia.com/content/circulars/CMTR73927.zip).

The compressed September payload was rechecked against its acquisition receipt before inspection. Its 37,271 records contain:

| Raw field | Observed values and counts |
|---|---|
| `ElgbltyClsgAuctnSsn` | `0`: 37,061; `1`: 210 |
| `XchgExclsv` | Empty: 37,271 |
| `SctyStsRETDBTMkt` | `2`: 27,604; `3`: 9,667; retained as filler values |

These are observations from one file, not evidence that those same distributions hold on other dates. Reproduction metadata and the revised header are saved in [schema-comparison.json](../../data/research/nse-master-schema-vintage/20260907/schema-comparison.json). The September payload SHA-256 remains `02d3df3cb15410588ca77a8f77f633ed84b0433d305335515dd7182b7dc2833e`.

## Captured evidence and applicability

[Capture manifest](../../data/research/nse-master-schema-vintage/20260907/manifest.json) records URLs, HTTP status, retrieval clocks, byte sizes, compressed-package hashes and extracted-member hashes. These local retrieval clocks are not original publication timestamps.

| Artifact | SHA-256 |
|---|---|
| `CMTR73845.zip` | `94f9288a24e815265feb03023f997ecc3a4993cbc1445b0b20383beb7c4c7239` |
| Extracted `CMTR73845.pdf` | `aef6e11c636ce079ec105307a55772a79d3c1be3218147f8b3fd97970312e65d` |
| Extracted `Annexure A.xlsx` | `da1dad1077b0fe70c14a068a1c4f6a665a80f35af81b6d454ba7271d2969efae` |
| `CMTR73927.zip` | `11988491ecb0088222614ae240995b6ef8881628757c903a959dd79c910a7479` |
| Extracted `CMTR73927.pdf` | `f5e04e3cc7fa33a995ddc2603b62fce3b2e1e4f230848d211567b855db5ff89e` |
| Extracted `PART-D.xlsx` | `30a4e37956ba5ab1acdda177411beca0146ebab0bcb155f1cd4f12576d195798` |

The standalone `CMTR73845.pdf` endpoint returned HTTP 404 HTML. That failed response is retained in the manifest and is **not** the PDF evidence; the valid PDF was extracted from the successful official ZIP response. No documentation was obtained through credentials or broker APIs.

Implementation should select the exact revised schema only on or after the documented effective date, validate the new CAS dictionary explicitly, retain both filler fields uninterpreted, and reject unexpected headers. This is an applicability rule derived from the operative circular, not proof that an early-deployed test file could never exist. Earlier/current master samples must not be carried across missing sessions or used to invent original availability times. Same-day price reconciliation and missing-date checks remain necessary before expanding any portfolio experiment.

No existing pinned note, production code, trade authorization, or Kite usage was changed by this research pass.
