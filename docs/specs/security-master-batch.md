# Dated NSE master acquisition and candidate audit

Extend the captured January 2025 sample with a bounded, frozen five-date probe:
5 February 2024 (announced public dissemination start), 6 January 2025 (reuse),
28 March and 1 April 2025 (permission-code boundary), and 3 September 2026
(latest saved raw session). Select dates before responses; no return-based choice.

Capture only the NSE-listed MII report through the verified official selector API.
Make at most one request per uncached date, sequentially with a one-second gap,
15-second HTTP timeouts, no automatic retries or redirects, and a 4 MiB body cap.
Persist unsuccessful responses/errors as well as successful responses. Reuse
hash-verified immutable receipts on restart, including failures; never silently
overwrite or repair a corrupt cache. Reuse the January sample without a request.
Acquisition must finish before any offline interpretation. No Kite access.

The offline audit pins its contract, implementation, prior sample plan and source
evidence. Verify each requested date, exact report descriptor, official host,
response attachment date, gzip/CSV shape and bounds against the captured 120-field
header. Reconcile every saved same-day raw record by symbol/series/ISIN/token after
checking its ZIP, CSV and normalized receipt against the frozen raw parent.
Retain all mismatches and every normalized master row. Missing/invalid responses
are explicit coverage gaps; never treat a partial batch as complete.

Decode broad instrument type, market identifier, normal status, eligibility and
permission separately, preserving raw values. Permission 2 is unresolved before
1 April 2025. Unknown codes remain unresolved. Schema interpretation is not proof
of a historically available schema or release clock. Do not interpret numeric
timestamp fields, forward-fill snapshots, merge changing identities by symbol,
or infer ETF/ordinary-share subtype from a name or ISIN prefix.

Implement a transparent candidate screen, not an admissible stock universe:
require broad equity type 0, EQ series, normal-market identifier 1, normal-market
eligibility 1, permission 0, deletion flag N, board lot 1 and a known status other
than suspended. Known non-equity types and documented SME marker/series are
excluded from this proposed universe. Other nonmatching or unknown fields remain
unresolved. Even matching candidates need ordinary-share, board, historical
schema and first-availability evidence. Preserve these blockers in every row.
Reconcile candidate counts separately for matched observations and all master
records. Master-only records are not evidence of actual trading.

Publish content-addressed reports and per-date normalized row artifacts. Report
exact coverage and candidate counts, with `admissible: false`, `can_trade: false`
and zero admitted members throughout. No portfolio rerun or performance claim.
