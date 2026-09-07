# PGEL: dated split identity

Research date: 7 September 2026. This note establishes a security-identity transition only. It does not authorize changing portfolio quantities, distributing shares, adjusting prices, or declaring a complete corporate-action ledger.

MSE/LIST/15638/2024, dated **9 July 2024**, explicitly changes PG Electroplast Limited's ISIN from **INE457L01011** to **INE457L01029**, effective for trades on and after the **10 July 2024 ex-date**. It states a subdivision from ₹10 to ₹1 face value. [Primary MSEI circular](https://www.msei.in/SX-Content/Circulars/2024/July/Circular-15638.pdf).

The separately captured NSE all-purpose 2024 action record also gives **10 July 2024** as PGEL's ex-date and record date and identifies the ₹10-to-₹1 split. Its old-ISIN field agrees with the dated circular; current face-value metadata is not independent historical identity proof. The captured body is `data/reports/portfolio-action-evidence/2024-partition-2.json`, pinned through its capture manifest. [NSE historical request](https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=01-07-2024&to_date=31-12-2024).

For a raw reference dated before 10 July 2024, this transition supports the old ISIN; from that ex-date it supports the new ISIN. Raw rows must still independently match canonical symbol, series, session and valid OHLCV. The ten-for-one share ratio is descriptive of this split, not automatic entitlement authorization. No earlier identity transitions, symbol changes or other actions are certified by this note.
