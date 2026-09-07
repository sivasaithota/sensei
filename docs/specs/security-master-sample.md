# One captured historical MII master

Validate the January 6, 2025 NSE-listed security master returned by the exact
official report-selector API. Keep this research-only and offline after capture;
do not bulk-download, infer stock eligibility or certify publication time.

Pin the response receipt and gzip bytes, requested date, server attachment filename,
NSE-only report descriptor, decompressed hash and exact observed header. Reject
wrong exchange/date descriptors, changed bytes, malformed gzip/CSV, header changes,
row-shape errors, duplicate tuple identities and duplicate/empty instrument tokens.
Bound compressed size to 4 MiB, decompression to 32 MiB and rows to 100,000.

Compare every same-session saved bhavcopy row on symbol, series, ISIN and instrument
token. Preserve matched, missing and token-conflicting counts and rows; no symbol-only
fallback or silent exclusion. Verify the raw ZIP/CSV and normalized receipt against
the frozen parent. Keep master-only records distinct: absence from a bhavcopy is
not proof of suspension or delisting. Report raw code distributions and examples,
without converting them into eligible-stock counts.

Requested date plus filename is source date evidence, not an embedded business-date
field or proof of historical first availability. Raw timestamp-field interpretation,
taxonomy version, status/board semantics and causal eligibility remain separate.
All outputs retain `admissible: false` and `can_trade: false`. Capture/schema evidence
may support later normalization after its precise meanings are documented.
