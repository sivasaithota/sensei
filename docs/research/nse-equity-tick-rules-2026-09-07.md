# NSE cash-equity tick sizes and adjusted-chart rounding

Research date: 7 September 2026. Scope: dated rules relevant to the frozen history ending 4 September 2026. No broker requests or market-data edits. **The rules below do not establish that the observed raw-versus-Kite differences are caused by rounding, and do not justify increasing a comparison tolerance.**

## Dated cash-market rules

**NSE/CMTR/62174, published 24 May 2024, effective 10 June 2024:** introduces ₹0.01 ticks for non-ETF securities below ₹250 in the specified equity series; the previous regular tick was ₹0.05. T+0 follows T+1. Initial determination uses the latest closing price available on 31 May 2024. Thereafter, the previous month's last trading-day close determines the next month's tick, effective its first trading day. [Official circular](https://nsearchives.nseindia.com/content/circulars/CMTR62174.pdf).

Corporate-action provisions are important: after a split, bonus, dividend, or rights issue, the **existing tick continues until the next monthly review**. A parent and a newly listed security arising from a corporate action retain the parent's tick until that review. Exchange computations including closing/base/equilibrium/settlement prices and price-band levels align with the applicable tick. Published security-master files contain the actual trading tick. [CMTR62174, pages 2–3](https://nsearchives.nseindia.com/content/circulars/CMTR62174.pdf).

**NSE/CMTR/67133, published 13 March 2025, effective 15 April 2025:** replaces the higher-price tick bands while leaving other provisions unchanged. [Official circular](https://nsearchives.nseindia.com/content/circulars/CMTR67133.pdf).

| Reference security price, ₹ | Cash-equity tick, ₹ |
|---|---:|
| Below 250 | 0.01 |
| 250 through 1,000 inclusive | 0.05 |
| Above 1,000 through 5,000 inclusive | 0.10 |
| Above 5,000 through 10,000 inclusive | 0.50 |
| Above 10,000 through 20,000 inclusive | 1.00 |
| Above 20,000 | 5.00 |

The first revision occurs on 11 April 2025 EOD, using the latest closing price available on 28 March 2025, for 15 April trading. Subsequently, the last trading-day close of the previous month determines the tick effective on the next month's first trading day. Exact ticks appear in `security.gz`, `nnf_security.gz`, or `NSE_CM_security_ddmmyyyy.csv.gz`. [CMTR67133, pages 1–2](https://nsearchives.nseindia.com/content/circulars/CMTR67133.pdf).

The 2026 search did not locate a later cash-equity revision superseding these bands. NSE's contract-specification page, updated 11 August 2026, still references FAOP67134 for stock futures following their underlying cash-security ticks. That is supporting continuity evidence, **not an exhaustive 2026 circular audit or a dated per-security tick record**. [NSE contract specifications](https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications), [FAOP67134](https://nsearchives.nseindia.com/content/circulars/FAOP67134.pdf).

## Application to the stocks under review

**Audit inference:** TATAINVEST, MCX, COFORGE, MAZDOCK, and HEG cannot be assigned one permanent tick by name, current price, or adjusted historical price. Determine the security's tick for the actual trade date using its dated security master and the then-effective rule. Crossing a price threshold intramonth is not itself a monthly review. A subdivision is not grounds for immediately dividing the live exchange tick by the share multiplier.

The operative price-step rules govern order entry in the exchange's trading system. They do not prescribe a vendor's retroactive transformation of past candles into a new share basis. [NSE Capital Market Regulations, section 2.5.6](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSECMregulations_6_0.pdf).

Consequently, a historical trade price, an exchange-calculated close, and a retrospectively adjusted chart value must remain distinct fields. This research has not fetched historical security masters or certified a tick for any specific local discrepancy. Mixed-sign differences of up to ₹0.50 in adjusted units, supplied as local context, remain unexplained by this document.

## Kite adjustment rounding: not established

The historical-candle API documentation specifies the OHLCV response but does not specify a split-adjustment rounding algorithm. The July 2025 developer response on adjustment calculations says calculations differ by corporate action; it does not publish decimal precision, tick selection, rounding direction, tie-breaking, or whether rounding occurs after each adjustment or only after the final composition. [Historical API documentation](https://kite.trade/docs/connect/v3/historical/), [Kite adjustment discussion](https://kite.trade/forum/discussion/15230/historical-data-with-price-adjusted-to-splits).

Other first-party statements are narrower: a July 2025 response lists adjusted corporate-action categories; an August 2026 response describes adjustment timing and delayed demerger treatment. Neither establishes rounding. [Adjustment categories](https://kite.trade/forum/discussion/15358/documentation-of-adjustments-in-historical-data), [adjustment timing](https://kite.trade/forum/discussion/16099/split-adjustment-data).

A 2018 response about relaying WebSocket price fields and a 2025 explanation of RSI calculation differences concern different interfaces/calculations. Neither can certify an adjusted daily-candle rounding convention. [WebSocket precision discussion](https://kite.trade/forum/discussion/4332/average-price-field-precision-only-up-to-2-decimals), [RSI discussion](https://kite.trade/forum/discussion/15618/rsi-values-not-matching-kite-daily-candles-off-by-0-02).

**Unresolved:** Kite's adjusted-chart rounding convention; the dated exchange tick for each discrepant local row; and the cause of each raw-versus-adjusted difference. Preserve these unknowns in the raw execution replay rather than converting a plausible tick-size explanation into a verified data repair.

## Follow-up: bounded HEG / MAZDOCK execution replay

For the pre-10-June-2024 ordinary-equity regime, NSE's indices FAQ, marked updated 4 January 2023, explicitly states that the tick is ₹0.05 for all stocks. CMTR62174 subsequently identifies ₹0.05 as the existing tick immediately before its June change. Together these support the regular ₹0.05 premise for **HEG 16 April–3 May 2024** and **MAZDOCK 30–31 May 2024**, assuming the raw receipts identify the ordinary NSE equity security/series. This is a rule-based inference, not an independently retrieved security-master receipt for those dates. [NSE FAQ](https://www.nseindia.com/static/products-services/indices-faqs).

The April 2024 consolidation was also inspected: CMTR61813, dated 29 April, replaces the June 2023 consolidation. Section 3.3, page 49, sends readers to product parameters/security masters for securities other than the enumerated one-paise instruments; it does **not** supply a blanket ₹0.05 regular-equity rule. Its explicit ₹0.05 table on page 11 concerns special pre-open, so must not be repurposed as proof for every normal-market trade. The retrieved copy is an NSE-authored PDF hosted by Ricago; direct NSE PDF retrieval failed. [CMTR61813 mirror](https://www.ricago.com/assets/front/base/file/file_management/1800.pdf).

For **MAZDOCK 18–27 June and 5 July 2024**, retain the **31 May and 28 June raw closing-price receipts**, respectively, to support the monthly threshold classification. If each applicable reference close is at least ₹250, the regular ₹0.05 classification follows. Current-day prices above ₹250 alone do not establish it. A caller-specified constant tick may describe only this evidenced interval; it should not silently become a global tick rule. These are requirements for the bounded replay, not a finding that the required local receipts have already been checked.
