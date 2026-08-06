# Indian equity research data sources

## Decision

Sensei should not build its research database by repeatedly scraping the public
NSE or Nifty Indices websites. The public pages are useful for manual validation
and small prototypes, but they do not provide a complete, contractually safe,
machine-readable point-in-time history. The production research store should be
built from licensed NSE/NSE Indices feeds (or an authorised vendor whose
contract expressly permits systematic research and storage), with public
exchange filings retained as the independent audit source.

This note identifies sources only. No data has been purchased, downloaded or
loaded into Sensei.

## Source matrix

| Requirement | Best authoritative source | Publicly downloadable | Research-grade status |
|---|---|---|---|
| Point-in-time Nifty 200/500 membership | NSE Indices historical constituent subscription | Current constituents and replacement announcements are public | **Licensed/paid is recommended** for complete effective-dated history |
| Stable security identity and symbol history | Daily NSE CM security master keyed by ISIN, plus NSE listing/symbol-change/delisting circulars | Current/daily files and delisting lists are public | License or written permission for systematic collection; build an internal effective-dated identity map |
| Splits, bonus, dividends, rights | NSE corporate-actions filings/report | Interactive CSV is public | Public validation; licensed corporate data for reliable bulk history |
| Mergers, demergers and schemes | NSE announcements/circulars, Nifty index corporate-action notices, depository ISIN records | Individual notices are public | Requires event normalization and predecessor/successor mapping; licensed feed preferred |
| Quarterly/annual fundamentals known-at timestamps | NSE Financial Results / Integrated Filing XBRL with broadcast and revision timestamps | CSV/XBRL/attachments are public through the UI | Licensed corporate feed preferred for bulk point-in-time reconstruction |
| Annual reports | NSE Annual Reports filings | Individual attachments and some timestamps are public | Audit/supporting source, not the primary normalized fundamentals feed |
| Broad-market and strategy benchmarks | Nifty Indices historical index/TRI reports and published methodologies | Historical index/TRI CSV, factsheets and methodologies are exposed publicly | Obtain permission/license for systematic storage, redistribution or product benchmarking |

## 1. Point-in-time Nifty 200 and Nifty 500 membership

The Nifty 200 page provides the current constituent download and defines the
index as Nifty 100 plus Nifty Midcap 100. The Nifty 500 page likewise exposes
the current constituent download. These are **current snapshots**, not a
survivorship-bias-safe membership history ([Nifty 200](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-200),
[Nifty 500](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-500)).

NSE Indices publishes dated replacement press releases with both exclusions,
inclusions and effective dates. They can reconstruct part of the history; for
example, the February 2026 review lists Nifty 500 removals and says when the
changes become effective. The archive also includes unscheduled changes caused
by corporate actions ([press-release archive](https://www.niftyindices.com/press-release),
[February 2026 replacement release](https://www.niftyindices.com/Press_Release/ind_prs23022026.pdf),
[Vedanta corporate-action release](https://www.niftyindices.com/Press_Release/ind_prs23042026.pdf)).

The methodology matters when replaying membership: broad-market indices are
reviewed periodically, and corporate events such as merger, spin-off,
delisting or suspension can cause additional replacements. Index divisor
adjustments prevent a constituent replacement itself from moving the index
level ([broad-market methodology](https://www.niftyindices.com/Methodology/Nifty_Broad_Market_Indices_Methodology.pdf)).

For a complete history, NSE Indices explicitly offers ongoing and historical
constituent data containing identifiers, weights, market capitalisation and
prices by subscription; enquiries go to `indices@nse.co.in`
([NSE Indices data subscription](https://www.niftyindices.com/offerings/data-subscription)).

**Conclusion:** do not infer historical membership from today's CSV. Buy the
effective-dated constituent history, or obtain a written quote from an
authorised vendor that includes removals, ad-hoc changes and identifiers. The
press-release reconstruction is suitable only as a cross-check or temporary
prototype and must include every scheduled and ad-hoc release.

## 2. Stable instruments, symbol changes and delistings

Use **ISIN as the security-level join key**, not the NSE ticker. NSE's daily CM
MII security file is available from All Reports, and NSE describes its security
master as containing symbol, ISIN, security code and series
([NSE All Reports](https://www.nseindia.com/all-reports),
[NSE report specification](https://www.nseindia.com/static/products-services/equity-market-data-reports-download)).
The current list of securities available for trading is separately published
by NSE ([securities available for trading](https://www.nseindia.com/static/products-services/equity-market-securities-available-for-trading)).

ISIN is stable for a particular security, but it is not a permanent company ID.
Capital restructurings can produce a replacement or additional ISIN. NSDL's
public master search exposes issuer, former name, ISIN, security description,
status and face value; CDSL also documents a current ISIN Master file
([NSDL master-search description](https://nsdl.co.in/downloadables/The%20Financial%20Kaleidoscope%20-%20October%202018.pdf),
[CDSL UDiFF/ISIN Master](https://www.cdslindia.com/DP/Harmonization.html)).

NSE provides downloadable lists of companies proposed for delisting and
already delisted. Dated exchange notices give the actual withdrawal date and
reason ([NSE delisting page](https://www.nseindia.com/static/list/list-of-companies-proposed-to-be-delisted)).

Sensei therefore needs two internal IDs:

- an immutable `instrument_id` for each listed security/ISIN episode; and
- an immutable `issuer_id` connecting predecessor and successor instruments.

Store an effective-dated alias table containing ISIN, exchange, ticker, series,
company name, listing date, last-trading/delisting date, predecessor,
successor, and the official notice that caused each change. Never rewrite old
bars to a company's current symbol.

## 3. Corporate actions

NSE's Corporate Actions filing page provides CSV output with symbol, company,
series, purpose, face value, ex-date, record date and book-closure dates. The
purpose field carries events such as dividends and face-value splits
([NSE Corporate Actions](https://www.nseindia.com/companies-listing/corporate-filings-actions)).
NSE also states that its corporate-action report contains symbol/series,
record/book-closure dates and ex-date
([NSE report specification](https://www.nseindia.com/static/products-services/equity-market-data-reports-download)).

Mergers, demergers, schemes and capital reductions cannot be represented by a
single split factor. Preserve the exchange announcement/circular, affected
ISINs, entitlement terms, effective/ex dates, cash component, and
predecessor-successor relationships. Nifty Indices' Vedanta notice illustrates
why: several dummy securities were introduced into affected indices at zero
price as part of a demerger
([official notice](https://www.niftyindices.com/Press_Release/ind_prs23042026.pdf)).

Required normalized event types are `cash_dividend`, `split`, `consolidation`,
`bonus`, `rights`, `spin_off`, `merger`, `demerger`, `capital_reduction`,
`symbol_change`, `listing` and `delisting`. Keep both raw and normalized events;
derive adjusted prices as a versioned research view rather than overwriting raw
OHLCV.

## 4. Point-in-time fundamentals

The NSE Financial Results page exposes quarterly/annual result metadata, XBRL,
CSV conversion and the **broadcast date/time**. The newer Integrated Filing
page additionally distinguishes original versus revised filings and exposes
the revised timestamp and reason
([Financial Results](https://www.nseindia.com/companies-listing/corporate-filings-financial-results),
[Integrated Filing example](https://www.nseindia.com/companies-listing/corporate-integrated-filing?symbol=YATRA&tabIndex=equity)).
SEBI introduced Integrated Filing for financial and governance filings from the
quarter ended 31 December 2024 onward
([SEBI circular](https://www.sebi.gov.in/web/?file=https%3A%2F%2Fwww.sebi.gov.in%2Fsebi_data%2Fattachdocs%2Ffeb-2025%2F1738668300985.pdf)).

For every fact Sensei must store at least:

- period end and fiscal period;
- standalone/consolidated and audited/unaudited status;
- exchange-received and dissemination/broadcast timestamps;
- original/revised status and revision timestamp;
- XBRL taxonomy/concept, unit, value and filing source; and
- `available_from`, the first timestamp at which a backtest may use the value.

Annual report attachments and their broadcast timestamps are publicly visible,
but older records can have missing timestamps. They are useful supporting
evidence, not a substitute for normalized point-in-time facts
([NSE Annual Reports](https://www.nseindia.com/companies-listing/corporate-filings-annual-reports)).

NSE's licensed Corporate Data product explicitly covers fundamentals,
announcements and shareholding. The currently published domestic fee is
₹10,60,000 for the online corporate feed; the end-of-day corporate-announcement
product is ₹5,00,000 per annum. Delivery and exact historical coverage must be
confirmed in a quote—the page describes online leased-line and EOD SFTP
products, not a guaranteed backfill
([NSE Corporate Data subscription](https://www.nseindia.com/static/market-data/corporate-data-subscription)).

**Conclusion:** use filings as the legal source of truth, but obtain a licensed
bulk feed or a vendor contract for ingestion. Backtests must join facts on
`available_from`, never merely on the financial period end.

## 5. Official benchmarks and factor comparators

Nifty Indices' Historical Data report exposes CSV output for price-index
history and separately for Total Return Index (TRI) and Net TRI history
([Historical Data](https://www.niftyindices.com/reports/historical-data)). The
official TRI methodology includes both constituent price movement and dividend
receipts, reinvesting dividends through the index on the ex-date
([TRI methodology](https://www.niftyindices.com/resources/index-concepts/total-return-index)).

Use TRI—not the price index—as the primary performance comparator. Minimum
benchmark set:

- Nifty 200 TRI and Nifty 500 TRI for the investable universe;
- Nifty200 Momentum 30 TRI as the transparent momentum baseline; and
- Nifty200 Quality 30 TRI as a non-price-only factor comparator.

The official strategy pages and methodologies define these baselines. Momentum
uses volatility-adjusted six- and twelve-month returns. Quality uses ROE,
debt/equity and five-year EPS-growth variability
([Nifty200 Momentum 30](https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-momentum-30),
[Nifty200 Quality 30](https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-quality-30),
[Quality methodology](https://www.niftyindices.com/Methodology/Method_NIFTY200_Quality30.pdf)).

Public methodologies, factsheets and interactive historical downloads are
excellent validation sources. They do not automatically grant broad rights to
store, redistribute or use index data commercially. NSE Indices says product
benchmarking may require prior approval/fees, and its disclaimer says use or
distribution of index data and creation of financial products require a
license ([index licensing](https://www.niftyindices.com/offerings/index-licensing),
[Nifty Indices disclaimer](https://www.niftyindices.com/disclaimer)). Obtain
written confirmation covering Sensei's internal automated research and any UI
display before operational use.

## Usage and licensing constraints

“Downloadable from a webpage” does not mean “free for an automated trading
database.” NSE copyright policy permits website content downloads for personal,
non-commercial or educational use with acknowledgement. NSE's market-data
policy defines market data broadly to include identifiers, historical and
corporate data; subscriber agreements govern use, storage, display and
redistribution. Commercial use is priced, redistribution is restricted, and
creating an index requires separate licensing
([NSE copyright policy](https://www.nseindia.com/static/nse-copyright),
[NSE Data Sharing and Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)).
The NSE Data portal terms also prohibit systematic or automated collection
without express written consent
([NSE Data portal terms](https://dotexdata.nseindia.com/TermsAndConditions/TermsofUse.pdf)).

Therefore:

- public downloads are acceptable for manual inspection and a small internal
  proof of concept only within their terms;
- do not deploy an unattended scraper as Sensei's data backbone;
- request written rights for automated retrieval, local historical storage,
  derived analytics, internal model use, backup retention and UI display; and
- do not redistribute raw exchange/index data in reports, APIs or a hosted UI
  unless the contract explicitly permits it.

## Blockers to resolve before unbiased strategy research

1. **No complete licensed point-in-time universe is currently confirmed.**
   Current constituent CSVs leave survivorship bias; press releases alone are
   labor-intensive and easy to miss.
2. **Identity lineage is not yet sourced as one dataset.** The daily security
   master, delisting files, symbol-change notices and depository ISIN records
   must be reconciled into issuer/instrument history.
3. **Corporate-action entitlement details are heterogeneous.** Simple events
   are structured; schemes require document parsing and human-verified mapping.
4. **Bulk historical fundamentals and restatement coverage are unconfirmed.**
   The public UI exposes timestamps, but licensed product backfill, delivery,
   taxonomy history and revision retention require written confirmation.
5. **Usage rights are unresolved.** Sensei is intended for trading, so the
   personal/educational website allowance is not a safe production basis.

## Recommended acquisition order

1. **Ask NSE Indices for a written quote and sample** for complete effective-
   dated Nifty 200 and Nifty 500 constituents, including additions, removals,
   identifiers, weights, ad-hoc changes and historical corrections. This fixes
   the largest current backtest bias first.
2. **Ask NSE Data for a written data-rights proposal** covering the CM security
   master, EOD/historical prices, corporate actions and historical corporate
   data. Require systematic ingestion, internal research, archival storage and
   derived-output rights. Confirm whether the quoted products contain full
   backfill or only forward delivery.
3. **Evaluate authorised vendors against the same schema** if direct exchange
   products are operationally or financially unsuitable. Require primary
   source lineage, as-reported/revised fundamentals, exchange timestamps,
   inactive instruments, merger lineage and contractual backtest use—not just
   an “adjusted price” field.
4. **Acquire official Nifty TRI and strategy-index history/permission** for
   Nifty 200, Nifty 500, Momentum 30 and Quality 30 benchmarking.
5. **Run a sample acceptance audit before buying:** choose delisted stocks,
   ticker changes, splits, bonuses, large dividends and two complex mergers;
   verify that point-in-time membership, identity, prices, actions and filings
   reconcile to official notices.
6. **Only then rerun strategy research.** Freeze the acquired dataset version,
   record every source timestamp and correction, and prevent the research loop
   from promoting any strategy trained on a current-only universe.

