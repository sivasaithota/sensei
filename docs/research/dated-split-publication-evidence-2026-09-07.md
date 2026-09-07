# HEG and MAZDOCK: contemporaneous split publication evidence

Research date: 7 September 2026. Scope: five original 2024 documents supporting the HEG and MAZDOCK splits already recorded in `config/stock-split-evidence-v1.json`. No annual report is used to establish 2024 knowledge. No code, existing configuration or prior research note was changed.

**Both ratios, ex dates and old/new ISIN transitions are supported by contemporaneously dated primary documents.** A conservative replay requiring every selected supporting document can use first-known sessions **18 October 2024 for HEG** and **27 December 2024 for MAZDOCK**. These are date-level availability conventions; they are not claims about the earliest announcement, exchange upload timestamp or actual historical receipt by the bot.

## Captured facts and dates

All page references below are one-based PDF pages. Every cited page was rendered locally with `pypdfium2`, viewed, and cross-checked against `pypdf` text. All five HTTP captures returned 200 and exact response bytes were retained unchanged under `data/research/dated-split-evidence/20260907/`.

| Primary document | Printed publication date | Verified claims and source pages | Next verified NSE session |
|---|---|---|---|
| [NSE Listing CML64528](https://nsearchives.nseindia.com/content/circulars/CML64528.pdf) | 2024-10-14 | Page 1: HEG subdivision from INR10 to INR2; new ISIN **INE545A01024**; new-ISIN trading and explicitly labelled ex date **2024-10-18**. Total resulting shares **5/1** follows directly from the face-value subdivision. Old ISIN and record date are not supplied here. | 2024-10-15 |
| [NSE Clearing CMPT64615](https://nsearchives.nseindia.com/content/circulars/CMPT64615.pdf) | 2024-10-17 | Page 1: HEG old ISIN **INE545A01016**, INR10 to INR2 split, record and ex dates **2024-10-18**. Page 2: ten sale shares require two old-ISIN shares for early pay-in, corroborating **5/1**. | 2024-10-18 |
| [MAZDOCK company record-date notice](https://www.mazagondock.in/images/pdf/Intimation%20of%20Record%20date%20for%20split%20of%20shares_02122024.pdf) | 2024-12-02 | Page 1: explicitly one fully paid INR10 share becomes two fully paid INR5 shares, total resulting shares **2/1**; record date **2024-12-27**. Does not independently state either ISIN or a separately labelled ex date. | 2024-12-03 |
| [MSE Listing 16513](https://www.msei.in/SX-Content/Circulars/2024/December/Circular-16513.pdf) | 2024-12-23 | Page 1: MAZDOCK old ISIN **INE249Z01012**, new ISIN **INE249Z01020**, INR10 to INR5 subdivision; ex date and new-ISIN trading effective **2024-12-27**. This is an MSE permitted-to-trade notice, not an NSE Listing circular. | 2024-12-24 |
| [NSE Clearing CMPT65800](https://nsearchives.nseindia.com/content/circulars/CMPT65800.pdf) | 2024-12-26 | Page 1: MAZDOCK old ISIN **INE249Z01012**, INR10 to INR5 split, record and ex dates **2024-12-27**. Page 2: ten sale shares require five old-ISIN shares, corroborating **2/1**. | 2024-12-27 |

The ratios describe total shares after subdivision per prior share, not additional bonus shares. They are derived from the published subdivision terms and explicit clearing examples, not historical price or volume ratios.

## Knowledge boundary for replay

The printed document dates are the contemporaneous dates actually verified. No source supplies a verified public-upload time in this capture. The September 2026 HTTP retrieval times establish when these exact bytes were saved now, not their historical availability. Treating the next trading session after each printed date as usable is a conservative date-level research convention, subject to that limitation.

- **HEG:** ratio, ex date and new ISIN are stated in the October 14 notice, usable under the convention from October 15. The captured notice explicitly stating the old ISIN is dated October 17. Requiring the complete selected old/new-ISIN evidence therefore gives **October 18**, also the ex session. Do not attach the complete captured identity chain to October 15 merely because the split ratio was already stated.
- **MAZDOCK:** ratio and record date are stated on December 2. MSE's December 23 document supplies the old/new ISIN chain and explicit ex date. That subset supports a December 24 first-known convention. Requiring **all three selected MAZDOCK documents**, including NSE Clearing's December 26 corroboration, gives **December 27**. This stricter choice deliberately does not claim earliest possible knowledge.

Neither advance knowledge nor document publication changes the economic effective date: do not apply either share subdivision to raw bars, inventory units or cash before its ex session. These documents do not determine dividend accounting, entitlement rounding, all other corporate actions, execution prices, index membership or portfolio performance.

## Independent raw-calendar verification

For each proposed first-known session, the existing raw NSE bhavcopy ZIP and its uncompressed CSV were hashed against the local capture manifest, then every CSV row's `TradDt` was inspected. Each proposed session is the immediately following calendar day, and each has a valid captured trading file; there is no intervening calendar day to classify. No new market-data request was made.

| Printed document date | Verified next session | Raw CSV rows | Observed distinct `TradDt` |
|---|---|---:|---|
| 2024-10-14 | 2024-10-15 | 2,875 | 2024-10-15 |
| 2024-10-17 | 2024-10-18 | 2,855 | 2024-10-18 |
| 2024-12-02 | 2024-12-03 | 2,907 | 2024-12-03 |
| 2024-12-23 | 2024-12-24 | 2,897 | 2024-12-24 |
| 2024-12-26 | 2024-12-27 | 2,911 | 2024-12-27 |

`calendar-verification.json` records exact local ZIP/manifest paths, their hashes, CSV hashes, original NSE source URLs and counts. Its SHA-256 is `2b6b8b511709573b78b2f25da80c56ab426873e1567b61673e009d8568c3a6be`. The bhavcopies remain quarantined research sources; this narrow calendar check does not promote their membership, adjustment or identity coverage.

## Exact-byte provenance

Capture manifest: `data/research/dated-split-evidence/20260907/manifest.json`.

Manifest SHA-256: `c0d58e1c2ed39ed8bca3a75588f7f1ec493c36bcdcb8b3e8051159a83613141e`.

The manifest preserves request URL, final URL, UTC capture time, HTTP status, file size, byte hash, printed publication date, each claim's page/scope, visual verification, and the date-level next-session convention. No cookies, credentials or response headers were retained.

| Local PDF name | SHA-256 |
|---|---|
| `CML64528.pdf` | `04381fceb449c5903854fab817a71252c76d8e1346a62e6fb022e9e652456581` |
| `CMPT64615.pdf` | `e88ddacdf0024dfd73bb16dbbd84a919c5551e22ed0f85f50ada547d878c03dd` |
| `MAZDOCK-record-date-02122024.pdf` | `2feb76de43bfa1613345133992a723f8e2a1b1863fdb2db78a85cc18cfbe9c3f` |
| `Circular-16513.pdf` | `c48889e5cf7f53ad59bc6ef36f158615ebd6aa40ce8735b2523f01c2c1806684` |
| `CMPT65800.pdf` | `06cab37595b1aa1beeaae14bbc05cbf577b805d63ffc372775702e41c5d4787f` |

No wider action search or completeness certification was performed. The original NSE Listing notice for MAZDOCK was not acquired in this bounded five-document task. No annual report, current instrument master or later retrospective statement was substituted for dated 2024 knowledge.
