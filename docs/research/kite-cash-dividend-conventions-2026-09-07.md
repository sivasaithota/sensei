# Kite cash-dividend conventions and the OFSS exception

Research date: 2026-09-07. Bounded primary-source review for the stock backtest. This note does not change data, certify returns, or establish a complete OFSS corporate-action ledger.

## What Kite documents

Zerodha's current chart policy says historical OHLC is adjusted for bonuses, stock splits, rights issues, spin-offs and extraordinary dividends, defining the latter as **2% and above of the underlying stock's market value**. Exchange records instead contain actual historical trading prices. This is not a promise that Kite provides a total-return series incorporating every ordinary cash dividend. The page does **not** publish a mathematical algorithm for backward cash-dividend price adjustments. [Official chart policy](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/charts/articles/kite-charts-not-matching-as-per-the-records-in-nse-or-bse).

Current Kite staff responses say historical adjustments occur in the beginning-of-day process on the ex-date before the market opens, with a later clarification referring to 8 AM. Staff also says volume is adjusted for relevant share actions, including bonuses and splits, **but not dividends**, and that there is no dedicated corporate-actions API. These describe the vendor process, rather than proving the exact revision time of each archived instrument. [Kite historical API policy and timing](https://kite.trade/forum/discussion/15971/getting-the-right-closing-prices-adjusted-for-corporate-actions).

Older responses conflict or lack precision. In 2019, Kite staff ultimately clarified that only splits and bonuses were adjusted, explicitly excluding dividends. A short September 2024 answer to a question titled “regular dividends” says adjusted prices appear from the ex-date without explaining coverage or formula. Neither should override the more specific current policy or be used as a historical blanket guarantee. Store the documentation version and actual capture timestamp. [2019 clarification](https://kite.trade/forum/discussion/4014/is-historical-data-dividend-adjusted), [September 2024 timing answer](https://kite.trade/forum/discussion/14427/in-historical-data-are-prices-adjusted-for-regular-dividends-how-quickly-is-it-updated).

**Conclusion:** treat Kite as vendor-adjusted OHLCV with documented action classes, not as verified raw prices, universally dividend-adjusted prices, or a certified total-return index. This bounded search did not locate an official equity-history specification resolving **additive/subtractive versus proportional** dividend adjustment, cumulative composition, rounding, or the historical point at which the dividend policy changed.

## Derivatives subtraction is a different contract

Zerodha explicitly describes subtracting extraordinary dividends from futures reference prices and option strikes, while leaving dividend-related contract lot sizes unchanged. It distinguishes ordinary dividends below 2%, for which those derivative adjustments are not made. This is a **derivatives-contract** rule; it does not establish how Kite rewrites every earlier equity candle. [Zerodha F&O adjustment policy](https://support.zerodha.com/category/console/corporate-actions/ca-others/articles/impact-of-corporate-actions-on-derivatives).

The official OFSS clearing notice for May 2024 likewise subtracts ₹240 from relevant futures' last cum-date settlement prices and option strikes. It specifies May 6 as the last cum-dividend date and May 7 as the ex-date. That is strong evidence for derivatives settlement treatment, but cannot certify either a constant ₹240 subtraction or a multiplicative factor throughout historical cash-equity OHLC. [NCL/CMPT/61793, April 29, 2024](https://nsearchives.nseindia.com/content/circulars/CMPT61793.pdf).

## Verified OFSS event notices

| Declaration | Cash amount per share | Record date | Exchange ex-date | Company's stated payment deadline |
|---|---:|---|---|---|
| April 24, 2024 | ₹240 interim | May 7, 2024 | May 7, 2024 | On or before May 23, 2024 |
| April 25, 2025 | ₹265 interim | May 8, 2025 | May 8, 2025 | On or before May 17, 2025 |

The 2024 company notice gives the amount, record date and deadline and says the board meeting concluded at **19:28 IST on April 24**. It therefore was not information available at that day's market close. NSE's separate circular fixes the ex-date. [2024 company board outcome](https://nsearchives.nseindia.com/corporate/OutcomeofBoardMeeting24042024sd_24042024194705.pdf), [NSE/FAOP/61775](https://nsearchives.nseindia.com/content/circulars/FAOP61775.pdf).

The 2025 company filing supplies its amount, record date and payment deadline; NSE confirms the ex-date and publishes revised option strikes separately. Its indexed first-page text was accessible, while the full 10.7 MB company PDF exceeded the browser reader's size limit. No exact shareholder bank-credit date or intraday public dissemination timestamp is inferred from the document's filename. [2025 company board outcome](https://nsearchives.nseindia.com/corporate/OFSS_25042025200814_OutcomeofBoardMeeting25042025.pdf), [NSE/FAOP/67797](https://nsearchives.nseindia.com/content/circulars/FAOP67797.pdf), [NSE/FAOP/67899](https://nsearchives.nseindia.com/content/circulars/FAOP67899.pdf).

These two events are not an exhaustive adjustment history. For example, the company's later annual report also records an October 17, 2025 declaration of ₹130 and an April 22, 2026 declaration of ₹270. Their existence means a September 2026 capture can reflect more events than the two May dividends alone; their complete ex/payment-date reconciliation is outside this bounded note. [OFSS 2025–26 annual report, retained-earnings note](https://www.oracle.com/a/ocom/docs/industries/financial-services/ofss-software-limited-ar-2025-26.pdf).

## Why the January 2024 ratios are insufficient

The prior investigation recorded these raw NSE and archived Kite values. They are observations, not newly declared corporate-action factors. [Local evidence and source request identities](kite-corporate-action-exceptions-2026-09-07.md).

| Date | Raw close | Kite close | Kite/raw, calculated | Raw minus Kite, calculated |
|---|---:|---:|---:|---:|
| January 17, 2024 | 5,086.20 | 4,564.50 | 0.89742834 | 521.70 |
| January 18, 2024 | 6,545.50 | 5,939.50 | 0.90741731 | 606.00 |

Our calculation: the raw close return is **28.6914%**, versus **30.1238%** for Kite. A single constant multiplier would preserve the raw return; one constant subtraction would produce equal raw-minus-Kite differences. These two observations fit neither simple hypothesis. That does not identify the actual transformation or prove a corporate action occurred between the sessions. A general affine formula could be fitted to two points but would merely fit those observations, not validate a vendor rule.

The dated earnings release on January 17 provides contemporaneous context for the genuine large market move. The verified May dividend notices do not create an ex-dividend event in January. Keep the move and investigate the adjustment discrepancy separately; do not erase the jump or promote a daily ratio change into an action ledger. [OFSS January 17, 2024 earnings release](https://www.oracle.com/in/a/ocom/docs/industries/financial-services/ofss-q3fy24-pr.pdf).

## Cash accounting and double counting

The following is an accounting example, not a claim about Kite's undisclosed formula. Suppose one actual share is bought for ₹100, goes ex a ₹10 dividend, and is sold for ₹90. Ignoring costs and taxes, economic proceeds are ₹90 plus the ₹10 entitlement, so the gain is zero. If an adjusted series rewrites that entry price to ₹90 and a simulator also adds ₹10 cash, it records a spurious ₹10 gain. Proportional adjustments can create the same category of duplication; adjusted returns are not automatically actual trade cash flows.

Conversely, omitting cash dividends from an actual-price ledger understates returns. The coherent choices are an actual-price ledger with dated entitlements, or a precisely specified synthetic return convention with matching units and no duplicate benefit. Unknown Kite adjustment mechanics make blindly adding **all** dividends to its historical prices unsafe. An event-by-event reconciliation must identify which benefits the data already embeds.

Zerodha says dividends are normally paid directly to the linked bank account. The company/RTA handles credits; broker documentation does not provide each shareholder's exact payment timestamp. Therefore an ex-date entitlement should be a receivable, not instant spendable broker cash. A declared payment deadline is not evidence of actual receipt; any cash-availability assumption must be explicit. [Zerodha dividend eligibility and payment](https://support.zerodha.com/category/console/corporate-actions/dividends/articles/i-hold-stocks-of-a-company-that-issued-dividends-how-and-when-will-i-get-the-dividends).

Splits and bonuses require consistent share units too. A five-for-one split multiplies actual shares by five; a two-for-one bonus adds two shares per original share. Price rescaling and a second independent quantity credit would duplicate the same benefit if the simulator already bought in post-action synthetic units. Preserve event ratios, eligibility, credit/tradability timing and actual quantities in the execution ledger. [Zerodha stock-split explanation](https://support.zerodha.com/category/console/corporate-actions/stock-splits/articles/stock-split), [Zerodha bonus explanation](https://support.zerodha.com/category/console/corporate-actions/bonus/articles/bonus-issue).

## Required before a dividend-aware backtest is certified

Reconcile actual held periods against dated cash/share actions; establish raw trade-price coverage; identify every vendor transformation affecting those periods; and separate receivables, available cash and share entitlements. Use contemporaneously available announcements for signals and operational decisions. Retrospectively revised prices can serve a defined analytical purpose, but their September download date does not establish what was observable years earlier. No return certification follows from this note alone.
