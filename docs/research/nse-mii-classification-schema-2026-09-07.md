# NSE MII classification schema: bounded source findings

Research date: 7 September 2026. This supplements the [dated classification source investigation](dated-stock-classification-sources-2026-09-07.md). It is a schema investigation, not a classification feed or certification of historical eligibility.

**The official 120-field MII schema and contemporary broad instrument, SME and status dictionaries are captured.** Both the 2023 and 2024 documented headers match the 6 January 2025 master after trimming incidental spreadsheet spaces. Fully paid ordinary-share eligibility and complete historical coverage are still not certified.

## Verified dated facts

| Source | Fact established | Consequence for ingestion |
|---|---|---|
| [NSE/MSD/60315, 19 January 2024](https://nsearchives.nseindia.com/content/circulars/MSD60315.pdf), page 1 | Announces daily website dissemination of the MII security and contract files, effective **5 February 2024**. Refers to existing member-extranet dissemination under circular 55276 of 17 January 2023. | Do not presume public January 2024 coverage merely because a later dated filename exists. The announcement does not prove that earlier files were never published retrospectively, or that all subsequent files are retained. |
| [NSE/MSD/57416, 4 July 2023](https://archives.nseindia.com/content/circulars/MSD57416.pdf), pages 1–2 | Identifies the compressed cash-market filename `NSE_CM_security_ddmmyyyy.csv.gz`; discontinues the corresponding uncompressed CSV dissemination from 17 July 2023. References schema-related circulars 54422, 55276 and 56654. | This establishes packaging and a format-reference chain. It is not the field dictionary and does not certify unchanged schema across 2024–2026. |
| [NSE/MSD/67344, 28 March 2025](https://nsearchives.nseindia.com/content/circulars/MSD67344.pdf), sections C, D and F | Adds value **2 = BSE listed** to MII field **17, `PrtdToTrad`**, effective **1 April 2025**. BSE-exclusive records may have eligible status while actual trading requires invocation of the alternative venue. Distinguishes NSE-only and combined security-master variants. | Preserve file scope and this permission value separately from status. An eligible record in the combined file cannot automatically enter a normal NSE stock universe. Do not infer missing historical values from this extension. |

The last circular also identifies a dollar suffix on BSE-exclusive symbols. That is documented provenance for this particular venue mechanism, not a generic symbol classifier. Its instruction to load the appropriate master before trading supports its operational use; it does not independently prove the public release timestamp of an archived file. [NSE/MSD/67344, sections C–D](https://nsearchives.nseindia.com/content/circulars/MSD67344.pdf).

## Official schema packages captured

Direct HTTP requests with browser-style headers resolved the **ZIP packages**, while the corresponding standalone `.pdf` URLs returned 404 HTML. The correct official sources are [MSD55276.zip](https://nsearchives.nseindia.com/content/circulars/MSD55276.zip) and [CMTR61813.zip](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip). This is a concrete packaging correction; a failed PDF URL must not be treated as absence of its circular.

The [local manifest](../../data/research/nse-mii-schema/20260907/manifest.json) records source URLs, paths, archive and extracted-member hashes, byte counts, and local capture-completion clocks. The local clocks are not original publication times. No historical master was downloaded by this research subtask; the main implementation separately captured the 6 January 2025 sample.

| Package/member | SHA-256 |
|---|---|
| `MSD55276.zip` | `b221d3ede7f7e6e8ba3e5da7377f147ce0535e22b7df8904c14d063797fd7c8e` |
| `MSD55276.pdf` inside that package | `2d9abce78153e299c9162e394cf7fdd33e065ae1f769092462c7e32971c2f2da` |
| `Annexure-A_CM.xlsx` inside that package | `05443f4d0b14163f2398ba3b6bdf133b633291780b65cfea58a2084d51b21a6d` |
| `CMTR61813.zip` | `d58c836cc1ce5504b328118b7887c91bc75189d13a806c5b3c83f343584a8c90` |
| `CMTR61813.pdf` inside that package | `9c956956c9c4e57f31bce4e6195bf58f1acbadeb3b45a6c28e533f1c88a21211` |
| `PART-D.xlsx` inside that package | `936082c7f2308d84e5865022dff0bf803738745dc38cbc5ae00695d28bd3be82` |

### Schema and sample agreement

The January 2023 circular identifies its Annexure A as the cash-market security-master format. Both pages of that circular were rendered and visually inspected. Sheet `Annexure 1_security master file` in `Annexure-A_CM.xlsx` lists 120 fields and maps the existing `Security.txt` field names to ISO tags. Every tag matches the separately captured 6 January 2025 CSV header in order after trimming three incidental spreadsheet spaces: field 9 `BidIntrvl`, field 57 `SctyTp`, and field 73 `UndrlygInstrmAsstClss`. Original headers remain preserved. [Official MSD55276 package](https://nsearchives.nseindia.com/content/circulars/MSD55276.zip).

The workbook explicitly marks `FinInstrmTp` (field 64), `FinInstrmClssfctn` (103) and `ClssfctnTp` (108) as **filler**. Their blank values in this sample therefore do not independently demonstrate missing classification records. Actual instrument type is field 8, `SctyTpFlg`, mapped from `InstrumentType`; series is field 3, `SctySrs`. [Official MSD55276 package, Annexure A](https://nsearchives.nseindia.com/content/circulars/MSD55276.zip).

The April 2024 consolidation repeats these mappings in `PART-D.xlsx`, sheet `Annexure 11`; its complete 120-tag sequence also matches the sample after trimming the same spreadsheet whitespace. Its cover identifies Part D as the exchange file formats and states that the consolidation replaces June 2023 circular 57270. Thus the contemporary code bridge below is supported within one official 2024 package, rather than inferred solely from the 2008 reference. [Official CMTR61813 package](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip).

### Broad instrument, market and status dictionaries

`PART-D.xlsx`, `Annexure 1`, rows 6–11 defines `InstrumentType`; `Annexure 11`, row 18 maps it to `SctyTpFlg`:

| Value | Documented class |
|---|---|
| 0 | Equities |
| 1 | Preference shares |
| 2 | Debentures |
| 3 | Warrants |
| 4 | Miscellaneous |

**Value 4 does not mean ETF exclusively, and value 0 does not by itself mean a fully paid ordinary main-board share.** The SBIN and BANKBEES observations can now be described as different documented broad classes, without inventing a complete subtype classifier. [Official CMTR61813 package, Part D, Annexures 1 and 11](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip).

The same package maps `SSEC` to MII field 11, `CallAuctnInd`. Its legend is 1 normal-market security, 2 IPO-session security, 3 relisting-session security, 4 call-auction-2 security, and **5 SME security**. This is a market-security identifier, not a permanent issuer attribute. Preserve an observed IPO or relisting value without assuming main-board status. `CMTR61813.pdf`, section 1.12, page 29, separately identifies SME series SM, ST, SZ, SL, SO and SQ for their respective trading arrangements; that page also says the block session is not applicable to SME securities despite listing SL in the historical series table. Page 29 was rendered with system fonts and visually inspected. Do not turn that series listing into a claim that every window is active. [Official CMTR61813 package, Part D Annexure 1 rows 99–104 and Annexure 11 row 21; PDF page 29](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip).

For normal-market status, the documented codes are 1 pre-open, 2 open, 3 suspended, 4 extended pre-open, 5 stock opens with market, and 6 price discovery. Normal-market eligibility is separately 0 ineligible or 1 eligible. Permission is separately 0 listed or 1 permitted to trade in this 2024 dictionary; the 2025 BSE value extension above must be handled by date and file scope. These fields describe different concepts and must not be collapsed into a single stock-class flag. [Official CMTR61813 package, Part D Annexure 1 rows 13–23 and Annexure 11 rows 27–30](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip).

### Current conclusion

The broad field meanings now have authoritative contemporary evidence and can be retained in the metadata coverage output. A sample's class, series, status and raw-price identity can be reconciled without relying on security-name heuristics. However, one captured master and two schema packages do not establish full 2024–2026 archive completeness, every subsequent code change, original pre-opening availability, fully paid share subtype, or permanent identity through corporate actions. Keep those remaining coverage and eligibility questions explicit.

## Bounded access record

The initial pass used four search queries and bounded reads of official circulars. Indexed text established the operational dates above; direct PDF and screenshot access failed. Two further exact field-name queries returned no results. The follow-up used four direct document requests: two PDF URLs returned 404, and the two ZIP URLs succeeded. This supersedes the initial conclusion that no local schema package had been captured. Extracted spreadsheet members were read locally, the January 2023 circular was visually inspected, and the relevant April 2024 series page was visually inspected after configuring system fonts.

No historical security-file URL was retried by this subtask, no bulk download was attempted, and no Kite requests, credits, purchases, account changes or external messages were made. The deliverables are this note and hashed source packages; no code, configuration or universe membership was changed.
