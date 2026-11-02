"""Synthetic demo GeoPackage so the app can be tried without any real data.

⚠️ EVERYTHING in this file is made up (names, population, temperature, amenities). It only exists to
show the layer structure the pipeline expects. Replace it with your own data for real analysis.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point, box

UTM = "EPSG:32644"
CENTRE = (78.2676, 30.0869)

AMENITIES = [  # (amenity tag, name prefix, count, centre-bias km, extra tag)
    ("hospital", "Demo Hospital", 4, 2.0), ("clinic", "Demo Clinic", 6, 2.5), ("pharmacy", "Demo Pharmacy", 12, 2.5),
    ("school", "Demo School", 16, 3.0), ("college", "Demo College", 3, 2.0), ("marketplace", "Demo Market", 4, 1.5),
    ("supermarket", "Demo Super Market", 5, 2.0), ("bank", "Demo Bank", 8, 1.8), ("atm", "Demo ATM", 8, 2.0),
    ("cafe", "Demo Cafe", 14, 1.5), ("park", "Demo Park", 5, 3.0), ("viewpoint", "Demo Viewpoint", 3, 3.5),
    ("attraction", "Demo Ghat", 4, 1.5), ("bus_stop", "Demo Bus Stop", 14, 3.0), ("drinking_water", "Demo Water Point", 6, 2.5),
    ("toilets", "Demo Toilets", 6, 2.5), ("post_office", "Demo Post Office", 2, 2.0), ("police", "Demo Police Post", 2, 2.0),
]


def make_sample(path: str = "data/sample/demo_city.gpkg", seed: int = 7) -> str:
    rng = np.random.default_rng(seed)
    c = gpd.GeoSeries([Point(*CENTRE)], crs=4326).to_crs(UTM).iloc[0]
    cx, cy = c.x, c.y
    R = 5500.0
    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if Path(path).exists():
        Path(path).unlink()

    def write(gdf, layer):
        gdf.set_crs(UTM).to_crs(4326).to_file(path, layer=layer, driver="GPKG")

    # boundary
    write(gpd.GeoDataFrame({"name": ["Demo study area"]}, geometry=[c.buffer(R, 64)]), "boundary")

    # river = a diagonal band; hills = east side
    def river_dist(x, y):
        return abs((y - cy) - 0.35 * (x - cx) + 600) / np.hypot(1, 0.35)

    # a dense, very hot neighbourhood with almost no services → shows up as a "priority zone"
    px, py = cx + 1300, cy + 900

    g, cells = 500, []
    for x in np.arange(cx - R, cx + R, g):
        for y in np.arange(cy - R, cy + R, g):
            cell = box(x, y, x + g, y + g)
            mx, my = x + g / 2, y + g / 2
            d = np.hypot(mx - cx, my - cy)
            if d > R:
                continue
            rv = river_dist(mx, my)
            forest = (mx - cx) > 3000 or rv < 250
            pop = 0.0 if forest else max(0.0, 2200 * np.exp(-d / 2300) * rng.uniform(0.6, 1.3))
            in_pocket = np.hypot(mx - px, my - py) < 1100
            if in_pocket and not forest:
                pop = max(pop, 1900 * rng.uniform(0.8, 1.2))
            heat = (33.5 + 6.5 * np.exp(-d / 2600) + rng.normal(0, 0.8) - (3.2 if rv < 450 else 0) - (2.5 if forest else 0)
                    + (3.5 if in_pocket else 0))
            ward = f"Demo Ward {int((my - (cy - R)) // 2000) * 6 + int((mx - (cx - R)) // 2000) + 1:02d}"
            cells.append(dict(name=ward, pop_sum=round(pop), heat_c=round(heat, 2), geometry=cell))
    grid = gpd.GeoDataFrame(cells)
    write(grid, "population_grid")

    # buildings
    bs = []
    for _, r in grid[grid.pop_sum > 0].iterrows():
        k = int(r.pop_sum / 14)
        x0, y0, _, _ = r.geometry.bounds
        for _i in range(min(k, 90)):
            w, h = rng.uniform(8, 22, 2)
            bx, by = x0 + rng.uniform(0, g - w), y0 + rng.uniform(0, g - h)
            bs.append(box(bx, by, bx + w, by + h))
    write(gpd.GeoDataFrame({"building": ["yes"] * len(bs)}, geometry=bs), "buildings")

    # amenities (more of them near the centre → realistic service gaps at the edges)
    pts = []
    for tag, nm, count, spread in AMENITIES:
        for i in range(count):
            r_ = abs(rng.normal(0, spread * 1000))
            a = rng.uniform(0, 2 * np.pi)
            x, y = cx + r_ * np.cos(a), cy + r_ * np.sin(a)
            if np.hypot(x - cx, y - cy) > R - 200 or river_dist(x, y) < 250 or np.hypot(x - px, y - py) < 1500:
                continue
            kind = {"supermarket": "shop"}.get(tag, "amenity")
            pts.append(dict(amenity=tag if kind == "amenity" else "", shop=tag if kind == "shop" else "",
                            name=f"{nm} {i + 1}", geometry=Point(x, y)))
    write(gpd.GeoDataFrame(pts), "amenities")

    # roads
    lines = [dict(name="Demo Highway", highway="primary", geometry=LineString([(cx - R, cy - 900), (cx + R, cy + 800)])),
             dict(name="Demo Ring Road", highway="secondary", geometry=LineString(list(c.buffer(2200, 64).exterior.coords)))]
    for i, off in enumerate(np.arange(-4000, 4001, 800)):
        lines.append(dict(name=f"Demo Street {i + 1}", highway="residential",
                          geometry=LineString([(cx - 4500, cy + off), (cx + 4500, cy + off + rng.uniform(-300, 300))])))
        lines.append(dict(name=f"Demo Lane {i + 1}", highway="residential",
                          geometry=LineString([(cx + off, cy - 4500), (cx + off + rng.uniform(-300, 300), cy + 4500)])))
    write(gpd.GeoDataFrame(lines), "roads")
    return path
