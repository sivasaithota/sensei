# Descriptive stock loss attribution

Overnight pass 2: analyze the four frozen results already produced in
`lower-turnover-comparison-v1-20260907.json`. Do not run new strategy variants.

1. Verify source report checksums, manifest-derived run IDs, saved settings,
   required Kite snapshot provenance, scoped frame digests and benchmark hash
   before publishing a derivative. Bind source and diagnostic implementation
   hashes to the derivative artifact. Never mutate prices or trade ledgers.
2. Account for every completed trade. Group realised P&L, costs, losses and trade
   counts by exit year, security, exit reason and fixed volatility bins. Exit-year
   realised P&L is not an annual portfolio return. No dropping losing securities.
   Reconcile summed trade net P&L to final campaign P&L with explicit tolerance
   for rounded trade amounts; reject open positions or material discrepancies.
3. Measure simple 14-bar average true range using exactly the last 15 benchmark
   sessions strictly before entry (the first close is needed for true range).
   Require every bar. Missing history produces an explicit unknown observation,
   never filling or shortening the window. Future and entry-day OHLCV must not
   affect the measure. This is adjusted-chart volatility, not certified raw risk.
4. Compare initial stop distance with that ATR. Freeze bins before inspection:
   below 1 ATR, 1 to below 2 ATR, at least 2 ATR, and unknown. Use actual entry
   fill and configured stop percentage for distance; no future price information.
5. Report fixed summaries, top losing/winning securities and stop/gap-stop
   contribution without recommending deletion of stocks or wider stops based
   solely on this history. Mark all results descriptive reused development,
   research-only, data-blocked, incapable of authorizing trades. No parameter
   sweep, new holdout designation, data purchase or Kite request.
6. Add meaningful regressions for prefix invariance, missing-session treatment,
   ATR arithmetic/bin boundaries and P&L reconciliation. Run checks and both
   review axes, commit/push verified work, and update the overnight progress
   note with concrete findings and the next bounded action.
