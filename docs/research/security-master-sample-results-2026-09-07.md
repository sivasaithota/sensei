# First historical NSE security master captured and reconciled

Captured the **NSE-listed security master for January 6, 2025** and the official
schema packages. This resolves the sample-download failure from the earlier pass.
It does not yet establish a complete historical universe or stock eligibility.

## Actual source and validation

The official [All Reports selector](https://www.nseindia.com/all-reports) was used
to select Archives, January 6, 2025, and **CM - MII - Security File (.gz) (NSE Listed
securities)**. Its observed `/api/reports` request is recorded exactly in the
[capture receipt](../../data/research/nse-master-sample/20260907/capture.json).
The browser download failed, but a direct HTTP request to that exact endpoint,
using ordinary browser-style headers and no account credentials, succeeded.

The response was HTTP 200, `application/x-gzip`, with attachment filename
`NSE_CM_security_06012025.csv.gz`. It contains **960,641 compressed bytes** and
**8,608,619 decompressed CSV bytes**, **120 columns** and **28,469 records**.
Raw bytes and the decoded CSV are retained under
`data/research/nse-master-sample/20260907/`.

- Compressed SHA-256: `ac2945ad785cb705a880e253e311a460fc57983b9d64444396d6d88f1795e2bc`.
- CSV SHA-256: `afaa6334f67add12d85c677f2eaef227c34620f88e76721c559f90bf7866ebb3`.
- Source date evidence: requested date and server attachment filename. The checker
  does not claim an embedded business-date field, original pre-opening availability,
  or unchanged historical vintage. Timestamp-like fields remain uninterpreted.

The offline auditor bounds compressed size, decompression and row count; validates
the pinned header; rejects malformed CSV and duplicate identities/tokens; and
checks the raw bhavcopy against the previously frozen ZIP/CSV/Parquet receipt.
There is no network call in the auditor.

## Same-session reconciliation

**All 2,976 bhavcopy observations match** the master on symbol, series, ISIN and
exchange instrument ID. Missing identities: **0**. Token conflicts: **0**. Matched,
missing and conflicting rows and explicit counts are retained in the report.

The master also has **25,493 records not observed in that day's bhavcopy**. These
are not silently discarded or called delisted: the master contains multiple series
and records with different statuses, while a bhavcopy records trading observations.
The 28,469 total is not a count of tradable ordinary companies.

| Master field `SctyTpFlg` | Documented broad class | Matched bhavcopy observations |
|---|---|---:|
| 0 | Equities | 2,487 |
| 1 | Preference shares | 1 |
| 2 | Debentures | 203 |
| 4 | Miscellaneous | 285 |

These are broad instrument classes, not final eligible-stock counts. BANKBEES has
flag 4; SBIN, HEG and MAZDOCK have flag 0 in their EQ records. Miscellaneous does not
mean ETF exclusively, and equities does not alone establish fully paid ordinary
main-board shares. The auditor retains raw flags; this table's meanings come from
the independently captured [official schema evidence](nse-mii-classification-schema-2026-09-07.md).

## Schema evidence now available

The correct circular downloads were ZIP packages rather than the unsuccessful
standalone PDF paths: [MSD55276.zip](https://nsearchives.nseindia.com/content/circulars/MSD55276.zip)
and [CMTR61813.zip](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip).
Their original PDFs and XLSX annexures are retained and pinned. Both documented
120-field ISO-tag arrays match this sample's header after trimming three incidental
spaces in the workbooks; the original source cells and sample header are preserved.

The schema explains that `FinInstrmTp`, `FinInstrmClssfctn` and `ClssfctnTp` are
filler fields. Their blanks are not a reason to infer missing classifications.
The actual broad type is `SctyTpFlg`. The 2024 dictionary also defines normal-market
status, eligibility, permission, and `CallAuctnInd=5` for SME securities. Those are
separate facts, not a single entry permission.

The source note records the February 5, 2024 public-distribution announcement and
April 2025 permission extension. These impose dated coverage/version questions;
they do not prove that all earlier files are absent or later files are complete.

## Reproduce and continue

Run `.venv/bin/python -m sensei.research.security_master_sample`.

- [Plan](../../config/security-master-sample-v1.json), SHA-256 `c2ecf9587a7b6004a0f7b454ded8941ea2ec88932124d3990f904e81a6e4c3c5`.
- [Final report](../../data/reports/security-master-sample/6a46e3c6c7e3fec78bd3f6c77302ac56e1a0d432a7c67621e7239953ef804a95/report.json), SHA-256 `6a46e3c6c7e3fec78bd3f6c77302ac56e1a0d432a7c67621e7239953ef804a95`.
- Auditor SHA-256 `36b66bfaf20eb00f1713ba4888bd6d910b1c98ca3e6e7fe75e76e64253683306`.
- Eleven focused tests pass. Review corrected the omission of matched rows and
  missing raw tokens from the output; explicit count conservation is now tested.
  Final Standards and Spec reviews are clear. Initial report retained.
- Full suite: **1,152 passed**, 32.73 seconds.

Next: capture a bounded cross-date batch through the verified report API, reconcile
each date, and identify schema or permission changes before expanding the archive.
Then normalize the documented fields with a declared availability convention and
explicit unresolved ordinary-share/board cases. Feed the dated coverage checker;
derive no eligibility from current membership, filenames alone or broad flags.
The eventual coherent portfolio rerun still needs complete action/identity coverage
and comparison against Nifty 500 gross TRI. No strategy was tuned here.

No Kite requests or credits, purchases, orders, external messages, live activation
or automation-state changes. This pass downloaded one master and two schema packages,
not the complete security-master archive.
