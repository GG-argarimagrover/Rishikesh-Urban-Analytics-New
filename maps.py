"""Steps 10–11 – interactive Folium maps and the static overview PNG."""
from __future__ import annotations

from pathlib import Path

import branca.colormap as cm
import folium
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .context import Ctx  # noqa: E402

CARTO_LIGHT = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
SAT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
CLASS_COLORS = {"Hot + low amenities": "#d7191c", "Hot": "#fd8d3c", "Low amenities": "#3182bd",
                "OK": "#c7e9c0", "Non-built": "#dddddd"}


def _base_map(ctx: Ctx):
    cx, cy = ctx.aoi_ll.centroid.x, ctx.aoi_ll.centroid.y
    m = folium.Map(location=[cy, cx], zoom_start=12, tiles=None, control_scale=True)
    folium.TileLayer(CARTO_LIGHT, attr="© OpenStreetMap contributors © CARTO", name="Light", max_zoom=19).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer(SAT, attr="Esri World Imagery", name="Satellite").add_to(m)
    return m


def _tip_fields(ctx: Ctx):
    f = ["place", "lst_c", "lst_anom_c", "access_score", "n_amen_walk", "missing", "class"]
    a = ["Place", "Summer LST °C", "vs city median °C", "Access score", f"Amenities ≤{ctx.cfg.walk_radius_m} m",
         "Missing types", "Class"]
    if ctx.has_pop:
        f.insert(1, "pop")
        a.insert(1, "Population")
    return f, a


def choropleth(ctx: Ctx, col, colors, caption, highlight=None, hl_color="#000", show_points=False,
               fname=None, grey_nonbuilt=True):
    units = ctx.units
    TIP_F, TIP_A = _tip_fields(ctx)
    g = units.copy()
    if grey_nonbuilt:
        g.loc[~g.is_built, col] = np.nan
    g = g[["geometry", col] + [c for c in TIP_F if c != col] + ["is_built"]].to_crs(4326)
    g["place"] = g.place.fillna("")
    g["missing"] = g.missing.fillna("")
    lo, hi = g[col].quantile([0.02, 0.98])
    if not np.isfinite(lo) or lo == hi:
        hi = (lo if np.isfinite(lo) else 0) + 1
        lo = hi - 1
    cmap = cm.LinearColormap(colors, vmin=lo, vmax=hi, caption=caption)
    m = _base_map(ctx)

    def style(f):
        v = f["properties"].get(col)
        if v is None:
            return {"fillColor": "#bbbbbb", "color": "#888", "weight": 0.2, "fillOpacity": 0.15}
        return {"fillColor": cmap(min(max(v, lo), hi)), "color": "#333", "weight": 0.3, "fillOpacity": 0.7}

    folium.GeoJson(g, name=caption, style_function=style,
                   tooltip=folium.GeoJsonTooltip(fields=TIP_F, aliases=TIP_A, localize=True)).add_to(m)
    if highlight is not None:
        h = g[units[highlight].values]
        if len(h):
            folium.GeoJson(h, name=f"Outlined: {highlight}",
                           style_function=lambda f: {"fillOpacity": 0, "color": hl_color, "weight": 2.5}).add_to(m)
    if show_points:
        fg = folium.FeatureGroup(name="Amenities", show=False)
        a = ctx.am.to_crs(4326).sample(min(len(ctx.am), 4000), random_state=1)
        for p, c in zip(a.geometry, a.category):
            folium.CircleMarker([p.y, p.x], radius=2, color="#1f4e79", fill=True, fill_opacity=0.8, weight=0.5,
                                tooltip=c).add_to(fg)
        fg.add_to(m)
    cmap.add_to(m)
    folium.LayerControl().add_to(m)
    if fname:
        m.save(fname)
    return m


def priority_map(ctx: Ctx, fname):
    TIP_F, TIP_A = _tip_fields(ctx)
    g = ctx.units[["geometry"] + TIP_F].to_crs(4326).copy()
    g["place"] = g.place.fillna("")
    g["missing"] = g.missing.fillna("")
    m3 = _base_map(ctx)
    folium.GeoJson(
        g, name="Class",
        style_function=lambda f: {"fillColor": CLASS_COLORS[f["properties"]["class"]], "color": "#333", "weight": 0.3,
                                  "fillOpacity": 0.25 if f["properties"]["class"] == "Non-built" else 0.75},
        tooltip=folium.GeoJsonTooltip(fields=TIP_F, aliases=TIP_A, localize=True)).add_to(m3)
    legend = ("<div style='position:fixed;bottom:30px;left:30px;z-index:9999;background:white;padding:8px 10px;"
              "border:1px solid #888;font-size:13px'>" +
              "".join(f"<div><span style='background:{c};display:inline-block;width:12px;height:12px;margin-right:6px'></span>{k}</div>"
                      for k, c in CLASS_COLORS.items()) + "</div>")
    m3.get_root().html.add_child(folium.Element(legend))
    folium.LayerControl().add_to(m3)
    m3.save(fname)
    return m3


def make_all_maps(ctx: Ctx, out: Path) -> list[str]:
    files = []
    choropleth(ctx, "lst_c", ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c", "#7f0000"],
               "Median summer land-surface temperature (°C)", highlight="hot", fname=str(out / "map_1_heat.html"))
    files.append("map_1_heat.html")
    choropleth(ctx, "access_score", ["#d7191c", "#fdae61", "#ffffbf", "#a6d96a", "#1a9641"],
               "Amenity access score (0 = none, 100 = excellent)", highlight="low_amenity", show_points=True,
               fname=str(out / "map_2_low_amenities.html"))
    files.append("map_2_low_amenities.html")
    priority_map(ctx, str(out / "map_3_priority.html"))
    files.append("map_3_priority.html")
    if ctx.has_pop:
        choropleth(ctx, "pop", ["#ffffcc", "#fed976", "#fd8d3c", "#e31a1c", "#800026"], "Estimated population per unit",
                   highlight="priority", fname=str(out / "map_4_population.html"), grey_nonbuilt=False)
        files.append("map_4_population.html")
    return files


def overview_png(ctx: Ctx, fname: str) -> None:
    units = ctx.units
    fig, axs = plt.subplots(1, 3, figsize=(20, 7))
    units.plot(ax=axs[0], column="lst_c", cmap="inferno", legend=True, missing_kwds={"color": "#dddddd"})
    axs[0].set_title("Summer land-surface temp (°C)")
    units.plot(ax=axs[1], column="access_score", cmap="RdYlGn", legend=True, missing_kwds={"color": "#dddddd"})
    axs[1].set_title("Amenity access score")
    units.assign(c=units["class"].map({"Hot + low amenities": 3, "Hot": 2, "Low amenities": 1, "OK": 0})).plot(
        ax=axs[2], column="c", cmap="RdYlBu_r", missing_kwds={"color": "#dddddd"}, legend=False)
    axs[2].set_title("Red = hot + low amenities")
    for a in axs:
        a.set_axis_off()
    plt.tight_layout()
    plt.savefig(fname, dpi=150)
    plt.close(fig)
