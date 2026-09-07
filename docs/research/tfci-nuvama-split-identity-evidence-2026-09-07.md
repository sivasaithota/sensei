# TFCILTD and NUVAMA split identity bridges

Research date: 7 September 2026. Official NSE notices establish both new ISINs,
the split face values and the ex-date on which the new identity applies to
trades. Together with the saved before/after raw observations, they explain why
an action record bearing the old ISIN can refer to the same holding whose
ex-date bar bears the new ISIN. The bridge is specific to each documented action;
it is not permission to join unrelated price histories by symbol.

## Verified action facts

| Symbol | Old ISIN observed immediately before | New ISIN | Ex/effective date | Face values | New shares per old share | NSE notice date |
|---|---|---|---|---|---|---|
| TFCILTD | `INE305A01015` | `INE305A01023` | 2025-09-19 | ₹10 → ₹2 | 5 | 2025-09-16 |
| NUVAMA | `INE531F01015` | `INE531F01023` | 2025-12-26 | ₹10 → ₹2 | 5 | 2025-12-17 |

[NSE/CML/70238](https://nsearchives.nseindia.com/content/circulars/CML70238.pdf)
names TFCILTD, its new ISIN and subdivision from ₹10 to ₹2. It explicitly makes
the new ISIN effective for trades from 19 September 2025.
[NSE/CML/71857](https://nsearchives.nseindia.com/content/circulars/CML71857.pdf)
provides the equivalent facts for NUVAMA from 26 December 2025. Both one-page PDFs
were downloaded, hash-pinned and visually inspected. The 5-for-1 ratio follows
from 10/2; NUVAMA's issuer confirmation also states this ratio explicitly.

Neither NSE notice prints the old ISIN. The old identities in the table are
independently observed in the local raw source, not attributed to those PDFs.
The [MSE TFCILTD notice](https://www.msei.in/SX-Content/Circulars/2025/September/Circular-17808.pdf)
and [MSE NUVAMA notice](https://www.msei.in/SX-Content/Circulars/2025/December/Circular-18319.pdf)
also enumerate the old/new pairs in official-source search results. Those
results are corroboration only: the direct TFCILTD MSE download timed out and
no MSE PDF is part of this pinned implementation evidence.

## Local raw confirmation

The [raw observation artifact](../../data/research/split-identity-bridges/20260907/raw-observations.json)
retains complete source rows, ZIP and CSV hashes for four existing files:

| Session | Symbol/series | Token | ISIN | Open | Close |
|---|---|---|---|---:|---:|
| 2025-09-18 | TFCILTD/EQ | 3466 | `INE305A01015` | 362.05 | 363.80 |
| 2025-09-19 | TFCILTD/EQ | 3466 | `INE305A01023` | 72.75 | 72.40 |
| 2025-12-24 | NUVAMA/EQ | 18721 | `INE531F01015` | 7282.00 | 7615.00 |
| 2025-12-26 | NUVAMA/EQ | 18721 | `INE531F01023` | 1520.00 | 1493.50 |

Both ex-date files retain the previous old-unit close in `PrvsClsgPric`. It is
therefore unsafe to interpret their apparent one-day price ratio as an economic
loss or a signal return without handling units. This observation is not a new
signal-adjustment rule.

An implementation should require the exact symbol, series, old ISIN, new ISIN,
ex-date and ratio, plus pinned notice and raw-source evidence. Unknown pairs or
conflicting ratios must still fail. Notice issuance dates precede ex-dates, but
this research capture does not establish the original intraday dissemination
clock. The bridge applies to accounting identity only; signal continuity needs
its own explicit policy.

## NUVAMA credit is later than market admission

The issuer's [30 December 2025 credit confirmation](https://www.nuvama.com/wp-content/uploads/2025/12/SE-Credit-Confirmation-of-equity-shares.pdf)
states that the split shares were credited through NSDL and CDSL. Its two
enclosures, both dated 29 December, report debit of `INE531F01015` and credit of
`INE531F01023` executed on **27 December 2025**. The CDSL amounts are 4,192,145
old shares and 20,960,725 new shares. The NSDL table separately includes an
account category with a 1 October 2026 lock-in release date. Both enclosure pages
were visually inspected.

These are aggregate depository processing facts. They do not prove a particular
broker account's sale availability, and public confirmation on 30 December must
not be treated as knowledge on 26 December. Consequently, the NSE ex-date
admission is not evidence that an existing holding's converted inventory was
credited before that opening. Keep market admission, economic entitlement,
depository processing, public knowledge and account availability distinct.
No equivalent TFCILTD credit confirmation was captured in this bounded pass.

## Receipt hashes

The [capture manifest](../../data/research/split-identity-bridges/20260907/manifest.json)
records three successful PDF downloads and one 15-second timeout. Sources came
from NSE and the issuer; there were no Kite calls, new raw-price downloads,
account actions or code changes. Capture timestamps are retrieval clocks.

| Artifact | SHA-256 |
|---|---|
| Manifest | `1fee3cd07fb10d1dda0eed0a96866879e97492189e211bab73cf41a53ccba453` |
| [Structured bridge fields](../../data/research/split-identity-bridges/20260907/bridges.json) | `b1a4815f40e48aebbc43842a65cc2696f4de545ea08483689b1ccfb0b5de14e9` |
| Raw observations | `b45ea3d6af881c44a343d67f2a8616e5c7c446aea3a4da4b3eb612a9f415855e` |
| `CML70238.pdf` | `2945d7111b213119cbd94dcba68786d5ef73f53ecef97f71fce01dfb3a6671b3` |
| `CML71857.pdf` | `0b7f194cea6268abd886e95b4dde2afc2cb5d6faa2690688595cbd62f39a3059` |
| `SE-Credit-Confirmation-of-equity-shares.pdf` | `9cca176413c0898761eb63bbf3e66e115ea94e4692363bbe751f90eb90d67640` |
