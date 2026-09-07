# MAZDOCK and HEG: verified share-unit lineage

Research date: 7 September 2026. Scope: the 2024 ISIN transitions and checks for later events through this research date. This is primary-source evidence for a narrow share-unit audit, not a certification of adjusted prices, executable quantities, or portfolio returns. No broker API calls were made.

## Verified 2024 transitions

| Symbol | Old ISIN | New ISIN | Face value | Ex date / new-ISIN trading effective date | Record date | Shares after split per share before split |
|---|---|---|---|---|---|---|
| MAZDOCK | INE249Z01012 | INE249Z01020 | ₹10 → ₹5 | 27 December 2024 | 27 December 2024 | **2** |
| HEG | INE545A01016 | INE545A01024 | ₹10 → ₹2 | 18 October 2024 | 18 October 2024 | **5** |

MAZDOCK sources: the company explicitly states one ₹10 share becomes two ₹5 shares and fixes the record date; NSE Clearing supplies the old ISIN and ex/record dates; MSE supplies both ISINs and the effective trading date. [Company notice, 2 December 2024](https://www.mazagondock.in/images/pdf/Intimation%20of%20Record%20date%20for%20split%20of%20shares_02122024.pdf), [NSE Clearing CMPT65800, 26 December 2024](https://nsearchives.nseindia.com/content/circulars/CMPT65800.pdf), [MSE LIST/16513/2024, 23 December 2024](https://www.msei.in/SX-Content/Circulars/2024/December/Circular-16513.pdf).

HEG sources: NSE Listing supplies the new ISIN and effective date; NSE Clearing supplies the old ISIN, ex date, and record date. Its settlement example explicitly converts ten post-split sale shares to two old-ISIN shares for early pay-in. The company annual report independently states one ₹10 share became five ₹2 shares effective 18 October 2024. [NSE CML64528, 14 October 2024](https://nsearchives.nseindia.com/content/circulars/CML64528.pdf), [NSE Clearing CMPT64615, 17 October 2024](https://nsearchives.nseindia.com/content/circulars/CMPT64615.pdf), [HEG FY2024–25 annual report, consolidated Note 17](https://nsearchives.nseindia.com/annual_reports/AR_26827_HEG_2024_2025_A_10072025113543.pdf).

The multipliers above come from published share subdivisions, not ratios inferred from market prices or data-provider volumes. Each expresses total resulting shares, not additional bonus shares.

## MAZDOCK evidence and limits

The 22 October 2024 board outcome initially approved the subdivision subject to shareholder approval. The later 2 December record-date notice supplies the operational date. These dates should not be substituted for the 27 December ex date in a trade ledger. The board outcome separately declared an interim cash dividend; that dividend does not change the split share count. [Company board outcome, 22 October 2024](https://www.mazagondock.in/images/pdf/BSE%20NSE%20Disclosure_Outcome%20of%20BM%20dtd%2022102024_signed.pdf), [company record-date notice](https://www.mazagondock.in/images/pdf/Intimation%20of%20Record%20date%20for%20split%20of%20shares_02122024.pdf).

The direct old-to-new ISIN notice retrieved here is from **MSE**, where the security was permitted to trade, rather than NSE Listing. NSE Clearing independently confirms the old ISIN and matching dates. The company's March 2025 governance filing confirms INE249Z01020 after the event. This is convergent primary evidence, but the original NSE Listing change-of-ISIN circular was not retrieved. [MSE notice](https://www.msei.in/SX-Content/Circulars/2024/December/Circular-16513.pdf), [NSE Clearing notice](https://nsearchives.nseindia.com/content/circulars/CMPT65800.pdf), [company governance filing, quarter ended 31 March 2025](https://mazagondock.in/images/pdf/Corporate%20Governance%20report_31032025.pdf).

The bounded review of the company's exchange-intimation index did not identify a later bonus, split, or demerger that should be multiplied into this event. That search result is **not an exhaustive no-further-actions certificate through September 2026**. Treat 2× as the verified component attributable to this particular split. [Company exchange-intimation index](https://www.mazagondock.in/English/Pages/Intimation-to-Stock-Exchanges).

## HEG: split and later demerger are separate

The FY2024–25 annual report reconciles issued shares from 38,595,506 to 192,977,530 and identifies the increase as the subdivision. Its five-year table reports no bonus allotments in FY2020–21 through FY2024–25. That supports a 5× split component and rules out an additional FY2024–25 bonus in this annual-report reconciliation; it does not establish the absence of all later actions. [HEG annual report, consolidated Note 17](https://nsearchives.nseindia.com/annual_reports/AR_26827_HEG_2024_2025_A_10072025113543.pdf).

A later, separate event exists: NSE Indices' **3 September 2026** notice identifies the demerger of HEG's graphite business into HEG Graphite Limited and the special pre-open session on **7 September 2026**. It adds a temporary DUMMYHEG index security at zero price effective 7 September, using the close of 4 September, and cites NSE CML76106 dated 1 September. That index treatment is not a statement that the resulting business has zero economic value. [NSE Indices demerger notice](https://niftyindices.com/Press_Release/ind_prs03092026.pdf).

The company's own public announcement says the record date is 7 September 2026 and eligible holders receive one resulting-company share per HEG share. However, the announcement itself directs readers to the formal exchange disclosures for authoritative terms. The company disclosure page returned HTTP 403 and CML76106 could not be retrieved in this pass. Consequently, this document does **not** certify the legal effective date, complete scheme terms, resulting-company ISIN, allotment/listing date, cost allocation, or final trading identifiers. [HEG company announcement](https://in.linkedin.com/company/heglimited), [company disclosure index](https://hegltd.com/intimation-to-stock-exchange/).

Audit implication: a demerger creates an entitlement to a different security; its ratio must not be multiplied into the parent's 2024 split as if it were another homogeneous share subdivision. A dataset ending 4 September 2026 precedes the exchange's 7 September special pre-open date. Extending that dataset requires separate entitlement and identifier handling, not a blanket extra split factor.

## Application boundary

These sources establish **MAZDOCK 2×** and **HEG 5×** for the specified 2024 share-unit transitions. They do not establish a broker's cumulative historical price-adjustment factor or the absence of cash-dividend adjustments. They also do not resolve fractional quantities, execution rounding, cash ledgers, or the validity of any particular backtest trade. Those require dated raw executions and an explicit unit convention. No price-derived ratio or portfolio quantity has been certified here.
