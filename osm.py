"""OpenStreetMap access (Overpass) with server fail-over and back-off."""
from __future__ import annotations

import time

import osmnx as ox

OVERPASS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]


def configure() -> None:
    ox.settings.use_cache = True
    ox.settings.timeout = 300


def osm_features(poly, tags, tries: int = 2):
    """Overpass servers are often busy → try several servers with back-off."""
    configure()
    last = None
    for url in OVERPASS:
        for attr, val in (("overpass_url", url), ("overpass_endpoint", url + "/interpreter")):
            if hasattr(ox.settings, attr):
                setattr(ox.settings, attr, val)
        for k in range(tries):
            try:
                return ox.features_from_polygon(poly, tags)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(5 * (k + 1))
    raise last
