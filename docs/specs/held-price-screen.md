# Held-price endpoint evidence screen

Overnight pass 5: inspect the original baseline and hold60 control, retaining
all 908 trade records (including shared trades in both runs). This is bounded
entry/exit evidence screening, not complete corporate-action certification.

Use the existing frozen-run verifier before source comparison. Read only the
existing quarantined raw NSE corpus; record its exact verified session hashes.
Do not fetch missing days. Match candidate equity rows by the frozen reference
symbol or ISIN, without fuzzy names, most-volume selection, or assuming a current
ISIN establishes historical identity. A unique candidate with a differing ISIN
remains explicitly unverified; multiple candidates are ambiguous. Preserve raw
symbol, series, ISIN and integrity status beside the current reference.

For each matched endpoint retain raw/Kite OHLCV, per-field price ratios and
Kite/raw volume ratio (unknown at zero volume). For trades with both endpoints,
screen changes exceeding 1% in the volume ratio as possible unit-scaling
discontinuities requiring source investigation. Do not label these confirmed
events or use raw/Kite close ratios to manufacture adjustment factors. Cash
dividend price treatment can differ from share-unit scaling.

Record every missing session, missing/ambiguous candidate, invalid raw row,
identity difference and unavailable ratio. An absence of flags proves neither
absence of dividends nor valid shareholder returns. Preserve all trades and
source prices. Bind screening code, source proofs, snapshot identity and raw
receipts into the output. Test matching ambiguity and zero-volume behavior.
Report primary broker/company evidence separately, update the overnight note,
run checks/reviews, and commit/push verified work. No dividends, entitlements,
orders, new subscriptions or price repairs are authorized by this screen.
