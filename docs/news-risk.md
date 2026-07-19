# Verified news and corporate-event risk

Sensei treats news as entry-risk evidence, never as a trade signal. The
governed scheduler refreshes the signed snapshot every 30 minutes and forces
a refresh during the 9:10–9:20 IST pre-entry window. The entry handler performs
no network calls: it consumes that pinned snapshot and fails closed if it is
more than 15 minutes old.

## Coverage

- Macro/geopolitical: RBI, PIB, Federal Reserve, ECB, Bank of England and
  bounded global-risk searches.
- Indian companies: the official NSE corporate-announcement API, restricted
  to instruments in the local trading universe.
- Results: quarterly/annual filing classification, reporting period, source
  attachment, and metrics present in the official announcement summary. An
  offline bounded PDF extractor is available for research enrichment; it hashes
  filing bytes and caches by content digest plus extractor version. Scheduled
  admission refreshes never download attachments.
- Corporate events: sales updates, guidance, dividends, buybacks, splits,
  bonus issues, mergers, promoter pledges, auditor events, insolvency,
  enforcement and trading suspension.
- Enforcement: official SEBI orders, scoped to symbols in the local universe.
- Natural disasters: official NDMA Sachet alerts, including their effective
  expiry. Alerts become company-specific when a configured operating region
  intersects the affected area.

Financial-result facts are source facts, not forecasts. Sensei does not infer
analyst expectations or enter a position because a metric appears favorable.

## Deterministic admission policy

- `BLOCK`: auditor event, insolvency or trading suspension for the instrument;
  critical market-wide event; stale or
  unverifiable required coverage.
- `CAUTION`: financial result, sales/guidance update, corporate action, promoter pledge,
  enforcement, monetary/geopolitical risk, or a material disaster exposure.
- `CLEAR`: verified required sources with no active material event.
- `UNKNOWN`: stale/corrupt snapshot or a required NSE, SEBI, NDMA or RBI source is
  unavailable. `UNKNOWN` blocks new exposure.

Exit and EOD safety work always runs independently of news availability.

## Company-to-region mapping

Add operating locations to `config/scheduler.json` when known:

```json
"company_regions": {
  "NSE:RELIANCE": ["Maharashtra", "Gujarat"],
  "NSE:TCS": ["Maharashtra", "Karnataka", "Tamil Nadu"]
}
```

Keep this mapping evidence-backed. An empty mapping does not invent company
exposure; only severe national-scale disaster headlines receive market-wide
caution.

## Operations

```bash
uv run sensei news-refresh
uv run sensei news-status
```

Every refresh journals source successes/failures and the signed snapshot
digest. Every Reporter decision records that same digest, observation time and
the exact event identities used by policy.
