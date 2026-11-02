"""All user-tunable settings in one place (mirrors the notebook's Step 3 + Step 13 form fields)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


@dataclass
class Config:
    # ---- input / output -------------------------------------------------
    gpkg: str = ""                    # path to GeoPackage ("" = no file: analyse a circle around Rishikesh using OSM only)
    out_dir: str = "output"
    # ---- layer selection (blank = auto-detect) --------------------------
    aoi_layer: str = ""               # polygon layer for the study area
    amenity_layer: str = ""           # point layer with amenities
    amenity_type_column: str = ""     # column in amenity layer with the type
    units_layer: str = ""             # polygon layer (wards/grid) to analyse instead of a regular grid
    heat_column: str = ""             # column in units layer with temperature (blank = compute from Landsat)
    pop_column: str = ""              # population column (blank = auto-detect pop_sum/population/pop…)
    amenity_source: str = "both"      # both | gpkg | osm
    # ---- analysis parameters --------------------------------------------
    grid_size_m: int = 500
    years: str = "2023,2024,2025"
    season_start: str = "04-01"
    season_end: str = "06-30"
    max_cloud: int = 30
    walk_radius_m: int = 1000
    hot_percentile: int = 90
    low_amenity_percentile: int = 25
    built_min_share: float = 0.03
    max_area_km2: int = 800
    fallback_radius_km: float = 10.0  # used when no GPKG is given or the study area is too large
    # ---- switches --------------------------------------------------------
    use_osm: bool = True              # False = never call OpenStreetMap (fully offline for vector data)
    use_ndvi: bool = True             # compute greenery (NDVI) from Landsat for the dashboard
    osm_tries: int = 2
    # ---- dashboard -------------------------------------------------------
    language: str = "Hinglish"        # English | Hinglish
    literacy_column: str = ""
    health_column: str = ""
    income_column: str = ""
    traffic_column: str = ""
    # ---- geography (Rishikesh specific) ----------------------------------
    utm: str = "EPSG:32644"           # UTM 44N
    centre_lon: float = 78.2676
    centre_lat: float = 30.0869

    # ---------------------------------------------------------------------
    def validate(self) -> "Config":
        if self.amenity_source not in ("both", "gpkg", "osm"):
            raise ValueError("amenity_source must be one of: both, gpkg, osm")
        if self.language not in ("English", "Hinglish"):
            raise ValueError("language must be English or Hinglish")
        if not 50 <= self.hot_percentile <= 99:
            raise ValueError("hot_percentile must be between 50 and 99")
        if not 1 <= self.low_amenity_percentile <= 50:
            raise ValueError("low_amenity_percentile must be between 1 and 50")
        if self.grid_size_m < 100:
            raise ValueError("grid_size_m must be >= 100 m")
        if self.gpkg and not Path(self.gpkg).is_file():
            raise FileNotFoundError(f"GeoPackage not found: {self.gpkg}")
        if not self.use_osm and self.amenity_source == "osm":
            raise ValueError("amenity_source='osm' needs use_osm=True")
        if not self.gpkg and not self.use_osm:
            raise ValueError("Without a GeoPackage you must enable OpenStreetMap (use_osm=True).")
        return self

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Config":
        names = {f.name: f for f in fields(cls)}
        clean: dict[str, Any] = {}
        for k, v in d.items():
            k = k.replace("-", "_")
            if k not in names:
                raise KeyError(f"Unknown setting: {k}")
            typ = names[k].type
            if v is None:
                continue
            if typ in ("int", int):
                v = int(v)
            elif typ in ("float", float):
                v = float(v)
            elif typ in ("bool", bool):
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            else:
                v = str(v)
            clean[k] = v
        return cls(**clean)

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yml", ".yaml"):
            import yaml
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text)
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
