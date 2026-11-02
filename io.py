"""GeoPackage helpers."""
from __future__ import annotations

import geopandas as gpd
import pyogrio

from .context import Ctx


def list_layers(gpkg: str) -> dict[str, str]:
    return {str(n): (str(t) if t is not None else "") for n, t in pyogrio.list_layers(gpkg)}


def describe_layers(ctx: Ctx) -> None:
    ctx.log(f"Layers in {ctx.cfg.gpkg}:")
    for n, t in ctx.lay_types.items():
        info = pyogrio.read_info(ctx.cfg.gpkg, layer=n)
        ctx.log(f" • {n:30s} {t:15s} {info['features']:>8} features | CRS: {info['crs']}")
        ctx.log(f"     columns: {list(info['fields'])[:15]}")


def read_layer(ctx: Ctx, name: str) -> gpd.GeoDataFrame:
    g = gpd.read_file(ctx.cfg.gpkg, layer=name)
    if g.crs is None:
        ctx.log(f"⚠️ '{name}' has no CRS – assuming EPSG:4326")
        g = g.set_crs(4326)
    g = g.to_crs(ctx.utm)
    g = g[g.geometry.notnull() & ~g.geometry.is_empty].copy()
    poly = g.geom_type.isin(["Polygon", "MultiPolygon"])
    g.loc[poly, "geometry"] = g.loc[poly, "geometry"].buffer(0)
    return g


def layer_fields(ctx: Ctx, name: str) -> list[str]:
    return [str(f) for f in pyogrio.read_info(ctx.cfg.gpkg, layer=name)["fields"]]
