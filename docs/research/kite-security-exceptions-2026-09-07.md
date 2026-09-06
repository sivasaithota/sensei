# Kite security exceptions: exchange identity and trading eligibility

Research date: 2026-09-07. Scope: three named exceptions in the frozen Kite archive, using official exchange/company sources and read-only local evidence. No broker requests, credential reads, price repairs, or trading activation were performed for this investigation.

## Findings that change the validation decision

| Security | Confirmed finding | Dataset treatment supported by the evidence |
|---|---|---|
| JBCHEPHARM | NSE suspended trading from 2026-07-17 because of amalgamation. | Stop expecting tradable NSE bars after 2026-07-16; retain the historical security and explicit merger event. Its missing earlier history is still unresolved. |
| FORCEMOT | NSE withdrew permitted-to-trade dealings from 2023-10-26; a new NSE listing became effective 2024-02-14. | The missing 2024-01-20 NSE bar is an expected inactive interval, not a bar to interpolate or copy from another exchange. |
| MAZDOCK | Public listing occurred 2020-10-12, but an archived response includes a zero-price row dated 2017-12-04. | Preserve and quarantine the anomalous row. The current instrument mapping does not establish historical identity for it. |

## JBCHEPHARM: suspension for amalgamation, not a simple symbol rename

NSE circular **NSE/CML/75178**, dated **2026-07-13**, suspends JBCHEPHARM, EQ series, from **2026-07-17**, explicitly after the close of trading on **2026-07-16**. Its stated reason is the scheme of amalgamation. This establishes the NSE trading boundary independently of any vendor's last recorded date. [NSE suspension circular](https://nsearchives.nseindia.com/content/circulars/CML75178.pdf)

The company’s own announcement index identifies an effective-date disclosure dated **2026-07-08**. A preceding company filing confirms that the proposed transaction is amalgamation of J.B. Chemicals & Pharmaceuticals into Torrent Pharmaceuticals. The effective-date attachment and record-date attachment did not load through the research browser, so this note does not certify their full terms, share-conversion ratio, fractional-share treatment, or allotment/trading dates. [JB effective-date disclosure page](https://jbpharma.com/download/disclosure-of-material-event-effective-date-of-amalgamation-08-07-2026/), [company filing describing the parties](https://nsearchives.nseindia.com/corporate/JBCHEPHARM_25032026195914_NSE_NCLT.pdf)

The old security is identified as **INE572A01036** in a June 2026 company disclosure filed with NSE. The locally captured September 6 NSE equity reference identifies TORNTPHARM as **INE685A01028**. These are distinct securities; simply renaming JBCHEPHARM history to TORNTPHARM would not represent the corporate action. [Official JBCHEPHARM disclosure with ISIN](https://nsearchives.nseindia.com/corporate/ixbrl/IT_179_20260629_192937749_WEB.html), [NSE equity reference](https://archives.nseindia.com/content/equities/EQUITY_L.csv)

Local evidence checked:

- JBCHEPHARM is absent from the frozen current Kite acquisition scope and the captured current NSE equity list. This is consistent with the exchange suspension; absence from a current master alone is not historical-identity proof.
- `data/prices/JBCHEPHARM.parquet` contains **one row only**, dated **2026-07-23**, with open/high/low/close all approximately **₹2,408.90**, volume **0**, and turnover **0**. Its SHA-256 is `23f161fcc27fb451859469500fe53ed1db5d00b6ea15d4305b4a62649ad9cecd`.
- Therefore the earlier shorthand “history ends July 23” overstates local coverage. This is one post-suspension vendor row, not an established tradable history through that date. Preserve it as source evidence; it cannot support a July 23 simulated fill.

Closure: post-July-16 missing NSE bars should be classified as suspended/merged security rather than download failures. Still unresolved: authentic pre-suspension historical OHLCV and a verified corporate-action ledger for portfolios holding the stock across the merger. Do not silently drop JBCHEPHARM from an earlier historical universe or splice Torrent prices into it.

## FORCEMOT: confirmed inactive NSE interval

NSE circular **CML58560** withdraws FORCEMOT from the permitted-to-trade category effective **2023-10-26**, after **2023-10-25** trading. It gives ISIN **INE451A01017**. The closing administrative sentence says the circular is effective October 25; the operative trading sentence explicitly makes withdrawal effective October 26 after the prior close. Use that stated trading boundary. [NSE withdrawal circular](https://archives.nseindia.com/content/circulars/CML58560.pdf)

The company’s February 13, 2024 disclosure attaches NSE circular **NSE/CML/60618**, dated **2024-02-12**. That circular admits FORCEMOT to NSE dealings from **2024-02-14**, EQ series, with the **same ISIN INE451A01017**. This is continuity of the security across an interval when it was unavailable on NSE, not evidence that the stock did not exist before 2024. [Company disclosure and attached NSE listing circular, pages 1–3](https://www.forcemotors.com/wp-content/uploads/2025/02/Announcement-under-Regulation-30-for-Listing-on-NSE.pdf)

Local independent observations agree with those boundaries:

- The verified raw NSE bhavcopy for **2024-01-20** contains **no FORCEMOT row**, including when checking all classes and series rather than only the equity-clean subset.
- The frozen Kite response for 2022-01-01 through 2026-09-04 contains bars for **2023-10-23**, **2023-10-25**, then **2024-02-14**, **2024-02-15**, and **2024-02-16**. No bars appear between October 25 and February 14 in that response.
- The captured NSE equity reference lists February 14, 2024 as the listing date. Applying that current listing-date field as a universal lower bound would incorrectly discard the earlier permitted-to-trade period, for which Kite has bars back to 2019-08-20.

The current evidence supports an NSE-ineligible interval **[2023-10-26, 2024-02-14)**. In an NSE-only backtest, January 20 is not a missing required FORCEMOT session. This does not establish availability or prices on BSE, nor authorize cross-exchange substitution. The backtest must also model what happens to an existing holding during the withdrawal interval; it must not invent daily exits or carry a forward-filled price as an executable quote.

Local evidence identifiers:

- Kite request hash: `c1c9f8237fe8ae59b29568a5a576e2c0de69a7a5c6fd35b1cdafe595ac18a8aa`, under `~/.local/share/sensei/kite/raw/c1/`.
- Raw NSE session source: [2024-01-20 bhavcopy](https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20240120_F_0000.csv.zip).
- Internally verified session manifest SHA-256: `c17b353d4410a60afe53c24cc4305f207a80a1a3e18146eafba89e008a1f7d6d`; CSV SHA-256: `14a267ba244f8b33001918f1ffa77d25e3334365168dc3caba80bf4b878f9e52`. Raw bhavcopy verification establishes internal consistency, not adjusted-price admissibility.

## MAZDOCK: pre-listing zero-price anomaly

Mazagon Dock’s official event archive dates its BSE listing ceremony to **2020-10-12**. The captured official NSE equity reference independently lists **2020-10-12** as MAZDOCK’s listing date. [Company listing event](https://mazagondock.in/English/Events/ViewEvent/102), [NSE equity reference](https://archives.nseindia.com/content/equities/EQUITY_L.csv)

The locally preserved rejected Kite response for 2017-11-26 through 2021-12-31 contains this exact row:

```json
["2017-12-04T00:00:00+0530", 0, 0, 0, 0, 7154666]
```

It assigns positive volume to zero open/high/low/close nearly three years before the documented listing. The response has 313 rows total and is stored under rejected request hash `5d7875eec7a93cb248344caaf9b46904c575978763c1fbeb490a5e40220b97e7` at `~/.local/share/sensei/kite/rejected/5d/`.

This is an invalid OHLCV record and a historical-identity anomaly. **Token reuse is not confirmed** by the documents or local response. Neither is a correction date or a replacement bar. Do not shift the date, fill prices, or count this as MAZDOCK trading in 2017. Any staged extraction of otherwise valid rows must preserve the rejected row and record the exclusion explicitly; the response must not be relabelled entirely clean.

## Implementation implications

Security eligibility needs dated exchange intervals and corporate actions, not only a symbol and earliest observed candle. Keep source publication dates separate from effective dates so a historical simulation cannot know a later notice prematurely. These findings support specific interval exclusions and anomaly classifications; they do not make the whole Kite archive point-in-time correct or corporate-action verified.

The frozen archive plan examined here is `4a26765db63fd41f2e11a1f40e718ef2517a0a3ac6a768eab03d99863b7d2c14`. Current reference data is the captured `~/.local/share/sensei/kite/reference/20260906-EQUITY_L.csv` and its receipt; the live NSE download URL is mutable, so reproducible checks should use that frozen local artifact.
