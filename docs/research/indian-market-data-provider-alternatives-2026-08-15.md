# Indian market-data provider alternatives

**Reviewed:** 2026-08-15
**Scope:** NSE cash equities for research-grade daily/EOD backtesting, not live
execution
**Status:** provider-selection research only; no provider has been approved

## Decision

**Superseded acquisition decision, 6 September 2026:** the owner has ruled
out AccelPix on cost grounds. Do not follow the AccelPix trial actions below
as the current plan. Evaluate lower-cost broker data first; see the
[updated source comparison](stock-low-cost-data-options-2026-09-06.md).
The original investigation below is retained as historical context.

Do not wait exclusively for TrueData. Request **historical API trials from
Global Financial Datafeeds (GFDL) and AccelPix in parallel**, then run both
through the same provider-neutral acceptance audit. They are the two practical
Indian-market candidates whose official material currently establishes an API,
more than ten years of NSE cash EOD history, a trial path, and NSE-authorized
vendor status.

Neither vendor's public documentation establishes all of the properties Sensei
needs: inactive/delisted coverage, effective-dated ISIN and symbol lineage,
point-in-time Nifty 200/500 membership, and a complete adjustment methodology
covering complex reorganizations. A passing price feed must therefore be paired
with **NSE Indices historical constituent data** (or, temporarily, a carefully
audited reconstruction from official reconstitution notices).

Continue using Yahoo only as a secondary discrepancy detector. Do not use it,
GFDL, AccelPix, EODHD, or a broker candle API as final strategy evidence until
the actual delivered sample passes the acceptance suite.

## Shortlist

| Source | What official material establishes | Missing or unproven | Role |
|---|---|---|---|
| **Global Financial Datafeeds** | NSE-authorized CM vendor; REST/WebSocket historical API; NSE cash daily/weekly/monthly history since 2010; historical-only package; personal-use API; trial path | Delisted/inactive universe, ISIN lineage, symbol changes, point-in-time membership and complete CA adjustment policy are not documented; price is quote-only | **Trial now — first choice** |
| **AccelPix** | NSE-authorized CM vendor; REST and Python historical APIs; symbol master; free API trial; advertises 15+ years of EOD and automatic split/bonus adjustments | Delisted coverage, ISIN lineage, complex actions, point-in-time membership and API price are not documented | **Trial now — first choice** |
| **NSE Data & Analytics** | Authoritative CM EOD/bhavcopy and security details; SFTP/online delivery; published 2026 domestic tariff | Not a ready-made adjusted research database; constituent history and normalized fundamentals remain separate | Authority/long-term source if budget permits |
| **NSE Indices** | Ongoing and historical constituent product with company names, identifiers, market cap, weights and prices; intended for quantitative research and portfolio construction | Quote-only; coverage dates and usage rights require contract confirmation | **Required survivorship-bias control** |
| **CMIE Prowess\_{dx}** | Since 1990; daily prices, corporate actions, quarterly/annual statements; retained companies rather than deliberately dropping them; bulk-style downloads | Designed for academia; individual trading rights, API automation, filing availability timestamps and current price are not established publicly | Fundamentals/research option, subject to written rights |
| **Capitaline** | More than 35,000 Indian companies, more than ten years of financials, quarterly results, ownership, prices and corporate events; ₹2,50,000/year/user | No public API or point-in-time filing-timestamp guarantee found | Expensive fundamentals fallback |
| **EODHD** | Self-service EOD API, splits/dividends, adjusted close, delisted lookup, bulk daily endpoint and $19.99/month personal EOD plan | Its public delisted documentation only guarantees symbol-change history for US; India-specific inactive coverage, identifiers, source lineage and index membership are not established | Cheap independent comparator, **not certification source** |
| **Bloomberg / FactSet / Refinitiv / other enterprise channels** | NSE Indices names enterprise redistribution channels; NSE's authorized-vendor list includes major enterprise vendors | Quote-only and likely disproportionate for a personal ₹3 lakh research account; exact historical fields require a sales contract | Escalation path, not first purchase |

## 1. Global Financial Datafeeds

NSE's current authorized-vendor list includes Global Financial Datafeeds for
Capital Market data. GFDL's own API documentation says its historical API
supports tick, minute, day, week and month periodicities, with NSE cash daily,
weekly and monthly history **since 2010**. It provides `GetHistory` through REST
and WebSocket APIs, and permits purchasing a historical-only package
([NSE vendor list](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/ListofAuthoizedVendors_NSEDATA.pdf),
[GFDL coverage](https://globaldatafeeds.in/global-datafeeds-apis/global-datafeeds-apis/introduction/type-of-data-available/),
[GFDL API comparison](https://globaldatafeeds.in/global-datafeeds-apis/global-datafeeds-apis/pricing-sales/api-pricing/)).

GFDL does not publish a fixed API price; it asks users to send their
requirements to sales. Its API product is explicitly available to individuals
for personal use, while commercial use requires exchange agreements. A public
free-trial route is available
([purchase eligibility](https://globaldatafeeds.in/global-datafeeds-apis/global-datafeeds-apis/pricing-sales/who-can-purchase/),
[free trial](https://globaldatafeeds.in/start-a-free-trial/)).

The official documentation does **not** prove that a historical instrument can
still be requested after delisting, that old symbols are mapped to ISINs, or
that adjusted bars handle dividends, rights, mergers and demergers. These are
sample-test questions, not assumptions.

## 2. AccelPix

NSE's authorized-vendor list includes AccelPix for Capital Market data. AccelPix
advertises a free API trial, more than 15 years of EOD history, and automatic
adjustment for splits and bonuses. Its REST documentation exposes date-range
EOD retrieval and a downloadable instrument master; its Python package also
supports EOD history
([NSE vendor list](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/ListofAuthoizedVendors_NSEDATA.pdf),
[AccelPix product site](https://accelpix.com/),
[REST API](https://support.accelpix.com/portal/en/kb/articles/pix-apis-realtime-and-historical-data-in-rest),
[Python API](https://support.accelpix.com/portal/en/kb/articles/pix-apis-realtime-and-historical-data-in-python)).

The public evidence is stronger than Yahoo for operational API access, but it
still does not demonstrate inactive securities, effective-dated identity,
dividend/rights/demerger treatment or historical index membership. The symbol
master example is a current master and is not proof of a historical master.
API pricing is quote-only; desktop/charting prices must not be mistaken for API
pricing.

## 3. Direct official products

### NSE Data & Analytics

NSE offers Capital Market EOD files containing bhavcopy and security/trade
details, with EOD delivery through SFTP and historical data through its online
platform. Effective 1 April 2026, the published domestic tariff lists:

- Capital Market EOD: **₹1,00,000 per year/site**, excluding taxes;
- Capital Market historical trade data: **₹1,10,000 per year/site**, excluding
  taxes.

The product is authoritative but is raw exchange data, not a point-in-time
research database with normalized issuer lineage and adjusted bars
([NSE product](https://www.nseindia.com/static/market-data/eod-historical-data-subscription),
[2026 domestic tariff](https://nsearchives.nseindia.com/web/mediaattachment/2026-04/Download_Pricing_file_-_Domestic_clients_20260424122229.pdf)).

NSE's research-data classification is useful for a lower-cost build: it lists
historical OHLC/volume, bhavcopies, listed-company financial results,
shareholding, announcements and corporate actions as freely available first-
basket data, while voluminous historical EOD, corporate data and historical
security masters are chargeable. That establishes availability, not blanket
permission for unattended scraping; storage and automated-use rights should be
confirmed in writing
([NSE research-data list](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Data%20list%20under%20NSE%20Data%20Sharing%20Policy%20for%20Research%20and%20Analysis_20250728.pdf),
[NSE data policy](https://www.nseindia.com/static/market-data/nse-data-policy)).

### NSE Indices

NSE Indices separately sells ongoing and historical constituent data containing
company names, identifiers, market capitalization, weights and prices. It
explicitly lists quantitative research and portfolio construction as uses.
This is the cleanest available answer to the current-universe survivorship bug;
the quote, coverage dates and internal-algo rights must be confirmed with
`indices@nse.co.in`
([NSE Indices data subscription](https://www.niftyindices.com/offerings/data-subscription)).

## 4. Fundamentals alternatives

CMIE says Prowess\_{dx} contains standardized financial statements, quarterly
statements for listed companies, daily share prices, corporate actions and
shareholding, with time series since 1990. It also says companies are not
deliberately dropped after entering the database. This is attractive for
survivorship-aware academic research, but the product is specifically described
as an academic service. Sensei must obtain written permission for personal algo
research, automated extraction and local retention, and verify that original
filing/broadcast timestamps and revisions are present before using any fact in a
point-in-time backtest
([CMIE Prowess\_{dx}](https://prowessdx.cmie.com/)).

Capitaline publishes broader commercial terms: more than 35,000 Indian listed
and unlisted companies, more than ten years of financials, quarterly results,
ownership, share prices and corporate events, priced at **₹2,50,000 per
year/user**. Its public page does not establish an API or filing-availability
timestamps, so it is not presently an integration-ready choice
([Capitaline](https://www.capitaline.com/Demo/Plus.aspx)).

GFDL also publishes REST endpoints for corporate actions, financial results,
ratios, shareholding and index constituents, but its public table limits most
corporate history to **30 days** and does not claim historical constituent
membership. It is useful for forward collection, not for rebuilding a ten-year
point-in-time fundamental database
([GFDL corporate API coverage](https://docs.globaldatafeeds.in/type-of-corporate-data-available-1142925m0)).

## 5. Low-cost international comparator

EODHD's $19.99/month personal EOD plan advertises worldwide EOD history,
splits/dividends, adjusted data, delisted data and a bulk-per-day API. Its EOD
endpoint provides raw OHLC, adjusted close and volume, and its free tier can be
used to test recent samples
([pricing](https://eodhd.com/pricing),
[EOD API](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes),
[bulk API](https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends)).

However, EODHD's own delisted-data documentation says symbol-change history is
currently US-only. It does not publicly establish point-in-time Nifty
membership, Indian ISIN lineage, or complete India-specific inactive coverage.
It should therefore be tested as a cheap independent comparator, not selected
as the sole evidentiary source
([delisted-data documentation](https://eodhd.com/financial-apis/delisted-stock-companies-data-2)).

## 6. Mandatory trial acceptance contract

Send GFDL and AccelPix the same request and require written answers plus a
machine-readable sample. A provider is not approved because its current active
stocks look correct.

### Required fields and rights

1. NSE EQ daily OHLCV for at least 2010-present, including inactive and delisted
   securities.
2. Stable identity: ISIN, exchange, series and effective-dated ticker/company
   name history; predecessor/successor links for reorganizations.
3. Raw and adjusted bars, with the exact adjustment formula and event version.
4. Splits, consolidations, bonuses, dividends, rights, mergers, demergers,
   capital reductions, listings and delistings.
5. Corrections/restatements and a reproducible revision policy.
6. Bulk or rate limits sufficient for roughly 500-1,000 symbols and ten-plus
   years without violating the contract.
7. Written permission for automated internal research, local storage, backups,
   derived statistics, model training and a private owner-only dashboard.
8. No redistribution of raw data is required.

### Forensic sample

The sample should contain at least:

- active securities with ordinary history;
- a renamed security;
- a delisted/inactive security;
- split and bonus cases;
- dividend and rights cases;
- a merger/demerger or capital-reduction case;
- a symbol reused or an ISIN changed after reorganization;
- one thinly traded security with suspended/no-trade sessions; and
- Nifty 200/500 additions and removals on several effective dates, if the vendor
  claims membership history.

The audit must compare vendor bars and actions against exchange records, detect
gaps/duplicates/impossible returns, verify adjustment-factor arithmetic, and
prove that the same query is reproducible later. Any unresolved identity or
corporate-action discrepancy fails the provider for locked validation.

## 7. Recommended acquisition combinations

### Option A — fastest and proportionate

1. Trial GFDL and AccelPix simultaneously.
2. Select the one that passes the forensic sample; use Yahoo and EODHD only as
   discrepancy sources.
3. Buy historical Nifty 200/500 membership from NSE Indices, or reconstruct a
   limited five-year history from every official scheduled and ad-hoc notice
   while the quote is pending.
4. Archive official NSE security masters, bhavcopies, actions and filing
   timestamps forward from now.

This is the recommended path for Sensei's current personal research scale.

### Option B — official but costlier

Use direct NSE EOD/historical data plus NSE Indices constituent history, then
build and audit Sensei's own adjustment and issuer-lineage layer. This maximizes
provenance but requires more engineering and at least the published NSE fees
above, before the separate index-data quote.

### Option C — fundamentals-first research

Use a passing GFDL/AccelPix price source plus CMIE or Capitaline after confirming
automated extraction rights and point-in-time filing timestamps. Do not infer
`available_from` from the financial period end.

## Actions now

1. Submit GFDL's and AccelPix's free API trial forms on the same day.
2. Paste the mandatory fields/rights and forensic-sample requirements above
   into both enquiries.
3. Ask for historical-only API pricing; do not purchase real-time data for this
   research task.
4. Keep the TrueData ticket open, but remove it from the critical path.
5. Build/run the provider-neutral acceptance audit before writing either adapter
   into the governed research catalog.
6. Keep all existing strategy conclusions preliminary until one provider and
   the point-in-time universe pass.

## Controlling conclusion

Sensei can move immediately without pretending the data problem is solved.
**GFDL and AccelPix are the practical trials; NSE Indices is the separate
survivorship fix.** No purchase should be made on marketing coverage alone, and
no strategy should receive real-capital authority from a present-day universe
or an unverified adjusted series.
