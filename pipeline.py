"""End-to-end orchestration (notebook Steps 4 → 13)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import amenities, dashboard, heat, indices, maps, places, units as units_mod
from .config import Config
from .context import Ctx
from .osm import configure as configure_osm


@dataclass
class Result:
    out_dir: Path
    files: list[str]
    summary: dict
    ctx: Ctx


def run_pipeline(cfg: Config, log: Callable[[str], None] | None = None,
                 progress: Callable[[int, str], None] | None = None) -> Result:
    cfg.validate()
    log = log or print
    progress = progress or (lambda pct, msg: None)
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    configure_osm()
    ctx = Ctx(cfg, log)

    progress(3, "Reading study area & analysis units")
    units_mod.build_units(ctx)
    ctx.has_pop = "pop" in ctx.units and float(ctx.units["pop"].sum()) > 0

    progress(10, "Land-surface temperature (Landsat)")
    heat.attach_heat(ctx)

    progress(35, "Built-up areas & place names")
    places.attach_built_up(ctx)
    places.attach_place_names(ctx)

    progress(50, "Amenities & access score")
    am = amenities.build_access_score(ctx)

    progress(58, "Flagging hot & under-served places")
    indices.flag_priority(ctx)
    by_place = indices.results_tables(ctx)

    progress(62, "Greenery (NDVI)")
    has_ndvi = heat.attach_ndvi(ctx)

    progress(72, "Points of interest, roads & indices")
    amenities.build_pois(ctx)
    cnt = indices.attach_poi_counts(ctx)
    roads = indices.attach_roads(ctx)
    real = indices.attach_indices(ctx, cnt, roads)
    ctx.units["pop"] = ctx.units["pop"].fillna(0)

    progress(80, "Writing maps & tables")
    files: list[str] = []
    units = ctx.units
    gpkg = out / "rishikesh_results.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    units.to_file(gpkg, layer="units", driver="GPKG")
    am[["category", "geometry"]].to_file(gpkg, layer="amenities_used", driver="GPKG")
    units.drop(columns="geometry").to_csv(out / "rishikesh_results.csv", index=False)
    by_place.to_csv(out / "rishikesh_by_place.csv")
    files += ["rishikesh_results.gpkg", "rishikesh_results.csv", "rishikesh_by_place.csv"]
    files += maps.make_all_maps(ctx, out)
    maps.overview_png(ctx, str(out / "overview.png"))
    files.append("overview.png")

    progress(92, "Building dashboard")
    fragment, summary = dashboard.build_dashboard(ctx, cnt, roads, real, has_ndvi)
    (out / "Rishikesh_Dashboard.html").write_text(dashboard.wrap_standalone(fragment), encoding="utf-8")
    files.insert(0, "Rishikesh_Dashboard.html")
    summary.update(has_ndvi=has_ndvi, language=cfg.language, units=len(units),
                   built_units=int(units.is_built.sum()), config=cfg.to_dict())
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    files.append("summary.json")

    progress(100, "Done")
    log(f"✅ Done. {len(files)} files written to {out.resolve()}")
    return Result(out_dir=out, files=files, summary=summary, ctx=ctx)
