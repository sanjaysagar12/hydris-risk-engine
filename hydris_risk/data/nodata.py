"""NoData rule (verified in Step 0): NaN/None, -9999, >= 9000, or label "no data" (any case).

Category numbers drive logic; labels are display-only. Real categories -1 ("arid", "no risk",
"no to low wastewater collected") are NOT NoData.
"""
from __future__ import annotations

import math
from typing import Any

SENTINEL_MAX = 9000


def is_nodata(value: Any = None, label: str | None = None) -> bool:
    if isinstance(label, str) and label.strip().lower() == "no data":
        return True
    if value is None:
        return True
    try:
        v = float(value)
    except (TypeError, ValueError):
        return True
    return math.isnan(v) or v <= -SENTINEL_MAX or v >= SENTINEL_MAX


def clean(value: Any) -> Any:
    """Value or None if NoData (numbers only)."""
    return None if is_nodata(value) else value
