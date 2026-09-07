# Remaining dated split identities

Research date: 7 September 2026. Scope: the saved 499-stock current-matched snapshot and captured NSE actions from 1 January 2024 through 4 September 2026. This is an **identity-only** supplement. It does not authorize automatic share entitlements, price transformations or portfolio adjustments.

The captured partition records contain 22 split-labelled symbols absent from the original ten-event split evidence. PGEL was delivered separately in `stock-split-identity-pgel-v1.json`; this file covers the remaining **21**, comprising 19 without a same-date bonus in the captured records and two combined split/bonus dates. “Without a same-date bonus” describes this captured scope, not complete corporate-action history.

Each linked primary exchange circular explicitly supplies the old/new ISIN and effective ex-date. NSE captured action ex-dates agree. The companion JSON retains current-universe symbols, with the historical AMIORG symbol distinguished below. New ISINs also match the saved current snapshot, used only as a consistency check.

| Current symbol | Effective ex-date | Old ISIN | New ISIN | Split component ratio | Dated primary source |
|---|---|---|---|---:|---|
| NESTLEIND | 2024-01-05 | INE239A01016 | INE239A01024 | 10 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/January/Circular-14689.pdf) |
| COCHINSHIP | 2024-01-10 | INE704P01017 | INE704P01025 | 2 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/January/Circular-14701.pdf) |
| CGCL | 2024-03-05 | INE180C01026 | INE180C01042 | 2 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/March/Circular-14980.pdf) |
| CANBK | 2024-05-15 | INE476A01014 | INE476A01022 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/May/Circular-15314.pdf) |
| BDL | 2024-05-24 | INE171Z01018 | INE171Z01026 | 2 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/May/Circular-15362.pdf) |
| ELECON | 2024-07-19 | INE205B01023 | INE205B01031 | 2 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/July/Circular-15678.pdf) |
| SAPPHIRE | 2024-09-05 | INE806T01012 | INE806T01020 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/September/Circular-15908.pdf) |
| VBL | 2024-09-12 | INE200M01021 | INE200M01039 | 2.5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/September/Circular-15949.pdf) |
| KIMS | 2024-09-13 | INE967H01017 | INE967H01025 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/September/Circular-15964.pdf) |
| GPIL | 2024-10-04 | INE177H01021 | INE177H01039 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/October/Circular-16089.pdf) |
| JINDALSAW | 2024-10-09 | INE324A01024 | INE324A01032 | 2 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/October/Circular-16114.pdf) |
| DRREDDY | 2024-10-28 | INE089A01023 | INE089A01031 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/October/Circular-16211.pdf) |
| SHRIRAMFIN | 2025-01-10 | INE721A01013 | INE721A01047 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2025/January/Circular-16557.pdf) |
| ACUTAAS | 2025-04-25 | INE00FF01017 | INE00FF01025 | 2 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2025/April/Circular-17050.pdf) |
| NAUKRI | 2025-05-07 | INE663F01024 | INE663F01032 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2025/May/Circular-17119.pdf) |
| BAJFINANCE | 2025-06-16 | INE296A01024 | INE296A01032 | 2 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2025/June/Circular-17333.pdf) |
| ZYDUSWELL | 2025-09-18 | INE768C01010 | INE768C01028 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2025/September/Circular-17786.pdf) |
| BEML | 2025-11-03 | INE258A01016 | INE258A01024 | 2 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2025/October/Circular-18064.pdf) |
| NUVAMA | 2025-12-26 | INE531F01015 | INE531F01023 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2025/December/Circular-18319.pdf) |
| KOTAKBANK | 2026-01-14 | INE237A01028 | INE237A01036 | 5 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2026/January/Circular-18443.pdf) |
| ANGELONE | 2026-02-26 | INE732I01013 | INE732I01021 | 10 | [MSEI circular](https://www.msei.in/SX-Content/Circulars/2026/February/Circular-18646.pdf) |

## Important distinctions

- **VBL:** the 2024 old ISIN is `INE200M01021`, not the API’s older `INE200M01013`. The dated 2024 circular states ₹5 to ₹2: **5/2**, not an integer split multiplier. The preceding June 2023 transition is outside this ledger. [2024 circular](https://www.msei.in/SX-Content/Circulars/2024/September/Circular-15949.pdf).
- **GPIL:** the dated 2024 circular gives old `INE177H01021`; the action API carries earlier `INE177H01013`. Use the dated transition, not the API’s stale ISIN. [Circular](https://www.msei.in/SX-Content/Circulars/2024/October/Circular-16089.pdf).
- **KOTAKBANK:** the January 2026 circular gives old `INE237A01028`; the action API carries earlier `INE237A01010`. [Circular](https://www.msei.in/SX-Content/Circulars/2026/January/Circular-18443.pdf).
- **ACUTAAS:** the April 2025 split occurred under **AMIORG** with old `INE00FF01017`, new `INE00FF01025`; the action API already uses the later name/symbol and new ISIN. NSE changed AMIORG to ACUTAAS effective **2 June 2025**, not the issuer’s earlier corporate-name approval date. Correct ISIN alone does not make the later symbol valid for an April raw-row lookup. [Split circular](https://www.msei.in/SX-Content/Circulars/2025/April/Circular-17050.pdf), [NSE name/symbol circular CML68201](https://nsearchives.nseindia.com/content/circulars/CML68201.pdf).
- **CGCL:** old `INE180C01026` changes to `INE180C01042`; the API carries earlier `INE180C01018`. The captured 5 March 2024 records include both a two-for-one split and **bonus 1:1**. The JSON ratio 2 describes the split component only; it is not a combined share entitlement. [NSE split-identity confirmation](https://nsearchives.nseindia.com/content/circulars/CML60920.pdf), [captured first-half 2024 request](https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=01-01-2024&to_date=30-06-2024).
- **BAJFINANCE:** old `INE296A01024` changes to `INE296A01032`; the API carries earlier `INE296A01016`. The captured 16 June 2025 records include both a two-for-one split and **bonus 4:1**. NSE’s corrigendum assigns the bonus shares to the new ISIN. The JSON ratio 2 excludes that bonus and must not drive combined entitlement accounting. [NSE split circular](https://nsearchives.nseindia.com/content/circulars/CML68472.pdf), [NSE bonus corrigendum](https://nsearchives.nseindia.com/content/circulars/CML68469.pdf), [captured first-half 2025 request](https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=01-01-2025&to_date=30-06-2025).

## Scope and limitations

These identity transitions support dated raw-row matching when the row also passes symbol, EQ-series, session and OHLCV checks. They do not establish dividend, rights or demerger entitlements, fractional-share settlement, adjustment factors, tradeability, historical universe membership, or original announcement availability. A dated circular can resolve identity without proving how a backtest should credit or sell newly issued shares.

The captured NSE whole-year 2024 response omitted a COASTCORP dividend found in its partition; that discrepancy remains in `data/reports/portfolio-action-evidence/manifest.json`. This selection used the partition union and does not certify provider completeness. Earlier-than-2024 transitions are not reconstructed here. Existing PGEL and ten-event notes/ledgers were not modified.
