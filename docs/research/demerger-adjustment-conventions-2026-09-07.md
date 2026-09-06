# Demerger adjustment conventions: ABFRL and VEDL

Research date: 2026-09-07. Scope: explain the two flagged discontinuities using company, exchange and broker sources. This note changes no prices, certifies no total-return series, and does not approve live trading.

## Finding

The historical-price discontinuities are consistent with Kite's documented use of **cost-of-acquisition (COA) allocation**, which is different from an exchange price-discovery convention or the return on a shareholder's complete entitlement. Zerodha explicitly says demerger charts use company-announced COA and that gaps can remain. Its developer forum discusses ABFRL specifically and confirms that adjustment was completed. That establishes the vendor convention, not the suitability of those returns for our portfolio accounting. [Zerodha chart policy](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/charts/articles/kite-charts-not-matching-as-per-the-records-in-nse-or-bse), [Kite ABFRL discussion](https://kite.trade/forum/discussion/15640/daily-history-data-is-not-adjusted-previous-days-data-after-split-bouns-right-issues).

## Company allocation and information dates

| Company letter date | Original company | Original-company COA | Resulting companies and COA |
|---|---|---:|---|
| 2025-05-22 | ABFRL | 75.68% | Aditya Birla Lifestyle Brands Limited (ABLBL): 24.32% |
| 2026-05-16 | Vedanta Limited | 52.34% | Vedanta Aluminium Metal Limited: 7.15%; Talwandi Sabo Power Limited: 12.23%; Malco Energy Limited: 21.49%; Vedanta Iron and Steel Limited: 6.79% |

ABFRL's letter is dated **May 22**, although the current website file is under a June upload directory. It specifies one ABLBL share per ABFRL share and a May 22 record date. Its percentages allocate the investor's pre-demerger acquisition cost. They do not state what either company's shares were worth in the market. An exact intraday exchange publication timestamp was not established here. [ABFRL's two-page COA letter](https://www.abfrl.com/wp-content/uploads/2025/06/ABFRL-ABLBL-Apportionment-of-Cost.pdf).

Vedanta's letter is dated **May 16**, also the date shown in its disclosure index. It specifies one share in each of the four resulting companies per original share, a May 1 effective/record date, and allocations based on net worth and the net assets transferred. These are acquisition-cost allocations. They were published after the April 30 ex-date; a simulation must not treat the May 16 allocation as news available before April 30. Use the entity names in the dated document when constructing the event ledger. [Vedanta's two-page COA letter](https://www.vedantalimited.com/public/uploads/19416/VEDLSEIntimationCostofApportionmentsigned.pdf), [company disclosure index](https://www.vedantalimited.com/eng/investor-relations-stock-exchange-announcements.php).

Kite staff separately says demerger history is adjusted once the applicable COA file is received. Thus the September archive is a later revised view of earlier prices, rather than proof of what a user could download on the original event date. [Kite historical-data adjustment timing](https://kite.trade/forum/discussion/16099/split-adjustment-data).

## What the exchange actually specified

NSE scheduled a special pre-open price-discovery session for ABFRL on May 22, 2025 and for VEDL on April 30, 2026. Both notices describe an auction, rather than applying the company's tax percentages as an opening quote. [ABFRL CMTR68037](https://nsearchives.nseindia.com/content/circulars/CMTR68037.pdf), [VEDL CMTR73856](https://nsearchives.nseindia.com/content/circulars/CMTR73856.pdf).

For these events, the exchange's derivative circulars provide **early expiry and reintroduction**, with new option strikes based on the capital-market special-session price. The clearing circulars settle existing contracts using the preceding cum-date capital-market settlement price. No published numerical `P/P0` cash-history adjustment factor was located in this bounded investigation. It would be incorrect to label a ratio calculated from daily bars as an NSE-published factor. [ABFRL FAOP68038](https://nsearchives.nseindia.com/content/circulars/FAOP68038.pdf), [ABFRL clearing CMPT68066](https://nsearchives.nseindia.com/content/circulars/CMPT68066.pdf), [VEDL FAOP73857](https://nsearchives.nseindia.com/content/circulars/FAOP73857.pdf), [VEDL clearing CMPT73864](https://nsearchives.nseindia.com/content/circulars/CMPT73864.pdf).

The local, internally hash-verified **raw NSE bhavcopies** provide the following actual daily-bar observations. An opening bar is useful evidence, but this investigation has not retrieved a separate auction-result or historical security-reference file proving its exact special-session reference status.

| Security | Last cum-date close | Ex-date open | Ex-date close | Raw source sessions |
|---|---:|---:|---:|---|
| ABFRL | ₹268.95 | ₹98.00 | ₹89.85 | [2025-05-21](https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20250521_F_0000.csv.zip), [2025-05-22](https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20250522_F_0000.csv.zip) |
| VEDL | ₹773.60 | ₹289.50 | ₹271.55 | [2026-04-29](https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20260429_F_0000.csv.zip), [2026-04-30](https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20260430_F_0000.csv.zip) |

Reads used `QuarantinedRawBhavcopy.verified_session`, parser `bhavcopy-parser/4`, EQ rows, with ISIN `INE647O01011` (ABFRL) and `INE205A01025` (VEDL). ZIP hashes in session order are `b68f134d6d228a3de695b4df1849483f38f764fa572255c392772b85d7985e5c`, `9ab10607b3f8b2de2d3ea127caf91c045d4bf6da301d2195b4010fe3eee2fa36`, `1db3c59deae1a562b430960bd33a78f2b131b29684e8f4de0f0af131fd4d805f`, and `a65fe2ff2dc7e73cd9af334541cb2fcee7eba812a4371f1cc7ee80461e53736b`. Source artifacts remain quarantined; integrity is not economic admissibility.

## Reconciliation arithmetic, not certified adjustment factors

The archived Kite closes and request identities are recorded in [the preceding exception investigation](kite-corporate-action-exceptions-2026-09-07.md). Applying the published COA percentages to raw preceding closes gives:

| Security | Raw close × original-company COA | Archived Kite preceding close | Interpretation |
|---|---:|---:|---|
| ABFRL | 268.95 × 0.7568 = 203.54136 | 203.55 | Very close, but a ₹0.00864 difference remains; exact vendor rounding is not proved. |
| VEDL | 773.60 × 0.5234 = 404.90224 | 404.90 | Consistent after rounding to paise. |

These are our calculations from the cited inputs. They support a COA-based explanation; they do not certify every earlier OHLC/volume adjustment or exclude additional corporate actions.

For comparison, dividing observed ex-date open by raw preceding close gives **0.3643799963 for ABFRL** and **0.3742244054 for VEDL**. Those are calculated opening-price ratios, **not exchange-published factors**. Forcing history through them would impose a different analytical convention and remove the overnight parent-price discontinuity by construction. It does not establish a shareholder's realized return or the price at which a new entitlement could be sold.

## Index marks and shareholder economics

NSE Indices' dated event notices add a dummy ABLBL constituent, and four equally weighted Vedanta dummy constituents, at zero before the relevant ex-date opening. Those notices confirm that the spun-off value is represented separately in index calculations. [ABFRL index event, May 19, 2025](https://www.niftyindices.com/Press_Release/ind_prs19052025.pdf), [Vedanta index event, April 23, 2026](https://www.niftyindices.com/Press_Release/ind_prs23042026.pdf).

The **current August 2026** index methodology (pages 320–323) derives a dummy value from previous close minus discovered parent price, floored at zero. It carries that mark until listing and then uses actual prices. This is a published index-marking convention, not an executable quote. The August document is later than both events; its exact historical version must be checked before claiming every rule was in force on those dates. [NSE Indices methodology](https://www.niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf).

Our accounting implication: with valid raw prices and entitlement quantities, a holding's marked value is `parent quantity × parent price + sum(entitled quantity × entitlement mark) + cash`. The mark must be explicitly classified as provisional or market-observed, and an unlisted entitlement must not become immediately spendable cash. Future listing prices cannot be inserted into earlier valuations. Merely crediting entitlements on top of already synthetic adjusted entry prices risks double counting.

## What is ready and what remains

Ready: exact company COA percentages and letter dates; documented vendor convention; legal share ratios; exchange ex-dates and auction rules; internally verified raw preceding closes and ex-date daily opens/closes. This is enough to explain why the existing apparent losses are not a reliable complete-holding return.

Not certified: an exact published cash-history factor, independent special-session reference-price artifact, complete historical vendor adjustment ledger, entitlement credit/listing timing and subsequent tradable histories, and an agreed valuation convention for unlisted claims. Until these are reconciled, preserve the original archive and mark affected backtest results as economically unresolved. Do not improve reported performance merely by smoothing the discontinuity or deleting the real event.
