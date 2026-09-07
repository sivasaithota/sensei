# A finite research convention for demerger entitlements

Research date: 8 September 2026. Scope: the liquid relative-strength replay blocked by TATAMOTORS on 14 October 2025 and VEDL on 30 April 2026. No code, policy configuration, prices or broker state changed by this note.

**Recommendation:** implement a separately identified, explicitly assumed entitlement-valuation scenario. There is an established NSE Indices convention for carrying unlisted spun-off assets. It can support useful portfolio research without pretending those marks are executable prices or evidence of account credit. Keep the strict evidence replay and its blockers alongside it.

## What the primary sources establish

NSE's explanation of its 2023 Reliance/Jio Financial treatment describes carrying the spun-off entity at the difference between the parent's previous close and its ex-date special pre-open session (SPOS) discovery price until listing. This predates both events. The March 2025 consultation repeats that convention as the **existing** methodology; its proposed revisions are not themselves evidence of adoption. [NSE explanation, updated 29 August 2023](https://www.nseindia.com/static/resources/nse-corporate-adjustment-for-reliance-Industries-Ltd-in-nifty-indices), [27 March 2025 consultation, page 1](https://www.niftyindices.com/docs/default-source/default-document-library/nse_indices_consultation_demerger.pdf?sfvrsn=16a6a35_2).

The current methodology specifies a zero floor when the discovered parent price equals or exceeds its previous close, a constant dummy mark before listing, and actual new-security prices from listing. It distinguishes NSE discovery, other-exchange discovery and absent discovery. The PDF retrieved here is **August 2026**, despite search snippets referring to March; do not present it as an archived October 2025 document. [NSE Indices methodology, printed pages 320–323, especially items 5–10](https://www.niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf#page=322).

The dated 1 December 2025 release adds equal-weight dummy assets for multiple resulting companies, effective **15 December 2025**. That timing precedes VEDL's event. It also changes eventual index-removal rules; index removal does not establish a retail investor's attainable sale. [Adopted revision, pages 4–5](https://www.niftyindices.com/Press_Release/ind_prs01122025.pdf#page=4).

| Event | Specific official confirmation |
|---|---|
| TATAMOTORS | NSE Indices' 7 October 2025 notice names **DUMMYTATAM**, SPOS on **14 October**, and inclusion in Nifty 500 from the preceding close. Its 13 November notice confirms **TMCV listing on 12 November** and index removal after the 14 November close. [Inclusion notice](https://www.niftyindices.com/Press_Release/ind_prs07102025.pdf), [listing/removal notice](https://niftyindices.com/Press_Release/ind_prs13112025.pdf). |
| VEDL | NSE Indices' 23 April 2026 notice names **DUMMYVEDL1–4** for Vedanta Aluminium Metal, Talwandi Sabo Power, Malco Energy, and Vedanta Iron and Steel respectively, with equal weights in Nifty 500 from the 29 April close. NSE scheduled SPOS on **30 April**, with unsuccessful discovery continuing in call auction. [Index notice](https://www.niftyindices.com/Press_Release/ind_prs23042026.pdf), [exchange circular CMTR73856](https://nsearchives.nseindia.com/content/circulars/CMTR73856.pdf). |

These notices' initial zero marks describe the index's pre-discovery setup. They do not justify leaving the entitlements worthless throughout the unlisted interval.

## Proposed deterministic portfolio contract

The following are **our research choices**, using the index convention as a valuation reference, not a claim to replicate every index operation.

1. Record legal entitlements separately from tradable holdings, using settled/eligible parent quantities and documented ratios. Existing legal research establishes one child per parent for Tata and one in each of four children for Vedanta. Preserve identities through subsequent renames. [Prior entitlement research](share-action-classification-demergers-2026-09-07.md).
2. After verified SPOS discovery, set the aggregate initial entitlement value per eligible parent share to `D = max(0, previous_raw_close − discovered_parent_price)`. For Tata, one child receives D. For Vedanta's four equal 1:1 entitlements, assign D/4 to each. This equal allocation is an index-inspired convention, not four independently observed business valuations. Never substitute tax acquisition-cost percentages.
3. Carry each child's initial mark until that child's verified listing; then use its own contemporaneous raw quotes. A first listing must not retrospectively reallocate value among still-unlisted siblings. Do not backfill listing prices into the unlisted interval.
4. Keep entitlement value nonspendable and ineligible for purchases, collateral or sale fills. Show both total marked NAV and its unlisted component. Actual selling requires a separately declared availability assumption, eligible series/identity, quotes, liquidity and costs. Admission alone is not proof of individual account credit.
5. Preserve the strategy's raw parent series and action history. Before replay, explicitly freeze how parent stops, high-water marks, pending orders and position limits react to the distribution. The index documents do not specify those trading rules. Do not let the parent ex-price drop mechanically masquerade as an economic loss, or add child value to an already adjusted parent series.
6. Publish scenario NAV, cash, listed holdings and unlisted entitlements separately. If anything remains unlisted or unsold at the endpoint, label the result **marked scenario**, not realized liquidation wealth. A stale constant mark understates observable volatility during the waiting period and can distort drawdown and equity-based sizing; report the maximum unlisted share of NAV and days outstanding.

## Concrete price and listing evidence found

NSE's SPOS page, updated **18 September 2024**, explicitly identifies the auction equilibrium as the day's opening price. Its member guide says the same. This supplies a substantive link between SPOS discovery and the exchange's raw daily open; it is stronger than assuming any opening bar is an auction result. The documentation does not name the exact `OPEN_PRICE`/UDiFF field or establish each event's auction timestamp. No separate numerical auction-result bulletin for these two dates was found in this bounded search. [NSE SPOS rules](https://www.nseindia.com/static/products-services/equity-market-special-pre-open-session), [member guide, question 5](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Member_Guide_and_FAQs_on_Special_Pre-Open_Session_in_Capital_Market.pdf).

The already frozen [raw panel](../../data/research/stock-closure/20260907/raw-panel.parquet), SHA-256 `b6564c244ad3fb31e407146b9ea3fcf49ffb36a1bed74739387d1c2e5d821b29`, contains:

| Parent | Previous close | Ex-date raw open | Calculated aggregate D | Later cross-check, not an ex-date input |
|---|---:|---:|---:|---|
| TATAMOTORS, 14 October 2025 | ₹660.75 | ₹400.00 | ₹260.75 | TMCV's 12 November first row has `prev_close=260.75`. |
| VEDL, 30 April 2026 | ₹773.60 | ₹289.50 | ₹484.10 | The four children's 15 June `prev_close` values total ₹484.10: 121.03, 121.03, 121.02, 121.02. |

Our inference is that these raw opens represent the relevant discovery values, based on the scheduled SPOS, NSE's opening-price definition, and the later reconciliation. Preserve that derivation in the input manifest. Later listing reference values are validation only: using them to assign ex-date values would introduce future information. An equal allocation of ₹484.10 gives ₹121.025 per child; retain precision or predeclare a deterministic residual-paise allocation that preserves the total. Do not round all four independently upward.

**All four Vedanta children listed on NSE on 15 June 2026.** The 17 June official index release names their listed symbols and confirms that common listing date. Therefore their constant unlisted marks must stop at listing, well before the 3 September snapshot endpoint. Subsequent notices record removal after the 18 June close for VEDPOWER/VISL, 22 June for VAML and 23 June for VOGL. Those dates illustrate distinct index exits, not our portfolio's fills. [17 June release](https://www.niftyindices.com/Press_Release/ind_prs17062026.pdf), [19 June release](https://www.niftyindices.com/Press_Release/ind_prs19062026.pdf), [22 June release](https://www.niftyindices.com/Press_Release/ind_prs22062026.pdf).

| Listed child | ISIN observed in the pinned raw panel | Raw coverage observed |
|---|---|---|
| VAML | INE1CDF01017 | 58 rows, 15 June–3 September 2026; BE then EQ |
| VEDPOWER | INE694L01019 | Same |
| VOGL | INE704J01044 | Same |
| VISL | INE1CLE01013 | Same |

These are observed row identities, not a completed action/permission audit. Reconcile them to admission notices and dated security masters before execution. The June 16 company filing independently confirms VOGL's identity. [Official filing](https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_167331_16062026170320_iXBRL_WEB.html).

## Required inputs and bounded fallback

Pin the primary notices and their publication dates; parent/child ISINs and symbol transitions; entitlement ratios; the preceding raw close; **an exchange-identified SPOS discovery price with date/session provenance**; each child's listing notice, raw price history and action history; and the declared execution/availability policy. Pin the methodology version as research provenance without backdating later revisions.

The base research manifest can explicitly declare `NSE_SPOS_RULE_PLUS_RAW_OPEN` as its inference basis, with the notices, FAQ and original raw rows pinned. If a stricter contract requires an event-specific auction bulletin or explicit bhavcopy field definition, that exact input remains open; preserve the strict result as blocked. Do not call the source-data blocker fully closed merely because a valuation convention exists. Missing ordinary raw prices or child identity remains a data error, not permission to invent prices.

For a finite next implementation, support the entitlement state transition once, preregister one base marking convention and one conservative diagnostic that excludes unlisted marks from deployable-equity sizing, and replay every existing account path unchanged. Keep all attempts. Remaining concrete work is child admission/identity and action validation, availability/execution assumptions, parent stop/order transformations, and accounting tests. This defines the valuation model; it does not certify a strategy edge or readiness for live trading.
