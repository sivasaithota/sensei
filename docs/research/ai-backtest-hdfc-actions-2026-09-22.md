# HDFC Bank: July dividend and August bonus evidence

Research date: 2026-09-22. Scope: repair evidence only; no strategy, source-panel, or accounting-engine changes. These are retrospective downloads of dated primary documents, not authenticated historical captures.

## Verified event chronology

| Event | Announcement / document date | Ex-date | Record date | Terms / availability |
| --- | --- | --- | --- | --- |
| Special interim dividend | 2025-07-19 | 2025-07-25 (archived NSE action record) | 2025-07-25 | ₹5 per existing ₹1 equity share; issuer scheduled payment for 2025-08-11 |
| Bonus | Board approval 2025-07-19 | 2025-08-26 | 2025-08-27 | 1 new share per 1 existing share; total-share multiplier 2 |
| Bonus admission | NSE circular 2025-08-22 | — | 2025-08-27 | Deemed allotment 2025-08-28; exchange trading admission effective 2025-08-29 |

The [July 19 issuer declaration](https://nsearchives.nseindia.com/corporate/HDFCBANK_19072025145605_SEintimationBMFinancial_Results19jul2025_FINAL.pdf), pages 1–3, establishes dividend amount, record/payment dates, board-approved bonus ratio and its record date. The approval was subject to required approvals. The [August 28 issuer allotment disclosure](https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/personal-banking/about-us/stakeholders-information/disclosures/other-stock-exchange-disclosure/18/28aug2025-se-disclosure-allotment.pdf) confirms actual allotment of 7,677,039,761 bonus shares that day in the same ratio.

The [NSE bonus adjustment circular FAOP69840](https://nsearchives.nseindia.com/content/circulars/FAOP69840.pdf), dated August 25, explicitly identifies August 26 as the ex/effective date and factor 2. The record date remains August 27. That day was the Ganesh Chaturthi trading holiday under [NSE capital-market circular CMTR65587](https://nsearchives.nseindia.com/content/circulars/CMTR65587.pdf), dated December 13, 2024. Thus the ex/record difference is supported by exchange documents, not inferred from a price discontinuity.

## Admission and identity proof

[NSE CML69791](https://nsearchives.nseindia.com/content/circulars/CML69791.pdf), dated **August 22, 2025**, explicitly admits the bonus securities to capital-market dealings from **August 29, 2025**. Its annexure names `HDFCBANK`, **ISIN `INE040A01034`**, record date August 27, deemed allotment August 28, and 7,677,039,761 securities. This supports `available_from=2025-08-29`, `availability_known_from=2025-08-22`, and an exchange-admission evidence basis. It does not establish any particular investor's demat credit time.

The local archived NSE action response at `data/reports/portfolio-action-evidence/2025-partition-2.json` contains both events but labels them `INE040A01018`. Its SHA-256 is `ce7349c44d41ef5396f2c6f056a119673780d8afaf12de517a7394697e388ee4`. The dividend record specifies ex-date and record date July 25, ₹5, face value ₹1. The bonus record specifies ex-date August 26, record date August 27 and 1:1. This archive supplies the dividend ex-date; the issuer declaration alone supplies only its record date. The current raw ISIN `INE040A01034` is supplied by the research task; the bonus admission independently proves that identifier. Do not broadly rewrite historical ISINs: scope any repair to these named events and verify the actual raw identity at their boundaries.

## Local evidence and accounting boundary

PDF bytes and corresponding `.pdf.json` receipts are under `data/research/ai-backtest-actions/20260922/`. Each receipt records requested/final URL, UTC retrieval time, HTTP status, content type, byte count and SHA-256.

| Local PDF | SHA-256 |
| --- | --- |
| `hdfc-20250719-declaration.pdf` | `d11b0ad22371d90f2f13ea056e7b5e800e4ab31974ed295358d4c14481a36b3e` |
| `hdfc-CML69791-bonus-admission.pdf` | `2c96429bb0241f8145781207c96366494abfcf4a5d32934bbe2640590816582c` |
| `hdfc-FAOP69840-bonus-exdate.pdf` | `d402d5c057df55f982846735e29a50656a3a497f3da4177d70f3ab79e544c186` |
| `hdfc-20250828-allotment.pdf` | `62674bb7d8f4b9f09eba645df14c6793f66114743fd8f48f73d1fca348b1fe94` |
| `hdfc-CMTR65587-2025-holidays.pdf` | `1e0f85615fbbcde9243dd6cafbbad4d9b581b8d2467fd9e27c0a4fe42a720c7d` |

`hdfc-local-action-extract.json` retains the two archived event rows, source-body hash, and matching request receipt from the existing NSE action manifest.

Bonus entitlement can be recognized on the documented ex-date while the new shares remain unavailable through August 28; August 29 admission is documentary evidence, not an assumed T+2 rule. Retaining the dividend as a nonspendable gross receivable follows the frozen research engine, despite the issuer's August 11 payment schedule. Disclose that accounting convention; the scheduled payment is not evidence of this simulated account receiving cash. Keep accounting repair evidence separate from AI decision packets to avoid supplying later corporate-action outcomes at earlier decisions.
