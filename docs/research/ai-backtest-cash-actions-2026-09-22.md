# Fixed-universe cash action verification, 22 September 2026

Five proposed cash dividends have issuer or NSE-hosted issuer evidence for their amounts and entitlement dates. These are research repair candidates, not production changes. Exact `replaces_source_id` values must be joined to the already retained rejected action records before admission.

| Symbol | Pilot raw ISIN | Cash per share | Candidate ex-date | Document-based known-from |
| --- | --- | ---: | --- | --- |
| AXISBANK | INE238A01034 | INR 1.00 | 2025-07-04 | 2025-04-25 |
| BEL | INE263A01024 | INR 0.90 | 2025-08-14 | 2025-08-05 |
| HAL | INE066F01020 | INR 15.00 | 2025-08-21 | 2025-06-27 |
| ICICIBANK | INE090A01021 | INR 11.00 | 2025-08-12 | 2025-06-27 |
| KOTAKBANK | INE237A01028 | INR 2.50 | 2025-07-18 | 2025-07-09 |

## Evidence and timing

- **AXISBANK:** The issuer's 31st AGM notice is dated 25 April 2025 on PDF page 15. Page 18 states the board's 24 April recommendation of INR 1 and the 4 July record date. The separate 25 April exchange letter was also readable through the research browser and confirms that date; its download redirected, so the pinned AGM notice is the byte-level evidence.
- **BEL:** The 19 May 2025 board outcome confirms INR 0.90 on PDF page 2. The separate 5 August book-closure notice, pages 1–2, specifies register closure 15–17 August and entitlement at close of business on 14 August. Use 5 August as the later notice date. These scanned pages were visually inspected.
- **HAL:** NSE-hosted issuer board outcome dated 27 June 2025, PDF page 1, confirms INR 15 and the 21 August record date; page 2 states the board meeting ended at 16:30. The dividend and record date remain conditional on AGM approval in the notice. Page 1 was visually inspected. The NSE attachment filename also dates its filing to 27 June.
- **ICICIBANK:** The 19 April board outcome, PDF page 2, recommends INR 11. The 27 June board outcome, page 1, sets the 12 August record date. Use 27 June as the later notice date.
- **KOTAKBANK:** AGM notice page 1 states INR 2.50 and the 18 July record date; page 12 repeats the entitlement terms. The separate exchange covering letter dated 9 July 2025 (PDF page 1) says the annual report and AGM notice are being submitted and refers to its earlier 8 July AGM intimation. Use the conservative evidenced publication date 9 July rather than the 28 June internal notice date.

The issuer PDFs mostly call these **record/entitlement dates**, not exchange ex-dates. Candidate ex-dates above retain the exact event dates supplied from the historical action archive; these documents corroborate the same entitlement dates. This review does not replace the retained exchange action record with a newly inferred date. Date-only `known_from` is based on dated documents; it does not authenticate their historical download or exact intraday public availability. All five notices precede their events. None supplies authority to make dividend receipts spendable before the frozen engine's existing receivable policy permits it.

## Raw identity and pinned files

Read-only inspection of `data/research/stock-closure/20260907/raw-panel.parquet` confirmed the ISIN and EQ series for each symbol on the exact candidate event date. Kotak has a different ISIN elsewhere in the full panel; the July 2025 event specifically uses INE237A01028. The original archive's stale-ISIN mismatch remains separate from these verified raw identities.

Machine-readable candidates: `data/research/ai-backtest-actions/20260922/cash-rule-candidates.json`. Each source includes its repository path and verified SHA-256. Each PDF has a sibling `.receipt.json` containing its download URL, retrieval timestamp, byte count and digest. The BEL server's certificate chain failed the local trust store; only those two public downloads used disabled certificate verification, explicitly recorded as `tls_verified: false`. This is a provenance limitation; files remain issuer-hosted and content-checked.

No events were left unverifiable. No source prices, accounting implementations, model artifacts or production files were edited.

## Primary sources

- [AXISBANK: axis-agm-notice.pdf](https://www.axis.bank.in/docs/default-source/annual-general-meeting/31st-annual-general-meeting/notice-convening-the-31st-annual-general-meeting.pdf) — local `data/research/ai-backtest-actions/20260922/axis-agm-notice.pdf`, SHA-256 `06750a497ef821bbedb7276781501c7e10895d7b44a1b816d3b4bb167c4efa6e`.
- [BEL: bel-dividend.pdf](https://bel-india.in/wp-content/uploads/2025/05/Recommendation-of-Final-Dividend-for-FY-2024-25.pdf) — local `data/research/ai-backtest-actions/20260922/bel-dividend.pdf`, SHA-256 `dc8cbfdeab89c95566b446f23ed2c8a25a3407ae198a4461099e4d77fee32cc8`.
- [BEL: bel-book-closure.pdf](https://bel-india.in/wp-content/uploads/2025/08/Notice-of-Book-Closure-05.08.2025.pdf) — local `data/research/ai-backtest-actions/20260922/bel-book-closure.pdf`, SHA-256 `3519eab8ad6a63c91f86c81b21937ef8e3a569417419859bbdda73119e566892`.
- [HAL: hal-dividend.pdf](https://nsearchives.nseindia.com/corporate/HAL_27062025164513_outcome_boardmeeting_27062025_signed.pdf) — local `data/research/ai-backtest-actions/20260922/hal-dividend.pdf`, SHA-256 `71825861313650e9e1687a67bf9a2de0b63e64a267de47d0f6198cee5e98450a`.
- [ICICIBANK: icici-dividend-results.pdf](https://www.icici.bank.in/content/dam/icicibank/managed-assets/docs/about-us/2025/notice/NSEBSE-april-2025.pdf?download=true) — local `data/research/ai-backtest-actions/20260922/icici-dividend-results.pdf`, SHA-256 `185da6e4ef6d4b4f4d46651fca44fa5d03aaa9896f23dacb8c4632cf231cf62c`.
- [ICICIBANK: icici-agm-record-date.pdf](https://www.icici.bank.in/content/dam/icicibank/managed-assets/docs/about-us/2025/notice/NSEBSE_27062025.pdf?download=1) — local `data/research/ai-backtest-actions/20260922/icici-agm-record-date.pdf`, SHA-256 `6baf90972bfbdf1f2bf72c38e2a01a5ffb585890d67bfb256a04c033793bbfe9`.
- [KOTAKBANK: kotak-agm-notice.pdf](https://www.kotak.com/content/dam/Kotak/investor-relation/Financial-Result/Annual-Reports/FY-2025/kotak-mahindra-bank/agm-notice.pdf) — local `data/research/ai-backtest-actions/20260922/kotak-agm-notice.pdf`, SHA-256 `1571f37262ddd54090e20fbe43b4eda92c5da34aa4c281c7beb37e69af48df8d`.
- [KOTAKBANK: kotak-notice-publication.pdf](https://www.kotak.com/content/dam/Kotak/investor-relation/governance/governance-sebi-tab/2025/agm-10july25/seintimationnoticeannualreport09072025.pdf) — local `data/research/ai-backtest-actions/20260922/kotak-notice-publication.pdf`, SHA-256 `f880579bd2416b4b82df7057fcbbad3934b35e0b6d649b8da99997522995f1f4`.
