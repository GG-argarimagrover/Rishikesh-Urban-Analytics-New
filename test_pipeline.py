import json
import re

import geopandas as gpd
import pytest

from rishikesh_urban.config import Config
from rishikesh_urban.pipeline import run_pipeline


def offline_cfg(gpkg, out, **kw):
    base = dict(gpkg=gpkg, out_dir=str(out), heat_column="heat_c", use_osm=False, use_ndvi=False, language="English")
    base.update(kw)
    return Config(**base)


def payload_of(html):
    return json.loads(re.search(r"const P = (.*?);\n", html, re.S).group(1))


def test_full_run_english(demo_gpkg, tmp_path):
    res = run_pipeline(offline_cfg(demo_gpkg, tmp_path / "o"), log=lambda m: None)
    for f in ["Rishikesh_Dashboard.html", "rishikesh_results.gpkg", "rishikesh_results.csv", "rishikesh_by_place.csv",
              "map_1_heat.html", "map_2_low_amenities.html", "map_3_priority.html", "map_4_population.html",
              "overview.png", "summary.json"]:
        assert (tmp_path / "o" / f).stat().st_size > 0, f
    units = gpd.read_file(tmp_path / "o" / "rishikesh_results.gpkg", layer="units")
    assert {"lst_c", "access_score", "priority", "class", "edu_idx", "health_idx", "econ_idx", "mob_idx"} <= set(units.columns)
    assert units.priority.sum() > 0                          # demo data has a deliberate hot + under-served pocket
    assert units.access_score.between(0, 100).all()
    html = (tmp_path / "o" / "Rishikesh_Dashboard.html").read_text(encoding="utf-8")
    P = payload_of(html)
    ids = [s["id"] for s in P["sections"]]
    assert ids == ["overview", "heat", "services", "edu_health", "econ", "mobility", "priority"]   # greenery skipped w/o NDVI
    assert "NaN" not in json.dumps(P) and "Infinity" not in json.dumps(P)
    assert "Heat – where it burns most" in html
    assert res.summary["priority_cells"] == int(units.priority.sum())


def test_hinglish(demo_gpkg, tmp_path):
    run_pipeline(offline_cfg(demo_gpkg, tmp_path / "o", language="Hinglish"), log=lambda m: None)
    html = (tmp_path / "o" / "Rishikesh_Dashboard.html").read_text(encoding="utf-8")
    assert "Garmi – kahan sabse zyada" in html and "Heat – where it burns most" not in html


def test_without_population_and_roads(demo_gpkg, tmp_path):
    g = gpd.read_file(demo_gpkg, layer="population_grid").drop(columns="pop_sum")
    amen = gpd.read_file(demo_gpkg, layer="amenities")
    bld = gpd.read_file(demo_gpkg, layer="buildings")
    p = tmp_path / "nopop.gpkg"
    g.to_file(p, layer="population_grid", driver="GPKG")
    amen.to_file(p, layer="amenities", driver="GPKG")
    bld.to_file(p, layer="buildings", driver="GPKG")
    run_pipeline(offline_cfg(str(p), tmp_path / "o", units_layer="population_grid"), log=lambda m: None)
    P = payload_of((tmp_path / "o" / "Rishikesh_Dashboard.html").read_text(encoding="utf-8"))
    assert "pop" not in P["sections"][0]["layers"]          # overview map falls back to heat
    assert P["sections"][0]["layers"] == ["lst"]
    assert not (tmp_path / "o" / "map_4_population.html").exists()


def test_real_columns_override_proxies(demo_gpkg, tmp_path):
    cfg = offline_cfg(demo_gpkg, tmp_path / "o", income_column="heat_c")
    res = run_pipeline(cfg, log=lambda m: None)
    html = (tmp_path / "o" / "Rishikesh_Dashboard.html").read_text(encoding="utf-8")
    assert "Income index" in html and "Economic-activity proxy" not in html
    assert (res.ctx.units.econ_idx == res.ctx.units.heat_c).all()


def test_heat_failure_propagates(demo_gpkg, tmp_path, monkeypatch):
    from rishikesh_urban import heat
    monkeypatch.setattr(heat, "compute_lst", lambda ctx: (_ for _ in ()).throw(RuntimeError("no scenes")))
    with pytest.raises(RuntimeError, match="no scenes"):
        run_pipeline(offline_cfg(demo_gpkg, tmp_path / "o", heat_column=""), log=lambda m: None)


def test_osm_down_degrades_gracefully(demo_gpkg, tmp_path, monkeypatch):
    """GeoPackage amenities still work when Overpass is unreachable, and OSM is only attempted once."""
    from rishikesh_urban import amenities
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise ConnectionError("overpass down")

    monkeypatch.setattr(amenities, "osm_features", boom)
    from rishikesh_urban import places
    monkeypatch.setattr(places, "osm_features", boom)
    logs = []
    cfg = offline_cfg(demo_gpkg, tmp_path / "o", use_osm=True, amenity_source="both")
    run_pipeline(cfg, log=logs.append)
    assert (tmp_path / "o" / "Rishikesh_Dashboard.html").exists()
    assert any("OpenStreetMap" in m and "unavailable" in m for m in logs)
    assert len(calls) == 1                               # amenities: one attempt, cached failure for POIs (buildings/names from gpkg)


def test_osm_only_mode_with_mocked_network(tmp_path, monkeypatch):
    """No GeoPackage: 10 km circle, OSM buildings/places/amenities + a Landsat-like raster (all mocked)."""
    import numpy as np
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import Point, box
    from rishikesh_urban import amenities, heat, places

    rng = np.random.default_rng(0)
    lon0, lat0 = 78.2676, 30.0869

    def fake_osm(poly, tags, tries=2):
        if "building" in tags:
            xs, ys = lon0 + rng.normal(0, .03, 3000), lat0 + rng.normal(0, .03, 3000)
            return gpd.GeoDataFrame({"building": "yes"}, geometry=[box(x, y, x + .0001, y + .0001) for x, y in zip(xs, ys)], crs=4326)
        if "place" in tags:
            return gpd.GeoDataFrame({"name": ["Tapovan", "Muni Ki Reti"], "place": "suburb"},
                                    geometry=[Point(lon0 - .02, lat0), Point(lon0 + .02, lat0)], crs=4326)
        kinds = ["hospital", "school", "pharmacy", "bank", "bus_stop", "marketplace", "college"]
        pts = [Point(lon0 + rng.normal(0, .03), lat0 + rng.normal(0, .03)) for _ in range(120)]
        return gpd.GeoDataFrame({"amenity": [kinds[i % 6] if kinds[i % 6] != "bus_stop" else None for i in range(120)],
                                 "highway": [("bus_stop" if i % 6 == 4 else None) for i in range(120)],
                                 "name": [f"Place {i}" for i in range(120)]}, geometry=pts, crs=4326)

    def fake_lst(ctx):
        minx, miny, maxx, maxy = ctx.aoi.bounds
        xs = np.arange(minx, maxx, 30.0); ys = np.arange(maxy, miny, -30.0)
        X, Y = np.meshgrid(xs, ys)
        cx, cy = ctx.aoi.centroid.x, ctx.aoi.centroid.y
        v = 33 + 7 * np.exp(-np.hypot(X - cx, Y - cy) / 4000)
        return xr.DataArray(v, coords={"y": ys, "x": xs}, dims=("y", "x"))

    for mod in (places, amenities):
        monkeypatch.setattr(mod, "osm_features", fake_osm)
    monkeypatch.setattr(heat, "compute_lst", fake_lst)
    monkeypatch.setattr(heat, "compute_ndvi", lambda ctx: fake_lst(ctx) * 0 + 0.3)

    cfg = Config(gpkg="", out_dir=str(tmp_path / "o"), language="English", use_osm=True, use_ndvi=True)
    res = run_pipeline(cfg, log=lambda m: None)
    P = payload_of((tmp_path / "o" / "Rishikesh_Dashboard.html").read_text(encoding="utf-8"))
    ids = [s["id"] for s in P["sections"]]
    assert "green" in ids and ids[0] == "overview"
    assert res.summary["population"] is None                    # no population without a ward layer
    assert set(res.ctx.units.place.dropna()) & {"Tapovan", "Muni Ki Reti"}
    assert res.ctx.units.lst_c.notna().sum() > 100
