# Kite historical capture

Owner request, 6 September 2026: the API key and 500 credits are ready; acquire
stock-market history efficiently. Existing mandate is NSE cash equity, swing
first, with all captured history remaining research data.

1. Capture credentials locally with hidden entry and macOS Keychain storage.
   Complete browser login through the configured loopback redirect. Keep
   credentials out of chat, command arguments, logs, source and data manifests.
   This integration may call only the authentication exchange and read-only
   instrument/history endpoints; it must not place orders.
2. Freeze the current NSE cash-segment EQ master and request plan. Match the
   current official NSE equity and SME lists to avoid capturing unrelated debt
   instruments; retain reference hashes, mappings, unmatched names and excluded
   master records. This is acquisition scope, not historical eligibility. Capture
   1996-01-01 through 2026-09-04 using at most 2,000 inclusive calendar dates
   per request, prioritizing 2022 onward and the existing research symbols.
   EQ is a capture category, not certification that every record is a stock.
   Report local symbols missing from the vendor master; current instruments
   must not be presented as complete historical constituent coverage. Verify
   that every selected instrument has disjoint, complete requested-date coverage.
3. Pace one capture process below the official 3 requests/second. Retry only
   bounded transient failures; halt on authentication, entitlement and rate
   limiting. Persist exact original responses and verified request manifests
   in a private store outside the repo. Publish response/manifest pairs
   atomically. Resume by verifying completed responses, including honest empty
   windows, without repeating their requests.
4. Probe the four known missing sessions and BSE/factor-discrepancy examples
   before every bulk acquisition or resume, reusing verified probe artifacts.
   Explicitly distinguish date presence from verified
   corporate-action treatment. Preserve separate provider data; never splice
   it into the existing Yahoo snapshot or enable trading automatically.
5. Validate timestamps, ranges, unique dates and OHLCV. Normalize completed
   captures into private per-instrument Parquet with raw-input lineage and
   coverage reports. Missing/invalid requests must not become fabricated bars
   or a successful completeness claim.
6. Retain invalid historical responses separately with request identity, original
   bytes, hashes and rejection reason. Continue acquiring other windows, reuse
   verified rejected responses on resume, and report their count explicitly.
   Conflicting duplicate bars must never be selected, merged or dropped silently.
   Corrupt caches and failed probes still stop the job. An acquisition containing
   rejected responses must exit unsuccessfully and block normalization until
   those responses receive an explicit, independently justified resolution.
