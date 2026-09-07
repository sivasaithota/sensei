# Demergers behind noninteger vendor volume factors

Research date: 7 September 2026; event scope ends with the frozen snapshot on 4 September 2026. This note classifies ABFRL, SIEMENS, TMPV and VEDL. It changes no prices, quantities, event ledger or broker state. The observed Kite/raw volume factors supplied by the local inventory are observations, not legal share entitlements.

The four representative supplied factors agree, to their six-decimal precision, with the reciprocal of the published **parent company's cost-of-acquisition allocation**. Actual endpoint ratios vary, so the evidence across the inventory is approximate agreement rather than equality at every endpoint. That supports a vendor adjustment convention, not a homogeneous subdivision of the parent's shares. Preserve these names as demerger/adjustment exceptions; do not round the factors to integers or pass them to the split quantity-step solver.

## Evidence and arithmetic

| Captured symbol | Representative supplied volume factor | Published parent COA | Our calculation: 1 / parent COA | Legal resulting-company entitlement per original share |
|---|---:|---:|---:|---|
| ABFRL | 1.321353 | 75.68% | 1.321353066 | One ABLBL share |
| SIEMENS | 1.312680 | 76.18% | 1.312680494 | One Siemens Energy India share |
| TMPV | 1.452433 | 68.85% | 1.452432825 | One TML Commercial Vehicles share, subsequently named Tata Motors Limited |
| VEDL | 1.910585 | 52.34% | 1.910584639 | One share in each of four separate resulting companies |

The company allocation sources are [ABFRL's COA letter](https://www.abfrl.com/wp-content/uploads/2025/06/ABFRL-ABLBL-Apportionment-of-Cost.pdf), [Siemens' COA letter](https://assets.ctfassets.net/17si5cpawjzf/1eIuZLuvSghEP1UDL8BTE0/88d568a97ed7f1284238a144c7a132f0/3--guidance-on-cost-of-apportionment.pdf), [Tata's COA letter filed with NSE](https://nsearchives.nseindia.com/corporate/TATAMOTORSSJS_12112025224654_NSEBSECOAFINAL.pdf), and [Vedanta's COA letter](https://www.vedantalimited.com/public/uploads/19416/VEDLSEIntimationCostofApportionmentsigned.pdf). The reciprocals are calculations from their percentages, not factors published by an exchange or a certification of every archived bar. This pass did not independently recalculate the inventory's volume observations. The local inventory reports SIEMENS endpoints spanning **1.3126793159449683–1.3126800730286918**, rather than one exact constant; other names also have endpoint variation. Integer-valued reported volumes may explain small discrepancies, but the vendor's rounding implementation is not established here.

## SIEMENS → Siemens Energy India

Siemens' 25 March 2025 company notice fixes **7 April 2025** as record date and specifies **one ₹2 Siemens Energy India Limited share for each ₹2 Siemens Limited share**. NSE's corporate-action record independently gives **7 April 2025 as both ex-date and record date**. [Company record-date notice](https://assets.ctfassets.net/17si5cpawjzf/3BaVBX9bhEbuweltVvQxbw/e3a52babbcfb8e885c0f6e7f8c0657f8/SEdisclosureRecordDate25032025.pdf), [NSE corporate actions](https://www.nseindia.com/companies-listing/corporate-filings-actions?symbol=SIEMENS&tabIndex=sme).

The parent is **Siemens Limited, SIEMENS, ISIN INE003A01024**; its August 2026 exchange filing confirms that identity. The resulting company is **Siemens Energy India Limited, ENRIN, ISIN INE1NPP01017**. NSE's dated listing notice admits the latter from **19 June 2025**, initially in BE series. The April entitlement date must not be treated as an immediately tradable ENRIN position. [Parent identity filing](https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_184965_11082026143408_iXBRL_WEB.html), [NSE listing press release, 17 June 2025](https://nsearchives.nseindia.com/web/pressrelease/2025-06/PR_List_17062025_20250617191748.pdf).

Siemens' **14 April 2025** guidance allocates **76.18%** of the original acquisition cost to Siemens and **23.82%** to Siemens Energy India. It separately identifies the scheme appointed date as **1 March 2025** and effective date as **25 March 2025**. These legal dates differ from the exchange ex-date. The COA letter is later than the ex-date; it cannot be treated as information available beforehand. [Company COA guidance, pages 1–2](https://assets.ctfassets.net/17si5cpawjzf/1eIuZLuvSghEP1UDL8BTE0/88d568a97ed7f1284238a144c7a132f0/3--guidance-on-cost-of-apportionment.pdf).

A dated June 2025 response on Zerodha's forum explicitly says its Siemens chart uses the **76.18% COA methodology** and can retain a price gap. The question's reference to 4 April is not the authoritative ex-date; use the exchange's 7 April record. [Zerodha Siemens explanation](https://tradingqna.com/t/why-siemens-nse-chart-is-still-not-adjusted-for-corporate-action-on-4-apr-2025/183188).

## TATAMOTORS → TMPV plus TMCV

The original listed **Tata Motors Limited** retained the passenger-vehicle business and was renamed **Tata Motors Passenger Vehicles Limited**. The commercial-vehicle undertaking went to **TML Commercial Vehicles Limited**, which was renamed **Tata Motors Limited**. The pre-existing passenger-vehicle subsidiary was amalgamated into the original listed company; it must not be confused with that company's later name. The company's shareholder notice distinguishes these entities and states that the scheme became effective on **1 October 2025**. [Company shareholder notice filed 9 October 2025](https://nsearchives.nseindia.com/corporate/TATAMOTORSSJS_09102025200440_NSEBSESHAREHOLDERINTIMATION.pdf).

The **record date is 14 October 2025**, with **one ₹2 resulting-company share for each ₹2 original listed share**. NSE records **14 October 2025 as the ex-date** too. These are distinct from the scheme's 1 October effective date. [Company record-date notice, 1 October 2025](https://nsearchives.nseindia.com/content/debt/WDM/TATAMOTORSSJS_01102025120200_NSEBSERECORDDATE.pdf), [NSE parent corporate-action record](https://www.nseindia.com/get-quote/equity/TMPV/Tata-Motors-Passenger-Vehicles-Limited).

| Role | Exchange identity evidenced by the cited source |
|---|---|
| Continuing original listed company | TMPV; Tata Motors Passenger Vehicles Limited; ISIN **INE155A01022** |
| Resulting commercial-vehicle company | TMCV; Tata Motors Limited; ISIN **INE1TAE01010** |

The parent ISIN is recorded in its [January 2026 NSE filing](https://nsearchives.nseindia.com/corporate/ixbrl/PRIOR_INTIMATION_75254_12012026161648_iXBRL_WEB.html); the resulting identity appears in its [November 2025 NSE filing](https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_127430_13112025190316_iXBRL_WEB.html). NSE's **CML70875** changes the continuing company's name and symbol from TATAMOTORS to TMPV effective **24 October 2025**. Thus the symbol-change date is not the demerger ex-date. [NSE capital-market name/symbol circular](https://nsearchives.nseindia.com/content/circulars/CML70875.pdf).

TMCV's listing and trading approval became effective **12 November 2025**, as confirmed by the parent's 10 November disclosure. The company had warned that resulting shares were not tradable between allotment and listing. These documents do not establish an individual account's exact credit timestamp. [Company listing disclosure](https://nsearchives.nseindia.com/corporate/TATAMOTORSSJS_10112025220440_NSEBSELISTING.pdf), [earlier shareholder notice](https://nsearchives.nseindia.com/corporate/TATAMOTORSSJS_09102025200440_NSEBSESHAREHOLDERINTIMATION.pdf).

The **12 November 2025** COA letter allocates **68.85% to TMPV** and **31.15% to TMCV**, explicitly using acquisition-cost allocation based on transferred net book assets. Its example retains the original share count and adds the same number of shares in the other entity. It does not multiply TMPV shares by 1.452433. The letter postdates the ex-date by almost a month; the September 2026 adjusted history therefore cannot establish the contemporaneous price history available in October 2025. [Company COA guidance, pages 2–3](https://nsearchives.nseindia.com/corporate/TATAMOTORSSJS_12112025224654_NSEBSECOAFINAL.pdf).

## ABFRL and VEDL: reused established evidence

This pass reuses the completed [event investigation](kite-corporate-action-exceptions-2026-09-07.md) and [demerger adjustment investigation](demerger-adjustment-conventions-2026-09-07.md), rather than asserting a fresh full-ledger review.

ABFRL's ex/record date is **22 May 2025**, with one ABLBL share per original ABFRL share. Its COA allocation is **75.68% ABFRL / 24.32% ABLBL**. The dated company evidence remains the [record-date letter](https://www.abfrl.com/wp-content/uploads/2025/05/SE-Record-Date.pdf), [22 May COA letter](https://www.abfrl.com/wp-content/uploads/2025/06/ABFRL-ABLBL-Apportionment-of-Cost.pdf) and [NSE special-session circular](https://nsearchives.nseindia.com/content/circulars/CMTR68037.pdf).

VEDL's exchange ex-date is **30 April 2026**; scheme effective/record date is **1 May 2026**. One original share entitles the holder to one share in each of **Vedanta Aluminium Metal Limited, Talwandi Sabo Power Limited, Malco Energy Limited and Vedanta Iron and Steel Limited** under the dated company documents. The **16 May 2026** allocation assigns **52.34%** to the continuing parent and respectively **7.15%, 12.23%, 21.49%, 6.79%** to those four entities. This is not a 1.910585-for-one parent-share split. [Company entitlement notice](https://www.vedantalimited.com/public/uploads/19056/VEDLSEIntimationRecordDate20April2026signed.pdf), [NSE ex-date circular](https://nsearchives.nseindia.com/content/circulars/FAOP73857.pdf), [company COA letter](https://www.vedantalimited.com/public/uploads/19416/VEDLSEIntimationCostofApportionmentsigned.pdf).

## Implication for the quantity evidence inventory

A homogeneous stock split changes the number of units representing the same security. These demergers distribute different businesses into separate securities, while tax guidance divides historical acquisition cost between them. Our inference from the approximate reciprocal agreement, supported by Zerodha's documented COA chart convention, is that vendor rescaling explains the noninteger volume observations. It does not supply a physical parent-share lot size, exchange execution price, or shareholder total-return factor. [Zerodha chart adjustment policy](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/charts/articles/kite-charts-not-matching-as-per-the-records-in-nse-or-bse).

Keep their integer entry increments **unknown in the current split-only evidence model**. Converting the observed decimal to a rational number and imposing its denominator as a trading lot would manufacture a convention from vendor chart scaling. It would not prove exchange-valid physical sizing. Likewise, adding all resulting shares on top of unreconciled adjusted parent prices can double count benefits.

Still missing for certification: complete prior/subsequent action coverage for every held interval; the vendor's exact historical revision and rounding records; a raw-price quantity convention; resulting-security account credit/tradability timing; and dated valuation of unlisted entitlements. Current ISIN/name documents identify entities but do not certify every earlier row's lineage. No complete no-further-actions claim is made through the snapshot end, and no currently recorded economic result is promoted by this classification.
