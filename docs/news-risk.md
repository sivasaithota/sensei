# Focused news-risk guard

Sensei treats news as entry-risk evidence, never as a trading signal.

## Required coverage

The official NSE corporate-announcement feed is the only mandatory news
provider. It is restricted to instruments in the local trading universe and
captures results, sales/business updates, corporate actions, auditor events,
insolvency and trading suspensions. Existing signed NSE surveillance and the
earnings-window guard remain independent mandatory controls.

RBI, PIB, Federal Reserve, ECB, Bank of England and bounded geopolitical RSS
feeds are advisory. Their events can produce caution or a verified critical
block, but an individual advisory-provider outage does not halt the desk.

Sensei deliberately does not ingest social media. It also does not scrape SEBI
HTML, infer company exposure from disaster regions, or download and interpret
financial-statement PDFs in the entry system.

## Admission policy

- `BLOCK`: an applicable trading suspension, insolvency, accounting fraud,
  exchange closure or other explicitly critical event.
- `CAUTION`: results, sales/guidance, corporate actions, rates, inflation or
  geopolitical risk. Caution is context and never creates a trade.
- `CLEAR`: fresh signed evidence with no applicable material event.
- `UNKNOWN`: stale/corrupt evidence or unavailable required NSE corporate
  coverage. Unknown evidence blocks new exposure.

The scheduler refreshes every 30 minutes and uses a five-minute refresh target
from 09:10 to 09:20 IST. The order path performs no network calls and consumes
only a signed snapshot no more than 15 minutes old. Exits and EOD safety work
remain independent of news availability.

## Operations

```bash
uv run sensei news-refresh
uv run sensei news-status
```

Every refresh records successful and failed sources plus the signed snapshot
digest. Reporter decisions record the same digest and exact event identities.
