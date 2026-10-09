"""pydeck map: one point per factory, coloured by number of Present risks (impact indicators and overall excluded)."""
from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st

GREEN, AMBER, RED = [6, 118, 71, 220], [247, 144, 9, 220], [217, 45, 32, 220]
LEGEND = "Map colour = number of Present risks: green 0, amber 1-2, red 3 or more (overall score and downstream impact not counted)."


def _colour(n: int) -> list[int]:
    return GREEN if n == 0 else AMBER if n <= 2 else RED


def factory_map(df: pd.DataFrame, selected: str | None) -> None:
    d = pd.DataFrame({
        "name": df["Factory"], "lat": df["_lat"], "lon": df["_lon"], "color": [_colour(n) for n in df["# present"]],
        "tip": [f"{n} present, {w} watch" for n, w in zip(df["# present"], df["# watch"], strict=True)],
        "overall": df["_overall"], "sel": df["Site ID"] == selected,
    })
    layers = [pdk.Layer("ScatterplotLayer", d, get_position=["lon", "lat"], get_fill_color="color", radius_min_pixels=7,
                        radius_max_pixels=14, get_radius=20000, pickable=True)]
    if d["sel"].any():
        layers.append(pdk.Layer("ScatterplotLayer", d[d["sel"]], get_position=["lon", "lat"], get_fill_color=[0, 0, 0, 0],
                                get_line_color=[21, 112, 239, 255], stroked=True, filled=False, line_width_min_pixels=3,
                                radius_min_pixels=14, get_radius=20000))
    view = pdk.data_utils.compute_view(d[["lon", "lat"]], 0.9) if len(d) > 1 else pdk.ViewState(
        latitude=float(d.lat.iloc[0]), longitude=float(d.lon.iloc[0]), zoom=6)
    deck = pdk.Deck(layers=layers, initial_view_state=view,
                    tooltip={"text": "{name}\n{tip}\nOverall textile: {overall}"})
    st.pydeck_chart(deck, height=340)
    st.caption(LEGEND)
