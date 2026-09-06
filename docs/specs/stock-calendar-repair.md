# Stock calendar repair

User request, 6 September 2026: start the next dataset-repair actions for the
NSE swing research baseline. The owner confirmed AccelPix access is pending.

Acceptance:

1. Preserve the original price files. Create a separate, reproducible snapshot
   containing every supplied instrument. Remove only the four officially
   confirmed holiday dates, and only when each removed row is a flat,
   zero-volume placeholder. Record source hashes and every excluded row.
   Unexpected holiday trading data must stop the repair before output is written.
2. Verify the snapshot's instrument set and content before reuse. Bind repair
   lineage into the frozen run's identity and report. Cleaning does not grant
   admissibility or trade authority.
3. Audit all four missing sessions against verified raw NSE sessions and the
   adjacent adjusted bars. Retain identity failures, listings outside the
   observed history and factor discrepancies. Neighbor agreement alone must
   never authorize insertion or count as an exact-date adjustment factor.
4. Keep the existing strategy, dates, capital, costs and drawdown settings
   frozen; rerun using a separate configuration pointing to the cleaned data.
   Report the actual calendar result, including remaining blocked sessions.
5. Document the evidence and the external data dependency. Do not estimate
   missing factors, invent returns, or alter runtime risk/live settings.
