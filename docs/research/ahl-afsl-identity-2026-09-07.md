# AHL / AFSL dated identity evidence

The symbol change is established: NSE circular **CML67269**, dated **25 March
2025**, changes **AHL / Abans Holdings Limited** to **AFSL / Abans Financial
Services Limited**, effective **1 April 2025**. The complete one-page circular was
downloaded and visually checked. Its table and effective-date sentence agree.
[Official NSE circular](https://nsearchives.nseindia.com/corporate/kjana_25032025171334_CML67269.pdf).

This resolves the name-change question but does not make the March 28 master a
valid description of that day's trading identities. The dated bhavcopy uses the
old symbol; the archive master already uses the new one. No alias or source-row
correction has been applied.

## Observed source rows

| Requested master / bhavcopy date | Master symbol and series | Traded raw symbol and series | Raw token / ISIN |
|---|---|---|---|
| 6 January 2025 | AHL EQ | AHL EQ | 13288 / INE00ZE01026 |
| 28 March 2025 | AFSL BE | AHL BE | 13293 / INE00ZE01026 |
| 1 April 2025 | AFSL BE | AFSL BE | 13293 / INE00ZE01026 |

Each master also contains the same issuer's BE, BL, EQ, IQ and RL identities,
with distinct tokens. All five rows use AHL in January and AFSL in both the March
and April samples. The March discrepancy therefore affects the master issuer's
symbol across series, rather than a single BE row. These are observations of
the captured datasets, not assertions from the name-change circular.

The three original compressed masters and raw ZIPs are referenced by SHA-256 in
[the full-row extract](../../data/research/ahl-afsl-identity/20260907/observations.json).
The parent [batch result](security-master-batch-results-2026-09-07.md) retains the
original exact-identity failure and broader receipt validation.

## Interpretation and implementation boundary

The March 28 raw symbol is consistent with the circular's April 1 effective
date. The master carries the announced future symbol. A next-session preparation
file is one plausible explanation; retrospective replacement or another archive
publication convention is also possible. The circular does **not** document
master-generation timing, first availability or the period each field represents.
Do not conclude that every dated master describes the next trading session from
this single example.

A future explicit identity-event adapter can record announcement date March 25,
effective date April 1, old symbol AHL and new symbol AFSL, with the circular hash.
The PDF does not state an intraday publication time, token, ISIN, series migration,
split ratio or economic action. Preserve those distinctions. Conservative
day-level knowledge would start on the next available session after the notice
date, unless a historical dissemination timestamp is independently verified.

For now:

- Keep the March 28 raw row as AHL BE and its missing exact master match visible.
- Do not rewrite March 28 history to AFSL or globally join on token / ISIN alone.
- Treat April 1 AFSL as the effective new symbol; preserve raw source identities
  in any later explicit continuity relation.
- Do not count this evidence as ordinary-share, main-board, first-availability or
  complete-universe proof. BE-to-EQ eligibility is a separate dated question.

## Captured evidence

- [Capture manifest](../../data/research/ahl-afsl-identity/20260907/manifest.json)
  records HTTP 200, original/final official URL, local acquisition timestamp and
  source byte count. Acquisition time is not historical publication time.
- [Saved circular](../../data/research/ahl-afsl-identity/20260907/CML67269.pdf):
  161,890 bytes; SHA-256
  `31f405ed7543c569fd8ae75635539eaf451724827ae5637bcae04bdde0b13299`.
- One direct public NSE PDF download; existing masters and bhavcopies reused.
  No Kite requests, credits, account changes or trading actions.
