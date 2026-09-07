# Consecutive dated masters and explicit identity timing

Audit every frozen raw session in January 2025 and 24 March–4 April 2025,
plus the cached 3 September 2026 schema probe. These windows are chosen for an
initial complete month and the documented AHL/AFSL transition, not performance.
Derive and verify the complete session lists against the pinned raw parent; never
omit a failed date. Limit the entire plan to 40 sessions. Use the existing bounded
capture helper in partitions of at most six, one uncached request per date, spacing
partitions as well as requests. Reuse cached files, including failures. Preserve
old plans, implementations and reports. Make no Kite requests.

Accept the original exact 120-field schema before 3 August 2026. From that date,
use CMTR73845's replacements at field 24 (ElgbltyClsgAuctnSsn) and field 59
(XchgExclsv), with every other header unchanged. Decode closing-auction eligibility
as 0/1 only. Fields 23 and 59 are fillers in the new schema: preserve raw content,
never infer exchange exclusivity or retail-debt status. Report raw filler-value
distributions without interpretation. Unknown CAS values must remain unresolved. Effective
schema dates do not establish archived-file publication time.

Keep exact same-date symbol/series/ISIN/token reconciliation. Add diagnostic identity
events only when a hash-pinned, explicitly dated NSE notice maps old/new symbols.
The AHL→AFSL event is announced 25 March and effective 1 April 2025. Diagnostics
must respect announcement/effective dates, matching ISIN, series and token, and
distinguish a master ahead of the effective symbol from one stale after it. Do not
rewrite source symbols, grant eligibility, join return histories, or count a
notice-explained discrepancy as an exact match. Other mismatches stay unexplained.
Preserve counterpart identities in affected normalized rows and label them
unresolved, even when their other fields would pass the candidate screen.

Retain all raw, decoded and blocker fields in deterministic gzip JSONL artifacts;
do not multiply uncompressed master artifacts across the whole month. Verify raw
ZIP/CSV/normalized receipts and all source pins. Store source failures as explicit
per-date gaps. Corrupt cached evidence is a hard error. A malformed source response
must not prevent auditing other dates.

Report per-window requested/validated sessions, longest consecutive validated run
on the frozen exchange-session calendar, exact reconciliation completeness, every
identity discrepancy, and candidate counts. A validated run is source/schema
coverage, not evidence of causal availability or a complete stock universe. Distinct
outputs must report zero admitted members, admissible=false and can_trade=false.
Do not rerun strategies until remaining daily classification, knowledge and coherent
accounting requirements are met.
