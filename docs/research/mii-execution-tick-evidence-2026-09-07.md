# MII execution tick: field mapping established, unit bridge qualified

Research date: 7 September 2026. **Use `BidIntrvl` when investigating the actual
tick field. `TickSz` is a documented filler.** The captured MII workbooks establish
this distinction, but do not explicitly state the unit of `BidIntrvl`.

## Primary schema checks

The following source rows were read locally with their original strings and
hashes preserved:

| Source | Actual tick field | Filler |
|---|---|---|
| [MSD55276, Annexure A](https://nsearchives.nseindia.com/content/circulars/MSD55276.zip), sheet `Annexure 1_security master file` | Row 16: field 9, `TickSize`, `VARCHAR[10]`, ISO `BidIntrvl ` | Row 65: field 58, `Filler`, `FLOAT[3,2]`, ISO `TickSz` |
| [CMTR61813, Part D](https://nsearchives.nseindia.com/content/circulars/CMTR61813.zip), `Annexure 11` | Row 19: the same field-9 mapping | Row 68: the same field-58 filler mapping |
| [CMTR73927, Part D](https://nsearchives.nseindia.com/content/circulars/CMTR73927.zip), `Annexure 10` | Row 19: the same field-9 mapping | Row 68: the same field-58 filler mapping |

The trailing space in the spreadsheet ISO tag is preserved above; the captured
CSV header uses `BidIntrvl`. Annexure 1 in the 2024 and 2026 workbooks describes
the original `TickSize` field as the tick/minimum spread size, at spreadsheet rows
62 and 63 respectively. Neither these descriptions nor the MII mapping rows
specify paise, rupees, or a scale conversion.

The existing source hashes were rechecked:

| Local source | SHA-256 |
|---|---|
| `data/research/nse-mii-schema/20260907/Annexure-A_CM.xlsx` | `05443f4d0b14163f2398ba3b6bdf133b633291780b65cfea58a2084d51b21a6d` |
| `data/research/nse-mii-schema/20260907/PART-D.xlsx` | `936082c7f2308d84e5865022dff0bf803738745dc38cbc5ae00695d28bd3be82` |
| `data/research/nse-master-schema-vintage/20260907/CMTR73927_PART-D.xlsx` | `30a4e37956ba5ab1acdda177411beca0146ebab0bcb155f1cd4f12576d195798` |

## Unit evidence from a related product

The official [NSE Masters Data specification v1.6, dated 5 May 2025](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE-Masters%20Data-v1.6.pdf)
states in section 2.3, printed page 7, that CM price fields are in paise and divide
by 100 to produce rupees. Its section 3.1, printed page 9, includes a numeric
`Tick Size` field for `security.txt`. This supports a paise interpretation of the
related field. However, that document describes the separately delivered Masters
Data product, including its own SFTP service. It does not explicitly mention MII
`BidIntrvl` or certify that the CSV carries an unchanged numeric scale. The
workbook name mapping plus that unit rule is therefore a **cross-format
inference**, not a direct MII unit statement.

The PDF was downloaded once from the official source. The
[receipt](../../data/research/mii-execution-tick/20260907/capture.json) pins HTTP
status 200, 817,499 bytes and PDF SHA-256
`a1e45b6de312ebf05298fac8a1c4fbe337b8339b7eb110ac75705925bd05487e`.

## Execution recommendation for the current diagnostic

Retain the already reconstructed, explicitly sourced tick policy for the
integrated portfolio diagnostic. Preserve `BidIntrvl` as a raw value alongside
it, enabling comparisons without silently changing execution assumptions. Do not
cast `TickSz`, substitute its blank value, or treat a raw `BidIntrvl=5` example as
universal proof of scale.

If a later research plan elects to interpret `BidIntrvl` as paise, it should pin
that inference, reject nonpositive/nonintegral values, reconcile independently
documented tick changes and assign the correct snapshot timing. It must retain a
separate flag for the unit assumption and must not claim historical publication
time has thereby been verified. This is modeling guidance, not another NSE rule.

No execution code, existing pinned note, source plan, account or Kite data was
changed. The bounded follow-up used local schema reads and one public PDF
download; it made no historical-master requests.
