# Stock-universe closure: documented boundary and research policy

Research date: 7 September 2026. This pass found an explicit MII definition of
non-SME normal-market securities, effective 16 June 2025. It did **not** find an
exhaustive dated rule establishing that every broad-equity EQ record is an
ordinary company share. A useful backtest can proceed under a precisely named
metadata proxy; it must retain that distinction in its results and admission
decision.

## New authoritative boundary

[NSE/CMTR/68176, issued 26 May 2025](https://nsearchives.nseindia.com/content/circulars/CMTR68176.pdf)
changes the description of `SSEC`, explicitly including MII
`NSE_CM_security_ddmmyyyy.csv.gz`, field 11, `CallAuctnInd`. Its merged table was
visually checked on page 1 of the captured PDF. The live effective date is
**16 June 2025**, with a separate 14 June mock. The revised meanings are:

| Code | Meaning |
|---|---|
| 1 | Non-SME securities eligible for normal and odd-lot markets |
| 2 | IPO-session securities, potentially including SME |
| 3 | Relisting-session securities, potentially including SME |
| 4 | Illiquid call-auction securities, potentially including SME |
| 5 | SME securities eligible for the normal market |

The circular leaves the structure and other fields unchanged. This is direct
support for a dated **non-SME** interpretation of code 1 from its effective
boundary. It neither establishes ordinary-share subtype nor supplies an ETF
dictionary. The earlier description only says normal-market security; the new
wording must not be silently backdated. [Official circular](https://nsearchives.nseindia.com/content/circulars/CMTR68176.pdf).

For implementation, retain the raw code, dictionary version, documentary effective
date and source hash. Select the applicable version using the modeled trading
session to which the snapshot is assigned, while separately preserving the
archive date. If an effective-date boundary coincides with an unverified snapshot
timing boundary, mark applicability unresolved rather than inferring deployment
from an unchanged header. This is a proposed modeling rule, not an additional
statement from the exchange.

## What still does not follow

The captured MII workbook describes broad types as equities, preference shares,
debentures, warrants and miscellaneous. It does not enumerate every ETF or other
fund-unit subtype under those values. The EQ series legend includes both fully
paid shares and ETFs. Thus broad type 0 plus EQ is a stronger candidate screen
than EQ alone, but the sources reviewed do not provide an exhaustive ordinary
share guarantee. Code 4 is not an ETF-only classification. These earlier findings
and their exact workbook/HTML hashes remain in the
[candidate-rules note](nse-master-universe-rules-2026-09-07.md), which cites the
[2024 consolidated package](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip)
and [NSE series legend](https://www.nseindia.com/static/market-data/legend-of-series).

Similar field names in different NSE products are insufficient evidence of
identical semantics. For example, the separately published market-feed dictionary
describes permission code 0 differently from the captured MII workbook. Do not
replace MII permission rules using this other product's table. [NSE real-time
CM feed v1.31, page 15](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Real%20time-CM-L1L2L3-V1.31_0.pdf).

## A usable, limited experiment contract

Use the name **“NSE dated broad-equity EQ metadata proxy”** for a research run.
“Ordinary main-board universe”, “historical Nifty 500 constituents”, and “complete
point-in-time stock universe” would assert facts this evidence does not establish.
This naming and the following rules are proposed research policy:

1. Require the immediately preceding frozen exchange-session master, a valid
   dated schema, a verified payload and the NSE-only report descriptor. No older
   master, same-day replacement, alias inference or current security list may
   fill a missing predecessor. Missing or corrupt evidence blocks new entries.
2. Apply the existing explicit proxy criteria: broad type 0, EQ series, market
   identifier 1, permission 0, normal-market eligibility, documented
   nonsuspended status, raw deletion flag N, and board lot 1. Preserve each raw
   field and every exclusion or unresolved reason. The lot/deletion predicates
   remain conservative policy choices, not extra subtype evidence.
3. Select candidates using information assigned to the preceding snapshot and
   price/liquidity history strictly before entry. Current-session full-day volume,
   turnover, closing price or an end-of-day exact match must not become a
   pre-open selection filter. Reconcile the resulting instrument and price
   identity for fill validation separately and disclose that availability model.
4. A missing metadata snapshot prevents new purchases; it does not erase held
   inventory, manufacture a sale, or suspend economically necessary valuation
   and corporate-action accounting. Missing prices and unsupported mandatory
   actions retain their own blocking rules.
5. Separate the return series from validity labels: cash retained because evidence
   is missing is an outcome of the conservative data policy, not proof of a good
   timing strategy. Report blocked-session and candidate coverage next to returns,
   costs, cash exposure and Nifty 500 TRI for the identical evaluation dates.

The proxy enables an end-to-end diagnostic without waiting for universal subtype
proof. It cannot satisfy a gate that specifically requires certified ordinary
shares or proven historical publication timestamps. Such a gate needs dated
security-level listing/admission evidence or an exhaustive documented mapping;
this pass did not obtain either for the whole candidate population.

## Publication and archive timing

[NSE/MSD/60315, 19 January 2024](https://nsearchives.nseindia.com/content/circulars/MSD60315.pdf)
announces daily public website dissemination of the MII files from **5 February
2024**, in addition to the existing extranet distribution. It does not specify
the website release hour, certify immutable archive revisions, or promise every
historical date remains downloadable. A failed retrieval for that date therefore
does not contradict the circular and must not become an empty valid master.

The [NSE simulated-environment FAQ, question 16](https://www.nseindia.com/static/trade/simulated-environment-faqs)
explains that simulated master filenames identify the replicated end-of-day file
date. This corroborates an EOD convention in that context. It does **not** state
that the public MII archive for date D was available before every subsequent
live opening. Its scope is periodic simulation replication, so it cannot certify
the live archive's delivery contract.

The repository's [27-pair identity diagnostic](security-master-daily-results-2026-09-07.md)
supports the preceding-session policy empirically. Exact identity matches do not
prove publication time or eliminate revisions. Keep
`historical_publication_time_verified=false` under this research policy.

## Local receipts and limits

Three direct public-source requests succeeded; no master sample acquisition,
Kite request, credential access or account action was performed. The new receipts
record retrieval time, URL, HTTP status, content type, size and SHA-256. Retrieval
clocks are not historical publication times.

| Artifact | SHA-256 |
|---|---|
| [Capture manifest](../../data/research/stock-universe-closure/20260907/manifest.json) | `50124f4c6656349ab6ed5b92bed96006f71f5744d7702448317643f91667e8e7` |
| `CMTR68176.pdf` | `043f5999fd5990c6d8017d647381a442aab486752854af82c62392b51b61da57` |
| `MSD60315.pdf` | `02d851cec85512d10440d47bf5c253545510711504cf53b35f67f3b134b02a35` |
| `simulated-environment-faqs.html` | `c0f3fefb86d8c32020931fa49e5b0e5013f9d29c66beb1f47cb21bb4bb6b9a0a` |

The search was bounded to primary exchange sources. Absence of an exhaustive
bridge in these reviewed sources is a research limit, not a claim that NSE has
never published one. Existing pinned notes and source plans were left unchanged.
