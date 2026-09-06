# Low-cost NSE daily data options — 6 September 2026

**Use Zerodha/Kite for the first data-quality probe: the user confirmed it is already their broker.** Proceed if paid data access is already enabled; otherwise the ₹500/month data subscription needs the user's acceptance. Having a Zerodha account does not imply having paid Kite data access. Upstox's free read-only data token is a fallback if the user declines that cost and has suitable access. This recommendation prioritizes existing access and cost; it does not rank feed accuracy without samples. AccelPix is excluded by the user's cost constraint.

## Verified advertised costs and coverage

| Provider | Historical-data cost | Daily history capability | Relevant uncertainty |
|---|---|---|---|
| **Upstox** | Analytics Token explicitly **free** | V3 `historical-candle/{instrument_key}/days/1/{to}/{from}`; documented availability from January 2000, up to ten years per daily request | No adjustment convention or special-session completeness established in the inspected docs. |
| **FYERS** | Historical, quotes and real-time data **free for clients** | History API; official launch announcement described 20+ years of daily equity data | Depth claim is from a 2021 announcement, not a per-symbol coverage guarantee; adjustments still need verification. |
| **Angel One SmartAPI** | API access advertised **free** | `getCandleData`, `exchange=NSE`, `interval=ONE_DAY`; maximum 2,000 days **per request** | The request-window limit is not a promise of total history depth. No adjustment convention verified. |
| **Zerodha Kite Connect** | **₹500/month per API key** for live + historical data; free Personal API excludes those data services | `GET /instruments/historical/{instrument_token}/day`; documentation says history spans several years | Exact stock coverage and adjustment behavior must be checked. Do not rely on old ₹2,000 historical add-on prices. |
| **DhanHQ** | **₹499 plus taxes/month** for Data APIs; trading APIs are separate | `POST /v2/charts/historical`; docs describe daily history back to inception | Official FAQ confirms bonus/split adjustment, but does not establish cash-dividend/volume/demerger conventions. |

Cost/coverage sources: [Upstox Analytics Token](https://upstox.com/developer/api-documentation/analytics-token/), [Upstox daily-history V3](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/); [FYERS datafeed pricing](https://support.fyers.in/portal/en/kb/articles/do-i-need-to-pay-for-datafeeds), [FYERS historical-depth announcement](https://fyers.in/community/t/introducing-my-api/12160); [Angel free API offering](https://smartapi.angelone.in/), [SmartAPI historical endpoint](https://smartapi.angelone.in/docs); [Zerodha data-plan pricing](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/historical-data-and-live-market-data-payment-plan), [Kite historical API](https://kite.trade/docs/connect/v3/historical/); [Dhan Data API pricing](https://dhan.co/support/platforms/dhanhq-api/how-can-i-access-live-market-data-through-dhan/), [Dhan daily history](https://dhanhq.co/docs/v2/historical-data/), [Dhan adjustment FAQ](https://dhan.co/support/platforms/dhanhq-api/is-the-historical-data-from-dhan-s-data-api-adjusted-for-corporate-actions-like-bonuses-and-splits/).

The quoted amounts concern API/data access. They do not establish that brokerage, account charges or every optional service is free. Zerodha's cited support page states ₹500 without resolving tax treatment; Dhan explicitly says plus taxes.

## Free fallback if paid Kite data is unavailable

Upstox's documented Analytics Token has one-year validity, supports read-only historical-data GET calls, and needs no static IP for the historical-data category. This fits a data acquisition task without granting order-placement capability. The page directs users to Developer Apps and allows one token per account; it does **not** establish account-free access. No token was requested, generated or used during this research. [Official token documentation](https://upstox.com/developer/api-documentation/analytics-token/).

An existing free broker account may provide a fallback. There is no evidence here that opening another account, paying for Dhan/Kite, or buying an expensive data feed will automatically resolve the actual defects.

## Required sample before choosing a feed

Use read-only authenticated access for a bounded TCS, BSE and ITC sample. Check the four actual exchange sessions missing from Yahoo—2024-01-20, 2024-03-02, 2024-05-18 and 2026-02-01—against the already verified raw NSE bhavcopies. Also check BSE's May 2025 bonus, nearby TCS dividends and ITC's demerger, preserving original API responses and hashes. Establish price/volume adjustment semantics before combining bars with existing adjusted history.

**Special-session coverage remains untested for every candidate in this comparison.** None of the inspected daily-candle offerings establishes a complete point-in-time Nifty 500 membership history, historical security-identity mapping, or guaranteed former-member/delisted-stock coverage. Those remain separate data requirements. A provider's “adjusted” label does not certify all corporate-action types or compatibility with Yahoo's adjusted series.

No authenticated requests, purchases, account creation, external messages or code changes were made for this comparison. The next action is a single provider sample using the user's existing broker access, followed by a documented pass/fail on the known defects.
