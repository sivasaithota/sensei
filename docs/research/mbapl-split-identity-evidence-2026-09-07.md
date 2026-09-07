# MBAPL split accounting identity

Research date: 7 September 2026. The documented split is **5 new shares per old
share**, effective/ex-date **3 July 2026**, replacing `INE900L01010` with
`INE900L01028` for MBAPL.

[NSE/CML/74938, 30 June 2026](https://nsearchives.nseindia.com/content/circulars/CML74938.pdf)
states the new ISIN, subdivision from ₹10 to ₹2, and application to trades from
the ex-date. [NSE/CML/74880, 25 June](https://nsearchives.nseindia.com/content/circulars/CML74880.pdf)
separately sets the face/paid-up-value change effective that date.

[NCL/CMPT/74989, 2 July](https://nsearchives.nseindia.com/content/circulars/CMPT74989.pdf)
explicitly identifies the old ISIN and 3 July record/ex-date. Its example equates
sale of ten new units with early pay-in of two old units. It describes old-ISIN
early pay-in on 3 July and new-ISIN early pay-in on 6 July. This is a settlement
procedure, not confirmation that a particular account received freely sellable
new shares on the ex-date. The new-ISIN notice and the relevant clearing table
were visually inspected from captured PDFs.

The [saved raw observations](../../data/research/mbapl-split-identity/20260907/raw-observations.json)
retain full source rows and ZIP/CSV hashes. MBAPL/EQ token 12686 stays unchanged:

| Session | ISIN | Open | Close | Previous close field |
|---|---|---:|---:|---:|
| 2026-07-02 | INE900L01010 | 593.25 | 604.30 | 593.25 |
| 2026-07-03 | INE900L01028 | 120.50 | 125.15 | 604.30 |

The ex-date previous-close field therefore retains old units. Applying the
documented 5-for-1 accounting conversion requires matching this exact event and
identity pair; it must not trigger an unrestricted symbol join or splice signal
history. Notice dates are distinct from this research's capture clocks and do
not establish original intraday dissemination times. Account-credit assumptions
remain separately labeled scenarios.

Three primary-source PDFs were downloaded. A secondary circular index was used
only to discover the original NSE links; all action claims above were checked
against the original sources. No previous evidence artifacts were changed, no
Kite or new raw-price calls were made, and no execution code was edited.

| Artifact in `data/research/mbapl-split-identity/20260907/` | SHA-256 |
|---|---|
| [Manifest](../../data/research/mbapl-split-identity/20260907/manifest.json) | `80df00fd896ddd4023c051f673a782c12f3428374dffd16c251e1fa1046fd2cd` |
| [Bridge fields](../../data/research/mbapl-split-identity/20260907/bridges.json) | `dbb4162ff15e41f34a22567a578896c3e05ede7eebdd3701a897d3f3b09fe95f` |
| Raw observations | `04989793a1799091faac7b257968d600ea5ad8330b5b9fac34cc1baeaade3958` |
| CML74938.pdf | `5d3bb309d228791f340b619fe7e030ad66c2289bbcd0044f32d7d4478083c7dc` |
| CML74880.pdf | `a5d2f70873d3833d4440cecf25b5d122fe3d967ac81173984eeaffe1c5115aaf` |
| CMPT74989.pdf | `becf3ecd62a3492aa2c49865e1aba37cb372e68d1350be98fcae6224ecc45cd7` |
