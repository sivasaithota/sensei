# Remaining split identity evidence — 7 September 2026

The bounded nine-name lookup supports six exact accounting identity bridges. Three remain unresolved under the implementation's requirement that the action API ISIN equal the immediately preceding raw-session ISIN and that an official notice document the new ISIN, effective date, and split ratio. No identity checks were relaxed to obtain a portfolio result.

One official NSE notice per name was captured. All nine downloaded PDF texts and rendered first-page tables were inspected. A secondary circular index helped discover some original URLs; it is not evidence for the findings below. The notices are retrospective accounting evidence, not proof of a historically available signal or credited broker inventory. No Kite requests or account actions were made.

## Findings

Dates are in 2026. Ratios mean new shares per old shares. Except where explicitly different below, the API source ISIN equals the immediately prior raw ISIN. Old ISIN evidence comes from the pinned raw rows; the change notices identify the new ISIN, not the old one.

| Symbol | Ex/effective date | Prior raw ISIN | New raw ISIN | Ratio | Official evidence and outcome |
| --- | --- | --- | --- | --- | --- |
| KRISHANA | July 3 | INE506W01012 | INE506W01020 | 5:1 | [CML74947, June 30](https://nsearchives.nseindia.com/content/circulars/CML74947.pdf), face ₹10→₹2. Exact accounting bridge documented. |
| MWL | July 10 | INE0JYY01011 | INE0JYY01029 | 10:1 | [CML75082, July 7](https://nsearchives.nseindia.com/content/circulars/CML75082.pdf), face ₹10→₹1. Exact accounting bridge documented. |
| POCL | July 21 | INE063E01053 | INE063E01061 | 5:2 | [CML75265, July 17](https://nsearchives.nseindia.com/content/circulars/CML75265.pdf), face ₹5→₹2. **Unresolved:** API source ISIN is INE063E01046, different from immediate prior raw ISIN. |
| JLHL | July 24 | INE682M01012 | INE682M01020 | 5:1 | [CML75329, July 22](https://nsearchives.nseindia.com/content/circulars/CML75329.pdf), face ₹10→₹2. Exact accounting bridge documented. |
| NARMADA | July 31 | INE117Z01011 | INE117Z01029 | 2:1 | [CML75480, July 30](https://nsearchives.nseindia.com/content/circulars/CML75480.pdf), face ₹10→₹5. Exact accounting bridge documented. |
| TEMBO | August 5 | INE869Y01010 | INE869Y01028 | 10:1 | [CML75555, August 4](https://nsearchives.nseindia.com/content/circulars/CML75555.pdf), face ₹10→₹1. Exact accounting bridge documented. |
| KIRLPNU | August 18 | INE811A01020 | INE811A01038 | 2:1 | [CML75661, August 10](https://nsearchives.nseindia.com/content/circulars/CML75661.pdf), face ₹2→₹1. **Unresolved:** this face-value notice does not state the new ISIN. |
| TDPOWERSYS | August 24 | INE419M01027 | INE419M01035 | 2:1 | [CML75855, August 20](https://nsearchives.nseindia.com/content/circulars/CML75855.pdf), face ₹2→₹1. **Unresolved:** API source ISIN is INE419M01019, different from immediate prior raw ISIN. |
| CORDELIA | August 25 | INE0LZF01013 | INE0LZF01039 | 10:1 | [CML75904, August 25](https://nsearchives.nseindia.com/content/circulars/CML75904.pdf), face ₹10→₹1. Exact accounting identity documented, but notice is dated on the ex-date. |

CORDELIA's notice cannot establish pre-open availability on August 25. No source in this batch establishes an exact publication timestamp, broker credit date, or tradable inventory credit. Keep those separate from the identity transition. Do not splice adjusted signal history with these records. POCL and TDPOWERSYS require a separate earlier identity-chain investigation before admission; substituting their immediately prior ISIN into the API field would fabricate source evidence. KIRLPNU's raw ISIN change and matching ratio do not substitute for the missing official new-ISIN notice under the selected acceptance rule.

## Pinned local evidence

Directory: `data/research/tail-split-identities/20260907/`. `bridges.json` retains all nine records, with six `documented_exact_accounting_bridge` and three `unresolved` statuses, explicit reasons, separate API/prior/new identities, token, date, ratio, and source hashes. Consumers must filter on the status rather than admit every record. `raw-observations.json` contains the 18 complete prior/ex raw rows and archive/member provenance hashes. Earlier TFCILTD, NUVAMA, and MBAPL captures are unchanged.

| Artifact | SHA-256 |
| --- | --- |
| bridges.json | `efeba8f1426f63aecb14c0c4dd8470e9359df3960337774b3107b01dd849caee` |
| raw-observations.json | `0f52e6046038c45b100e7a0bb808d47dfab626bf179ebd4acda31dc9d6a8ef24` |
| manifest.json | `5005571df658a2595775015d178687f7a2d35cd9e43ee9a345507b56cf8516e6` |
| CML74947.pdf | `53b667dc18f977168675d494535d63e67af1e279c828bebef7afb89943f3117c` |
| CML75082.pdf | `95babf7815acf1afc4ff1416b7fd67e21c81af26c619108fef2e12bd524b0e17` |
| CML75265.pdf | `31b503eb49c62b6899b8dc1f0193fc05f463727dbf8ce722eac802b00972766c` |
| CML75329.pdf | `e1fd95d45ea98820ce60f897e9cbbd91300a4638dea45880773f60a9823778bc` |
| CML75480.pdf | `8be309542bcbe358eaa90f8e8f84bba47f64186cad42f2c04dea9c5bb95e603c` |
| CML75555.pdf | `ab0fb4f205d49b297b3ef8467ee769373b408a434d1e4e4a66af2a739df98f0e` |
| CML75661.pdf | `97cdbaabfdc310a2cd9f6a9912e79f50dff3d103d7993876411f2fb2d03d7173` |
| CML75855.pdf | `6016bec01414f6596ed077b937ebe4d24f5fd940ffca7e483730f1b40b4da8e9` |
| CML75904.pdf | `bb7d52446938721830277f5f3a171ea561d0aaa4b8d69e361d9140280d42996f` |

This frozen list completes the requested bounded lookup. Unresolved cases remain explicit; no alternate-source chase or strategy-outcome selection was performed.
