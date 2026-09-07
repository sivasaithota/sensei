# BSE bonus shares: trading-availability evidence boundary

Research date: 7 September 2026. Target: an official exchange listing/trading-admission notice for BSE Limited's **270,752,718 bonus equity shares**, specifically confirming admission from **27 May 2025**.

**No qualifying exchange admission notice was retrieved in the bounded four-query search.** The evidence remains a pre-event company plan for May 27 trading and a subsequent confirmation of May 26 allotment. This finding does not establish that the exchange failed to admit the shares or that the notice does not exist; it means the required admission evidence was not obtained here.

## What the existing primary sources establish

The three previously captured PDFs were already visually verified in [the dated bonus evidence note](dated-bse-bonus-publication-evidence-2026-09-07.md). Their bytes were independently rehashed against the existing capture manifest in this pass; all three matched. Existing pinned documents and manifests were not modified.

| Source | Fact supported | Limit |
|---|---|---|
| [BSE company record-date notice, 12 May 2025](https://nsearchives.nseindia.com/corporate/BSE1_12052025155558_NSEintimation.pdf), page 1 | Symbol BSE / ISIN INE118H01025; two new shares per existing share; May 23 record date; May 26 deemed allotment; **planned** trading availability May 27. | An issuer's advance schedule, not an exchange admission order or confirmation of individual account credit. |
| [NSE/FAOP/67987, 14 May 2025](https://nsearchives.nseindia.com/content/circulars/FAOP67987.pdf), page 1 | Explicit 2:1 bonus and May 23 ex/effective date for derivative adjustments. | Does not admit the newly allotted cash-equity shares to trading or establish when they can be delivered by a particular holder. |
| [BSE company allotment notice, 26 May 2025](https://nsearchives.nseindia.com/corporate/BSE1_26052025095238_NSEintimation.pdf), pages 1–2 | Actual May 26 allotment of 270,752,718 shares; total shares increase from 135,376,359 to 406,129,077; bonus equity ranks pari passu with existing equity. | Allotment is not proof of exchange trading admission, depository credit to a particular account, or a broker's sellable balance. The statement cannot establish earlier May 23 knowledge or availability. |

The source hashes, respectively, are `f8409e9b5fa351634e3cb9639dc482d8371dcf433f9d3a31cf0e79efb1021944`, `c2d755649ce6e09630034c71d969cd571fdf237ef738645f11f020b535ccb07d`, and `a0b3d39241f52ce5577794f0159ec590375c49544476f2eeb3107fbcd8a2c6df`. Exact paths and capture provenance remain in `data/research/dated-bonus-evidence/20260907/manifest.json`.

## Exact bounded search

Four official-domain queries were executed:

1. `site:nsearchives.nseindia.com "BSE" "270752718" "2025"`
2. `site:nsearchives.nseindia.com "BSE Limited" "May 27, 2025" "listing"`
3. `site:nseindia.com "BSE" "bonus" "27-May-2025" "admitted"`
4. `site:bseindia.com "270752718" "May" "2025"`

The returned leads predominantly contained BSE Limited as the exchange addressee of unrelated issuers. An [official GHCL filing about May 27 listing/trading approvals](https://nsearchives.nseindia.com/corporate/GHCL_28052025101643_GHCL_Intimation_StockExchange_Trading_Approvals_ESOP_May2025.pdf) concerned GHCL ESOP shares and was rejected as evidence for BSE's bonus shares. Other observed leads concerned DCM, Wipro, Ravinder Heights, Minda Corporation, MedPlus, ESAB or Meesho. None supplied the requested BSE issuer/quantity/admission-date combination.

The search was stopped at the authorized bound. No qualifying additional primary document was obtained, so no new admission PDF or successful-capture manifest was created under the proposed `data/research/bse-bonus-availability/20260907/` directory. No new PDF was visually certified in this pass; the relevant existing PDFs retain their earlier visual checks.

## Replay boundary

Keep the bonus entitlement, allotment, market admission and account credit as distinct facts. An ex-date price-coordinate change does not make the additional shares physically sellable on May 23.

If the replay needs to exercise a May 27 availability transition now, label it **an explicit research scenario assumption based on the issuer's announced schedule**. It must not be reported as independently verified exchange admission or actual broker credit. A strict evidence-only scenario can leave additional shares pending/unavailable until the required evidence arrives. Neither scenario is certified as the historical account ledger by this note.

To close market admission, obtain the exchange's dated approval/circular identifying BSE Limited, the bonus quantity, equity class/ISIN and effective listing/dealing date, or an issuer filing attaching that actual exchange approval. Even a valid market-admission notice would still not establish this account's depository credit or broker-side availability; those require separate account evidence. No broker API, payment, order, external message, source-code change or pinned-evidence edit occurred.
