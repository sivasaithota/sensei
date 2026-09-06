# Corporate-action and event exceptions in recent Kite history

Research date: 2026-09-07. This bounded investigation classifies six large close-to-close moves identified in the recent research snapshot. It does not certify a complete corporate-action ledger, calculate replacement adjustment factors, or alter source data. The price comparisons below were independently read from the frozen Kite archive and the internally verified local raw NSE bhavcopy corpus.

## Decision summary

| Security and flagged date | Evidence-backed classification | Remaining requirement |
|---|---|---|
| ABFRL, 2025-05-22 | Confirmed demerger into ABLBL; vendor has already adjusted earlier prices, but a large discontinuity remains. | Reconcile vendor adjustment policy and entitlement valuation; inspect positions crossing the event. |
| VEDL, 2026-04-30 | Confirmed demerger into four additional companies; earlier prices are already partly adjusted relative to raw exchange bars. | Reconcile all four entitlements and existing adjustments before computing portfolio returns. |
| SCI, 2023-03-31 | Confirmed demerger record date; positive vendor jump does not establish a clean economic return. | Exchange price discovery and adjustment reconciliation remain unresolved. |
| OFSS, 2024-01-18 | Official earnings announcement immediately precedes the jump; raw NSE prices also show a large positive move. | Keep the market move; reconcile why vendor and raw return percentages differ. |
| ZEEL, 2024-01-23 | Official Sony termination announcement precedes the fall; raw NSE bars corroborate its approximate magnitude. | Retain the loss event; ordinary data and execution checks still apply. |
| FORCEMOT, 2024-02-14 | NSE listing resumes after a documented withdrawal interval. | Treat as a return across a trading gap, not one ordinary consecutive trading day. |

## ABFRL: confirmed distribution, unresolved vendor economics

ABFRL's May 12, 2025 exchange disclosure fixes **May 22, 2025** as the record date and grants **one ABLBL share per ABFRL share**. The issued ABLBL shares were proposed for exchange listing subject to approvals. [Company record-date and entitlement notice](https://www.abfrl.com/wp-content/uploads/2025/05/SE-Record-Date.pdf)

NSE Indices' May 19 announcement confirms a special price-discovery session for ABFRL on May 22, following NSE circular CMTR68037. It adds the resulting company as a dummy index constituent from that date, demonstrating that the distributed security must be accounted for separately in index economics. A dummy index constituent is not an executable stock quote. [Official index corporate-action notice](https://niftyindices.com/Press_Release/ind_prs19052025.pdf)

| Session | Raw NSE close | Kite close | Raw volume | Kite volume |
|---|---:|---:|---:|---:|
| 2025-05-21 | 268.95 | 203.55 | 16,517,340 | 21,825,237 |
| 2025-05-22 | 89.85 | 89.85 | 35,644,420 | 35,644,420 |

Kite's observed close return is about **−55.86%**. Its pre-event prices and volumes differ from raw NSE values while the ex-date bar agrees. This establishes that the series is not simply raw exchange history. It does **not** establish which adjustments were applied or the correct distribution-inclusive return. Do not “repair” this by multiplying prices by the 1:1 share entitlement: equal share counts do not imply equal values.

## VEDL: four entitlements and distinct ex/record dates

Vedanta's April 20, 2026 notice fixes **May 1, 2026** as scheme effective date and record date. For each existing Vedanta share, it specifies one share in each of VAML, TSPL, MEL and VISL. It also states the intended TSPL and MEL names as Vedanta Power and Vedanta Oil and Gas. [Company record-date and consideration notice](https://www.vedantalimited.com/public/uploads/19056/VEDLSEIntimationRecordDate20April2026signed.pdf)

NSE circular **FAOP73857**, dated April 22, explicitly identifies the demerger ex-date as **April 30, 2026**, with capital-market price discovery on that date. Keep this exchange ex-date distinct from the scheme's May 1 effective/record date. Zerodha's own support page explains that May 1 is a market holiday. [NSE demerger circular](https://nsearchives.nseindia.com/content/circulars/FAOP73857.pdf), [broker operational explanation](https://support.zerodha.com/category/console/corporate-actions/ca-others/articles/vedanta-demergers)

| Session | Raw NSE close | Kite close | Raw volume | Kite volume |
|---|---:|---:|---:|---:|
| 2026-04-29 | 773.60 | 404.90 | 54,738,724 | 104,582,985 |
| 2026-04-30 | 271.55 | 271.55 | 73,870,853 | 73,870,853 |

The vendor close return is about **−32.93%**. Earlier history is already different from the raw exchange history. Neither the complete raw price drop nor the residual vendor drop alone is a validated total return on an eligible holding. Crediting four new share positions on top of an already adjusted synthetic price series could also double count value. A coherent raw-price-plus-entitlement ledger or a fully reconciled adjusted-return convention is required. No exact adjustment factor is certified here.

## Other large moves

**SCI:** NSE's announcement record identifies March 31, 2023 as the demerger record date, disclosed March 20. The Ministry of Ports, Shipping and Waterways' SCI page independently records a 1:1 SCILAL allocation to eligible SCI shareholders. These identify a real distribution event; they do not certify the vendor's approximately **+30.00%** return from ₹69.86 on March 29 to ₹90.82 on March 31. Those two raw exchange sessions are unavailable in the local bhavcopy corpus. [NSE SCI announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol=SCI&tabIndex=equity), [ministry SCI record](https://www.mopsw.nic.in/sagarvidyakosh/index.php?title=SCI)

The company disclosure index links a March 20 record-date notice and a May 12 cost-of-acquisition notice. The attachment reader could not retrieve them during this investigation, so their contents are not asserted here. A tax cost-allocation percentage would in any event not automatically be a market-return adjustment factor. [SCI company disclosure index](https://www.shipindia.com/investors/disclosures_under_listing_regulation/12)

**OFSS:** Its January 17, 2024 results release reports quarterly revenue growth of 26% and net income growth of 69% year on year. The following day's market jump has a contemporaneous earnings event; this is a supported context, not proof of sole causation. Raw NSE closes are ₹5,086.20 on January 17 and ₹6,545.50 on January 18, approximately **+28.69%**; Kite closes are ₹4,564.50 and ₹5,939.50, approximately **+30.12%**, with matching daily volumes. Keep the jump and investigate the price-adjustment difference instead of deleting it for exceeding a threshold. [Official earnings release](https://www.oracle.com/in/a/ocom/docs/industries/financial-services/ofss-q3fy24-pr.pdf)

**ZEEL:** Sony issued its merger-termination notice on January 22, 2024. Raw NSE closes fall from ₹231.40 on January 20 to ₹155.95 on January 23, approximately **−32.61%**; Kite records ₹226.64 and ₹152.74, approximately the same percentage change, with matching volumes. This corroborates a large market loss around the announced event; magnitude alone is not a reason to exclude it. [Sony's original termination notice](https://www.sony.com/en/SonyInfo/IR/news/20240122_E.pdf)

**FORCEMOT:** The February 14, 2024 bar follows October 25, 2023 in the captured sequence because of the documented NSE withdrawal interval. The approximately +31.93% change spans that interval. See the dated eligibility evidence in [security exceptions](kite-security-exceptions-2026-09-07.md).

## Reproducibility and baseline implications

Frozen plan: `4a26765db63fd41f2e11a1f40e718ef2517a0a3ac6a768eab03d99863b7d2c14`. All Kite requests below cover 2022-01-01 through 2026-09-04; original responses remain under `~/.local/share/sensei/kite/raw/<first-two-hash-characters>/<request-hash>/response.bin`.

| Symbol | Request hash |
|---|---|
| ABFRL | `85c94cdd43619613349e3988d7bbdf35c10127a09b423e134091604bad97b058` |
| VEDL | `e5a10cfe2fbccdfb985756679dbc6a1a9000a6c5f996b273fde7e8d11e593c1f` |
| SCI | `a2071a86988761f221170071fa1c3251bd5c9e89003fbcc34d6326ba5a17d76d` |
| OFSS | `ae551bed22645364e82f168537b4864674a3eb6663fd72cfbc5d84a748b2901c` |
| ZEEL | `5e39fdfce857209db3829e09a92fb58a9aac41fc32ffa113778297dc85b6bc06` |

Raw exchange comparisons used `QuarantinedRawBhavcopy.raw_session` for each stated date, selecting the EQ row. This verifies internal artifact integrity but does not promote raw data into adjusted-price admissibility.

The immediate baseline check is whether positions or rolling signal windows cross these events. An unheld demerger can still distort momentum, volatility, ATR stops, liquidity estimates and stock ranking. A fixed large-return filter cannot distinguish a distribution, a suspension gap, an earnings jump and a real crash. Preserve all original observations and attach event-specific evidence; certify economics only after reconciling the affected price convention, position entitlements and timing.
