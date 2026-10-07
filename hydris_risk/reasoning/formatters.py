"""Number/label formatting. Everything returns None (never "None"/"nan") when the input is missing."""
from __future__ import annotations

import calendar
import math
import re
from typing import Any

CAT_NAMES = {-1: "arid / none", 0: "low", 1: "low–medium", 2: "medium–high", 3: "high", 4: "extremely high"}


CAT_TITLES = {-1: "Arid", 0: "Low", 1: "Low–Medium", 2: "Medium–High", 3: "High", 4: "Extremely High"}


def clean_label(label: str | None) -> str | None:
    """Prose style for a verbatim data label: 'Medium - High (20-40%)' -> 'Medium–High (20–40%)'."""
    if not label:
        return None
    return re.sub(r"(?<=\d)-(?=\d)", "–", label.replace(" - ", "–"))


def month_name(m: int) -> str:
    return calendar.month_name[m]


def cat_titles(cfg: dict[str, Any]) -> dict[int, str]:
    """Category -> title for this risk (drr's scheme is Low/Low-Medium/Medium/Medium-High/High)."""
    return {**CAT_TITLES, **cfg.get("cat_titles", {})}


def cat_name(cat: int | None, cfg: dict[str, Any] | None = None) -> str | None:
    """Lower-case category name for headlines, e.g. 'medium–high'."""
    if cat is None:
        return None
    t = cat_titles(cfg or {}).get(cat)
    return t.lower() if t else None


def _decimals(cfg: dict[str, Any]) -> int:
    return cfg.get("decimals", 1 if cfg.get("display") == "percent" else 2)


def _cat(x: float, thresholds: list[float]) -> int:
    return sum(t <= x for t in thresholds)


def _num_text(v: float, d: int, cfg: dict[str, Any], scale: float = 1.0) -> str:
    """Round to d decimals, adding decimals until the rounded number sits in the same category as v
    (so '0.2487' is shown as '0.249', never as '0.25' next to the label 'Low (<0.25)')."""
    thr = [round(t * scale, 10) for t in cfg.get("thresholds", [])]
    for dd in range(d, d + 9):
        text = f"{v:.{dd}f}"
        if not thr or _cat(float(text), thr) == _cat(v, thr):
            return text
    return text


def fmt_value(raw: float | None, cfg: dict[str, Any]) -> str | None:
    """Raw value with unit. Ratios shown as %; gtd gets a direction in words per `decline_sign`."""
    if raw is None:
        return None
    d = _decimals(cfg)
    if cfg.get("display") == "percent":
        v = raw * 100
        if cfg.get("sig") and v:  # small shares (flood): keep `sig` significant figures
            d = max(d, cfg["sig"] - 1 - math.floor(math.log10(abs(v))))
        text = _num_text(v, d, cfg, 100)
        if "." in text and float(text) == int(float(text)):
            text = str(int(float(text)))  # whole percentages without ".0"
        return f"{text}%"
    if cfg.get("display") == "score":
        return f"{_num_text(raw, d, cfg)} of 5"
    text = _num_text(raw, d, cfg)
    if cfg.get("decline_sign"):
        text = f"{raw:+.{len(text.split('.')[-1]) if '.' in text else 0}f}"
    unit = cfg.get("unit_display", cfg.get("unit"))
    unit = None if unit in (None, "", "ratio") else unit
    text = f"{text}{unit}" if unit and unit.startswith("/") else f"{text} {unit}" if unit else text
    if sign := cfg.get("decline_sign"):
        falling = raw > 0 if sign == "positive" else raw < 0
        word = "no change" if round(raw, d) == 0 else ("falling" if falling else "rising")
        text += f" ({word})"
    return text


def per_people(raw: float | None) -> str | None:
    """'about 1.5 in every 1,000 people' for a population share."""
    if raw is None or raw <= 0:
        return None
    for denom in (1_000, 100_000, 1_000_000):
        if raw * denom >= 1 or denom == 1_000_000:
            n = raw * denom
            break
    text = f"{n:.2g}" if n < 10 else f"{n:.0f}"
    return f"about {text} in every {denom:,} people"


def fmt_raw_display(raw: float | None, cfg: dict[str, Any]) -> str | None:
    """Values-panel text: fmt_value plus the per-people form where configured (flood)."""
    text = fmt_value(raw, cfg)
    if text and cfg.get("per_people") and (pp := per_people(raw)):
        text += f" ({pp})"
    return text


def fmt_delta(delta: float, cfg: dict[str, Any]) -> str:
    """Signed difference: percentage points for ratios, plain signed number otherwise."""
    d = _decimals(cfg)
    if cfg.get("display") == "percent":
        return f"{delta * 100:+.{d}f} points"
    return f"{delta:+.{d}f}"


def fmt_amount(delta: float, cfg: dict[str, Any]) -> str:
    """Unsigned distance, e.g. '3.4 points'."""
    return fmt_delta(abs(delta), cfg).lstrip("+")


def place(name_1: str | None, name_0: str | None) -> str:
    parts = [p for p in (name_1, name_0) if p]
    return f" ({', '.join(parts)})" if parts else ""
