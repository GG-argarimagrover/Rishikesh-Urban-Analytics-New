"""Step 5 – Land-surface temperature (and NDVI) from Landsat 8/9 via Microsoft Planetary Computer."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from affine import Affine
from rasterio import features

from .context import Ctx


def _search_items(ctx: Ctx):
    import planetary_computer as pc
    from pystac_client import Client
    cfg = ctx.cfg
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
    items = {}
    for y in [s.strip() for s in cfg.years.split(",") if s.strip()]:
        search = cat.search(
            collections=["landsat-c2-l2"], bbox=ctx.bbox,
            datetime=f"{y}-{cfg.season_start}/{y}-{cfg.season_end}",
            query={"eo:cloud_cover": {"lt": cfg.max_cloud}, "platform": {"in": ["landsat-8", "landsat-9"]}})
        for it in search.items():
            items[it.id] = it
    return list(items.values())


def _load(ctx: Ctx, items, bands):
    import odc.stac
    return odc.stac.load(items, bands=bands, bbox=ctx.bbox, crs=ctx.utm, resolution=30,
                         groupby="solar_day", chunks={}, resampling="nearest").compute()


def compute_lst(ctx: Ctx):
    items = _search_items(ctx)
    ctx.log(f"Found {len(items)} Landsat scenes with < {ctx.cfg.max_cloud}% cloud")
    if not items:
        raise RuntimeError("No Landsat scenes found – try a wider season, more years, or higher max_cloud.")
    ds = _load(ctx, items, ["lwir11", "qa_pixel"])
    raw = ds.lwir11.astype("float32")
    lst = raw.where(raw > 0) * 0.00341802 + 149.0 - 273.15          # Kelvin → °C
    qa = ds.qa_pixel.fillna(1).astype("uint16")
    bad = ((qa & 0b11110) != 0) | ((qa & 1) != 0)                    # cloud, cirrus, shadow, fill
    lst = lst.where(~bad & (lst > 5) & (lst < 75))
    nobs = lst.notnull().sum("time")
    med = lst.median("time", skipna=True).where(nobs >= 2)
    ctx.log(f"Used {ds.sizes['time']} clear-sky dates → median summer LST")
    return med.transpose("y", "x")


def compute_ndvi(ctx: Ctx):
    items = _search_items(ctx)
    ds = _load(ctx, items, ["red", "nir08", "qa_pixel"])
    r = ds.red.astype("float32")
    nr = ds.nir08.astype("float32")
    r = r.where(r > 0) * 0.0000275 - 0.2
    nr = nr.where(nr > 0) * 0.0000275 - 0.2
    nd = (nr - r) / (nr + r)
    qa = ds.qa_pixel.fillna(1).astype("uint16")
    nd = nd.where((((qa & 0b11110) == 0) & ((qa & 1) == 0)) & (nd > -0.2) & (nd < 1))
    return nd.median("time", skipna=True).transpose("y", "x")


def zonal_mean(da, units: gpd.GeoDataFrame, min_px: int = 3) -> pd.Series:
    xs, ys = da.x.values, da.y.values
    dx, dy = xs[1] - xs[0], ys[1] - ys[0]
    tr = Affine(dx, 0, xs[0] - dx / 2, 0, dy, ys[0] - dy / 2)
    ids = features.rasterize(((g, int(u)) for g, u in zip(units.geometry, units.uid)),
                             out_shape=da.shape, transform=tr, fill=0, dtype="int32")
    vals = da.values.astype("float64")
    ok = (ids > 0) & np.isfinite(vals)
    n = int(units.uid.max()) + 1
    s = np.bincount(ids[ok], weights=vals[ok], minlength=n)
    c = np.bincount(ids[ok], minlength=n)
    out = np.where(c >= min_px, s / np.maximum(c, 1), np.nan)
    return pd.Series(out[units.uid.values], index=units.index)


def attach_heat(ctx: Ctx):
    """Adds `lst_c` to units. Returns the raster (or None when a column was supplied)."""
    units, cfg = ctx.units, ctx.cfg
    if cfg.heat_column and cfg.heat_column in units.columns:
        units["lst_c"] = pd.to_numeric(units[cfg.heat_column], errors="coerce")
        ctx.log(f"Using temperature column '{cfg.heat_column}' from your GeoPackage")
        raster = None
    else:
        if cfg.heat_column:
            ctx.log(f"⚠️ heat column '{cfg.heat_column}' not found in the units layer – computing from Landsat instead.")
        raster = compute_lst(ctx)
        units["lst_c"] = zonal_mean(raster, units)
    if units["lst_c"].notna().sum() == 0:
        raise RuntimeError("Temperature is empty for every unit – check the study area / heat column.")
    ctx.log(units.lst_c.describe().round(1).to_string())
    return raster


def attach_ndvi(ctx: Ctx) -> bool:
    units = ctx.units
    units["ndvi"] = np.nan
    if not ctx.cfg.use_ndvi:
        return False
    try:
        units["ndvi"] = zonal_mean(compute_ndvi(ctx), units).round(2)
        ctx.log(f"Greenery (NDVI) computed: mean {units.ndvi.mean():.2f}")
    except Exception as e:  # noqa: BLE001
        ctx.log(f"⚠️ Could not compute vegetation (NDVI): {str(e)[:100]}")
    return bool(units.ndvi.notna().any())
