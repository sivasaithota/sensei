# BSE May 2025 bonus: dated publication evidence

Research date: 7 September 2026. Scope: contemporaneous BSE bonus ratio, ex date, identity and announced allotment/trading schedule. Three exact primary PDFs were captured and all five pages visually checked with local `pypdfium2` renders, against the web PDF reader's extracted text. No broker call, code/configuration edit or portfolio-accounting claim is involved.

**The May 12 company notice plus May 14 NSE circular support a pre-ex evidence bundle with conservative first-known session May 15, 2025.** The issue is **two additional shares per existing share**, hence **3/1 total resulting shares**, with **May 23, 2025 ex date**. The later May 26 allotment notice is separate post-event corroboration and must not establish knowledge or share availability on May 23.

## Primary facts and pages

| Document and printed publication date | Verified facts | Evidence role and next-session convention |
|---|---|---|
| [BSE company record-date notice, May 12, 2025](https://nsearchives.nseindia.com/corporate/BSE1_12052025155558_NSEintimation.pdf) | Page 1 identifies symbol **BSE**, ISIN **INE118H01025**, and two new fully paid INR2 shares per existing share. Record date **May 23**; deemed allotment **May 26**; planned trading availability **May 27**. | Required pre-ex evidence; usable under a next-session convention from **May 13**. The notice references earlier shareholder approval but that earlier source was not captured or used as a first-known date. |
| [NSE/FAOP/67987, May 14, 2025](https://nsearchives.nseindia.com/content/circulars/FAOP67987.pdf) | Page 1 explicitly lists BSE LIMITED, BONUS, 2:1, and ex/effective date **May 23**. It gives a derivative adjustment factor of 3. Page 2 says clearing corporations will separately communicate position-adjustment methodology. | Required pre-ex evidence; next session **May 15**. Used for the stated event and date, not to import F&O lot sizes, rounding or execution rules into cash equities. |
| [BSE company allotment notice, May 26, 2025](https://nsearchives.nseindia.com/corporate/BSE1_26052025095238_NSEintimation.pdf) | Page 1 identifies BSE / **INE118H01025** and actual allotment on May 26 of **270,752,718** bonus shares; shares outstanding increase from **135,376,359** to **406,129,077**. It repeats the ratio and May 23 record date. Page 2 says bonus shares rank pari passu with existing equity. | **Post-event corroboration only**; next-session convention **May 27**. Excluded from the pre-ex evidence dependency set. Does not independently prove a specific account's credit, exchange trading-admission timestamp or actual sale availability. |

The company notice's explicitly additional 2:1 entitlement determines the total 3/1 share-coordinate ratio. No observed raw/adjusted price or volume ratio was used to infer it. The May 26 count reconciliation confirms that ratio retrospectively; it is not needed to manufacture prior knowledge.

## Timing, identity and application limits

The source publication dates above are dates printed on the documents. The capture URLs contain date/time-like strings, but they are not treated as verified historical dissemination timestamps. September 2026 HTTP capture times establish when the exact bytes were retrieved now. Advancing to the next verified NSE session is an explicit date-level research convention, not proof that a historical bot received the notice then or that this was the earliest public announcement.

Requiring both pre-ex documents gives **May 15** as the conservative first-known session. The economic ex date remains **May 23**: advance knowledge must not alter historical raw prices or quantities before effectiveness. For a deliberately specified price-coordinate replay, the 3/1 entitlement supports an ex-date coordinate change. Such a mathematical representation is not a physical share-credit or sellability ledger.

In particular, the issuer itself separates **May 23 record date**, **May 26 deemed allotment** and **May 27 planned trading availability**. It would be unsupported to triple freely sellable physical inventory on May 23. The later actual allotment confirmation does not move its information backward. No fractional physical-share handling, account credit or settled-delivery policy is certified here.

The May 12 notice establishes a dated pre-ex symbol/ISIN association. Its match to the May 26 notice corroborates the same reported ISIN across these filings; neither notice is a complete old-to-new identity-history certificate. In particular, the proposed raw replay history **May 13, 2024 through May 30, 2025** must still check each raw row's symbol/ISIN. Even consistent row identifiers do not turn a May 2025 printed notice into proof of the entire earlier lineage. That historical coverage check belongs to the replay and is not asserted completed by this document.

Dividend treatment remains a separately declared modeling choice. This task does not verify the complete corporate-action set for the warm-up window, certify provider adjustment conventions, or show strategy returns.

## Raw-calendar cross-check

Existing local NSE bhavcopy ZIP and CSV bytes were verified against their capture manifests, and every CSV row's `TradDt` was checked for the proposed next sessions. Each is the calendar day immediately following the printed date, so there is no intervening day to classify:

| Document date | Verified next NSE session | CSV rows |
|---|---|---:|
| 2025-05-12 | 2025-05-13 | 2,982 |
| 2025-05-14 | 2025-05-15 | 2,969 |
| 2025-05-26 | 2025-05-27 | 2,983 |

`data/research/dated-bonus-evidence/20260907/calendar-verification.json` preserves exact local raw and manifest paths, SHA-256 values, original NSE URLs and observed date sets. Its SHA-256 is `abfa1c3ff3a87dbf295d7ea95ae3ca966c2f2afeaee8beb3620b01ba24e4166e`. This narrow check does not promote the quarantined bhavcopies to complete point-in-time market evidence.

## Exact captured bytes

Directory: `data/research/dated-bonus-evidence/20260907/`.

Manifest SHA-256: `2d3f3215258cea1ce60cef8a240ccc19462a54b41be4bac774c180972f4ed366`.

| File | Bytes | SHA-256 |
|---|---:|---|
| `BSE-record-date-20250512.pdf` | 867,716 | `f8409e9b5fa351634e3cb9639dc482d8371dcf433f9d3a31cf0e79efb1021944` |
| `FAOP67987.pdf` | 126,355 | `c2d755649ce6e09630034c71d969cd571fdf237ef738645f11f020b535ccb07d` |
| `BSE-allotment-20250526.pdf` | 306,955 | `a0b3d39241f52ce5577794f0159ec590375c49544476f2eeb3107fbcd8a2c6df` |

All captures returned HTTP 200. The manifest records request/final URLs, UTC retrieval times, publication dates, evidence roles, page-specific claims and visual verification. PDFs are unchanged response bytes. No credentials, cookies or response headers were retained.

The bounded search used two additional queries: `site:nsearchives.nseindia.com/corporate BSE "May" "2025" "INE118H01025" "bonus"` and `site:bseindia.com "2025" "May 23" "Record" "bonus" "BSE Limited"`. The May 12 notice resolved the requested pre-ex identity and planned dates; no broader search or additional capture was needed.
