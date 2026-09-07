# Partial Nifty 500 notice register

Captured and verified 12 official NSE Indices notices on 7 September 2026.
The register contains **342 source rows**, preserving original announcements,
corrections and future effective dates. It is **not a historical constituent set**.
No strategy, return result or trading eligibility changes in this pass.

## Evidence and interpretation

The [versioned register](../../config/nifty500-notice-register-v1.json) pins each
PDF's official URL, SHA-256, page count, announcement date, effective date and
preceding close. Every transcribed Nifty 500 table was visually checked against
the PDF. Exact downloaded bytes and the capture manifest remain in the local
research archive at `data/research/nifty500-membership-notices/20260907/`.
Large research captures are not committed; the register retains their hashes and
source URLs. The audit requires those pinned local captures to reproduce.

| Notice date | Effective date | Rows | Meaning |
|---|---|---:|---|
| 2024-02-28 | 2024-03-28 | 68 | Scheduled review, before subsequent correction |
| 2024-03-19 | 2024-03-28 | 2 | Revokes IREDA inclusion and VGUARD exclusion |
| 2024-08-23 | 2024-09-30 | 54 | Scheduled review |
| 2024-09-13 | 2024-09-17 | 1 | RAYMONDLSL exclusion |
| 2025-02-06 | 2025-02-10 | 1 | ITCHOTELS exclusion |
| 2025-02-21 | 2025-03-28 | 60 | Scheduled review |
| 2025-05-19 | 2025-05-22 | 1 | DUMMYABFRL index placeholder inclusion |
| 2025-08-22 | 2025-09-30 | 36 | Scheduled review |
| 2025-09-15 | 2025-09-23 | 2 | PEL exclusion and RELINFRA inclusion |
| 2026-02-23 | 2026-03-30 | 62 | Scheduled review |
| 2026-08-10 | 2026-09-30 | 54 | Future review, outside evaluation window |
| 2026-09-03 | 2026-09-07 | 1 | Future DUMMYHEG index placeholder inclusion |

For the 1 January 2024–3 September 2026 window, using announcement knowledge
through the end of 3 September 2026, classification is:

- 283 retained notice rows effective within the window;
- 55 future effective rows;
- 2 original rows explicitly revoked;
- 2 revocation records retained as evidence.

The 283 retained rows are not certified final historical transitions: an
uncollected correction or intervening notice may alter their interpretation.
References to earlier dummy additions in later notices remain contextual notes;
they were not promoted to contemporaneously available announcements. Temporary
dummy entries carry no inferred tradable instrument identity.

## Audit result

Run `.venv/bin/python -m sensei.research.membership_notices` from the repository.
The final report is
`data/reports/membership-notices/ebc9fc21be2a6b1d4a0e598bb45789e148041a3a412063d7f62f0932bb05de78/report.json`.

- Report SHA-256: `ebc9fc21be2a6b1d4a0e598bb45789e148041a3a412063d7f62f0932bb05de78`.
- Register SHA-256: `0741266eeeefa6610c49495ccc8fa66dc44cacb841dd9c5252e62785fea08a31`.
- Capture manifest SHA-256: `2c25818f00e0aa8c47bb5eb0ba9fe5afc38539148375299d1934c44eef6ab99e`.
- Decision: `DATA_BLOCKED`; authority: `RESEARCH_ONLY`; `can_trade=false`.
- Membership intervals remain empty; entry eligibility remains undefined.

The audit verifies the register, capture manifest and PDF byte hashes, including
both requested and final official-source URLs. Classification respects parsed
publication/effective dates; a later correction cannot change an earlier
knowledge cutoff. The report records its implementation hash as well.

Seventeen focused tests cover revocation timing, compact ISO date input, future
changes, placeholders, inadmissibility, invalid targets/pages/duplicate sources,
capture tampering, redirected sources and reproducibility. Independent review
identified the date-format and redirected-source gaps; both were corrected before
the final artifact was generated.

Full suite: **1,037 passed**. Standards review: no remaining findings after the
two fixes. Spec review: no findings.

## Remaining work

The [bounded anchor search](nifty500-anchor-search-2026-09-07.md) obtained no
independently dated complete starting set or reconciliation checkpoint. A complete
change sequence, stable instrument mapping and dummy lineage are also unresolved.
Today's constituent list cannot be backdated to repair those gaps.

The prior [raw portfolio comparison](raw-portfolio-results-2026-09-07.md) remains
baseline ₹286,796.32 and hold60 ₹323,748.95 from ₹300,000, versus +22.9535% for
Nifty 500 TRI. Both remain without a clear net edge. No new return experiment,
Kite request, credit spending or live order occurred in this pass.

Do not repeat this finite capture or tune the rejected strategy family. The next
independent task is a bounded contract for date-aware corporate-action transforms
and their acceptance tests; membership reconstruction still requires the missing
dated evidence.
