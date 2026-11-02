"""Step 7 (access score) + the points-of-interest layer used by the dashboard."""
from __future__ import annotations

import re

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .context import Ctx
from .io import read_layer
from .osm import osm_features

# ---------------------------------------------------------------- access-score categories
CATS = {
    "health":           {"amenity": ["hospital", "clinic", "doctors", "pharmacy", "dentist"]},
    "education":        {"amenity": ["school", "college", "university", "kindergarten", "library"]},
    "food_market":      {"amenity": ["marketplace", "restaurant", "cafe", "fast_food"],
                         "shop": ["supermarket", "convenience", "greengrocer", "grocery", "general", "bakery"]},
    "finance_services": {"amenity": ["bank", "atm", "post_office", "police", "townhall"]},
    "transport":        {"amenity": ["bus_station", "taxi"], "highway": ["bus_stop"],
                         "public_transport": ["station", "stop_position", "platform"]},
    "open_space":       {"leisure": ["park", "playground", "garden"]},
    "water_sanitation": {"amenity": ["drinking_water", "toilets"]},
}
KW = [("health", "hospital|clinic|health|pharm|doctor|medic|dispens|dental|chemist"),
      ("education", "school|college|universit|educat|library|kindergarten|anganwadi|institute"),
      ("food_market", "market|shop|store|restaurant|cafe|food|bakery|mall|grocery|bazaar|dhaba|sweet"),
      ("finance_services", "bank|atm|post|police|municipal|govern|fire|panchayat|court"),
      ("transport", "bus|taxi|station|transport|stand|railway|auto"),
      ("open_space", "park|garden|playground|ground|stadium"),
      ("water_sanitation", "water|toilet|sanit|washroom")]

# ---------------------------------------------------------------- dashboard POI kinds
KINDS = {
    "hospital":      r"hospital|clinic|health|dispens|nursing|doctor|chikits|aspatal",
    "pharmacy":      r"pharm|chemist|medicine|medical store",
    "school":        r"school|kindergarten|vidyalaya|anganwadi",
    "college":       r"college|universit|institute|mahavidyalaya",
    "supermarket":   r"supermarket|super market|\bmart\b|mall|grocery|kirana|bazaar|marketplace|\bmarket\b|department_store|convenience",
    "entertainment": r"cinema|theatre|theater|entertain|nightclub|\bclub\b|amusement|museum|water_park|theme_park|arts_centre|events_venue|attraction|viewpoint|rafting|adventure|resort|stadium|\bpark\b|garden|\bghat\b|cafe",
    "bank":          r"\bbank\b|\batm\b",
    "transport":     r"bus_station|bus_stop|\bbus\b|taxi|railway|public_transport|bus stand|bus_stand",
}

OSM_TAGS = {
    "amenity": sorted({v for r in CATS.values() for v in r.get("amenity", [])} |
                      {"hospital", "clinic", "doctors", "pharmacy", "school", "college", "university", "kindergarten",
                       "cinema", "theatre", "nightclub", "arts_centre", "events_venue", "cafe", "marketplace", "bank",
                       "atm", "bus_station", "taxi"}),
    "shop": sorted({v for r in CATS.values() for v in r.get("shop", [])} | {"supermarket", "mall", "department_store"}),
    "leisure": ["park", "playground", "garden", "stadium", "water_park"],
    "tourism": ["attraction", "museum", "theme_park", "viewpoint"],
    "highway": ["bus_stop"],
    "public_transport": ["station", "stop_position", "platform"],
}


# tag values that define a dashboard POI (subset of OSM_TAGS – keeps restaurants etc. out of the POI counts)
POI_OSM_TAGS = {
    "amenity": {"hospital", "clinic", "doctors", "pharmacy", "school", "college", "university", "kindergarten", "cinema",
                "theatre", "nightclub", "arts_centre", "events_venue", "cafe", "marketplace", "bank", "atm",
                "bus_station", "taxi"},
    "shop": {"supermarket", "mall", "department_store", "convenience", "grocery"},
    "leisure": {"park", "garden", "stadium", "water_park"},
    "tourism": {"attraction", "museum", "theme_park", "viewpoint"},
    "highway": {"bus_stop"},
}


def _is_poi_row(df):
    m = pd.Series(False, index=df.index)
    for k, vals in POI_OSM_TAGS.items():
        if k in df.columns:
            m |= df[k].isin(vals)
    return m


def classify(row):
    for cat, rules in CATS.items():
        for k, vals in rules.items():
            v = row.get(k)
            if isinstance(v, str) and v in vals:
                return cat
    return None


def kw_category(txt):
    t = str(txt).lower()
    for cat, pat in KW:
        if re.search(pat, t):
            return cat
    return "other"


def _osm_raw(ctx: Ctx):
    """One cached OSM download shared by the access score and the dashboard POIs."""
    if ctx.osm_error is not None:          # don't hammer Overpass twice when it is down
        raise ctx.osm_error
    if ctx.osm_raw is None:
        try:
            raw = osm_features(ctx.aoi_pad_ll, OSM_TAGS, ctx.cfg.osm_tries).to_crs(ctx.utm)
        except Exception as e:  # noqa: BLE001
            ctx.osm_error = e
            raise
        ctx.osm_raw = raw
        ctx.log(f"Downloaded {len(raw):,} amenity-like features from OpenStreetMap")
    return ctx.osm_raw


def _amenity_layer_name(ctx: Ctx) -> str:
    if ctx.cfg.amenity_layer:
        return ctx.cfg.amenity_layer
    return next((n for n in ctx.lay_types if re.search("amenit|poi", n, re.I)), "")


def _source_wants(ctx: Ctx, which: str) -> bool:
    src = ctx.cfg.amenity_source
    if which == "gpkg":
        return src in ("both", "gpkg")
    return ctx.cfg.use_osm and src in ("both", "osm")


def build_access_score(ctx: Ctx) -> gpd.GeoDataFrame:
    units, cfg = ctx.units, ctx.cfg
    parts = []
    layer = _amenity_layer_name(ctx)

    if layer and _source_wants(ctx, "gpkg"):
        a = read_layer(ctx, layer)
        a["geometry"] = a.geometry.representative_point()
        ctx.log(f"Your amenity layer '{layer}': {len(a)} features; columns = {[c for c in a.columns if c != 'geometry']}")
        if cfg.amenity_type_column and cfg.amenity_type_column in a.columns:
            txt_cols = [cfg.amenity_type_column]
        else:
            txt_cols = [c for c in a.columns if c.lower() in
                        ("amenity", "type", "fclass", "category", "class", "featuretype", "amenity_type",
                         "feature", "shop", "name", "name_en")]
        ctx.log(f"Using these columns to work out amenity types: {txt_cols or 'none found → single generic category'}")
        a["category"] = a[txt_cols].astype(str).agg(" ".join, axis=1).map(kw_category) if txt_cols else "amenity"
        parts.append(a[["category", "geometry"]])

    if _source_wants(ctx, "osm") or (not parts and cfg.use_osm):
        try:
            raw = _osm_raw(ctx).copy()
            raw["category"] = raw.apply(classify, axis=1)
            raw = raw[raw.category.notnull()]
            parts.append(gpd.GeoDataFrame({"category": raw.category.values},
                                          geometry=raw.geometry.representative_point().values, crs=ctx.utm))
        except Exception as e:  # noqa: BLE001
            ctx.log(f"⚠️ OpenStreetMap amenities unavailable right now ({str(e)[:80]}) – continuing without them.")

    if not parts:
        raise RuntimeError("No amenities available – add an amenity layer to your GeoPackage or retry when OSM is reachable.")
    am = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=ctx.utm)
    cats = sorted(set(am.category) - {"other"})
    if not cats:
        am["category"] = "amenity"
        cats = ["amenity"]
    ctx.log("Amenities by type:\n" + am.category.value_counts().to_string())

    xy = np.c_[units.geometry.centroid.x, units.geometry.centroid.y]
    all_tree = cKDTree(np.c_[am.geometry.x, am.geometry.y])
    units["n_amen_walk"] = all_tree.query_ball_point(xy, cfg.walk_radius_m, return_length=True)
    units["d_nearest_amenity_m"] = all_tree.query(xy)[0].round(0)

    cov = np.zeros((len(units), len(cats)), dtype=bool)
    prox = np.zeros((len(units), len(cats)))
    for j, c in enumerate(cats):
        pts = am[am.category == c]
        d = cKDTree(np.c_[pts.geometry.x, pts.geometry.y]).query(xy)[0]
        units[f"d_{c}_m"] = d.round(0)
        cov[:, j] = d <= cfg.walk_radius_m
        prox[:, j] = np.exp(-d / cfg.walk_radius_m)

    units["coverage"] = cov.mean(axis=1)
    units["missing"] = [", ".join(cats[j] for j in np.where(~cov[i])[0]) or "none" for i in range(len(units))]
    # 50 % share of amenity types within walking distance + 50 % smooth distance-decay closeness
    units["access_score"] = (100 * (0.5 * units.coverage + 0.5 * prox.mean(axis=1))).round(1)
    ctx.log(f"Access score = 50% type coverage within {cfg.walk_radius_m} m + 50% distance-decay closeness")
    ctx.log(units.access_score.describe().round(1).to_string())
    ctx.am = am
    return am


# ------------------------------------------------------------------ dashboard POIs
def _with_text(df, cols):
    cols = [c for c in cols if c in df.columns]
    t = df[cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower() if cols else pd.Series("", index=df.index)
    return gpd.GeoDataFrame({"txt": t.values}, geometry=df.geometry.values, crs=df.crs)


def build_pois(ctx: Ctx) -> gpd.GeoDataFrame:
    """Points of interest (hospital, school, market, …) from your GeoPackage and/or OSM, de-duplicated."""
    cfg = ctx.cfg
    sources = []
    layer = _amenity_layer_name(ctx)
    if layer and _source_wants(ctx, "gpkg"):
        a = read_layer(ctx, layer)
        a["geometry"] = a.geometry.representative_point()
        cols = [c for c in a.columns if c != "geometry" and
                re.search("type|categ|class|name|amen|shop|leisure|tourism|fclass|feature|desc", c, re.I)]
        g = _with_text(a, cols)
        g["src"] = "gpkg"
        sources.append(g)
    if _source_wants(ctx, "osm") or (not sources and cfg.use_osm):
        try:
            o = _osm_raw(ctx)
            o = o[_is_poi_row(o).values].copy()
            o["geometry"] = o.geometry.representative_point()
            g = _with_text(o, ["amenity", "shop", "leisure", "tourism", "highway", "name"])
            g["src"] = "osm"
            sources.append(g)
        except Exception as e:  # noqa: BLE001
            ctx.log(f"⚠️ OpenStreetMap unavailable – dashboard uses your GeoPackage amenities only. {str(e)[:80]}")
    if not sources:
        raise RuntimeError("No amenity data found – add an amenity layer to your GeoPackage.")

    allp = pd.concat(sources, ignore_index=True)
    frames = [allp[allp.txt.str.contains(pat, regex=True)][["src", "geometry"]].assign(kind=k) for k, pat in KINDS.items()]
    pois = pd.concat(frames, ignore_index=True)
    pois = gpd.GeoDataFrame(pois, geometry="geometry", crs=ctx.utm)

    keep = np.ones(len(pois), bool)                 # drop OSM points that duplicate your own (within 40 m)
    for k in KINDS:
        gk = pois[(pois.kind == k) & (pois.src == "gpkg")]
        ok = pois[(pois.kind == k) & (pois.src == "osm")]
        if len(gk) and len(ok):
            d = cKDTree(np.c_[gk.geometry.x, gk.geometry.y]).query(np.c_[ok.geometry.x, ok.geometry.y])[0]
            keep[pois.index.get_indexer(ok.index[d < 40])] = False
    pois = pois[keep].reset_index(drop=True)
    ctx.pois = pois
    return pois
