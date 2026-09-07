# Dated schema, daily coverage and master timing

The revised NSE schema is implemented, the AHL/AFSL effective symbol is documented,
and consecutive daily acquisition is now tested. The key finding is that an
archive's filename date must not automatically be treated as its trading-session
identity date. The preceding-session master resolves the observed identity
differences in the paired diagnostic below. This supports a research policy;
it does not certify historical publication time or an admissible stock universe.

## What changed

`security_master_daily` accepts the original 120-field header before 3 August 2026
and the two documented replacements from that date. CAS eligibility is decoded
only as 0/1. Fields 23 and 59 remain uninterpreted fillers, even when populated.
The [official schema evidence](nse-master-schema-vintage-2026-09-07.md) now resolves
the September mismatch that the previous audit correctly rejected.

The [NSE identity notice](ahl-afsl-identity-2026-09-07.md) makes AHL → AFSL effective
1 April 2025, announced 25 March. The March 28 master already has AFSL while the raw
price file correctly has AHL. The new diagnostic records both identities, source
hash and effective date. It does not rewrite symbols or claim an exact match.
Other token-matched but symbol/ISIN-different records remain unresolved and carry
their counterparts into the compressed row artifact.

The runner verifies complete windows against the frozen raw session calendar,
captures through bounded partitions and preserves failures. Every normalized row
retains source values, decoded values, reasons, reconciliation and admission
blockers in deterministic gzip JSONL. All prior source modules and frozen plans
remain unchanged. The output does not enter portfolio selection or live execution.

## Consecutive coverage

| Requested window | Validated masters | Missing source dates | Longest consecutive validated run |
|---|---:|---|---|
| January 2025 | 21 / 23 | January 13, 22 | January 1–10: 8 exchange sessions |
| March 24–April 4, 2025 | 6 / 9 | April 2, 3, 4 | March 24–April 1: 6 exchange sessions |

All five gaps are retained HTTP 404 responses, each 54 bytes. They are not empty
valid masters. Neither window is complete. The prior February 2024 retrieval gap
was not retried and remains unresolved; this work does not establish the global
earliest available archive date.

The initial 33-session run also includes the cached September 3 schema probe:
28 masters validate, retaining 814,785 metadata rows. They reconcile 83,222 of
83,235 same-day price observations exactly. All 13 differences share a token but
differ in symbol or ISIN. One is explained by the AHL notice; none is silently
repaired. On paired dates, using the preceding-session master removes those
observed differences as described below.

## Prior-session timing diagnostic

The diagnostic uses only the immediately preceding session from the frozen raw
calendar. It never carries a master across a missing prior session. Its source
report, source receipts, CSV hashes, raw observations, implementation and output
are pinned. It performs exact tuple comparisons only; no aliases, future metadata
fallback or ordinary-share classification are introduced.

The initial diagnostic finds exact matches for **all 76,685 observations across
26 available prior-session pairs**. On the fair comparison subset of 23 dates
with both same-day and preceding-session masters, the same-day comparison matches
67,795 of 67,807 observations; the preceding-session comparison matches all
67,807. Thus all 12 discrepancies in that paired subset disappear.

This is evidence of snapshot timing, not proof that all fields in every archive
were published before the next opening or that there are no historical revisions.
The September TCC case has no September 2 master in the original 33-date plan, so
it cannot be included in that paired conclusion. A separate v2 plan adds only
September 2 to test it; original windows and captures are preserved.

The v2 check confirms September 3's **3,635 / 3,635** observations against the
September 2 master. The final preceding-session diagnostic therefore matches
**80,320 / 80,320 observations across 27 date pairs**. On the 24 dates where both
comparisons exist, same-day masters match 71,429 / 71,442 and preceding-session
masters match 71,442 / 71,442: all 13 discrepancies in that paired subset disappear.

The added September 2 file itself has a MANBRO/KDGREEN same-day difference. Its
preceding September 1 master is outside this frozen sample, so that case is not
claimed resolved. The final 34-date acquisition validates 29 masters containing
852,039 rows; same-day matching is 86,854 / 86,868. Compressed normalized artifacts
total 52,314,262 bytes. The five source gaps remain unchanged. This bounded diagnostic
does not turn a missing predecessor into permission to use an older snapshot.

## Validation and reproduction

The focused daily/batch/parser suite passes **52 tests**. Full suite: **1,193
passed in 31.55 seconds**. Standards and Spec reviews found no actionable issues.
Tests cover schema activation, uninterpreted fillers, unknown CAS values,
announcement/effective-date diagnostics, missing-session preservation, partition
spacing, corruption versus source gaps, and deterministic compressed records.

Run `.venv/bin/python -m sensei.research.security_master_daily audit --plan
config/security-master-daily-v1.json` to reproduce the original daily report.
The default CLI remains this frozen v1 plan. `capture` reuses verified cached
successes and failures; a repeat was verified to make zero network requests.
Use `--plan config/security-master-daily-v2.json` for the final expanded audit.

Initial evidence:

- [Frozen v1 plan](../../config/security-master-daily-v1.json), SHA
  `69190b70980572c85e379e0cbd40cad7eb5c5f0b6ea1ca7487bae72c7ee23e12`.
- [Initial daily report](../../data/reports/security-master-daily/41a8b9f449ffd9674145a509b7ede528e52d5616d3f54e3f7f6ab49040f30add/report.json),
  content SHA `41a8b9f449ffd9674145a509b7ede528e52d5616d3f54e3f7f6ab49040f30add`.
- [Initial timing report](../../data/research/master-snapshot-timing/20260907/0d0e177cc0223033899c8e3ba2165bb87ae182162adadc95830ac4ae26fa8285/report.json),
  content SHA `0d0e177cc0223033899c8e3ba2165bb87ae182162adadc95830ac4ae26fa8285`.
- The retained timing script is
  `data/research/master-snapshot-timing/20260907/probe.py`.
- Daily implementation SHA
  `b6d3313a2c388ef8d2fc151a981a0becb52701cfa2faddb9dab40b7086d02657`.

Final expanded evidence:

- [V2 plan](../../config/security-master-daily-v2.json), SHA
  `3077d19377faf87cc10a4888f1731f27037899e8e6f2df85a2c4df33fecd11d5`.
- [V2 daily report](../../data/reports/security-master-daily/088d901dbf04499d3d2f53e6557201b9b472037664c890c1fec5876d63cf962e/report.json),
  content SHA `088d901dbf04499d3d2f53e6557201b9b472037664c890c1fec5876d63cf962e`.
- [V2 timing diagnostic](../../data/research/master-snapshot-timing/20260907/ab1a22af49fcfe04223459cae18b03db0e63df8659fd4d224ffeacf6e9ca84a8/report.json),
  content SHA `ab1a22af49fcfe04223459cae18b03db0e63df8659fd4d224ffeacf6e9ca84a8`.
- Its preserved script is
  `data/research/master-snapshot-timing/20260907/probe-v2.py`.

This pass made 29 master requests for the original plan and one for the additional
September date. Schema research fetched two official ZIPs; identity research fetched
one official PDF. **Zero Kite requests or credits**, purchases, orders, portfolio
reruns, activation, external messages or automation changes occurred.

## Next implementation

Implement an explicitly labelled prior-session metadata policy, with no new entry
when the required snapshot is missing. Resolve ordinary-share/board eligibility
and identity continuity for lagged indicators under that policy, then expand the
frozen daily block. Preserve the distinction between a documented effective event,
an assumed historical availability policy and verified account/execution state.
Only after those accounting and universe inputs agree should the portfolio be
evaluated against Nifty 500 TRI. No new performance claim follows from this audit.
