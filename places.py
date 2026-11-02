"""Step 6 – built-up areas & place names."""
from __future__ import annotations

import re

import geopandas as gpd
import numpy as np

from .context import Ctx
from .io import read_layer
from .osm import osm_features


def attach_built_up(ctx: Ctx) -> None:
    units, cfg = ctx.units, ctx.cfg
    bld = None
    bl = next((n for n in ctx.lay_types if re.search("build", n, re.I) and "Polygon" in ctx.lay_types[n]), "")
    if bl:
        bld = read_layer(ctx, bl)
        ctx.log(f"Using your buildings layer '{bl}' ({len(bld):,} buildings)")
    elif cfg.use_osm:
        try:
            bld = osm_features(ctx.aoi_ll, {"building": True}, cfg.osm_tries)
            bld = bld[bld.geom_type.isin(["Polygon", "MultiPolygon"])].to_crs(ctx.utm)
            ctx.log(f"{len(bld):,} OSM buildings loaded")
        except Exception as e:  # noqa: BLE001
            ctx.log(f"⚠️ No buildings layer and OSM unavailable – all units treated as built-up. {str(e)[:120]}")
    else:
        ctx.log("No buildings layer and OSM disabled – all units treated as built-up.")
    ctx.bld = bld

    units["built_share"] = np.nan
    if bld is not None and len(bld):
        b = gpd.GeoDataFrame({"a": bld.area.values}, geometry=bld.centroid.values, crs=ctx.utm)
        j = gpd.sjoin(b, units[["uid", "geometry"]], predicate="within")
        share = j.groupby("uid").a.sum() / units.set_index("uid").geometry.area
        units["built_share"] = units.uid.map(share).fillna(0)
        units["n_buildings"] = units.uid.map(j.groupby("uid").size()).fillna(0).astype(int)
    units["is_built"] = units.built_share.fillna(1) >= cfg.built_min_share
    ctx.log(units.is_built.value_counts().rename({True: "built-up units", False: "non-built (forest/river/etc.)"}).to_string())


def attach_place_names(ctx: Ctx) -> None:
    """your names → OSM places → nearest named road → 2 km 'Zone' blocks."""
    units, cfg = ctx.units, ctx.cfg
    cent = units.copy()
    cent["geometry"] = units.geometry.centroid
    units["place"] = units[ctx.name_col].astype(str) if ctx.name_col else None

    if units["place"].isnull().any() and cfg.use_osm:
        try:
            pl = osm_features(ctx.aoi_pad_ll, {"place": ["suburb", "neighbourhood", "village", "hamlet", "town",
                                                          "quarter", "locality"]}, cfg.osm_tries)
            pl = pl[pl["name"].notnull()].to_crs(ctx.utm)
            pl = gpd.GeoDataFrame({"pname": pl["name"].values}, geometry=pl.geometry.centroid.values, crs=ctx.utm)
            jn = gpd.sjoin_nearest(cent[["uid", "geometry"]], pl, how="left", max_distance=2500).drop_duplicates("uid")
            units["place"] = units.place.fillna(units.uid.map(jn.set_index("uid").pname))
            ctx.log(f"{pl.pname.nunique()} OSM place names used")
        except Exception as e:  # noqa: BLE001
            ctx.log(f"⚠️ OSM place names unavailable. {str(e)[:100]}")

    if units["place"].isnull().any():
        rl = next((n for n in ctx.lay_types if re.search("road", n, re.I) and "Line" in ctx.lay_types[n]), "")
        if rl:
            rd = read_layer(ctx, rl)
            rn = next((c for c in rd.columns if c.lower() in ("name", "name_en", "road_name", "fclass_name")), None)
            if rn:
                rd = rd[rd[rn].notnull()][[rn, "geometry"]]
                jn = gpd.sjoin_nearest(cent[["uid", "geometry"]], rd, how="left", max_distance=400).drop_duplicates("uid")
                near = units.uid.map(jn.set_index("uid")[rn])
                label = near.map(lambda v: f"Near {v}" if isinstance(v, str) and v.strip() else np.nan)
                units["place"] = units.place.fillna(label)
                ctx.log(f"Used named roads from '{rl}' to label places")

    if units["place"].isnull().any():
        mnx, mny = ctx.aoi.bounds[0], ctx.aoi.bounds[1]
        bx = ((cent.geometry.x - mnx) // 2000).astype(int)
        by = ((cent.geometry.y - mny) // 2000).astype(int)
        units["place"] = units.place.fillna("Zone " + by.map(lambda v: chr(65 + v % 26)) + bx.astype(str))
        ctx.log("Remaining units labelled by 2 km 'Zone' blocks")
