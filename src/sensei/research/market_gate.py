"""Fixed research new-entry eligibility; no effect on existing holding exits."""

from __future__ import annotations

import pandas as pd

from sensei.research.market_attribution import market_states


def entry_masks(frames, benchmark, existing=None):
    allowed = market_states(benchmark)["state"].eq("above_sma200")
    if existing is not None and set(existing) != set(frames):
        raise ValueError("existing eligibility must cover exactly the price universe")
    masks = {}
    for symbol, frame in frames.items():
        mask = allowed.reindex(frame.index, fill_value=False)
        if existing is not None:
            prior = existing[symbol]
            if (not prior.index.equals(frame.index) or not pd.api.types.is_bool_dtype(prior.dtype)
                    or prior.isna().any()):
                raise ValueError("existing eligibility must be boolean and aligned with every price session")
            mask = mask & prior
        masks[symbol] = mask
    return masks
