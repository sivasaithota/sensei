# Dated NSE stock classification: source route and ingestion contract

Research date: 7 September 2026. This is a bounded source investigation for the proposed daily NSE liquidity universe, not a historical-universe certificate or an implemented eligibility feed.

**A concrete official daily security-master route exists. Its usable historical coverage and ordinary-stock classification semantics remain unverified.** The next ingestion pass should investigate that route before attempting to reconstruct classifications from names or today's security lists. No dated security-master file was successfully captured in this pass; failed requests establish an access failure here, not absence of the files at NSE.

## Official route

NSE's [All Reports page](https://www.nseindia.com/all-reports/) lists a historical date selector and two distinct reports: the MII security file for NSE-listed securities, and the version including BSE-exclusive securities. The distinction must be retained in provenance; the two reports must not be combined as though they describe the same exchange universe.

[NSE circular MSD67344](https://nsearchives.nseindia.com/content/circulars/MSD67344.pdf), section D, identifies the dated filename `NSE_CM_security_ddmmyyyy.csv.gz`. It distinguishes the NSE-only member path `/cmftp/common/ntneat` from the interoperability paths, links both website variants to All Reports, and instructs members to upload the appropriate master daily before trading hours. This supports investigating a dated pre-trading operational file. It does **not** prove an exact public publication timestamp, unchanged historical vintage, complete public archive, or a particular ordinary-stock/ETF classification field. The indexed official circular excerpt was accessible; a subsequent direct PDF request timed out, so no locally hashed PDF is claimed.

An older primary format reference, [NSE/CMTR/11581, 4 November 2008](https://nsearchives.nseindia.com/content/circulars/cmtr11581.htm), documents `security.gz` and `nnf_security.gz`. It includes instrument type, market eligibility/status, board lot, tick size, listing/expulsion/readmission dates, ISIN and a local update timestamp. Its token is scoped to a symbol–series combination. The instrument-type legend groups equities separately from preference shares, debentures, warrants and miscellaneous securities; it does not provide a distinct ETF category in that legend. **This is an old format reference, not evidence that the 2024–2026 MII CSV schema or its codes are identical.** In particular, its local database update time is not automatically a public release time.

NSE's [segment-wise historical reports](https://www.nseindia.com/static/regulations/segment-wise-historical-reports) also list monthly exchange reports and a definition workbook across 2024–2026. These are secondary source leads for reconciliation. Their contents were not downloaded or examined here, and monthly report labels alone do not establish daily classifications.

## What the saved raw file actually says

The saved `data/nse_bhavcopy_raw/2024/BhavCopy_20240101.csv.zip` was directly decoded for the following comparison. Its already recorded ZIP SHA-256 is `067374fc5663cc4c0db1e4022e6e50de3491e3bbc7f209ec12fccbdafdd1fcfd`; the earlier [universe feasibility investigation](daily-nse-universe-feasibility-2026-09-07.md) describes the independently verified endpoint receipt. Source URL: [NSE 1 January 2024 bhavcopy](https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20240101_F_0000.csv.zip).

| Raw field | SBIN | BANKBEES |
|---|---|---|
| `FinInstrmTp` | STK | STK |
| `SctySrs` | EQ | EQ |
| `NewBrdLotQty` | 1 | 1 |
| `FinInstrmId` | 3045 | 11439 |
| `ISIN` | INE062A01020 | INF204KB15I9 |
| `FinInstrmNm` | STATE BANK OF INDIA | NIP IND ETF BANK BEES |

Thus **STK + EQ + board lot 1 admits this ETF as well as the company share**. The name is useful diagnostic evidence for this example; substring matching is not a defensible complete classification policy. Neither the different financial-instrument IDs nor the different ISINs establishes permanent economic identity through future corporate actions. No such cross-date identity rule was inferred.

The [current parser](../../src/sensei/data/bhavcopy.py) retains symbol, series and ISIN, but drops these raw name, instrument-ID and board-lot fields from the normalized schema. Its interim equity-series label explicitly is not an authoritative security master. A diagnostic extension can preserve the fields without promoting that label to ordinary-stock eligibility.

## Next ingestion contract

The following is a proposed engineering contract, not a claim about the downloaded data:

1. **Resolve the actual historical download through the official report entry.** Request one early and one later sample, ideally bracketing an observed listing or SME migration. Record NSE-only versus interoperability scope, report label, requested session, resolved URL, retrieval time, response status, compressed/decompressed hashes and the exact schema. Reject HTML/error bodies and wrong-date files. Apply bounded sizes, rows and decompression limits before parsing.
2. **Pin the applicable contemporary format documentation.** Locate the dated MII schema and all changes affecting the sample windows. Demonstrate ordinary company equity versus ETF, preference shares, debt, rights entitlements, REIT/InvIT and SME using positive and negative examples. If a master code only says “equities,” preserve an unknown subtype until dated additional evidence resolves it. Do not assume the 2008 code dictionary still applies.
3. **Separate clocks.** Preserve effective session, file business date, documented release/known-from time, retrieval time and revision identity. A same-session master may inform an opening decision only when its pre-opening availability is supported. Otherwise use a conservative later decision boundary and explicitly report the lag; never backdate knowledge from the filename alone.
4. **Keep classification separate from tradability and identity.** Proposed normalized fields are internal instrument ID, symbol, series, ISIN, exchange token, security subtype, board/listing segment, status/eligibility, effective interval, known-from time and source hashes. Each field needs its own evidence or an explicit unknown. A master token is a cross-check, not an invented perpetual identifier. Split ISIN changes, renamed symbols, reused symbols and SME migrations require dated transitions; an unexplained conflict blocks the affected mapping.
5. **Reconcile the archive before generating eligibility.** Compare every required session against an independently established exchange calendar; compare classified records against that session's raw symbol–series–ISIN tuples. Distinguish missing source, missing master row, suspended security, no trade and unknown classification. Never turn a missing response into a universe deletion or infer a delisting from last observed trading.
6. **Freeze a metadata-only coverage report first.** Report confirmed ordinary shares, confirmed exclusions, unknown rows, duplicate identities, unsupported schema periods and missing sessions. Only then derive a separately named, preregistered liquidity universe using information available at the previous decision close. Persist held positions independently of subsequent eligibility. No point-in-time or full-universe admissibility flag should be enabled merely because this adapter exists.

## Bounded access result and decision

Four primary-source search queries were used, followed by official-page reads. Direct requests to All Reports and the cited circular timed out. Two **candidate, unconfirmed URL paths**, constructed from the observed dated filename under NSE's existing cash archive directory, also timed out: `https://nsearchives.nseindia.com/content/cm/NSE_CM_security_01012024.csv.gz` and `https://nsearchives.nseindia.com/content/cm/NSE_CM_security_06012025.csv.gz`. Neither URL was validated as the actual report download; neither timeout is evidence that its historical file does not exist. No response body was retained, no bulk download was attempted, and there were no Kite calls, purchases, or account actions.

**Next concrete action:** resolve one historical NSE-only MII master from the official selector, verify its schema and class semantics against the raw examples above, then expand only after that sample passes. Until then, the custom stock-liquidity universe remains a viable proposal with an unresolved classification input. Current lists and name/ISIN heuristics must not fill that gap silently.
