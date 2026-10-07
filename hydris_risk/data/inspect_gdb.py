"""Step 0: inspect an Aqueduct .gdb and write a markdown report."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyogrio

NODATA_NUM = (-9999, -32767, -9998, -1)


def inspect_gdb(gdb: str | Path, out: str | Path = "data/cache/inspection_report.md") -> str:
    lines: list[str] = [f"# Aqueduct inspection: `{Path(gdb).name}`", ""]
    layers = pyogrio.list_layers(str(gdb))
    lines += ["## Layers", ""] + [f"- `{n}` ({g})" for n, g in layers] + [""]
    for name, _ in layers:
        info = pyogrio.read_info(str(gdb), layer=name)
        df = pyogrio.read_dataframe(str(gdb), layer=name, read_geometry=False)
        lines += [
            f"## Layer `{name}`", "",
            f"- rows: {len(df)}", f"- geometry: {info['geometry_type']}", f"- CRS: {info['crs']}",
            f"- columns ({len(df.columns)}): {', '.join(df.columns)}", "",
        ]
        for c in df.columns:
            if c.endswith("_label"):
                vals = sorted(map(str, df[c].unique()), key=str)
                lines.append(f"- distinct `{c}` ({len(vals)}): {vals[:30]}")
        lines.append("")
        lines += ["| column | min | max | NaN | sentinel counts |", "|---|---|---|---|---|"]
        for c in df.columns:
            if c.endswith(("_raw", "_cat")) or (c.endswith(("_r", "_c")) and "_x_" in c):
                s = df[c]
                if not np.issubdtype(s.dtype, np.number):
                    continue
                sent = {v: int((s == v).sum()) for v in NODATA_NUM if (s == v).any()}
                lines.append(f"| {c} | {s.min()} | {s.max()} | {int(s.isna().sum())} | {sent} |")
        lines.append("")
    text = "\n".join(lines)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(inspect_gdb(sys.argv[1]))
