# Kite archive validation and first swing baseline

Owner instruction, 7 September 2026: start validating the archive, establish a
price-based swing baseline, and assess historical crisis coverage before adding
news or social sentiment to decisions.

1. Audit every frozen capture request against original bytes and manifests.
   Count accepted, rejected and missing windows separately. Diagnose all defects
   inside rejected responses without selecting conflicting bars or altering raw
   data. Report actual coverage in declared crisis windows; never infer complete
   coverage from an early first date or certify historical membership.
2. Materialize a separate recent development snapshot of the original research
   symbols matched to the frozen Kite master. Retain all matching instruments,
   including incomplete histories, and list every unmapped symbol explicitly.
   This is a current matched-stock development cohort, not a historical Nifty
   500 universe. The full-archive normalization gate remains unchanged.
3. Missing/rejected requests in the selected date window block this snapshot.
   Unresolved old requests outside that window remain in the archive and are
   recorded as limitations. Remove only independently confirmed flat, zero-volume
   holiday placeholders, using the existing audited rule. Never fill missing
   prices, merge vendors or silently omit poorly performing/covered stocks.
4. Publish atomically with input plan, universe, raw-response and output hashes,
   implementation identity and symbol mapping. Verify those identities and the
   exact output file set before the frozen runner uses the snapshot. Snapshot
   authority is always research-only; corporate actions and historical identities
   remain uncertified. Repeated runs cannot restore an untouched holdout.
5. Run the existing frozen momentum_breakout_55 settings with the existing
   ₹300,000 account, costs, risk settings and configurable 100% research drawdown
   boundary. Report the actual result, including any simulation blockers, without
   changing strategy parameters to obtain a passing result.
6. Capture primary-source resolutions for listing/suspension/merger exceptions;
   distinguish an inactive exchange interval from an absent provider bar. Keep
   news/sentiment collection as subsequent work, with timestamps and separate
   evaluation required before it can influence orders. No live activation.
