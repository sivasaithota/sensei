# Sustainable daily Indian-equity data after the TrueData trial

**Reviewed:** 2026-08-23
**Scope:** personal/internal NSE cash-equity research and trading
**Status:** source-selection note; no new source is authorized for governed evidence yet

## Decision

Do **not** buy TrueData's full corporate package merely to keep the trial corpus
current. Freeze the trial corpus as a private historical baseline, then maintain
daily deltas through a source-neutral pipeline with three roles:

1. **Contracted API for unattended ingestion:** request a personal-use quote
   from Global Financial Datafeeds (GFDL) for its corporate API plus NSE cash
   EOD history. Its official documentation covers continuous announcements,
   attachments, financial results and shareholding, and EOD corporate actions,
   classification, market capitalisation and bhavcopy. Most corporate endpoints
   expose a rolling 30-day history, which is sufficient if Sensei archives every
   day ([GFDL corporate coverage](https://docs.globaldatafeeds.in/type-of-corporate-data-available-1142925m0),
   [API list](https://docs.globaldatafeeds.in/list-of-apis-923685m0)). Obtain
   written permission for automated retrieval, local retention, backups, model
   research and private dashboard display before activation.
2. **Official exchange/depository sources for reconciliation:** use NSE, BSE,
   NSDL and CDSL filings to verify samples, timestamps and important events.
   They are sources of truth, but the public NSE website must not become an
   unattended scraper target: NSE explicitly prohibits systematic or automated
   collection, including scraping and data extraction
   ([NSE Terms of Use](https://www.nseindia.com/static/nse-terms-of-use)).
3. **Derive analytics locally:** ratios, peer groups and market capitalisation
   do not need separate expensive feeds when their point-in-time inputs are
   available. Store the raw inputs and version the formulas.

This is a continuity solution, not a cure for the research corpus's historical
survivorship gaps. Complete delisted coverage, effective-dated Nifty 200/500
membership and corporate-action-adjusted long history remain separate licensed
data requirements.

## Dataset map

| Dataset | Sustainable daily source | Frequency | Free/public status | What Sensei should store |
|---|---|---:|---|---|
| Announcements and attachments | **GFDL corporate API**: `GetCorporateAnnouncements` and attachment downloader; reconcile important disclosures on [NSE announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements?tabIndex=equity) and BSE | Poll 1–2 min during the day; final sweep after close | NSE/BSE pages are publicly viewable, but not permission for automated scraping; API is licensed | Exchange, security/ISIN, subject/category, received/disseminated/broadcast timestamps, revision/linkage, attachment bytes/hash and retrieval timestamp |
| Financial results | GFDL result endpoints; official [NSE financial filings](https://www.nseindia.com/companies-listing/corporate-filings-financial-results) or BSE XBRL/PDF for audit | Event-driven; nightly reconciliation | Public UI/downloads exist; unattended NSE harvesting is prohibited without permission | Original and revised filing timestamps, period, consolidated/standalone, audited status, XBRL taxonomy/facts, source attachment, `available_from` |
| Shareholding patterns | GFDL SHP endpoints; reconcile via [NSE SHP](https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern) | Event-driven/quarterly, not truly daily | Public UI/CSV/XBRL for manual use; licensed API for automation | As-of, submission/revision/broadcast timestamps, promoter/public/institutional categories, pledge facts, raw XBRL/hash |
| Ratios | **Derive locally** from point-in-time financial facts and split-adjusted/share-count inputs | Recompute on new result, action or EOD price | No additional feed required | Formula version, input fact IDs and availability timestamps; never join on period-end alone |
| Classification | GFDL sectoral classification; security identity from the daily NSE MII security file | Nightly identity diff; classification on change | NSE's [All Reports](https://www.nseindia.com/all-reports) exposes the current security file; public site restrictions still apply | Effective-dated exchange/series/symbol/ISIN plus sector/industry/sub-industry and provider taxonomy version |
| Peers | **Derive locally** from effective-dated industry, business classification, market-cap/liquidity band and listing segment | Recompute weekly or after classification/result changes | No separate vendor endpoint is necessary | Transparent peer-rule version and reason each peer was selected; do not accept opaque vendor peers as trading truth |
| Market capitalisation | **Derive** EOD close × point-in-time shares outstanding; GFDL market-cap endpoint can be a discrepancy check | EOD | Derivable; raw shares may come from financial/SHP/action data | Price timestamp, share-count fact and availability timestamp, formula/version; distinguish full, free-float and index market cap |
| FII/FPI and DII | [NSE FII/FPI & DII CSV](https://www.nseindia.com/reports/fii-dii) for provisional T-day flows; [NSDL](https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx) or [CDSL](https://www.cdslindia.com/eservices/publications/fiidaily) for final custodian-confirmed FPI | Provisional after close; final FPI next day | Public reports; confirm automated-use rights or ingest through a contracted source | Source, provisional/final flag, market/route/category, gross buy/sell/net, reporting date and revision time. Do not overwrite provisional observations |
| Corporate actions | GFDL corporate-action endpoint; validate material events against [NSE corporate actions](https://www.nseindia.com/companies-listing/corporate-filings-actions) and exchange notices | Nightly plus pre-open effective-date check | Public pages are validation sources; licensed API for automation | Raw notice and normalized dividend/split/bonus/rights/merger/demerger event, ex/record/effective dates, old/new ISINs, versioned adjustment factor |
| Symbol/name changes | Daily effective-dated security-master diff plus exchange circulars and depository identifiers | Nightly | NSE publishes a current security file and a `Latest change` report on All Reports; complete historical lineage is not guaranteed | Immutable `instrument_id`, issuer ID, ISIN episode, effective-dated aliases/series, predecessor/successor and official notice |
| Daily/EOD OHLCV | Licensed GFDL/AccelPix historical API, or direct NSE EOD SFTP | Once after official final file; correction sweep next morning | NSE exposes bhavcopy on All Reports, but automated website collection is prohibited; direct EOD is licensed | Raw unadjusted OHLCV/turnover/delivery, exchange/series/ISIN, source file hash, publication/retrieval time and correction version |

## Why not an NSE/BSE scraper?

NSE's public pages clearly expose daily bhavcopy, a security master, corporate
filings, corporate actions, shareholding and FII/DII CSVs
([NSE All Reports](https://www.nseindia.com/all-reports),
[NSE FII/DII report](https://www.nseindia.com/reports/fii-dii)). NSE copyright
policy permits viewing, printing and downloading content for personal,
non-commercial or educational use with acknowledgement, but its Terms of Use
separately prohibit systematic or automated collection
([copyright policy](https://www.nseindia.com/static/nse-copyright),
[Terms of Use](https://www.nseindia.com/static/nse-terms-of-use)). A download
button or undocumented JSON endpoint is therefore **not** an automation licence.

Do not bypass cookies, bot protection, rate limits, CAPTCHA, session controls or
robots rules. Use public exchange pages for manual review and small,
terms-compliant checks. For an unattended trading system, use an explicit
vendor/API agreement or obtain written exchange permission.

NSE's data policy also treats EOD, historical, identifier and corporate data as
Market Data whose use, storage, display and redistribution are governed by a
subscriber agreement. It allows NSE Data to set reduced fees for some
non-commercial users, but defines research as purposes other than trading or
profit; Sensei should not assume it qualifies
([NSE Data Sharing and Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)).

## Paid choices

### Recommended proportionate choice

Request one combined, personal/internal quote from **GFDL** for:

- NSE cash EOD/historical prices;
- corporate announcements plus vendor-served attachments;
- financial results and shareholding;
- corporate actions, company data and classification; and
- written rights for automated collection and indefinite private retention.

GFDL documents REST APIs for all these daily deltas and states that its market
APIs are intended for traders building their own analysis/trading software
([GFDL API introduction](https://globaldatafeeds.in/global-datafeeds-apis/global-datafeeds-apis/introduction/introduction-to-apis/),
[fundamental API](https://globaldatafeeds.in/fundamental-data-apis/)). Its public
documentation does not publish the personal corporate-API price; obtain a
written quote and a forensic sample before purchase. Price history and
corporate data should remain separate adapters so another vendor can replace
either one.

For EOD price history only, AccelPix remains a second vendor to trial, but its
public documentation has not established an equivalent complete corporate
feed. Do not buy real-time ticks for a swing/EOD research need.

### Direct NSE choice (authoritative but disproportionate)

NSE provides Capital Market EOD files through SFTP and historical data through
its online platform
([EOD/historical subscription](https://www.nseindia.com/static/market-data/eod-historical-data-subscription)).
Its corporate subscription is currently ₹10,60,000/year for the online feed or
₹5,00,000/year for the after-8-PM EOD corporate-announcement product
([NSE corporate data](https://www.nseindia.com/static/market-data/corporate-data-subscription)).
This is not proportionate for Sensei's present personal account.

## Daily operating schedule

1. **Continuous, 08:00–22:00 IST:** poll licensed announcement deltas; download
   vendor-served attachments; deduplicate by exchange filing ID plus hash.
2. **18:30–20:30:** ingest final EOD price file, delivery data, corporate
   actions, security-master changes and provisional FII/DII.
3. **20:30:** ingest result/SHP/company-data deltas; calculate ratios, market
   cap and peers only after all raw facts pass validation.
4. **Next morning 07:30:** correction/revision sweep and final NSDL/CDSL FPI;
   retain both provisional and final records.
5. **Pre-entry:** publish one signed `DataReadinessSnapshot` with session date,
   completeness, source freshness, corrections and hashes. Fail closed on
   missing price/security identity or stale surveillance; treat a missing
   optional fundamental update as degraded context, not as permission to trade.

Every job must be idempotent, append-only for raw artifacts, resumable with
checkpoints, and able to classify `data`, honest `no_data`, entitlement failure
and transport failure separately. Revalidate stored manifests from bytes;
never trust a sticky first-write classification.

## What to do now

1. Keep the TrueData trial store immutable and quarantined; it is the backfill,
   not the live provider.
2. Ask GFDL for a **personal/internal NSE-CM EOD + Corporate REST API** quote
   and a 3–7 day trial with explicit local-retention rights.
3. Run its sample through the existing provider-neutral audit: identity,
   timestamps, revisions, attachments, action arithmetic, gaps, corrections and
   replayability.
4. In parallel, keep the current NSE bhavcopy corpus only as a discrepancy
   detector until automated-use permission/licensing is resolved.
5. Do not admit the new source into governed research/trading until its manifest
   records contract rights, lineage, coverage, correction policy and acceptance
   results.

## Primary sources

- [NSE Terms of Use](https://www.nseindia.com/static/nse-terms-of-use)
- [NSE Copyright Policy](https://www.nseindia.com/static/nse-copyright)
- [NSE Data Sharing and Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
- [NSE All Reports / bhavcopy and security master](https://www.nseindia.com/all-reports)
- [NSE paid EOD and historical data](https://www.nseindia.com/static/market-data/eod-historical-data-subscription)
- [NSE paid corporate data](https://www.nseindia.com/static/market-data/corporate-data-subscription)
- [NSE corporate announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements?tabIndex=equity)
- [NSE shareholding patterns](https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern)
- [NSE FII/FPI and DII report](https://www.nseindia.com/reports/fii-dii)
- [CDSL final FII/FPI daily data](https://www.cdslindia.com/eservices/publications/fiidaily)
- [NSDL final FPI daily report](https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx)
- [GFDL corporate API coverage](https://docs.globaldatafeeds.in/type-of-corporate-data-available-1142925m0)
- [GFDL fundamental API](https://globaldatafeeds.in/fundamental-data-apis/)
