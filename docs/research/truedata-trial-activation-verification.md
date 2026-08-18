# TrueData trial activation verification

Date: 2026-08-18
Status: activated private trial capture in progress; no governed promotion

## Verdict

The new trial email clearly grants a **corporate/fundamental data trial** with:

- real-time corporate announcements over WebSocket at `wss://corp.truedata.in:9092`;
- historical corporate/fundamental data over REST, authenticated with a bearer token;
- the same login credentials for WebSocket and REST; and
- expiry on 2026-08-21.

It does **not** clearly grant NSE equity/index price streaming or historical market-price REST. The email labels the subscription segments as “Corporate and Fundamental Data.” Port `9092` and host `corp.truedata.in` are the documented corporate-announcement feed, not the market-price WebSocket. The market-data manual documents a separate `push.truedata.in` WebSocket and different sandbox/production ports.

Therefore, the safest current interpretation is:

| Capability | Verified from trial email + official docs | Confidence |
|---|---|---|
| Corporate announcement WebSocket | Yes, `corp.truedata.in:9092` | High |
| Corporate/fundamental historical REST | Yes, via auth + corporate REST | High |
| Historical market-price REST (`history.truedata.in`) | Not confirmed by this activation email | Low |
| NSE price WebSocket (`push.truedata.in`) | No; no price-feed segment or market WebSocket port supplied | High |
| Symbol-master API | Documented generally, but trial entitlement not confirmed | Medium |

The earlier vendor reply said both market historical and corporate data would be enabled with trial limits. The activation email is narrower. The entitlement returned by authentication and the first non-destructive probes must be treated as the source of truth; the downloader must not assume NSE EQ/Indices history until that is confirmed.

## Official connection contract

### Corporate/fundamental channel

The official corporate manual states that corporate announcements stream over WebSocket, while announcements, results and shareholding data are available historically through REST. It specifies:

- WebSocket: `wss://corp.truedata.in:9092` with query-string login;
- REST authentication: `POST https://auth.truedata.in/token` using form fields `username`, `password`, and `grant_type=password`;
- REST data base: `https://corporate.truedata.in/`;
- REST authorization: bearer token; and
- corporate REST rate limit: one call per second.

Sources:

- [Corporate API v1.1 extracted text](/Users/sivasaithota/Documents/sensei-private/truedata/review-2026-08-17/text/corporate-api-v1.1.txt), lines 183–203 and 213–216.
- [Corporate API PDF](/Users/sivasaithota/Documents/sensei-private/truedata/review-2026-08-17/TD_Docs/TrueData%20Corporate%20and%20Fundamental%20Data%20API%20Documentation%20v%201.1%20(2).pdf), pages 9–12.
- [Latest official TrueData documentation folder](https://www.dropbox.com/scl/fo/3wqc0iqwrz1qmoo0ddrpb/ACwQolXbC9Ns6kO7474LC6I?rlkey=km27y0cqn2esacst5q4zo0dm9&st=rj0t3kyy&dl=0).

### Market-price channel

The market-data manual separates real-time price streaming from historical REST:

- real-time prices use `wss://push.truedata.in:<port>`;
- the documented market sandbox port is `8086`, while production is `8084`;
- historical market data uses `POST https://auth.truedata.in/token`, followed by bearer-authenticated requests to `https://history.truedata.in/`; and
- the historical token is documented as valid for about 3,600 seconds.

The trial email supplies neither `push.truedata.in` nor port `8086`; it supplies the corporate host and corporate port instead. “Real-Time + History” in that email should consequently be read as real-time corporate announcements plus historical corporate/fundamental REST unless TrueData explicitly confirms otherwise.

Sources:

- [Market API v2.6 extracted text](/Users/sivasaithota/Documents/sensei-private/truedata/review-2026-08-17/text/market-api-v2.6.txt), lines 253–276 and 714–725.
- [Market API PDF](/Users/sivasaithota/Documents/sensei-private/truedata/review-2026-08-17/TD_Docs/TrueData%20Market%20Data%20API%20Documentation%20v%202.6%20(2).pdf), pages 9 and 19–21.
- [TrueData sandbox test page](https://wstest.truedata.in/).

## Mismatches in the current Sensei harness

The host/auth implementation is broadly correct for the documented production REST services:

- auth host: `auth.truedata.in`;
- history base: `history.truedata.in`;
- corporate base: `corporate.truedata.in`;
- symbol-master base: `api.truedata.in`; and
- one-second corporate pacing.

However, the planned request contract has material mismatches with the latest official Postman collection:

1. **Trial scope is assumed too broadly.** The default plan requests `eq` and `in` symbol masters, EOD Bhavcopies, and `getbars` from the historical market service. The activation email only identifies Corporate and Fundamental Data as subscribed segments.

2. **Corporate actions use the wrong service and parameters.** The latest official collection places `getcorpactionrange` under `history.truedata.in` and uses `exdatefrom`/`exdateto`. The harness sends `getCorpActionRange` to `corporate.truedata.in` with `symbol`/`from`/`to`.

3. **Symbol-change history uses the wrong service/endpoint.** The latest collection documents `history.truedata.in/getsymbolchangehistory`; the harness sends `getSymbolNameChange` to `api.truedata.in`.

4. **Several corporate detail endpoint names are stale.** Examples from the latest collection:

   - `getSHPListByDate`, not `getSHPList`;
   - `getAllShpById`, not `getSHPAllItems`;
   - `getShpSummaryById`, not `getSHPSummary`;
   - `getShpDetailById`, not `getSHPDetailById`;
   - `getBalSheetById2`, not `getBalSheetById`; and
   - announcement details are exposed as `getannouncementbyid` and `announcementfile2`, rather than only `announcementfile`.

5. **The original harness had no WebSocket support.** The activated-trial work
   added a separate checkpointed recorder for the confirmed port 9092 feed. It
   validates JSON messages, retains changed revisions, deduplicates identical
   replays, reconnects with bounded backoff, and never persists the
   credential-bearing connection URL.

Sources:

- [Current TrueData harness](/Users/sivasaithota/Documents/trade/src/sensei/data/truedata.py), especially the service bases and `TrialPlan.for_trial`/`expand_detail_plan`.
- [Latest official market REST Postman collection](/Users/sivasaithota/Documents/sensei-private/truedata/latest-2026-08-18/postman/TD%20Rest%20API%201.0%20Copy.postman_collection.json).
- [Latest official corporate Postman collection](/Users/sivasaithota/Documents/sensei-private/truedata/latest-2026-08-18/postman/TD%20Corporate%20Copy%203.postman_collection%20(4).json).
- [Latest official symbol-master Postman collection](/Users/sivasaithota/Documents/sensei-private/truedata/latest-2026-08-18/postman/TD%20Symbol%20Master%20v%201.0.postman_collection%20(4).json).
- [Latest official Postman folder](https://www.dropbox.com/scl/fo/uoa5ikkwplpcb6t113e8s/APbX5FqEvjMEZEhbKGK0Xgk?rlkey=rk6wi7y4wltx4avldz0i2owj1&st=ttsj4mue&dl=0).

## Required correction before activation traffic

Do not run the current full `sensei-truedata run` plan unchanged. First:

1. update the endpoint names, services and parameters to the latest Postman contract;
2. split the plan into independently selectable `corporate`, `history`, and `master` capabilities;
3. add a credential-safe entitlement probe that authenticates once and probes only tiny, bounded requests;
4. default to the corporate-only plan because that is the confirmed subscription;
5. enable the market-history plan only if the entitlement probe confirms it;
6. run the separate corporate WebSocket recorder for port 9092 throughout the
   short trial; and
7. keep every downloaded vendor file outside Git and quarantined from governed strategy evidence.

## Security note

The official Postman bundle includes literal example credentials and at least one literal bearer-token value. Even if these examples are expired, the collection must remain outside Git and should be treated as confidential. This report intentionally does not reproduce any password, token, or credential-bearing URL. The trial password should be set only in the local process environment or OS keychain.

## Evidence handling

The pre-activation verification used only downloaded official documentation and
Postman files. The later live-contract observations below used the owner-approved
trial credentials without persisting them. The official bundles remain outside
the repository under:

`/Users/sivasaithota/Documents/sensei-private/truedata/latest-2026-08-18/`

## Live contract observation

The first authorized corporate-only capture on 2026-08-18 verified all 93
financial-result list requests and all 93 shareholding-list requests. The legacy
`annoucements` range endpoint returned HTTP 404 for all 93 dates. Because that
range endpoint is absent from the latest official Postman collection, it was
removed from the default REST plan rather than retried blindly. No downloaded
payload was promoted into the governed market-data catalog.

Those successful lists contained 13,617 distinct financial-result IDs and 5,503
distinct shareholding IDs. Expanding every convenience projection would require
about 98,000 rate-limited calls. The trial capture therefore uses the documented
comprehensive `getAllResultItemsById` and `getAllShpById` endpoints—about 19,000
detail calls—while preserving the raw lists for later reconciliation.

The legacy range failure leaves a historical-announcement coverage gap. The
new recorder captures real-time announcements from its start time forward and
stores them in the same private, content-verified quarantine. It deliberately
does not claim to backfill announcements emitted before the connection began.
Its live handshake received the vendor's subscription and heartbeat control
frames without reconnecting; those frames are counted and ignored rather than
misclassified as announcement failures.
