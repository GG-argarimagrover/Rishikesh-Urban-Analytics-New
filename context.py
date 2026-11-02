"""Shared state passed between pipeline stages (replaces the notebook's global variables)."""
from __future__ import annotations

from typing import Callable

import geopandas as gpd

from .config import Config


class Ctx:
    def __init__(self, cfg: Config, log: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.log = log or print
        self.lay_types: dict[str, str] = {}
        self.units: gpd.GeoDataFrame | None = None
        self.aoi = None            # shapely geometry (UTM)
        self.aoi_ll = None         # shapely geometry (EPSG:4326)
        self.aoi_pad_ll = None
        self.bbox = None           # lon/lat bounds of aoi
        self.bld: gpd.GeoDataFrame | None = None
        self.name_col: str | None = None
        self.osm_raw: gpd.GeoDataFrame | None = None   # raw OSM amenity download (cached)
        self.osm_error: Exception | None = None
        self.am: gpd.GeoDataFrame | None = None        # classified amenities used for access score
        self.pois: gpd.GeoDataFrame | None = None      # dashboard points of interest
        self.by_place = None
        self.has_pop = False

    @property
    def utm(self) -> str:
        return self.cfg.utm
