"""Steps 8–9 (hot / under-served / priority flags, tables) and the dashboard indices
(education, health, economy, mobility)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.ops import unary_union

from .amenities import KINDS
from .context import Ctx
from .io import read_layer


# ------------------------------------------------------------------ Step 8
def flag_priority(ctx: Ctx) -> None:
    units, cfg = ctx.units, ctx.cfg
    built = units[units.is_built & units.lst_c.notnull()]
    if built.empty:
        raise RuntimeError("No built-up units with a temperature value – nothing to analyse.")
    hot_thr = np.nanpercentile(built.lst_c, cfg.hot_percentile)
    low_thr = np.nanpercentile(built.access_score, cfg.low_amenity_percentile)
    ref = np.nanmedian(built.lst_c)

    ok = units.is_built & units.lst_c.notnull()
    units["lst_anom_c"] = (units.lst_c - ref).round(1)
    units["hot"] = ok & (units.lst_c >= hot_thr)
    units["low_amenity"] = units.is_built & (units.access_score <= low_thr)
    units["priority"] = units.hot & units.low_amenity
    units["class"] = np.select(
        [units.priority, units.hot, units.low_amenity, units.is_built],
        ["Hot + low amenities", "Hot", "Low amenities", "OK"], default="Non-built")
    units["lst_c"] = units.lst_c.round(1)

    ctx.log(f"Hot threshold (top {100 - cfg.hot_percentile}%): ≥ {hot_thr:.1f} °C | city median: {ref:.1f} °C")
    ctx.log(f"Low-amenity threshold (bottom {cfg.low_amenity_percentile}%): access score ≤ {low_thr:.1f}")
    ctx.log(units["class"].value_counts().to_string())
    if ctx.has_pop:
        tot = units["pop"].sum()
        for lab, msk in [("living in hot units", units.hot), ("living in low-amenity units", units.low_amenity),
                         ("living in hot AND low-amenity units", units.priority)]:
            p = units.loc[msk, "pop"].sum()
            ctx.log(f"  {p:>10,.0f} people ({100 * p / tot:.1f}%) {lab}")


# ------------------------------------------------------------------ Step 9
def results_tables(ctx: Ctx) -> pd.DataFrame:
    units = ctx.units
    built = units[units.is_built & units.lst_c.notnull()]
    agg = dict(units=("uid", "count"), mean_lst_c=("lst_c", "mean"), max_lst_c=("lst_c", "max"),
               hot_units=("hot", "sum"), mean_access=("access_score", "mean"),
               low_amenity_units=("low_amenity", "sum"), priority_units=("priority", "sum"))
    by_place = built.groupby("place").agg(**agg)
    if ctx.has_pop:
        by_place["population"] = built.groupby("place")["pop"].sum()
        by_place["pop_hot"] = built[built.hot].groupby("place")["pop"].sum()
        by_place["pop_low_amenity"] = built[built.low_amenity].groupby("place")["pop"].sum()
        by_place["pop_priority"] = built[built.priority].groupby("place")["pop"].sum()
        by_place = by_place.fillna(0)
    by_place = by_place.round(1)
    by_place = by_place[by_place.units >= 2]
    ctx.by_place = by_place
    return by_place


# ------------------------------------------------------------------ dashboard enrichment
def decay(d, scale):
    return np.exp(-np.asarray(d, dtype=float) / scale)


def pct_rank(s, index):
    return pd.Series(np.asarray(s), index=index).rank(pct=True) * 100


def attach_poi_counts(ctx: Ctx) -> dict[str, int]:
    units, pois = ctx.units, ctx.pois
    cnt = {k: int((pois.kind == k).sum()) for k in KINDS}
    ctx.log(f"Points of interest found: {cnt}")
    xy = np.c_[units.geometry.centroid.x, units.geometry.centroid.y]
    for k in KINDS:
        p = pois[pois.kind == k]
        if len(p):
            t = cKDTree(np.c_[p.geometry.x, p.geometry.y])
            units[f"cnt_{k}"] = t.query_ball_point(xy, ctx.cfg.walk_radius_m, return_length=True)
            units[f"dist_{k}"] = t.query(xy)[0]
        else:
            units[f"cnt_{k}"] = 0
            units[f"dist_{k}"] = 1e5
    if "pop" not in units:
        units["pop"] = 0.0
    units["pop"] = units["pop"].fillna(0)
    return cnt


@dataclass
class RoadInfo:
    layer: str = ""
    major_dist: pd.Series | None = None
    total_km: float = 0.0


def attach_roads(ctx: Ctx) -> RoadInfo:
    units = ctx.units
    units["road_km"] = 0.0
    units["road_dens"] = np.nan
    info = RoadInfo(major_dist=pd.Series(np.nan, index=units.index))
    rl = next((nm for nm in ctx.lay_types if re.search("road", nm, re.I) and "Line" in ctx.lay_types[nm]), "")
    if not rl:
        ctx.log("No road layer found in your GeoPackage – mobility uses transport stops only.")
        return info
    try:
        rd = read_layer(ctx, rl)
        inter = gpd.overlay(rd[["geometry"]], units[["uid", "geometry"]], how="intersection", keep_geom_type=True)
        length = inter.geometry.length.groupby(inter["uid"]).sum()
        units["road_km"] = units.uid.map(length).fillna(0) / 1000
        units["road_dens"] = (units.road_km / (units.geometry.area / 1e6)).round(1)
        cc = next((c for c in rd.columns if c.lower() in ("highway", "fclass", "road_type", "roadtype", "type", "class",
                                                           "roadclass", "rd_class", "code")), None)
        if cc:
            mj = rd[cc].astype(str).str.lower().str.contains(
                r"motorway|trunk|primary|secondary|national|\bnh\b|state|\bsh\b|major", regex=True)
            if mj.any():
                info.major_dist = pd.Series(units.geometry.centroid.distance(unary_union(rd[mj].geometry)).values,
                                            index=units.index)
        info.layer = rl
        info.total_km = float(units.road_km.sum())
        ctx.log(f"Roads: {info.total_km:,.0f} km from '{rl}'")
    except Exception as e:  # noqa: BLE001
        ctx.log(f"⚠️ Road analysis failed: {str(e)[:100]}")
        info.layer = ""
    return info


def attach_indices(ctx: Ctx, cnt: dict[str, int], roads: RoadInfo) -> dict[str, bool]:
    units, cfg = ctx.units, ctx.cfg
    idx = units.index
    units["edu_idx"] = (100 * (0.6 * decay(units.dist_school, 1000) + 0.4 * decay(units.dist_college, 2000))).round(1)
    units["health_idx"] = (100 * (0.6 * decay(units.dist_hospital, 2000) + 0.4 * decay(units.dist_pharmacy, 1000))).round(1)

    comps, weights = [], []
    if units.built_share.notna().any():
        comps.append(pct_rank(units.built_share.fillna(0), idx)); weights.append(0.3)
    if ctx.bld is not None and len(ctx.bld):
        try:
            b2 = gpd.GeoDataFrame({"a": ctx.bld.area.values}, geometry=ctx.bld.centroid.values, crs=ctx.utm)
            jj = gpd.sjoin(b2, units[["uid", "geometry"]], predicate="within")
            comps.append(pct_rank(units.uid.map(jj.groupby("uid").a.mean()).fillna(0), idx)); weights.append(0.2)
        except Exception:  # noqa: BLE001
            pass
    comps.append(pct_rank(units[["cnt_supermarket", "cnt_entertainment", "cnt_bank"]].sum(axis=1), idx)); weights.append(0.3)
    if roads.layer:
        comps.append(pct_rank(units.road_dens.fillna(0), idx)); weights.append(0.2)
    units["econ_idx"] = (sum(c * w for c, w in zip(comps, weights)) / sum(weights)).round(1)

    comps, weights = [], []
    if roads.layer:
        comps.append(pct_rank(units.road_dens.fillna(0), idx)); weights.append(0.4)
    if roads.major_dist is not None and roads.major_dist.notna().any():
        comps.append(pd.Series(100 * decay(roads.major_dist.fillna(1e5), 1500), index=idx)); weights.append(0.3)
    if cnt["transport"]:
        comps.append(pd.Series(100 * decay(units.dist_transport, 800), index=idx)); weights.append(0.3)
    units["mob_idx"] = (sum(c * w for c, w in zip(comps, weights)) / sum(weights)).round(1) if weights else np.nan

    def real_col(name, target):
        if name and name in units.columns:
            units[target] = pd.to_numeric(units[name], errors="coerce")
            return True
        return False

    return dict(edu=real_col(cfg.literacy_column, "edu_idx"), health=real_col(cfg.health_column, "health_idx"),
                econ=real_col(cfg.income_column, "econ_idx"), mob=real_col(cfg.traffic_column, "mob_idx"))
