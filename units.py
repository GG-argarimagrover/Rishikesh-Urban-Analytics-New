"""Step 4 – study area & analysis units."""
from __future__ import annotations

import re

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, box
from shapely.ops import unary_union

from .context import Ctx
from .io import layer_fields, list_layers, read_layer

POP_CANDIDATES = ("pop_sum", "population", "pop", "pop_total", "pop_count")


def _circle(ctx: Ctx, radius_km: float):
    c = gpd.GeoSeries([Point(ctx.cfg.centre_lon, ctx.cfg.centre_lat)], crs=4326).to_crs(ctx.utm).iloc[0]
    return c.buffer(radius_km * 1000)


def build_units(ctx: Ctx) -> gpd.GeoDataFrame:
    cfg = ctx.cfg
    poly_layers: list[str] = []
    aoi_layer, units_layer = cfg.aoi_layer, cfg.units_layer

    if cfg.gpkg:
        ctx.lay_types = list_layers(cfg.gpkg)
        poly_layers = [n for n, t in ctx.lay_types.items() if "Polygon" in t]
        if not aoi_layer and poly_layers:
            aoi_layer = next((n for n in poly_layers if re.search("bound|aoi|study|area", n, re.I)), poly_layers[0])
        if aoi_layer:
            aoi_gdf = read_layer(ctx, aoi_layer)
            aoi = unary_union(aoi_gdf.geometry)
            if len(aoi_gdf) > 200:      # e.g. a buildings layer – use its hull as the study area
                aoi = aoi.convex_hull
            ctx.log(f"Study area from layer: {aoi_layer}")
        else:
            aoi = unary_union([box(*read_layer(ctx, n).total_bounds) for n in ctx.lay_types])
            ctx.log("Study area = bounding box of all layers")
    else:
        aoi = _circle(ctx, cfg.fallback_radius_km)
        ctx.log(f"No GeoPackage given → using a {cfg.fallback_radius_km:g} km circle around Rishikesh centre (OpenStreetMap data only)")

    area_km2 = aoi.area / 1e6
    ctx.log(f"Study area: {area_km2:,.0f} km²")
    if area_km2 > cfg.max_area_km2:
        aoi = _circle(ctx, cfg.fallback_radius_km)
        ctx.log(f"⚠️ Area too large → using a {cfg.fallback_radius_km:g} km radius around Rishikesh centre instead.")
    ctx.aoi = aoi

    if cfg.gpkg and not units_layer:            # auto-use a polygon layer that already carries population
        for n in poly_layers:
            flds = [f.lower() for f in layer_fields(ctx, n)]
            if any(f in POP_CANDIDATES for f in flds):
                units_layer = n
                ctx.log(f"Auto-detected analysis units with population: '{n}'")
                break

    if units_layer:
        units = read_layer(ctx, units_layer)
        units = units[units.intersects(aoi)].copy()
        ctx.log(f"Using {len(units)} polygons from '{units_layer}' as analysis units")
    else:
        minx, miny, maxx, maxy = aoi.bounds
        g = cfg.grid_size_m
        cells = [box(x, y, x + g, y + g) for x in np.arange(minx, maxx, g) for y in np.arange(miny, maxy, g)]
        units = gpd.GeoDataFrame(geometry=cells, crs=ctx.utm)
        units = units[units.intersects(aoi)].copy()
        ctx.log(f"Created {len(units)} grid cells of {g} m")

    if units.empty:
        raise ValueError("No analysis units fall inside the study area – check your layers / CRS.")

    units = units.reset_index(drop=True)
    units["uid"] = np.arange(1, len(units) + 1)
    ctx.name_col = next((c for c in units.columns if c.lower() in
                         ("name", "ward", "ward_name", "wardname", "locality", "area", "name_en")), None) if units_layer else None

    pop_col = cfg.pop_column if cfg.pop_column in units.columns else next(
        (c for c in units.columns if c.lower() in POP_CANDIDATES), None)
    if pop_col:
        units["pop"] = pd.to_numeric(units[pop_col], errors="coerce").fillna(0).round(0)
        ctx.log(f"Population column: '{pop_col}' → total {units['pop'].sum():,.0f} people in study units")
    else:
        ctx.log("No population column found – results will not be population-weighted.")

    ctx.aoi_ll = gpd.GeoSeries([aoi], crs=ctx.utm).to_crs(4326).iloc[0]
    ctx.aoi_pad_ll = gpd.GeoSeries([aoi.buffer(1500)], crs=ctx.utm).to_crs(4326).iloc[0]
    ctx.bbox = ctx.aoi_ll.bounds
    ctx.units = units
    return units
