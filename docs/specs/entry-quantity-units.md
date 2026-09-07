# Evidence-aware entry quantity increments

Pass 7 fixes the sizing representation defect established by the MAZDOCK/HEG
split audit. Add an explicit optional mode to the research portfolio simulator;
preserve numerical behavior when it is omitted. Do not promote either mode to
live or certified authority.

The caller supplies a dated positive-integer adjusted-unit increment for each
instrument and an evidence artifact SHA-256. An increment of two means one
physical entry share is represented by two units of the supplied adjusted price
series. Require the map's instrument universe to match the price universe.
Dates must be unique naive daily timestamps within that instrument's calendar;
noninteger, boolean, nonpositive and infinite increments are invalid. Missing
dates or nullable values mean unknown and block entry. Do not forward-fill or
silently use one. Require the evidence hash whenever a map is supplied, and
reject a hash supplied without a map. The hash identifies caller-supplied
evidence; the simulator does not certify that external evidence itself.

Consult the increment on the prospective entry date, independently of the signal
and any existing entry-eligibility mask. The largest order must be a multiple of
that increment. Preserve notional allocation limits, cash including entry fees,
and stop risk including both-side fees under the delivery model. Flat-cost mode
must also obey the increment. An unaffordable first increment produces no entry.
Retain quantities of existing positions when entry increments change; do not
apply a second split credit in an already adjusted coordinate system.

Bind the normalized map, evidence hash and relevant implementation into campaign
identity. Report whether quantities use legacy synthetic integer units or
explicit entry increments, and state that neither certifies raw execution prices,
ticks, dividends or complete corporate-action accounting. Keep can_trade=false.

Verify cash/risk/notional boundaries, missing and malformed unit evidence,
entry-date alignment, existing-mask composition, unchanged control outcomes,
identity changes, and no double-credit of held quantities. Reproduce the three
known fractional cases with isolated entries using their saved unit evidence;
label this a sizing reproduction, not a corrected full portfolio. Preserve all
saved controls. Run the full suite and independent Standards/Spec reviews, then
document results and the next evidence-coverage work before committing/pushing.
