# Selected raw replay: corporate-action coverage

Research date: 7 September 2026. Scope: four saved HEG/MAZDOCK holding intervals, including both endpoints. This is a retrospective evidence review for a bounded raw-price replay, not an adjustment ledger or permission to release a strategy.

## Decision

**All four intervals clear the corporate-action coverage check within NSE's returned calendar-2024, all-purpose corporate-action record scope.** The two successful historical queries resolve the earlier rights/demerger coverage gap within that scope: they contain no action with an ex-date inside any saved interval. Annual capital and dividend reconciliations corroborate the returned events. This is scoped clearance for the selected replay, not an unrestricted “no corporate actions” or full-history certificate. Preserve all four intervals in the replay denominator.

| Security | Saved interval, inclusive | NSE 2024 records returned | Records with ex-date inside interval | Action coverage clearance |
|---|---|---:|---:|---|
| HEG | 2024-04-16–2024-05-03 | 2 | 0 | Cleared within returned NSE scope |
| MAZDOCK | 2024-05-30–2024-05-31 | 3 | 0 | Cleared within returned NSE scope |
| MAZDOCK | 2024-06-18–2024-06-27 | 3 | 0 | Cleared within returned NSE scope |
| MAZDOCK | 2024-07-05–2024-07-05 | 3 | 0 | Cleared within returned NSE scope |

## Captured NSE historical evidence

The [NSE corporate-actions page](https://www.nseindia.com/companies-listing/corporate-filings-actions) provides company and custom date filters. The following requests specify the equity segment, one symbol, and **1 January–31 December 2024**, without a purpose filter. Each returned HTTP 200 and a JSON array. No returned row is a rights or demerger action.

| Request | Complete returned event list, using `exDate` | Local response body |
|---|---|---|
| [HEG, calendar 2024](https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol=HEG&from_date=01-01-2024&to_date=31-12-2024) | 2024-07-31 AGM/dividend ₹22.50; 2024-10-18 split ₹10 to ₹2 | `data/reports/raw-replay-action-evidence/heg-2024.json` |
| [MAZDOCK, calendar 2024](https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol=MAZDOCK&from_date=01-01-2024&to_date=31-12-2024) | 2024-09-19 AGM/dividend ₹12.11; 2024-10-30 interim dividend ₹23.19; 2024-12-27 split ₹10 to ₹5 | `data/reports/raw-replay-action-evidence/mazdock-2024.json` |

The two response bodies were recaptured once and saved unchanged on 7 September 2026 at approximately 01:31:54 UTC. `data/reports/raw-replay-action-evidence/manifest.json` records each exact request URL, UTC capture time, HTTP status, body SHA-256 and count. Its SHA-256 is `488cf83426507a7747ac0548f87e08f17ebb713282edfd4ec05be5bcb0ebc9e9`. No cookies, credentials or request headers are stored.

## HEG evidence

The FY2024–25 annual report covers 1 April 2024–31 March 2025. Its standalone changes-in-equity statement lists one dividend distribution: FY2023–24 final, ₹22.50 per share, ₹8,683.99 lakh. Note 17 reconciles shares through the five-for-one subdivision, record date 18 October 2024, with no other change; its five-year table explicitly reports no bonus allotments. These are annual reconciliations, rather than isolated later split notices. [Annual report, PDF pages 87, 100–101; printed pages 168, 194–197](https://nsearchives.nseindia.com/corporate/HEG_10072025113929_HEGAnnualReport.pdf).

The company's AGM publication fixes **31 July 2024** as the final-dividend eligibility date and **7 August 2024** as the AGM date. This distribution falls after the saved holding. [Company publication filed with NSE, 29 June 2024, PDF pages 2–3](https://nsearchives.nseindia.com/corporate/HEG_29062024114449_stockletternewspapercuttingagm.pdf).

The annual report dates initial board approval of the graphite demerger/amalgamation scheme to **22 May 2024**, after exit. It gives an appointed date of **1 April 2024**, but says final approvals remained pending and no scheme adjustments were made to FY2024–25 results. The appointed date is not evidence of an April market ex-date or shareholder entitlement. [Annual report, PDF page 24; printed pages 42–43](https://nsearchives.nseindia.com/corporate/HEG_10072025113929_HEGAnnualReport.pdf).

## MAZDOCK evidence

The FY2024–25 annual report covers all three intervals. Note 18's complete share reconciliation has zero ordinary issuance and buyback; the sole count change is the two-for-one split on **27 December 2024**. This supports no completed split, bonus or rights-share allotment during the intervals. It does not independently exclude an uncompleted rights offer. [Annual report, printed pages 198–199](https://mazagondock.in/images/pdf/Annual%20Report%20FY%202024-25.pdf).

The annual equity reconciliation lists final dividends of ₹24,425 lakh and interim dividends of ₹46,772 lakh; these sum to its ₹71,197 lakh annual dividend cash outflow. The interim dividend was ₹23.19 per old ₹10 share, approved **22 October 2024**, record **30 October 2024**. The second interim dividend was declared in April 2025, after that reporting year. This closes the annual distribution total, rather than relying on one isolated dividend notice. [Annual report, printed pages 79, 117, 167–169](https://mazagondock.in/images/pdf/Annual%20Report%20FY%202024-25.pdf).

The final FY2023–24 dividend was **₹12.11 per old share**, recommended **29 May 2024**, subject to AGM approval. A recommendation is not an ex-date. [Board recommendation, 29 May 2024](https://www.mazagondock.in/images/pdf/Recommendation_of_Final_Dividend_by_BOD_29.05.2024.pdf). The later AGM publication establishes **19 September 2024** as eligibility date, with AGM on **26 September 2024**. These dates are after every selected MAZDOCK interval. [Company AGM publication, 5 September 2024, PDF page 2](https://www.mazagondock.in/images/pdf/BSE%20NSE%20Disclosure_Newspaper%20publication%20of%20AGM%20notice_05092024_signed.pdf).

## Certification boundary

- The absence findings apply to the complete returned arrays for these explicit NSE calendar-2024 queries, corroborated by the annual reconciliations. They do not certify all history, other securities, undisclosed events, or completeness beyond the provider's record scope.
- A rights entitlement can exist before allotment; a demerger can distribute another security without changing the parent's share count. Unchanged capital alone cannot settle those questions. The identified HEG scheme's pending status is direct evidence for that scheme, not a certificate for every possible distribution.
- NSE's returned `faceVal` fields contain current values (HEG 2, MAZDOCK 5), while the rows carry old ISINs. Use explicit action subjects and ex-dates for this coverage check; these mixed metadata fields are not dated identity proof. The payload has null broadcast dates, so it supplies no announcement-availability timestamp.
- The older MAZDOCK FY2023–24 annual report could not be fully retrieved through the available reader. The subsequent full-year report, dated AGM publication and successful historical NSE queries provide the evidence used here. Search-result omissions and current quote-page action lists are not the basis for clearance.
- These subsequently published annual reports and current historical-query captures are retrospective audit evidence. They must not be introduced as information available to a strategy at its 2024 entry time.
- No factor is inferred from volumes, no raw/adjusted price is repaired, and no dividend is added to an already adjusted series. Action coverage clearance does not itself validate historical security identity, raw-price integrity, cost arithmetic, share quantities, or full-portfolio returns.

This research note and two unchanged public NSE response bodies with their manifest were saved. No broker request, price change, portfolio rerun or live action was performed.
