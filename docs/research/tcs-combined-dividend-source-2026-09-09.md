# TCS combined cash dividend, January 2026

Reviewed 9 September 2026. The exact unsupported source event `db590d16db179e06a958bd8625f455445219efd7e282d23895c1f05411c11073` is a **₹57 gross cash dividend per share**, comprising ₹11 interim and ₹46 special dividend. It is not a share distribution.

TCS's dated **12 January 2026** press release confirms the aggregate ₹57, the ₹46 special component, **17 January** record date and **3 February** announced payment date. The notice was published before the ex-date; conservatively treat its terms as known after the 12 January close. [Company release filed with NSE](https://archives.nseindia.com/corporate/TCS_CORPCS_12012026155540_PressReleaseletter.pdf).

The NSE corporate-action row identifies **16 January 2026 as ex-date and 17 January as record date**. Preserve that distinction. The raw row is already captured in `data/reports/portfolio-action-evidence/2026-through-09-04.json`, with ISIN `INE467B01029`, EQ series, and the combined interim/special text. Its body hash and original capture manifest are pinned in the new [TCS source manifest](../../data/research/strategy-design/20260909/tcs-dividend/source-manifest.json). [NSE action record](https://www.nseindia.com/companies-listing/corporate-filings-actions?symbol=TCS&tabIndex=equity).

The new declaration PDF SHA-256 is `a94fabc9a7a2a8069841b8100380806e31e5e5cc1119963292d162cbbdc83ab1`; its adjacent receipt records URL and capture time. The captured NSE HTML is a shell without event payload, so the frozen NSE JSON is the ex-date evidence. The TCS stock-information page request returned HTTP 403 and supplies no local evidence.

The announced payment date does not certify individual receipt or withholding. This source repair implies no change to the portfolio's existing dividend-receivable/spendability policy. The demerger source manifest remains unchanged.
