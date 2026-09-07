# Nifty 500 historical anchor: bounded official-source search

Research date: 7 September 2026. Question: can an independently dated, complete Nifty 500 constituent list be obtained for the opening of 1 January 2024 / close of 29 December 2023, or a dated 2024–2025 checkpoint?

**No qualifying full constituent set was obtained in this bounded search.** Eight search queries restricted to official NSE / NSE Indices domains surfaced dated index statistics and research papers, but no verified full historical constituent file. This is a retrieval result, not proof that NSE never published such a file. The historical membership anchor remains unresolved.

This extends [the membership coverage note](nifty500-membership-coverage-2026-09-07.md). It does not duplicate the separate capture and transcription of scheduled reviews, corrections and ad hoc notices. A list of changes cannot establish the unchanged members without a valid anchor.

## Sources inspected

| Official source | Dated content observed | Full constituent-set result |
|---|---|---|
| [Nifty 500 product page](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-500) | Downloads link to Factsheet, Index Constituent and May 2024 / October 2025 research papers. The page labels sector data as the previous month's last trading day. | No historical selector or dated constituent archive was observed in the inspected page. Clicking Index Constituent returned an internal error in the web reader; no response body or historical date was obtained from that click. |
| [Nifty 500 factsheet](https://www.niftyindices.com/Factsheet/ind_nifty_500.pdf) | The retrieved two-page document is dated **31 August 2026**. Its company table contains ten top constituents by weight. | Wrong date for the requested anchor and only a partial company list. Its headline count of 500 is not a membership set. |
| [Nifty 500 May 2024 whitepaper](https://www.niftyindices.com/docs/default-source/indices/nifty-500/nifty-500-whitepaper_2024.pdf) | Fifteen-page paper. Inspected text includes market/turnover coverage as of **28 March 2024**, methodology, return statistics and fund information. | No complete company/symbol/ISIN register was obtained. The dated aggregate coverage is useful context but cannot identify all members. Text search for an annex found none; this is not a substitute for a constituent file. |
| [Nifty 500 October 2025 whitepaper](https://www.niftyindices.com/docs/default-source/indices/nifty-500/nifty-500-whitepaper_2025.pdf) | Seventeen-page paper. Inspected text includes market coverage and return analysis through **30 September 2025**. | No full constituent set was obtained. Aggregate methodology/sector/performance exhibits cannot serve as a checkpoint. Text search for an annex found none. |
| [Nifty500 Equal Weight 2024 whitepaper](https://www.niftyindices.com/docs/default-source/indices/nifty500-equal-weight/nifty500-equal-weight-whitepaper_2024.pdf?sfvrsn=e2ee6b35_4) | Thirteen-page paper; exhibits explicitly use **31 December 2024 beginning-of-day** weights. Observed tables give concentration buckets and sector weights, followed by return/attribution analysis. | This is a genuine dated aggregate checkpoint, but no full list of its stocks or the parent Nifty 500's stocks was obtained. Top-stock/top-50 aggregate weights do not identify those sets. |

The whitepapers were opened through the web reader and their dated/table/constituent/annex text inspected. No binary archives or complete historical membership tables were captured in this pass. The conclusion is deliberately limited to what was retrieved and inspected.

## Other exact-date search leads

The following official documents appeared in search results. Their observed passages were index-level or corporate-earnings aggregates; they were not exhaustively audited page by page and are **not certified absent of every possible appendix**. No full member list was obtained from these leads:

- [Benchmark Riskometer, 29 December 2023](https://www.niftyindices.com/Benchmark_Riskometer/NSE_Indices_Riskometer_2023-12.pdf): the exact target date appears, but the observed table lists index names and risk scores, not the 500 securities.
- [NSE Market Pulse, December 2023](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Market%20Pulse_December%202023.pdf): observed earnings charts reference Nifty 500 companies at the end of September 2023.
- [NSE Market Pulse, June 2024](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/MarketPulse_June2024.pdf): observed sector earnings analysis references Nifty 500 as of 31 March 2024.
- [NSE Corporate Earnings Review, Q1 FY25](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Q1FY25_CorporateEarningsReview.pdf): observed aggregates reference Nifty 500 as of 30 June 2024.
- [NSE Market Pulse, June 2025](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Market%20Pulse_June%202025_0.pdf): observed earnings analysis references Nifty 500 as of 31 March 2025.
- [NSE Corporate Earnings Review, Q3 FY26](https://nsearchives.nseindia.com/web/mediaattachment/2026-03/Q3FY26_Corporate_Earnings_Review_20260305120652.pdf): the observed passage references 31 December 2025 constituents while excluding Tata Motors for the analysis. That analytical exclusion is another reason not to treat an earnings sample as the complete index.
- [Nifty MidSmallcap 400 factsheet](https://archives.nseindia.com/content/indices/ind_Nifty_MidSmallcap_400.pdf): search exposed a 31 December 2024 date, but it is a different index. No independently dated full Nifty 100 and MidSmallcap 400 sets were obtained to support a union.

## Exact search log and bound

Eight queries were submitted, each with domain restrictions `niftyindices.com` and `nseindia.com`. Follow-up opens/finds/clicks were limited to the returned official leads and Nifty 500 download links; there were no additional search queries.

1. `"Nifty 500" "December 29, 2023" constituents`
2. `"Nifty 500" "December 2023" "constituents"`
3. `"Nifty 500" "2024" "Constituents as on"`
4. `"Nifty 500" "2025" "Constituents as on"`
5. `"ind_nifty500list" "2023"`
6. `"Nifty 500" "constituents" "2024" filetype:xlsx`
7. `"Nifty 500" "constituents" "2025" filetype:csv`
8. `"Nifty 500" "constituents" "December 31, 2024"`

Current/dynamic pages, replacement notices, unrelated index factsheets and aggregate reports were not promoted to historical anchor evidence. Today's CSV was not backdated; ETF holdings were not substituted for index membership.

## Remaining acquisition boundary

A usable anchor must supply the complete identifier set with an explicit effective date and opening/closing convention, including any temporary demerger constituents. A checkpoint at another date could support reconstruction only with a fully reconciled sequence of intervening changes, revocations, symbol/identity transitions and dummy additions/removals. Matching a headline count or a few top weights is insufficient.

The prior local audit's current CSV and 2020-ending change workbook remain insufficient for the 2024 starting set; see the linked coverage note for their recorded scope and hashes. The current Kite-matched 499 price instruments likewise do not establish Nifty 500 historical membership.

The concrete official fallback remains [NSE Indices historical constituent data](https://www.niftyindices.com/offerings/data-subscription), identified in the previous pass. A dated delivered list or an existing independently archived official constituent file is needed before admitting a membership anchor. No purchase, quote request, external message, broker request, code change or membership-data fabrication occurred. Only this note was created.
