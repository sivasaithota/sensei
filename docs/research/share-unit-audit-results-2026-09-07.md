# Split-adjusted quantities expose non-executable share counts

Pass 6 establishes a concrete execution-representation defect in the saved
baseline and hold60 controls: integer quantities on backward-adjusted prices
can represent fractional physical shares. It does not change either portfolio's
returns. They remain DATA_BLOCKED and research-only.

## Evidence and result

[Primary evidence](mazdock-heg-share-lineage-2026-09-07.md) establishes MAZDOCK's
2-for-1 split effective December 27, 2024 and HEG's 5-for-1 split effective
October 18, 2024, including their old/new ISINs. The manually transcribed ledger
is `config/stock-split-evidence-v1.json`; it pins that research note's hash.

The audit required both saved endpoints to predate the specified split, matching
raw old ISIN and reference new ISIN, matching documented volume scaling, and
all OHLC fields to agree with raw divided by the split multiplier within ₹0.05
in adjusted-price units. That diagnostic envelope does not certify tick prices.

| Shared trade | Saved adjusted units | Physical equivalent | Whole-share floor | Adjusted units at floor |
|---|---:|---:|---:|---:|
| HEG, April 16–May 3, 2024 | 123 | 24.6 | 24 | 120 |
| MAZDOCK, May 30–31, 2024 | 35 | 17.5 | 17 | 34 |
| MAZDOCK, June 18–27, 2024 | 30 | 15 | 15 | 30 |
| MAZDOCK, July 5, 2024 | 21 | 10.5 | 10 | 20 |

Each trade appears in both portfolios. Of all 908 source trade records, six are
fractional physical equivalents and two integral; 893 are outside this two-event
ledger and seven outside its pre-split scope. Outside-scope records are unknown,
not passes. Integral equivalents do not establish otherwise-valid executions.
No prices, fees, cash balances, P&L or source records were changed.

Final artifact:
`data/reports/share-unit-audit/ab1fc239b6c885158f1d874c1b2a25dbbccce0f4928ed565549d0551432f5067/report.json`.
The directory name equals its SHA-256. It pins the input held-price screen,
source proofs, ledger, research note and implementation. Independent Standards
and Spec reviews were clear; the Spec reviewer reproduced all counts and exact
quantity conversions. Targeted tests: 16 passed. Full suite: **938 passed**.

## Next implementation step

Add explicit entry quantity increments to the research portfolio sizing path,
with dated evidence required to interpret adjusted units as actual shares.
Sizing must round down within cash, risk and allocation limits, including fees;
an unaffordable whole share must result in no entry. Bind the unit map into the
experiment identity. Unknown unit evidence must not silently become a multiplier
of one when this mode is requested. Preserve the existing control mode and mark
its synthetic-unit limitation explicitly.

First validate the sizing correction with a bounded reproduction of these known
cases and meaningful cash/risk tests. Do not rerun a full portfolio with only two
securities' unit evidence and call it corrected. The current evidence is too
narrow for that. Held positions must not receive a second split quantity credit
if their coordinate system already includes the same split.

Cash-dividend adjustments, execution-price/tick rounding, and demerger claims
remain separate unresolved accounting work. HEG's September 7, 2026 demerger
falls after the frozen September 4 capture and must not be folded into its 2024
split multiplier when extending the dataset.
