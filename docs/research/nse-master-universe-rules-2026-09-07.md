# Dated NSE master: candidate-universe rules and remaining evidence

Research date: 7 September 2026. This note supplies conservative rules for the bounded cross-date metadata audit. It does not approve a trading universe or rerun a portfolio.

**The captured evidence supports a dated candidate screen, with explicit exclusions and unresolved cases. It does not yet certify that `SctyTpFlg=0`, `SctySrs=EQ`, and `CallAuctnInd=1` always identify ordinary main-board shares.** The missing bridge is a complete dated subtype and board interpretation, particularly the treatment of every ETF and other equity class. One correct BANKBEES example cannot establish a universal mapping.

## Captured sources

| Source | Local receipt and SHA-256 | Evidence |
|---|---|---|
| [NSE/MSD/67344, 28 March 2025](https://nsearchives.nseindia.com/content/circulars/MSD67344.pdf) | [manifest](../../data/research/nse-master-rules/20260907/manifest.json); PDF `8cff554cd21720ada13a9837f47e33f000f43974e1b8da480e49f200204c1786` | Sections C, D and F, pages 2–4, visually inspected after local rendering. |
| [NSE Legend of series](https://www.nseindia.com/static/market-data/legend-of-series) | [HTML receipt](../../data/research/nse-master-rules/20260907/legend.capture.json); HTML `57309990d7e4418d3f3293a7a11a94116bc99afdf15a5e2b7267b28ce153bba7` | Current captured page displays an update date of 19 September 2024. This is not an archived 2024 page capture. |
| [NSE/CMTR/61813 package, 30 April 2024](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip) | Existing [schema manifest](../../data/research/nse-mii-schema/20260907/manifest.json); `PART-D.xlsx` SHA `936082c7f2308d84e5865022dff0bf803738745dc38cbc5ae00695d28bd3be82` | Annexures 1 and 11 supply the instrument, market, eligibility, status and MII-tag mappings described in the [schema note](nse-mii-classification-schema-2026-09-07.md). Relevant workbook rows were rechecked locally. |

Capture clocks record when this research downloaded the documents. They are not historical release timestamps for security masters.

## Permission version boundary

MSD67344 introduces **`PrtdToTrad=2` for BSE-listed exclusive securities**, at MII field 17, effective **1 April 2025**. A mock on 29 March is separately identified. Such records may be marked eligible even though trading depends on invocation of the alternative venue. The circular distinguishes the NSE-only master from the combined NSE/BSE-exclusive master, despite identical base filenames. Therefore preserve the report descriptor alongside the payload and date. [Official circular, sections C, D and F](https://nsearchives.nseindia.com/content/circulars/MSD67344.pdf).

For production-session interpretation, use the pre-extension dictionary `0=listed`, `1=permitted to trade` before 1 April; add the documented meaning of `2` from that date. An earlier `2` is a version anomaly requiring evidence, not an ordinary NSE admission. A later `2` is interpretable but excluded from this NSE-only candidate policy. An unexpected `2` in an NSE-only response must also be reported as a file-scope inconsistency. Other undocumented values remain unresolved. These are proposed audit rules, not claims that the selected archive samples contain such anomalies.

## What the other fields establish

The series legend groups fully paid equity shares **and ETFs** under EQ, with separate SME and partly-paid series. EQ alone therefore cannot exclude ETFs. The page does not map MII instrument codes to ETF status, distinguish all voting/share classes, or certify that its current content exactly reproduces the displayed 2024 update. Applying it before 19 September 2024 needs earlier evidence. [NSE Legend of series](https://www.nseindia.com/static/market-data/legend-of-series).

The 2024 workbook labels `SctyTpFlg=0` equities and `4` miscellaneous; `1/2/3` denote preference shares, debentures and warrants. `CallAuctnInd=1` denotes normal-market security, while `5` identifies SME security. Codes `2/3/4` describe IPO, relisting and call-auction-2 sessions. These are distinct dimensions. Normal-market state `3` means suspended; eligibility `0` means ineligible. Other documented states include pre-open, open, extended pre-open, stock opens with market, and price discovery. Requiring state `2` exclusively would incorrectly equate a snapshot's current phase with daily eligibility. [CMTR61813, Part D, Annexures 1 and 11](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip).

The same workbook describes DeleteFlag as whether the security is deleted; its cited row does not enumerate the character mapping. Retaining raw Y/N is justified; interpreting Y as a conservative exclusion is a policy assumption until its value dictionary is pinned. It is not evidence that the issuer delisted on the file date. A row absent from a bhavcopy likewise does not prove deletion.

## Proposed candidate screen

Apply these rules to each independently validated dated row, retaining all source fields and reasons. Exclusion means outside this narrow candidate policy; it need not mean the instrument was legally untradeable.

1. Require a verified master date/scope/schema and an exact symbol, series, ISIN and token reconciliation where a raw observation exists. Missing or conflicting identity remains unresolved. Master-only rows must remain separately visible, because a raw-price observation is not a listing register.
2. Exclude documented non-equity broad types, SME market code `5`, non-EQ series, BSE-exclusive permission `2`, suspended normal-market state and normal-market ineligibility. Keep reasons separate; never turn miscellaneous into an ETF-only class.
3. Preserve unknown codes as unresolved. Treat deletion-marked rows conservatively and report the explicit deletion-policy assumption. IPO, relisting and call-auction-2 rows are outside the initial normal-market candidate screen; do not infer their permanent board.
4. The initial implemented screen requires broad equity type `0`, EQ series, normal-market identifier `1`, permission **`0`**, eligible status, a documented nonsuspended state, raw **`DelFlg=N`**, and board lot exactly **`1`**. A qualifying row may be labelled **metadata candidate pending subtype/board and timing evidence**. Permission `1` remains unresolved outside this initial candidate policy; the documented meaning “permitted to trade” does not make it inherently invalid. Requiring N and a one-share board lot are conservative policy choices, not proof of ordinary-share subtype. Missing or other deletion values do not qualify and remain unresolved unless an independent exclusion applies. This label cannot populate `confirmed_main_board_ordinary` or set `admissible=true`.

This screen is useful for measuring gaps and narrowing the instruments requiring evidence. Positive ordinary-share classification needs a documented exhaustive code bridge or dated security-level admission evidence; name/ISIN-prefix heuristics and today's security list are insufficient replacements. Exact daily identity still needs corporate-action continuity for lagged indicators.

## Timing and coverage limits

The 2023 MII mapping establishes field names, while the captured 2024 consolidation supplies the code dictionary. Identical headers alone do not certify unchanged semantics for the February 2024 sample or all later dates. Label dictionary applicability as a research assumption where the contemporary version chain is incomplete.

The exchange's instruction to load a master before trading is evidence of intended operational use. It does not prove when a particular archived payload was published or whether it was revised. Same-session eligibility and same-session observed turnover must not automatically become pre-open knowledge. A future research run could explicitly test a prior-session snapshot policy with lagged prices, but that assumption must be named, hash-pinned and distinguished from verified historical availability; it cannot silently forward-fill missing dated classifications.

This subtask made two direct public-source downloads, each successful, plus bounded official-source web searches/reads. No Kite requests or credits, orders, account changes, purchases or strategy evaluation occurred. Source files and this note are the only deliverables.
