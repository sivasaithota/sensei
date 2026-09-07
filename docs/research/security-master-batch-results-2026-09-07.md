# Cross-date security-master results

The dated acquisition and candidate audit are implemented. Three masters pass the
pinned 120-field schema and produce 87,835 retained normalized rows. The five-date
probe is incomplete: February's response is 404, March has one unresolved identity,
and September changes two header fields. This is data-validation progress, not a
new strategy result or an admissible historical universe.

| Master session | Schema/response | Raw observations | Exact matches | Provisional candidates among exact matches |
|---|---|---:|---:|---:|
| 2024-02-05 | HTTP 404; retained response | Not audited | — | — |
| 2025-01-06 | Validated; cached control | 2,976 | 2,976 | 1,760 |
| 2025-03-28 | Validated | 3,001 | 3,000 | 1,858 |
| 2025-04-01 | Validated | 3,014 | 3,014 | 1,863 |
| 2026-09-03 | HTTP 200; header mismatch | Not audited | — | — |

Counts describe dated rows, not distinct companies across time. No rows are admitted
to a portfolio. The candidate filter requires broad equity, EQ, normal-market
identifier, eligibility, listed permission, raw deletion flag N, lot 1 and a known
nonsuspended state. Each row still carries ordinary-share, board, historical-schema
and first-availability blockers. This is not the historical Nifty 500 universe.

## Findings that prevent extending the backtest yet

The March raw observation is `AHL / BE / INE00ZE01026 / 13293`. The captured master
instead contains `AFSL / BE / INE00ZE01026 / 13293`. Shared token and ISIN do not
authorize a symbol fallback. The report retains the missing raw identity and the
master-only identity. A dated symbol-change notice and timing reconciliation are
needed before connecting their histories; no name-change timing is inferred here.

September retains 120 columns but changes field 24 from `ElgbltyRETDBTMkt` to
`ElgbltyClsgAuctnSsn` and field 59 from `Rsvd01` to `XchgExclsv`. The old parser
rejects this schema. A bounded official-source investigation did not establish
their definitions/effective dates; see the [schema-change note](nse-master-schema-change-2026-09-07.md).
The permission-field circular does not explain either change.

The February response has the expected filename but HTTP 404 and only 54 bytes.
It is not an empty valid master. This single failed retrieval does not prove the
whole early archive is absent. The public-dissemination announcement is not a
retention guarantee.

The successful 2025 masters contain no unknown codes in the five decoded dimensions
and no permission value 2. The implementation nevertheless treats that value as
unknown before 1 April 2025 and a BSE-exclusive scope anomaly thereafter. The
[rule evidence](nse-master-universe-rules-2026-09-07.md) pins the official extension
and explains why EQ alone cannot exclude ETFs.

## Reproduction and integrity

Run `.venv/bin/python -m sensei.research.security_master_batch audit` for the offline
final audit. `capture` reuses the same verified cache, including failures. A second
capture run was checked and made **zero network requests**. New acquisition made
four NSE master requests, with January reused. Two public-source research documents
were downloaded separately. This pass made **zero Kite requests and spent zero
Kite credits**.

- [Frozen acquisition plan](../../config/security-master-batch-v1.json), SHA
  `05b1312bb9db9e880bde529165f7012789f0fadfe28a3e8bc70bcb23248c46db`.
- [Final audit plan](../../config/security-master-batch-v2.json), SHA
  `877a89e380d43cf070de01a94d1d065e3402366a86b284cdddad3988d17461ae`.
- [Final report](../../data/reports/security-master-batch/9a6431f9230b4733cf600dbf339102a22ec0166afbdfeaca2963bec46db58d13/report.json),
  content SHA `9a6431f9230b4733cf600dbf339102a22ec0166afbdfeaca2963bec46db58d13`.
- Implementation SHA `a1b9263eec6b096e3b0d891a161806230c52aa520bf9cc068b2368070f2aea4e`.

The final plan pins all five receipts and response bodies, including failed or
schema-rejected captures. Reports point to hash-addressed JSONL artifacts retaining
every raw field, decoded field, reason, blocker and raw-reconciliation state.
Normalized raw receipts, source ZIPs and CSV hashes are checked against the earlier
frozen raw-portfolio parent. Capture corruption is a hard error; source absence or
invalid source formatting is a reported gap. Token conflicts remain unresolved in
the individual row artifact as well as the aggregate report.

The original report `38dbc09e0615021e2cc2fbe0eb17cd6bab7e7f68202077dd69b2bbdb16a22a73`
and its original implementation bytes under
`data/research/nse-master-batch/v1/captured-implementation.py` remain saved. The final
plan records review fixes without rewriting the acquisition plan or fetching again.
The CLI defaults to v2; v1 intentionally will not accept the changed implementation.

## Validation and next implementation

The focused parser/batch suite passes 33 tests, including malformed DEFLATE
isolation, gzip bounds, cache success/failure reuse, token-conflict rows, unknown
codes, dated permission interpretation, mismatched attachments and partial batches.
Independent Standards and Spec review findings were fixed and both reviews cleared.
The final full suite passes **1,174 tests in 30.28 seconds**.

Next, resolve the observed schema changes and AHL/AFSL effective identity with dated
exchange evidence, then acquire a frozen contiguous daily block around the intended
warmup/start period. Specify a prior-session metadata policy and its first-availability
assumption before using liquidity or classification to select stocks. Do not rerun
the portfolio on these five isolated candidates or silently use today's membership.
Daily coverage, ordinary-share/board evidence, identity continuity and coherent raw
signal/accounting coverage remain prerequisites for the Nifty 500 TRI comparison.
