# Primary sources for the demerger accounting replay

Captured and reviewed on 9 September 2026. This evidence supports the explicitly assumed research contract in [the valuation note](demerger-entitlement-valuation-method-2026-09-08.md); it does not establish individual broker credits or executable prices for unlisted securities.

The [source manifest](../../data/research/strategy-design/20260909/demergers/source-manifest.json) pins 21 primary documents, request URL, resolved URL, capture time and SHA-256 receipts. Its SHA-256 is `54164d91f119a10800dd285a02ee84d65be63e85ec873fa5e04ddf2fa2aa4d78`. Admission circulars are distributed by NSE as ZIP packages containing a PDF and shareholding annexure; the extracted PDFs and original ZIPs are both pinned. Failed `.pdf` requests remain recorded and are not evidence of unavailable admissions.

## Dated terms

Tata's **1 October 2025** notice fixes **14 October** as record date, with one ₹2 resulting-company share for each ₹2 parent share. Its 9 October communication identifies the continuing passenger-vehicle company and the separate commercial-vehicle company and confirms the **1 October** scheme effective date. NSE's **3 October** circular schedules SPOS for **14 October**. NSE's **16 October** rename notice changes TATAMOTORS to TMPV effective **24 October**. Parent equity ISIN `INE155A01022` must be checked against raw/master continuity; the rename notice itself states name and symbol. [Record notice](https://nsearchives.nseindia.com/content/debt/WDM/TATAMOTORSSJS_01102025120200_NSEBSERECORDDATE.pdf), [shareholder communication](https://archives.nseindia.com/corporate/TATAMOTORSSJS_09102025200440_NSEBSESHAREHOLDERINTIMATION.pdf), [SPOS circular](https://archives.nseindia.com/content/circulars/CMTR70614.pdf), [rename circular](https://archives.nseindia.com/content/circulars/CML70875.pdf).

Vedanta's **20 April 2026** notice fixes **1 May** as effective and record date and specifies one share in **each** of four resulting companies per parent share. VEDPOWER's face value is ₹10; the other three children's face values are ₹1. These different face values do not change the 1:1 entitlement counts. NSE schedules SPOS on **30 April**; the **23 April** index notice confirms that ex-date and four equal-weight dummy assets. Parent equity ISIN observed in the frozen panel is `INE205A01025`. [Company notice](https://www.vedantalimited.com/public/uploads/19056/VEDLSEIntimationRecordDate20April2026signed.pdf), [SPOS circular](https://archives.nseindia.com/content/circulars/CMTR73856.pdf), [index notice](https://www.niftyindices.com/Press_Release/ind_prs23042026.pdf).

## Admissions and no-lookahead availability

All five admission PDFs specify **BE series and market lot 1**. The announcement date below is the earliest dated admission captured in this bounded pass, not an exhaustive claim about the first public mention. Treat date-only notices as known by that day's close, not before its open.

| Child | ISIN | Admission notice date | Listing date | Allotment date stated in admission | Primary admission package |
|---|---|---|---|---|---|
| TMCV | INE1TAE01010 | 10 Nov 2025 | 12 Nov 2025 | 15 Oct 2025 | [CML71207](https://archives.nseindia.com/content/circulars/CML71207.zip) |
| VAML | INE1CDF01017 | 11 Jun 2026 | 15 Jun 2026 | 4 May 2026 | [CML74659](https://archives.nseindia.com/content/circulars/CML74659.zip) |
| VEDPOWER | INE694L01019 | 11 Jun 2026 | 15 Jun 2026 | 4 May 2026 | [CML74668](https://archives.nseindia.com/content/circulars/CML74668.zip) |
| VOGL | INE704J01044 | 11 Jun 2026 | 15 Jun 2026 | 5 May 2026 | [CML74666](https://archives.nseindia.com/content/circulars/CML74666.zip) |
| VISL | INE1CLE01013 | 11 Jun 2026 | 15 Jun 2026 | 4 May 2026 | [CML74664](https://archives.nseindia.com/content/circulars/CML74664.zip) |

The admission annexures independently restate each 1:1 ratio. The later legal allotment dates must not be backdated into pre-ex-date knowledge; ex-date receivables can instead rest on the earlier entitlement notices. Market admission is a valid **declared research availability assumption**, with sellability still constrained by actual series, identity, price, capacity and execution rules. It does not prove an individual account had received shares.

TMCV's transfer to EQ is announced **12 November**, effective **26 November 2025**. VAML and VOGL transfers are announced **15 June**, effective **30 June 2026**. These notices are also pinned. Do not infer VEDPOWER/VISL's EQ transition from their siblings; use the dated security masters and actual rows. [TMCV transition](https://archives.nseindia.com/content/circulars/CML71242.pdf), [VAML transition](https://archives.nseindia.com/content/circulars/CML74703.pdf), [VOGL transition](https://archives.nseindia.com/content/circulars/CML74704.pdf).

## Valuation provenance and remaining limits

The pinned **May 2024 SPOS member guide**, question 5, identifies auction equilibrium as the day's open. The **March 2025** consultation describes constant dummy-price treatment as the then-existing method. The **1 December 2025** adopted revision establishes multiple equal-weight dummies from **15 December**. The pinned general methodology is **August 2026 / 20260821**, a later reference that must not be represented as published before these events. [SPOS guide](https://archives.nseindia.com/web/sites/default/files/inline-files/Member_Guide_and_FAQs_on_Special_Pre-Open_Session_in_Capital_Market.pdf), [existing method in March consultation](https://www.niftyindices.com/docs/default-source/default-document-library/nse_indices_consultation_demerger.pdf?sfvrsn=16a6a35_2), [adopted revision](https://www.niftyindices.com/Press_Release/ind_prs01122025.pdf), [current pinned methodology](https://www.niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf).

The contract is labeled `NSE_SPOS_RULE_PLUS_RAW_OPEN`: inferred discovery from official SPOS rules plus the frozen exchange raw opening row. A separate numerical auction bulletin is not asserted. The previously checked raw prices imply **₹260.75** for Tata's child and **₹484.10 aggregate / ₹121.025 per child before rounding** for Vedanta. Listing marks replace dummy values; none of these children remains unlisted through the 3 September endpoint. No tax cost-allocation percentage enters valuation.

Still not established here: individual account credit times, complete child corporate-action coverage after listing, and exact intraday dissemination times of every dated notice. Those limits require explicit replay assumptions or validation, not additional invented prices. This source pass changed no trading code, parameters or broker state.
